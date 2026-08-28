"""Portal da Transparencia de MG — confirma se o Estado PAGOU o convenio.

O QUE ISTO RESOLVE. O pedido do dono: "no portal fazemos as pesquisas por CNPJ do
Municipio para confirmar se o pagamento foi realizado". Hoje isso e feito a mao,
convenio a convenio.

O CAMINHO, provado em teste real (26/08/2026) e so com HTTP — sem browser, sem
login, sem credencial:

    CNPJ -> GET listagem com id_favorecido=0  -> resolve o id interno do portal
         -> GET listagem com o id            -> ids de empenho + token de sessao
         -> GET detalhamento=1               -> HISTORICO (traz o nº do convenio)
         -> GET detalhamento=3               -> pagamento (data, OB, situacao, valor)

⚠️ NAO E SPA. A URL parece Angular, mas o portal e JOOMLA (`com_transparenciamg`)
e a listagem vem renderizada no HTML. O detalhe e que e AJAX.

⚠️ SEM O COOKIE, O DETALHE DEVOLVE 0 BYTES — nao erro, nao 403: vazio. O cookie e
o token saem da propria listagem, entao o fluxo se resolve sozinho.

⚠️ OS DADOS ABERTOS NAO SERVEM. `dm_empenho_desp_AAAA.csv.gz` (dados.mg.gov.br)
tem 9 colunas e NAO traz o historico. Sem historico nao ha vinculo com o
convenio, e o vinculo e o ponto inteiro deste coletor. Medido, nao suposto.

⚠️ SO MINAS. E o portal do ESTADO de MG: serve municipio de MG e mais ninguem. O
coletor filtra por `uf='MG'` e, em tenant sem municipio de MG, nao faz uma
requisicao sequer — e diz isso no log, para "nao coletou" nunca se confundir com
"nao ha o que coletar".
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import date, datetime

logger = logging.getLogger("transparencia_mg")

_BASE = "https://www.transparencia.mg.gov.br"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# ⚠️ USER-AGENT DE NAVEGADOR NAO E ENFEITE: medido, o portal devolve 403 para o
# UA do curl/httpx em alguns caminhos (o download dos dados abertos, por exemplo).

# As abas do modal, na numeracao do proprio portal.
_ABA_EMPENHO = 1
_ABA_PAGAMENTO = 3

# ORCAMENTO. O host tem 2 vCPU e um LOCK UNICO entre todos os coletores — a regra
# da casa e nunca aumentar concorrencia de scraping. Os defaults sao propositalmente
# conservadores: e melhor cobrir menos por rodada, todo dia, do que estourar a
# janela e ser morto no meio, deixando estado pela metade.
_BUDGET_S = float(os.getenv("TRANSPMG_BUDGET_S", "600") or 600)
_MAX_MUNICIPIOS = int(os.getenv("TRANSPMG_LOTE_MUNICIPIOS", "8") or 8)
_MAX_DETALHES = int(os.getenv("TRANSPMG_MAX_DETALHES", "150") or 150)
_PAUSA_S = float(os.getenv("TRANSPMG_PAUSA_S", "0.4") or 0.4)

# ⚠️ MODO MEDICAO. `TRANSPMG_SO_LISTAGEM=1` varre as listagens, loga quantos
# empenhos cada municipio tem e NAO BUSCA DETALHE NEM GRAVA NADA. Existe porque
# tres numeros que mudam o desenho por ordens de grandeza (quantos empenhos por
# municipio, se a fase `pago` aceita janela por data de pagamento, e a taxa de
# acerto do vinculo) so producao responde — e chutar qualquer um deles custa mais
# do que medir.
_SO_LISTAGEM = (os.getenv("TRANSPMG_SO_LISTAGEM", "0") or "0").strip() == "1"


# ---------------------------------------------------------------------------
# FUNCOES PURAS — sao elas que decidem o vinculo, e as unicas testaveis sem banco
# (nao ha Postgres de teste em lugar nenhum deste repo).
# ---------------------------------------------------------------------------

# ⚠️ A REGEX DO CONVENIO, e por que ela e assim.
#
# O historico medido em producao:
#   "APROPRIACAO EMPENHO - INVESTIMENTOS AQUISICAO DE VEICULOS ... MUNICIPIO DE
#    PEQUI 1261002849/2025 9492993"
#
# O numero do convenio e `1261002849/2025`. Logo DEPOIS vem `9492993`, solto — e
# e por causa dele que a regex exige a BARRA e o ano de 4 digitos: um `\d{6,}`
# solto pegaria os dois e o segundo viraria um "convenio" que nao existe.
#
# 6 a 12 digitos cobre o que o SIGCON usa (nr_proposta/nr_plano_trabalho tem
# formatos diferentes por orgao) sem descer a numero de 3 digitos, que em texto
# livre e quase sempre outra coisa.
_RE_CONVENIO = re.compile(r"\b(\d{6,12})\s*/\s*((?:19|20)\d{2})\b")
# O numero solto que costuma seguir o do convenio. GUARDADO, nao usado para
# juntar — ver o comentario da coluna `numero_solto` na migration.
_RE_SOLTO = re.compile(r"/(?:19|20)\d{2}\s+(\d{6,9})\b")


def extrair_referencias(historico: str | None) -> tuple[str | None, str | None]:
    """(numero_do_convenio, numero_solto) a partir do texto livre do historico.

    Devolve (None, None) quando nao ha nada no formato — que e diferente de
    "historico vazio" e diferente de "nao li o historico". Quem distingue os tres
    e o `vinculo_status`, ver `classificar`."""
    s = " ".join((historico or "").split())
    if not s:
        return None, None
    m = _RE_CONVENIO.search(s)
    if not m:
        return None, None
    ref = f"{m.group(1)}/{m.group(2)}"
    ms = _RE_SOLTO.search(s)
    return ref, (ms.group(1) if ms else None)


def _so_digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def normalizar_ref(v) -> str:
    """Forma comparavel de um numero de convenio: so digitos, sem zeros a
    esquerda no corpo.

    ⚠️ O PORTAL E O SIGCON ESCREVEM DIFERENTE. O historico traz
    `1261002849/2025`; o SIGCON guarda o mesmo numero ora com barra, ora sem, e
    as vezes com zero a esquerda. Comparar as strings cruas erraria por
    pontuacao, e errar aqui vincula PAGAMENTO AO CONVENIO ERRADO — pior do que
    nao vincular."""
    d = _so_digitos(v)
    return d.lstrip("0") or d


def casar_convenio(ref: str | None, candidatos: list[dict]) -> tuple[int | None, str, str]:
    """Acha o convenio do municipio cujo numero bate com `ref`.

    `candidatos`: [{id, nr_proposta, nr_plano_trabalho, nr_siafi, nr_sigcon}, ...]
    Devolve (convenio_id, status, metodo).

    ⚠️ A ORDEM DAS COLUNAS E DELIBERADA e vai do mais especifico ao mais generico.
    `nr_sigcon` fica por ULTIMO porque ele e DERIVADO (nr_siafi > nr_plano >
    nr_proposta, ver sigcon_scraper) — casar por ele primeiro esconderia por qual
    campo o vinculo aconteceu de verdade, e e essa informacao que vai dizer,
    depois, qual chave vale a pena manter.

    ⚠️ AMBIGUIDADE NAO ESCOLHE. Dois convenios com o mesmo numero devolvem
    'ambiguo' e convenio_id None. Escolher "o primeiro" seria inventar um vinculo
    com 50% de chance de estar errado, e ninguem saberia."""
    if not ref:
        return None, "sem_numero", ""
    alvo = normalizar_ref(ref)
    if not alvo:
        return None, "sem_numero", ""
    for campo in ("nr_proposta", "nr_plano_trabalho", "nr_siafi", "nr_sigcon"):
        achados = [c for c in candidatos if normalizar_ref(c.get(campo)) == alvo]
        if len(achados) == 1:
            return achados[0].get("id"), "casado", campo
        if len(achados) > 1:
            return None, "ambiguo", campo
    return None, "nao_casou", ""


def classificar(detalhe_ok: bool, tem_rotulo: bool, historico: str | None,
                ref: str | None, convenio_id: int | None, status_casamento: str) -> str:
    """O `vinculo_status` final. Sete valores, nenhum deles colapsado num NULL.

    ⚠️ Sem esta distincao, uma mudanca de ROTULO no portal se disfarca de
    "empenho sem historico" para sempre — a cobertura cai e nada acusa. E o mesmo
    defeito que ja custou um ciclo inteiro nas Notas de Empenho."""
    if not detalhe_ok:
        return "detalhe_falhou"
    if not tem_rotulo:
        return "layout_mudou"
    if not (historico or "").strip():
        return "sem_historico"
    return status_casamento if not convenio_id else "casado"


def montar_pagamentos(linhas: list[dict]) -> dict:
    """O bloco `pagamentos`, no MESMO formato de `ops_obs` das voluntarias.

    ⚠️ O formato e copiado de proposito: `rm_builder._desembolso_ops_obs` e
    `rm_pdf._desembolso_destaque` ja sabem ler isso. Um formato proprio exigiria
    um segundo parser no builder — e seria a segunda copia da mesma regra, que
    neste repo e o jeito conhecido de as duas divergirem."""
    obs = []
    total = 0.0
    for l in linhas:
        v = l.get("valor")
        if v is not None:
            total += float(v)
        obs.append({
            "data_emissao_ob": l.get("data"),
            "valor": v,
            "numero_ob": l.get("numero"),
            "situacao": l.get("situacao"),
        })
    return {
        "valor_desembolsado": round(total, 2),
        "data_ultimo_desembolso": (obs[-1].get("data_emissao_ob") if obs else None),
        "obs": obs,
    }


# ---------------------------------------------------------------------------
# LEITURA DO HTML — o portal e Joomla, entao tudo chega renderizado.
# ---------------------------------------------------------------------------
_RE_ID_EMPENHO = re.compile(r'data-idEmpenho="(\d+)"')
# ⚠️ O TOKEN CSRF aparece em DUAS formas no mesmo HTML: como `&<md5>=1` (dentro
# do `data-session` que o JS concatena na URL) e como `name="<md5>" value="1"`
# (o campo escondido do formulario). Aceitar so uma delas e apostar em qual
# bloco do template vai sobreviver a proxima atualizacao do portal.
_RE_TOKEN = re.compile(
    r'(?:name="([0-9a-f]{32})"\s+value="1"|([0-9a-f]{32})=1)')


def ler_id_favorecido(html: str, cnpj: str) -> str | None:
    """O id interno do favorecido, a partir da pagina de LISTAGEM DE FAVORECIDOS
    (a mesma URL, com id_favorecido=0).

    ⚠️ E ESTE PASSO QUE DESTRAVA TUDO, e ele nao era obvio. O portal NAO tem
    autocomplete (digitar no campo nao dispara requisicao nenhuma) e o POST do
    formulario com o CNPJ cru resolve para id=0 e devolve zero empenho. O id
    estava no link da propria pagina de favorecidos."""
    # ⚠️ TODAS as ocorrencias, e a PRIMEIRA NAO-ZERO — nao a primeira. A pagina
    # cita a si mesma (`.../0/0/<cnpj>/4`, o link do breadcrumb "Favorecidos"),
    # entao `search` acha o zero e o coletor concluiria que nao resolveu. Custou
    # um teste contra o HTML de verdade para aparecer.
    achados = re.findall(
        r"despesa-favorecidos/\d{4}/[\d-]+/[\d-]+/(\d+)/0/" + re.escape(_so_digitos(cnpj)),
        html or "")
    return next((a for a in achados if a != "0"), None)


def ler_ids_empenho(html: str) -> list[str]:
    return list(dict.fromkeys(_RE_ID_EMPENHO.findall(html or "")))


def ler_token(html: str) -> str | None:
    m = _RE_TOKEN.search(html or "")
    return (m.group(1) or m.group(2)) if m else None


def _texto(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html or "").split())


_ROTULO_HIST = "Histórico do Empenho"


def ler_detalhe_empenho(html: str) -> dict:
    """Campos da aba Empenho. `tem_rotulo` diz se a pagina AINDA tem o rotulo do
    historico — e o que separa "layout mudou" de "historico vazio"."""
    t = _texto(html)
    tem_rotulo = ("Histórico do Empenho" in t) or ("Historico do Empenho" in t)
    hist = ""
    m = re.search(r"Hist[oó]rico do Empenho:\s*(.*?)(?:\s+Refor[cç]o|\s+Anula[cç][ãa]o|$)", t)
    if m:
        hist = m.group(1).strip()
    # ⚠️ O VALOR VAI ATE O PROXIMO ROTULO CONHECIDO, e nao ate "dois espacos" ou
    # "a proxima palavra com dois-pontos". O texto achatado do portal e uma linha
    # so — "Número do Empenho: 881 Ano de Exercício: 2026 Data de Registro..." —
    # e qualquer heuristica de espacamento devolve None ou o campo inteiro.
    _ROTULOS = ("Número do Empenho", "Ano de Exercício", "Data de Registro do Empenho",
                "Tipo de Empenho", "CNPJ/ CPF e Descrição do Favorecido",
                "Valor Inicial da despesa empenhada", "Valor Atual do Empenho",
                "Descrição Histórico do Empenho", "Reforço", "Anulação")

    def _campo(rot):
        prox = "|".join(re.escape(r) for r in _ROTULOS if r != rot)
        mm = re.search(re.escape(rot) + r":\s*(.*?)\s*(?:" + prox + r"|$)", t)
        v = (mm.group(1).strip() if mm else "")
        return v or None
    return {
        "tem_rotulo": tem_rotulo,
        "historico": hist,
        "nr_empenho": _campo("Número do Empenho"),
        "ano_exercicio": _campo("Ano de Exercício"),
        "tipo_empenho": _campo("Tipo de Empenho"),
    }


_RE_DINHEIRO = re.compile(r"R\$\s*([\d.]+,\d{2})")
_RE_LINHA_PGTO = re.compile(
    r"(\d{2}/\d{2}/\d{4})\s+(\S+)\s+(.+?)\s+(\d{14})\s*-\s*.+?R\$\s*([\d.]+,\d{2})")


def _num_br(v) -> float | None:
    if not v:
        return None
    try:
        return float(str(v).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def ler_pagamentos(html: str) -> list[dict]:
    """Linhas da aba Pagamento.

    Medido: "25/03/2026 1939 Acatada pelo banco 18313874000164 - PM PEQUI
    R$ 938.793,55". A `situacao` importa tanto quanto o valor — "Acatada pelo
    banco" e o que confirma que o dinheiro saiu; ha estados intermediarios que
    NAO sao pagamento."""
    out = []
    for m in _RE_LINHA_PGTO.finditer(_texto(html)):
        out.append({
            "data": m.group(1),
            "numero": m.group(2),
            "situacao": m.group(3).strip(),
            "valor": _num_br(m.group(5)),
        })
    return out


# ---------------------------------------------------------------------------
# O LACO DE COLETA
# ---------------------------------------------------------------------------
def _db():
    import psycopg2
    return psycopg2.connect(os.getenv("DATABASE_URL_SYNC", ""))


def _sessao():
    """httpx com o UA de navegador e o cookie jar vivo.

    ⚠️ O COOKIE E OBRIGATORIO e sai da propria listagem: sem ele o endpoint de
    detalhe devolve ZERO BYTE — nao erro, nao 403, vazio. Um cliente sem cookie
    jar coletaria a listagem inteira e depois falharia em todo detalhe, com o log
    dizendo apenas "veio vazio"."""
    import httpx
    return httpx.Client(headers={"User-Agent": _UA}, follow_redirects=True,
                        timeout=60.0)


def _url_listagem(ano: int, id_fav: str, cnpj: str, fase: str = "empenhado") -> str:
    return (f"{_BASE}/consultas-1/despesa-estado/despesa/despesa-favorecidos/"
            f"{ano}/01-01-{ano}/31-12-{ano}/{id_fav}/0/{cnpj}/4/0/{fase}")


def _url_detalhe(id_empenho: str, aba: int, token: str, ano: int) -> str:
    return (f"{_BASE}/index.php?option=com_transparenciamg"
            f"&task=estado_despesa.filtrarDetalhamento&detalhamento={aba}"
            f"&id_empenho={id_empenho}&dataInicio=01/01/{ano}&dataFim=31/12/{ano}"
            f"&{token}=1")


def _municipios_mg(cur) -> list[dict]:
    """Municipios de MG com CNPJ, do MAIS DESATUALIZADO para o mais recente.

    ⚠️ RODIZIO, e nao ordem alfabetica. E a licao que `add_scraper_municipio_
    coleta.sql` registra: com ordem fixa, a rodada era cortada por volta do 10º de
    41 e os do fim da lista NUNCA eram atualizados — em silencio."""
    cur.execute(r"""
        SELECT m.id, m.nome, regexp_replace(COALESCE(m.cnpj, ''), '\D', '', 'g') AS cnpj,
               MAX(e.id_favorecido) AS id_fav,
               MAX(e.updated_at)    AS visto_em
        FROM municipios m
        LEFT JOIN transparencia_mg_empenhos e ON e.municipio_id = m.id
        WHERE upper(COALESCE(m.uf, '')) = 'MG'
          AND length(regexp_replace(COALESCE(m.cnpj, ''), '\D', '', 'g')) = 14
          AND COALESCE(m.active, true)
        GROUP BY m.id, m.nome, m.cnpj
        ORDER BY visto_em ASC NULLS FIRST, m.id
    """)
    return [{"id": r[0], "nome": r[1], "cnpj": r[2], "id_fav": r[3]}
            for r in cur.fetchall()]


def _convenios(cur, municipio_id: int) -> list[dict]:
    """Candidatos a vinculo, do MESMO municipio.

    ⚠️ Restrito ao municipio DE PROPOSITO: numero de convenio nao e unico entre
    municipios, e casar carteira inteira acharia homonimo de outra prefeitura."""
    cur.execute("""
        SELECT id, nr_proposta, nr_plano_trabalho, nr_siafi, nr_sigcon
        FROM convenios_estadual WHERE municipio_id = %s
    """, (municipio_id,))
    return [{"id": r[0], "nr_proposta": r[1], "nr_plano_trabalho": r[2],
             "nr_siafi": r[3], "nr_sigcon": r[4]} for r in cur.fetchall()]


def _grava_empenhos(cur, mun: dict, id_fav: str, ids: list[str], ano: int) -> int:
    """Insere os empenhos da listagem. NAO toca no detalhe — quem preenche
    historico/pagamento e a fila, depois.

    ⚠️ `DO UPDATE` so no que a LISTAGEM sabe. Um `DO UPDATE SET historico=...`
    aqui apagaria o detalhe ja lido a cada rodada, e a fila re-leria tudo todo
    dia — 2 requisicoes por empenho, para sempre."""
    n = 0
    for i in ids:
        cur.execute("""
            INSERT INTO transparencia_mg_empenhos
                (id_empenho, municipio_id, cnpj_favorecido, id_favorecido,
                 ano_exercicio, raw_data)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (id_empenho) DO UPDATE SET
                id_favorecido = EXCLUDED.id_favorecido,
                updated_at    = NOW()
        """, (int(i), mun["id"], mun["cnpj"], id_fav, ano,
              '{"fonte": "listagem", "ano": %d}' % ano))
        n += cur.rowcount or 0
    return n


def _fila_detalhe(cur, limite: int) -> list[dict]:
    """Empenhos ainda sem detalhe lido, os mais antigos primeiro."""
    cur.execute("""
        SELECT id_empenho, municipio_id, ano_exercicio
        FROM transparencia_mg_empenhos
        WHERE detalhe_lido_em IS NULL
        ORDER BY id_empenho
        LIMIT %s
    """, (limite,))
    return [{"id": r[0], "municipio_id": r[1], "ano": r[2] or date.today().year}
            for r in cur.fetchall()]


def coletar() -> dict:
    """Uma rodada. Devolve o resumo, que tambem vai para o log.

    DUAS FASES, e elas sao separadas de proposito:
      1. LISTAGEM  — 1 ou 2 GET por municipio, descobre os empenhos que existem;
      2. DETALHE   — 2 GET por empenho AINDA NAO LIDO, preenche historico e
                     pagamento, e tenta o vinculo com o convenio.
    A fase 2 e limitada por `TRANSPMG_MAX_DETALHES` e pelo orcamento de tempo: e
    melhor cobrir um pedaco por rodada, todo dia, do que estourar a janela e ser
    morto no meio.
    """
    t0 = time.monotonic()
    ano = date.today().year
    res = {"municipios": 0, "empenhos_novos": 0, "detalhes": 0,
           "casados": 0, "sem_convenio": 0, "sem_municipio_mg": False}
    conn = _db()
    conn.autocommit = False
    cur = conn.cursor()
    muns = _municipios_mg(cur)
    if not muns:
        # ⚠️ DIZER ISTO EM VOZ ALTA. Tenant sem municipio de MG nao tem o que
        # coletar aqui, e "nao coletou" jamais pode se confundir com "nao ha o que
        # coletar" — e o portal e do ESTADO de Minas.
        logger.info("nenhum municipio de MG com CNPJ neste tenant — nada a coletar")
        res["sem_municipio_mg"] = True
        conn.close()
        return res

    cli = _sessao()
    token = None
    try:
        for mun in muns[:_MAX_MUNICIPIOS]:
            if time.monotonic() - t0 > _BUDGET_S:
                logger.info("orcamento esgotado na listagem — resto fica p/ a proxima")
                break
            id_fav = mun.get("id_fav")
            try:
                if not id_fav:
                    # PASSO 1: resolve o id interno. So na primeira vez do
                    # municipio — depois ele fica na tabela.
                    r0 = cli.get(_url_listagem(ano, "0", mun["cnpj"]).rsplit("/0/", 1)[0])
                    id_fav = ler_id_favorecido(r0.text, mun["cnpj"])
                    if not id_fav:
                        logger.info(f"  {mun['nome']}: CNPJ nao resolveu id no portal "
                                    f"({len(r0.content)} bytes) — sem empenho estadual?")
                        continue
                r = cli.get(_url_listagem(ano, id_fav, mun["cnpj"]))
                ids = ler_ids_empenho(r.text)
                token = ler_token(r.text) or token
                logger.info(f"  {mun['nome']}: {len(ids)} empenho(s) em {ano} "
                            f"(id_favorecido={id_fav})")
                if not _SO_LISTAGEM:
                    res["empenhos_novos"] += _grava_empenhos(cur, mun, id_fav, ids, ano)
                    conn.commit()
                res["municipios"] += 1
            except Exception as e:
                logger.warning(f"  {mun['nome']}: listagem falhou — {str(e)[:90]}")
            time.sleep(_PAUSA_S)

        if _SO_LISTAGEM:
            logger.warning("TRANSPMG_SO_LISTAGEM=1 — NADA foi gravado (modo medicao)")
            return res
        if not token:
            logger.info("sem token de sessao — nenhuma listagem respondeu; fila do "
                        "detalhe nao roda nesta rodada")
            return res

        # FASE 2 — a fila do detalhe.
        for it in _fila_detalhe(cur, _MAX_DETALHES):
            if time.monotonic() - t0 > _BUDGET_S:
                logger.info("orcamento esgotado na fila do detalhe")
                break
            try:
                r1 = cli.get(_url_detalhe(str(it["id"]), _ABA_EMPENHO, token, it["ano"]))
                ok = len(r1.content) > 200
                d = ler_detalhe_empenho(r1.text) if ok else {"tem_rotulo": False, "historico": ""}
                ref, solto = extrair_referencias(d.get("historico"))
                cid, st_casa, metodo = casar_convenio(ref, _convenios(cur, it["municipio_id"]))
                status = classificar(ok, d.get("tem_rotulo", False), d.get("historico"),
                                     ref, cid, st_casa)
                pgs = None
                if ok:
                    r3 = cli.get(_url_detalhe(str(it["id"]), _ABA_PAGAMENTO, token, it["ano"]))
                    linhas = ler_pagamentos(r3.text)
                    # ⚠️ `None` quando a chamada nem respondeu; `montar_pagamentos([])`
                    # quando ela respondeu e nao ha pagamento. NULO e "nao
                    # consultado" — nunca "nao houve pagamento".
                    pgs = montar_pagamentos(linhas) if len(r3.content) > 100 else None
                import json as _json
                cur.execute("""
                    UPDATE transparencia_mg_empenhos SET
                        historico = %s, convenio_ref = %s, numero_solto = %s,
                        convenio_id = %s, vinculo_status = %s, vinculo_metodo = %s,
                        nr_empenho = COALESCE(%s, nr_empenho),
                        tipo_empenho = COALESCE(%s, tipo_empenho),
                        pagamentos = COALESCE(%s::jsonb, pagamentos),
                        detalhe_lido_em = NOW(), updated_at = NOW()
                    WHERE id_empenho = %s
                """, (d.get("historico"), ref, solto, cid, status, metodo,
                      d.get("nr_empenho"), d.get("tipo_empenho"),
                      (_json.dumps(pgs, ensure_ascii=False) if pgs is not None else None),
                      it["id"]))
                conn.commit()
                res["detalhes"] += 1
                if cid:
                    res["casados"] += 1
                else:
                    res["sem_convenio"] += 1
            except Exception as e:
                conn.rollback()
                logger.warning(f"  empenho {it['id']}: detalhe falhou — {str(e)[:90]}")
            time.sleep(_PAUSA_S)
    finally:
        cli.close()
        cur.close()
        conn.close()
    logger.info(
        f"=== Transparencia MG: {res['municipios']} municipio(s), "
        f"{res['empenhos_novos']} empenho(s) novo(s), {res['detalhes']} detalhe(s) — "
        f"{res['casados']} casaram com convenio, {res['sem_convenio']} nao "
        f"({time.monotonic()-t0:.0f}s) ===")
    return res


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    coletar()
