"""
Obras.gov.br / CIPI — obras federais no municipio, sem login e sem token.

O Cadastro Integrado de Projetos de Investimento reune as obras federais com
execucao fisica, fontes de recurso, tomador e executor. Complementa o SISMOB (so
saude) e o SIMEC (so educacao): aqui entra o resto — mobilidade, saneamento,
habitacao, seguranca, e a **reconstrucao da Defesa Civil**, que em Nova Palma e
22 dos 30 projetos.

⭐⭐ **04/09/2026: A FONTE MUDOU DE HOST, E COM ELA SUMIRAM TRES ARMADILHAS.**
Ate 03/09 este coletor falava com `api.obrasgov.gestao.gov.br`, que **recusa o
IP da VPS** (429 na primeira requisicao, medido tres vezes) — e por isso ficou
pronto e desligado por dois dias. O Governo publica o MESMO acervo em
**`api-publica.obrasgov.gestao.gov.br/obras`**, com contrato OpenAPI proprio,
e esse host **responde 200 ao servidor** (0,16 s, medido em 04/09).

O que a medicao contra a API nova mostrou, ponto a ponto contra o que a antiga
obrigava:

    paginacao mente (`last` sempre true) .... NAO: total_items constante (10.372
                                             no RS) em qualquer pagina/tamanho
    paginas se sobrepoem (41 de 200) ....... NAO: zero repetidos, ordem estavel
    rate limit apertado (3s -> 429) ........ NAO: 12 requisicoes seguidas SEM
                                             pausa, zero erro, 0,72 s de media
    projeto sem CNPJ ....................... MELHOR: 87% tem (antes 60%)
    filtro desconhecido ignorado em silencio  SIM, CONTINUA — ver armadilha 1

Por isso a varredura caiu de ~8 minutos por UF (60 paginas x 8 s de pausa) para
~75 segundos (52 paginas de 200 a ~0,7 s). O teto de `tamanho_da_pagina` e
**200**; 201 devolve 422.

AS ARMADILHAS QUE VALEM NESTA API, todas medidas em 04/09/2026:

1. ⚠️⚠️ **PARAMETRO DESCONHECIDO NAO DA ERRO — em `/projeto-investimento`.**
   `codigo_ibge=4313102` devolve HTTP 200 com o estado inteiro (`total_items`
   identico ao da consulta sem filtro), e quem confiasse nele gravaria obra do
   Amapa como sendo do municipio. Nesse endpoint o unico filtro que serve
   continua sendo `uf_principal`.

   ⭐ **MAS O FILTRO TERRITORIAL EXISTE — no `/geometria`** (medido 07/09/2026):

       /geometria sem filtro .......... 216.278
       /geometria?cod_ibge=4313102 ....      26
       /geometria?cod_ibge=9999999 ....       0   (nao devolve tudo)

   E dai que sai o `vinculo='territorio'`. Ver `projetos_do_territorio`.

2. ⚠️⚠️ **O MUNICIPIO SE RECONHECE POR CNPJ, NUNCA POR NOME** (diretriz do dono,
   04/09/2026). Casar por nome trouxe, na medicao, **379 obras da Universidade
   Federal de Santa Maria** como se fossem da prefeitura — mais 6 do hospital
   universitario. Nome tem homonimo e o erro e silencioso: nao levanta excecao,
   nao zera a contagem, so mistura dinheiro de outro ente no painel do cliente.
   Por isso este coletor depende de `municipios.cnpj` estar preenchido (o
   `ingestion/siconfi.py` preenche sozinho, do cadastro de entes do Tesouro) e
   soma os CNPJs proprios de fundos e autarquias ja conhecidos.

3. ⚠️ **O PROJETO RARAMENTE DIZ ONDE FICA.** De 200 projetos do RS medidos, so
   32 tinham CEP ou endereco — e 174 tinham CNPJ em `tomadores`/`executores`. O
   CNPJ e o caminho; endereco e enfeite.

4. ⚠️ **`sistema_resp` REVELA SOBREPOSICAO COM O QUE JA COLETAMOS.** Uma UBS do
   RS veio com `sistema_resp: SISMOB` — ou seja, o CIPI reune obras que o
   `sismob_obras` ja traz por outro caminho. A coluna `sistema_origem` guarda
   isso para a tela poder dizer "esta obra voce ja ve no SISMOB" em vez de
   mostrar a mesma obra duas vezes como se fossem duas.

5. ⚠️ **UMA OBRA PODE TER VARIOS TOMADORES**, e um deles pode ser de outro ente
   (consorcio, obra intermunicipal). O casamento e por interseccao de CNPJ com a
   carteira, e um projeto que casa com dois municipios e gravado para os dois.

   ⭐ **A CHAVE PASSOU A SER `(municipio_id, id_unico)` em 07/09/2026** — a troca
   que `migrations/add_obrasgov.sql` ja previa no proprio cabecalho. Com a chave
   global antiga a ultima gravacao vencia, e o vinculo territorial tornou isso
   comum: 5 projetos da carteira do freitas estao em mais de um municipio, e um
   deles em 41 dos 42.

6. ⚠️ **NEM TODA GEOMETRIA E UMA OBRA NA CIDADE.** Projeto guarda-chuva tem
   geometria em centenas de municipios — `324.31-80` ("Manutencao rodoviaria na
   malha federal do DNIT em MG") esta em 790. Eles entram com
   `vinculo='abrangencia'` em vez de posarem de obra local. Ver
   `ABRANGENCIA_MAX`.

Rodavel por Scheduled Task em qualquer worker, ou a mao:
    python -u ingestion/obrasgov.py            # coleta de verdade
    python -u ingestion/obrasgov.py --dry      # varre e mostra, sem gravar
"""
import json
import logging
import os
import re
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("obrasgov")

# ⚠️ `api-publica`, e nao `api`. O host sem o prefixo e o que bloqueia a VPS.
BASE = os.getenv("OBRASGOV_BASE",
                 "https://api-publica.obrasgov.gestao.gov.br/obras")
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 dados abertos Obras.gov.br)",
      "Accept": "application/json"}
FONTE = "OBRASGOV"
TIMEOUT = 90

# Teto da fonte: 201 devolve 422.
TAMANHO_PAGINA = min(int(os.getenv("OBRASGOV_TAMANHO_PAGINA", "200") or "200"), 200)
# Sem rate limit observado (12 requisicoes seguidas, zero erro). Meio segundo e
# cortesia com a fonte, nao necessidade — e ainda deixa a varredura do RS em
# ~75 s.
PAUSA_S = float(os.getenv("OBRASGOV_PAUSA_S", "0.5") or "0.5")
# Guarda contra `total_pages` absurdo. 52 paginas cobrem o RS; 400 cobre SP com
# folga e ainda impede um laco infinito se a fonte mudar de comportamento.
TETO_PAGINAS = int(os.getenv("OBRASGOV_TETO_PAGINAS", "400") or "400")
MIN_INTERVAL_H = int(os.getenv("OBRASGOV_MIN_INTERVAL_H", "20") or "20")
# ⚠️ TETO DA TAREFA INTEIRA, e a fase de detalhe so comeca se couber nele. A
# Scheduled Task mata o processo em `timeout -k 30 1800`; a varredura de
# projetos (que e a parte que nao pode ser perdida) leva ~75 s por UF, e a de
# detalhe ~450 s fixos. Sem esta guarda, um tenant de 4 UFs entraria no detalhe
# com 200 s de sobra e seria degolado no meio — perdendo o log final, que e
# onde o resultado aparece. Mesma disciplina do `_TETO_TAREFA_S` da
# Transferencia Especial.
TETO_TAREFA_S = float(os.getenv("OBRASGOV_TETO_TAREFA_S", "1700") or "1700")
# Quanto a fase de detalhe precisa para comecar. ⚠️ O NUMERO VEIO DA MEDICAO, e
# a estimativa anterior (450 s para os cinco) errou por mais do dobro: o custo
# real dos cinco e 1.020 s. Com o rodizio de `_detalhe_da_rodada` a rodada leva
# os dois baratos (60 s) mais o pior dos caros (384 s) = ~450 s, e 500 s de
# reserva cobre isso com folga.
DETALHE_MIN_S = float(os.getenv("OBRASGOV_DETALHE_MIN_S", "500") or "500")


def _so_digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


# ⚠️ A FONTE MANDA PARTE DO TEXTO COM ACENTO CODIFICADO DUAS VEZES, e isso e
# dela, nao nosso. Medido em 04/09/2026 pedindo o projeto `137854.31-54`: os
# bytes que chegam sao
#
#     b'Creche Proinf\xc3\x83\xc2\xa2ncia  - Ara\xc3\x83\xc2\xbajos'
#
# que e o UTF-8 de "Ã¢" — ou seja, o Governo leu um texto latin-1 como se fosse
# UTF-8 e gravou o resultado. Na tela sai "Creche ProinfÃ¢ncia - AraÃºjos".
#
# O conserto e exato: reinterpretar os bytes como latin-1 desfaz a camada extra.
# Mas ele SO PODE SER APLICADO ONDE O ESTRAGO EXISTE — em "PAVIMENTAÇÃO", que
# esta correto, a mesma operacao produziria lixo. Por isso as tres guardas:
# procurar a assinatura do estrago, tentar a conversao, e desistir se ela nao
# melhorar. Sem elas, um "conserto" cego corromperia o texto sadio da maioria.
_MOJIBAKE = re.compile(r"Ã[-¿]|Â[-¿]|â€")


def _texto(v) -> str | None:
    """Texto da fonte, com o acento duplamente codificado desfeito."""
    s = str(v or "").strip()
    if not s:
        return None
    for _ in range(2):        # a fonte tem casos de DUAS camadas
        if not _MOJIBAKE.search(s):
            break
        try:
            candidato = s.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        # So aceita se de fato reduziu o estrago: uma conversao que nao melhora
        # e uma conversao que esta errada.
        if len(_MOJIBAKE.findall(candidato)) >= len(_MOJIBAKE.findall(s)):
            break
        s = candidato
    return s or None


def pagina(client: httpx.Client, uf: str, n: int) -> dict | None:
    """Uma pagina da UF. `None` = desistiu, e NAO significa "acabou".

    Mantem backoff no 429 mesmo sem rate limit observado: a medicao de hoje nao
    promete o comportamento de amanha, e o custo de ter a rede pronta e zero
    enquanto ela nao for usada."""
    params = {"uf_principal": uf, "pagina": n, "tamanho_da_pagina": TAMANHO_PAGINA}
    return _get_com_retry(client, "projeto-investimento", params)


# ⚠️ 5xx DERRUBAVA A RODADA INTEIRA, e isso foi medido em producao duas vezes:
#
#     06/09 03:18  500 Internal Server Error  na pagina 63 de MG
#     07/09 02:48  502 Bad Gateway            na pagina 12 de MG
#
# Nos dois casos o montesiao registrou `error` com ZERO gravados — a varredura
# inteira perdida por um soluco de uma pagina. O `raise_for_status()` levantava,
# a excecao subia ate o `except` do `ingest` e desfazia tudo.
#
# 5xx e TRANSITORIO por definicao ("o servidor falhou", nao "voce errou"), e
# merece o mesmo backoff que o 429 ja tinha. O que continua levantando e 4xx:
# 404 ou 422 significam que NOS pedimos errado, e insistir nao conserta.
#
# ⚠️ E a fase de detalhe multiplicou a exposicao: a rodada passou de ~75s para
# ~8-10 min e de dezenas para mais de mil paginas. A chance de encontrar um 5xx
# no caminho deixou de ser desprezivel.
_STATUS_RETENTAVEIS = (429, 500, 502, 503, 504)


def _get_com_retry(client: httpx.Client, caminho: str, params: dict) -> dict | None:
    """GET com backoff em 429 e 5xx. `None` = desistiu (e NAO "acabou")."""
    for espera in (0, 15, 45, 90):
        if espera:
            time.sleep(espera)
        r = client.get(f"{BASE}/{caminho}", params=params, headers=UA, timeout=TIMEOUT)
        if r.status_code in _STATUS_RETENTAVEIS:
            log.info("    %s em %s p%s — aguardando %ds", r.status_code, caminho,
                     params.get("pagina"), espera or 15)
            continue
        r.raise_for_status()
        return r.json()
    log.warning("    %s: desisti apos 4 tentativas (ultimo status %s)",
                caminho, r.status_code)
    return None


def varrer_uf(client: httpx.Client, uf: str) -> tuple[dict, bool]:
    """Todos os projetos da UF, por `id_projeto_investimento`.

    Devolve (projetos, completo). `completo=False` quando a varredura parou por
    rate limit ou pelo teto — e nesse caso a rodada NAO pode marcar obra como
    ausente, porque a ausencia pode ser nossa.

    ⚠️ Aqui `total_pages` E confiavel (medido: constante em qualquer pagina e
    tamanho), diferente da API antiga, onde ele era calculado a partir da pagina
    pedida. Ainda assim o dedup por id continua: ele custa nada e protege de uma
    mudanca de ordenacao que ninguem anunciaria."""
    por_id: dict[str, dict] = {}
    n, total_pages = 1, None
    while n <= TETO_PAGINAS:
        d = pagina(client, uf, n)
        if d is None:
            if n == 1:
                log.error("  %s: 429 JA NA PRIMEIRA PAGINA. Se isto persistir, o "
                          "host novo passou a recusar o IP como o antigo faz — "
                          "conferir com scripts/medir_obrasgov_vps.sh", uf)
            else:
                log.warning("  %s: interrompida por rate limit na pagina %d "
                            "(%d projeto(s)) — resultado PARCIAL", uf, n, len(por_id))
            return por_id, False

        itens = d.get("data") or []
        if total_pages is None:
            total_pages = d.get("total_pages") or 1
            log.info("  %s: %s projeto(s) em %s pagina(s)",
                     uf, d.get("total_items"), total_pages)
        if not itens:
            return por_id, True
        novos = 0
        for x in itens:
            uid = x.get("id_projeto_investimento")
            if uid and uid not in por_id:
                por_id[uid] = x
                novos += 1
        if n % 10 == 0 or n == total_pages:
            log.info("    pagina %d/%s — acumulado %d", n, total_pages, len(por_id))
        if n >= total_pages:
            return por_id, True
        n += 1
        time.sleep(PAUSA_S)
    log.warning("  %s: teto de %d paginas — resultado PARCIAL", uf, TETO_PAGINAS)
    return por_id, False


def _pagina_de(client: httpx.Client, caminho: str, params: dict, n: int) -> dict | None:
    """Uma pagina de QUALQUER endpoint da API. `None` = desistiu no 429.

    Generaliza o `pagina()` acima, que so sabia falar com `/projeto-investimento`
    e so sabia filtrar por UF. Os outros seis endpoints do contrato usam o mesmo
    envelope e o mesmo teto de 200 por pagina.
    """
    p = {**params, "pagina": n, "tamanho_da_pagina": TAMANHO_PAGINA}
    return _get_com_retry(client, caminho, p)


def varrer(client: httpx.Client, caminho: str, params: dict | None = None,
           teto: int | None = None) -> tuple[list[dict], bool]:
    """Todas as paginas de um endpoint. Devolve (linhas, completo)."""
    linhas: list[dict] = []
    n, total_pages = 1, None
    limite = teto or TETO_PAGINAS
    while n <= limite:
        d = _pagina_de(client, caminho, params or {}, n)
        if d is None:
            log.warning("  %s: interrompido por rate limit na pagina %d "
                        "(%d linha(s)) — PARCIAL", caminho, n, len(linhas))
            return linhas, False
        linhas.extend(d.get("data") or [])
        if total_pages is None:
            total_pages = d.get("total_pages") or 1
        if n >= total_pages:
            return linhas, True
        n += 1
        time.sleep(PAUSA_S)
    log.warning("  %s: teto de %d paginas — PARCIAL", caminho, limite)
    return linhas, False


# ⭐ O FILTRO TERRITORIAL EXISTE — so nao esta no endpoint que este coletor usava.
#
# A armadilha 1 la em cima continua valendo ao pe da letra: `/projeto-investimento`
# ignora `codigo_ibge` e devolve o estado inteiro com HTTP 200. Mas o `/geometria`
# e outra coisa (medido em 07/09/2026):
#
#     /geometria sem filtro ............... 216.278
#     /geometria?cod_ibge=4313102 .........      26
#     /geometria?cod_ibge=9999999 .........       0   (nao devolve tudo)
#
# ⚠️ E ELE NAO SUBSTITUI O CNPJ, SOMA-SE A ELE. Medido nos tres tenants:
#
#     Nova Palma    CNPJ=30  geometria=26   so CNPJ=5   so geometria=1
#     Santa Maria   CNPJ=78  geometria=436  so CNPJ=7   so geometria=365
#     Monte Siao    CNPJ=5   geometria=8    so CNPJ=0   so geometria=3
#
# Ha obra sem geometria cadastrada (que so o CNPJ acha) e muita obra de OUTRO
# ente no territorio (que so a geometria acha). Descartar qualquer um dos dois
# caminhos perde dado real.
#
# ⚠️ ACIMA DESTE CORTE O PROJETO NAO E UMA OBRA NA CIDADE. Amostra de 124
# projetos da carteira do freitas: 102 com geometria em UM municipio, 15 em 2 a
# 5, 3 em MAIS DE CEM — e esses tres sao `324.31-80` ("Manutencao rodoviaria na
# malha federal do DNIT em MG", 790 municipios), a FUNASA (202) e uma consultoria
# de PE que aparece em municipio de MG (312). O primeiro sozinho cai em 41 dos 42
# municipios do freitas: gravar como "obra em Araujos" seria o mesmo ruido 41
# vezes. Eles entram MARCADOS ('abrangencia'), nao descartados — a tela decide.
ABRANGENCIA_MAX = int(os.getenv("OBRASGOV_ABRANGENCIA_MAX", "20") or "20")


def projetos_do_territorio(client: httpx.Client, ibge: str) -> set[str]:
    """`id_projeto_investimento` com geometria NO municipio, pelo codigo IBGE."""
    if len(str(ibge or "")) != 7:
        return set()
    linhas, _ = varrer(client, "geometria", {"cod_ibge": ibge})
    return {x.get("id_projeto_investimento") for x in linhas
            if x.get("id_projeto_investimento")}


def projeto_por_id(client: httpx.Client, pid: str) -> dict | None:
    """UM projeto pelo id. Para o que a varredura da UF nao trouxe.

    ⚠️ A GEOMETRIA APONTA PROJETO DE OUTRA UF. `varrer_uf` filtra por
    `uf_principal`, e a `uf_principal` nem sempre e a do territorio: o
    `123265.26-04` e uma consultoria com `uf_principal=PE` que tem geometria em
    municipio de MG (medido em 07/09/2026). Sem esta busca, o vinculo
    territorial dele se perderia em silencio — a promessa de "tudo o que esta no
    territorio" so vale se o projeto for buscado onde ele estiver.
    """
    d = _pagina_de(client, "projeto-investimento",
                   {"id_projeto_investimento": pid}, 1)
    itens = (d or {}).get("data") or []
    return itens[0] if itens else None


_ABRANG_CACHE: dict[str, int | None] = {}


def _abrangencia(client: httpx.Client, pid: str) -> int | None:
    """Em quantos municipios do BRASIL este projeto tem geometria.

    E o numero que separa a obra na cidade do projeto guarda-chuva: o
    `324.31-80` ("Manutencao rodoviaria na malha federal do DNIT em MG")
    devolve 790, e sozinho cai em 41 dos 42 municipios do freitas.

    ⚠️ UMA REQUISICAO POR PROJETO TERRITORIAL, e o cache e o que a torna
    suportavel — em Santa Maria sao 365 projetos so no territorio (~135 s). So
    e consultado para quem entrou PELA geometria: projeto que casou por CNPJ e
    da prefeitura por definicao, e a abrangencia nao muda isso.
    """
    if pid in _ABRANG_CACHE:
        return _ABRANG_CACHE[pid]
    try:
        d = _pagina_de(client, "geometria", {"id_projeto_investimento": pid}, 1)
        n = int((d or {}).get("total_items") or 0) or None
    except Exception as e:
        log.warning("    abrangencia de %s falhou: %s", pid, str(e)[:80])
        n = None
    _ABRANG_CACHE[pid] = n
    return n


def cnpjs_do_projeto(p: dict) -> set[str]:
    """CNPJs de 14 digitos em tomadores e executores (armadilhas 2 e 3).

    ⚠️ Cada lista tem o SEU nome de campo (`cnpj_tomador`, `cnpj_executor`) —
    nao ha um `codigo` generico como na API antiga. Ler o campo errado devolve
    conjunto vazio e o municipio fica sem nenhuma obra, em silencio."""
    out = set()
    for lista, campo in (("tomadores", "cnpj_tomador"),
                         ("executores", "cnpj_executor")):
        for x in (p.get(lista) or []):
            c = _so_digitos(x.get(campo))
            # Orgao federal aparece com codigo SIAFI/UG curto (36210), que nao
            # casa com CNPJ nenhum e cai fora pelo comprimento.
            if len(c) == 14:
                out.add(c)
    return out


def _alvos(cur) -> dict[str, list[dict]]:
    """{uf: [municipios]} com os CNPJs conhecidos de cada um.

    Mesma descoberta do `che_rs.py`: a prefeitura vem de `municipios.cnpj` e as
    demais entidades (tipicamente o Fundo Municipal de Saude) saem das fontes
    federais ja coletadas."""
    cur.execute("""
        SELECT id, nome, upper(coalesce(uf,'')),
               regexp_replace(coalesce(cnpj,''), '\\D', '', 'g'),
               coalesce(ibge_code, '')
          FROM municipios
         WHERE active AND coalesce(uf,'') <> ''
         ORDER BY nome
    """)
    # `ibge` entra aqui desde 07/09/2026: e a chave do filtro territorial do
    # `/geometria`, que o CNPJ nao substitui (ver `projetos_do_territorio`).
    municipios = [{"id": r[0], "nome": r[1], "uf": r[2], "cnpjs": set(),
                   "ibge": r[4]}
                  for r in cur.fetchall()]
    proprio = {m["id"]: m for m in municipios}
    ids = list(proprio)
    cur.execute("""
        SELECT id, regexp_replace(coalesce(cnpj,''), '\\D', '', 'g')
          FROM municipios WHERE active
    """)
    cnpj_proprio = {r[0]: r[1] for r in cur.fetchall()}

    extras: dict[int, set[str]] = {}
    if ids:
        cur.execute("""
            SELECT DISTINCT municipio_id, cnpj FROM (
                SELECT s.municipio_id,
                       regexp_replace(coalesce(s.nu_cnpj,''), '\\D', '', 'g') AS cnpj
                  FROM sismob_obras s WHERE s.municipio_id = ANY(%s)
                UNION
                SELECT p.municipio_id,
                       regexp_replace(coalesce(p.cnpj,''), '\\D', '', 'g')
                  FROM transferegov_pac p WHERE p.municipio_id = ANY(%s)
            ) t WHERE length(cnpj) = 14
        """, (ids, ids))
        for mid, cnpj in cur.fetchall():
            extras.setdefault(mid, set()).add(cnpj)

    por_uf: dict[str, list[dict]] = {}
    for m in municipios:
        if len(cnpj_proprio.get(m["id"]) or "") == 14:
            m["cnpjs"].add(cnpj_proprio[m["id"]])
        m["cnpjs"] |= extras.get(m["id"], set())
        if m["cnpjs"]:
            por_uf.setdefault(m["uf"], []).append(m)
        else:
            log.info("  %s/%s: sem CNPJ conhecido — nao da para reconhecer as "
                     "obras dele (rode ingestion/siconfi.py, que preenche)",
                     m["nome"], m["uf"])
    return por_uf


_SQL = """
INSERT INTO obrasgov_projetos (
    municipio_id, id_unico, nome, descricao, funcao_social, meta_global,
    natureza, especie, situacao, uf, cep, endereco,
    data_inicial_prevista, data_final_prevista, data_inicial_efetiva,
    data_final_efetiva, data_situacao, data_cadastro,
    populacao_beneficiada, empregos_gerados, valor_investimento_previsto,
    origens_recurso, eixos, tipos, tomadores, executores, repassadores,
    sistema_origem, raw_data, atualizado_em,
    vinculo, cod_ibge_geometria, abrangencia_municipios)
VALUES (%(mid)s, %(uid)s, %(nome)s, %(desc)s, %(social)s, %(meta)s,
        %(natureza)s, %(especie)s, %(situacao)s, %(uf)s, %(cep)s, %(end)s,
        %(dt_ini_prev)s, %(dt_fim_prev)s, %(dt_ini_efe)s, %(dt_fim_efe)s,
        %(dt_sit)s, %(dt_cad)s, %(pop)s, %(empregos)s, %(valor)s,
        %(origens)s, %(eixos)s, %(tipos)s, %(tomadores)s, %(executores)s,
        %(repassadores)s, %(sistema)s, %(raw)s::jsonb, NOW(),
        %(vinculo)s, %(cod_ibge_geo)s, %(abrangencia)s)
-- ⚠️ A CHAVE INCLUI O MUNICIPIO desde 07/09/2026: obra intermunicipal (e,
-- com o vinculo territorial, toda rodovia federal) pertence a varios da
-- carteira, e com `id_unico` global a ultima gravacao apagava as outras.
ON CONFLICT (municipio_id, id_unico) DO UPDATE SET
    nome = EXCLUDED.nome,
    descricao = EXCLUDED.descricao, funcao_social = EXCLUDED.funcao_social,
    meta_global = EXCLUDED.meta_global, natureza = EXCLUDED.natureza,
    especie = EXCLUDED.especie, situacao = EXCLUDED.situacao, uf = EXCLUDED.uf,
    cep = EXCLUDED.cep, endereco = EXCLUDED.endereco,
    data_inicial_prevista = EXCLUDED.data_inicial_prevista,
    data_final_prevista = EXCLUDED.data_final_prevista,
    data_inicial_efetiva = EXCLUDED.data_inicial_efetiva,
    data_final_efetiva = EXCLUDED.data_final_efetiva,
    data_situacao = EXCLUDED.data_situacao, data_cadastro = EXCLUDED.data_cadastro,
    populacao_beneficiada = EXCLUDED.populacao_beneficiada,
    empregos_gerados = EXCLUDED.empregos_gerados,
    valor_investimento_previsto = EXCLUDED.valor_investimento_previsto,
    origens_recurso = EXCLUDED.origens_recurso, eixos = EXCLUDED.eixos,
    tipos = EXCLUDED.tipos, tomadores = EXCLUDED.tomadores,
    executores = EXCLUDED.executores, repassadores = EXCLUDED.repassadores,
    sistema_origem = EXCLUDED.sistema_origem,
    raw_data = EXCLUDED.raw_data, atualizado_em = NOW(),
    vinculo = EXCLUDED.vinculo,
    cod_ibge_geometria = EXCLUDED.cod_ibge_geometria,
    abrangencia_municipios = EXCLUDED.abrangencia_municipios
"""


def _lista(itens, *campos) -> list[str]:
    """Nomes de uma lista aninhada, tentando os campos na ordem dada."""
    fora = []
    for x in (itens or []):
        for c in campos:
            v = _texto(x.get(c))
            if v:
                fora.append(v)
                break
    return fora


def _data(v):
    """`None` continua `None`: data efetiva vazia e "ainda nao aconteceu"."""
    s = str(v or "").strip()
    return s[:10] if s else None


def linha(municipio_id: int, p: dict, vinculo: str = "prefeitura",
          cod_ibge: str | None = None, abrangencia: int | None = None) -> dict:
    """Uma linha do banco a partir do projeto da API nova.

    `vinculo` / `cod_ibge` / `abrangencia` NAO saem do payload — eles descrevem
    COMO aquele projeto foi ligado a este municipio, e isso e decisao do
    coletor. Ver `ABRANGENCIA_MAX` para o que cada valor significa.

    ⚠️ TODOS os nomes de campo mudaram com o host (camelCase -> snake_case, e
    varios renomeados: `nome` -> `desc_nome`, `fontesDeRecurso` ->
    `investimentos_previstos`). Ler um campo antigo devolve `None` sem erro
    nenhum — a linha grava vazia e ninguem percebe."""
    invest = p.get("investimentos_previstos") or []
    # A fonte traz uma linha por origem (Federal, Estadual, Municipal).
    valor = None
    for f in invest:
        v = f.get("vl_investimento_previsto")
        if isinstance(v, (int, float)):
            valor = (valor or 0) + v
    eixos_tipos = p.get("eixos_tipos") or []
    return {
        "mid": municipio_id,
        "uid": p.get("id_projeto_investimento"),
        "nome": _texto(p.get("desc_nome")),
        "desc": _texto(p.get("desc_projeto")),
        "social": _texto(p.get("desc_funcao_social")),
        "meta": _texto(p.get("desc_meta_global")),
        "natureza": p.get("natureza_intervencao"),
        "especie": p.get("especie_intervencao"),
        "situacao": p.get("situacao"),
        "uf": p.get("uf_principal"),
        "cep": str(p.get("nr_cep") or "").strip() or None,
        "end": _texto(p.get("desc_endereco")),
        "dt_ini_prev": _data(p.get("dt_inicial_prevista")),
        "dt_fim_prev": _data(p.get("dt_final_prevista")),
        "dt_ini_efe": _data(p.get("dt_inicial_efetiva")),
        "dt_fim_efe": _data(p.get("dt_final_efetiva")),
        # A API nova nao publica data da situacao; o campo fica nulo em vez de
        # receber a de cadastro, que responderia outra pergunta.
        "dt_sit": None,
        "dt_cad": _data(p.get("dt_cadastro")),
        "pop": p.get("populacao_beneficiada"),
        "empregos": p.get("qtd_empregos_gerados"),
        "valor": valor,
        "origens": [_texto(f.get("desc_nome_fonte_recurso")) or ""
                    for f in invest],
        "eixos": _lista(eixos_tipos, "eixo"),
        "tipos": _lista(eixos_tipos, "tipo"),
        "tomadores": _lista(p.get("tomadores"), "organizacao_tomador"),
        "executores": _lista(p.get("executores"), "organizacao_executor"),
        "repassadores": _lista(p.get("repassadores"), "organizacao_repassador"),
        # Armadilha 4: diz se a obra ja chega por outro coletor nosso.
        "sistema": p.get("sistema_resp"),
        "raw": json.dumps(p, ensure_ascii=False),
        "vinculo": vinculo,
        # So preenchido quando o vinculo veio da geometria: e a PROVA de que o
        # municipio saiu do Governo, e nao de um casamento por CNPJ nosso.
        "cod_ibge_geo": int(cod_ibge) if str(cod_ibge or "").isdigit() else None,
        "abrangencia": abrangencia,
    }


# ---------------------------------------------------------------------------
# DETALHE: os cinco endpoints que a API publica e o coletor nao lia
# ---------------------------------------------------------------------------
# ⭐ VARRE A FONTE INTEIRA E CASA EM MEMORIA, em vez de perguntar projeto a
# projeto. A escolha e de custo, e foi medida em 07/09/2026:
#
#     por projeto: 5 requisicoes cada. Santa Maria (436 projetos) = 2.180
#                  requisicoes = ~13 min. Freitas (565) = ~17 min. E cresce com
#                  a carteira, entao o pior tenant define o teto da task.
#     varrer tudo: 1.278 paginas nos cinco endpoints = ~450 s, SEMPRE — nao
#                  importa se o tenant tem 1 municipio ou 60.
#
# Medido de verdade: `/contrato` inteiro (39 paginas) em 14,3 s, 0,37 s por
# pagina. Os outros quatro sao extrapolacao dessa taxa.
#
# ⚠️ SEQUENCIAL, e por decisao do dono (07/09/2026) mesmo depois de a VPS virar
# 8 nucleos. O gargalo nao e CPU — sao 0,37 s de ida e volta ate o Governo, com
# a maquina parada esperando. Paralelizar cortaria o tempo, mas e exatamente o
# que a skill `ingestion` proibe ("Never raise scraping concurrency"), e o custo
# de errar contra fonte federal ja foi pago duas vezes (TCE-RS e Especiais).
# ⚠️ TETO PROPRIO, e MAIOR que o `TETO_PAGINAS` da varredura por UF. Medido em
# 07/09/2026: `/empenho` tem 89.477 linhas = 448 paginas, e o teto de 400 cortou
# a varredura em 80.000 — o coletor gravaria empenho faltando e diria apenas
# "PARCIAL" numa linha de log. 700 cobre o maior endpoint com folga e continua
# sendo guarda contra laco infinito.
TETO_PAGINAS_DETALHE = int(os.getenv("OBRASGOV_TETO_PAGINAS_DETALHE", "700") or "700")

# ⭐ DOIS GRUPOS, E SO UM DOS CAROS POR RODADA. O custo real, medido contra a
# fonte (a estimativa de 450s errou por mais do dobro):
#
#     execucao-fisica ...... 384s    71.743 linhas
#     empenho .............. 301s    89.477 linhas
#     estudo-viabilidade ... 276s    78.227 linhas
#     contrato .............. 30s     7.624 linhas
#     historico-paralisada .. 29s     8.000 linhas
#     ------------------------------------------
#     TODOS ............... 1.020s
#
# Varrer os cinco toda noite seria ~17 min POR TENANT, e os cinco tenants
# baixariam as mesmas 1.278 paginas da mesma fonte federal todo dia. Os dois
# baratos custam 60s juntos e vao sempre; os tres caros entram em rodizio, um
# por rodada — cada um se atualiza a cada tres dias, que e frequencia de sobra
# para percentual de obra e nota de empenho.
_DETALHE_SEMPRE = (
    ("contrato", "contratos"),
    ("historico-situacao-cancelada-paralisada", "paralisacao"),
)
_DETALHE_RODIZIO = (
    ("execucao-fisica", "execucao"),
    ("empenho", "empenhos"),
    ("estudo-viabilidade", "estudo"),
)


def _detalhe_da_rodada(dia: int | None = None) -> tuple[tuple[str, str], ...]:
    """Os endpoints desta rodada: os dois baratos + UM dos caros, por rodizio.

    O rodizio e pelo dia do ano, entao ele avanca sozinho e nao precisa de
    estado no banco. Funcao PURA para o teste poder percorrer os tres dias.
    """
    import datetime
    d = dia if dia is not None else datetime.date.today().timetuple().tm_yday
    return _DETALHE_SEMPRE + (_DETALHE_RODIZIO[d % len(_DETALHE_RODIZIO)],)


def _num(v):
    return v if isinstance(v, (int, float)) else None


def _soma(itens, campo) -> float | None:
    """Soma um campo numerico da lista. `None` quando NENHUM item tinha valor —
    zero e uma afirmacao ("nao foi empenhado nada") que so pode ser feita quando
    a fonte de fato disse zero."""
    vistos = [x.get(campo) for x in itens if isinstance(x.get(campo), (int, float))]
    return round(sum(vistos), 2) if vistos else None


def coletar_detalhe(client: httpx.Client, ids: set[str]) -> dict[str, dict]:
    """Detalhe dos projetos em `ids`, varrendo os cinco endpoints inteiros.

    Devolve {id_projeto: {execucao, empenhos, contratos, paralisacao, estudo}},
    so com os projetos pedidos — o resto da fonte e descartado na hora, para a
    varredura da base nacional nao virar memoria.
    """
    fora: dict[str, dict] = {}
    if not ids:
        return fora
    for caminho, chave in _detalhe_da_rodada():
        t0 = time.time()
        # ⚠️ FILTRA PAGINA A PAGINA, e nao no fim. `/empenho` sozinho tem 89.477
        # linhas: acumular a fonte inteira para depois jogar 99% fora seria
        # carregar dezenas de MB de JSON por endpoint sem precisar. Aqui so
        # sobrevive o que e da carteira.
        vistas = casadas = 0
        n, total_pages, completo = 1, None, True
        while n <= TETO_PAGINAS_DETALHE:
            d = _pagina_de(client, caminho, {}, n)
            if d is None:
                log.warning("  detalhe %s: rate limit na pagina %d — PARCIAL",
                            caminho, n)
                completo = False
                break
            for x in (d.get("data") or []):
                vistas += 1
                pid = x.get("id_projeto_investimento")
                if pid in ids:
                    fora.setdefault(pid, {}).setdefault(chave, []).append(x)
                    casadas += 1
            if total_pages is None:
                total_pages = d.get("total_pages") or 1
            if n >= total_pages:
                break
            n += 1
            time.sleep(PAUSA_S)
        else:
            completo = False
        log.info("  detalhe %-40s %6d linha(s) na fonte, %4d da carteira, %5.1fs%s",
                 caminho, vistas, casadas, time.time() - t0,
                 "" if completo else "  ⚠️ PARCIAL")
    return fora


def linha_detalhe(pid: str, d: dict) -> dict:
    """As colunas de detalhe de UM projeto, a partir do que `coletar_detalhe` juntou.

    ⚠️ O QUE VIRA COLUNA E O QUE A TELA ORDENA E SOMA; o resto fica em JSONB.
    Mesmo desenho de `transferegov_te.pagamentos` e `transferegov_propostas.
    ops_obs` — evita cinco tabelas e um JOIN por endpoint para servir uma linha.
    """
    execucao = d.get("execucao") or []
    empenhos = d.get("empenhos") or []
    # A execucao fisica tem uma linha por medicao: vale a MAIS RECENTE, e a
    # ordem da fonte nao e garantida.
    atual = max(execucao, key=lambda x: str(x.get("dt_cadastro_execucao") or ""),
                default=None) if execucao else None
    return {
        "pid": pid,
        # ⚠️ `percentual_execucao_FISICA`, e o sufixo nao e detalhe: escrevi
        # `percentual_execucao` no #408 e a coluna ficou NULA em 538 de 538
        # obras do freitas por tres dias, sem erro em log nenhum — `.get()`
        # de chave inexistente devolve None, que aqui e indistinguivel de
        # "a fonte nao mediu esta obra". Ver `test_os_nomes_dos_campos_...`.
        "pct": _num((atual or {}).get("percentual_execucao_fisica")),
        "dt_exec": _data((atual or {}).get("dt_cadastro_execucao")),
        "empenhado": _soma(empenhos, "valor_empenho"),
        "liquidado": _soma(empenhos, "liquidado"),
        "pago": _soma(empenhos, "pago"),
        # Restos a pagar: a fonte separa inscrito, a liquidar, liquidado e pago.
        # O que interessa na tela e o INSCRITO — quanto ficou para o ano que vem.
        "restos": _soma(empenhos, "rpinscrito"),
        "empenhos": json.dumps(empenhos, ensure_ascii=False) if empenhos else None,
        "contratos": (json.dumps(d["contratos"], ensure_ascii=False)
                      if d.get("contratos") else None),
        "paralisacao": (json.dumps(d["paralisacao"], ensure_ascii=False)
                        if d.get("paralisacao") else None),
        "estudo": (json.dumps(d["estudo"], ensure_ascii=False)
                   if d.get("estudo") else None),
    }


_SQL_DETALHE = """
UPDATE obrasgov_projetos SET
    percentual_execucao = %(pct)s, data_execucao = %(dt_exec)s,
    valor_empenhado = %(empenhado)s, valor_liquidado = %(liquidado)s,
    valor_pago = %(pago)s, valor_restos_pagar = %(restos)s,
    empenhos = %(empenhos)s::jsonb, contratos = %(contratos)s::jsonb,
    paralisacao = %(paralisacao)s::jsonb,
    estudo_viabilidade = %(estudo)s::jsonb,
    detalhe_atualizado_em = NOW()
 WHERE id_unico = %(pid)s
"""


def _log_ingest(cur, conn, status: str, n: int, erro: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES ('obrasgov', %s, %s, %s, NOW())",
            (status, n, erro))
        conn.commit()
    except Exception as e:
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def ingest(dry: bool = False) -> int:
    from datetime import datetime

    from ingestion._resilience import get_sync_db_url, neon_connect

    t_inicio = time.time()
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            if not dry and os.getenv("OBRASGOV_FORCE") != "1":
                cur.execute("SELECT max(finished_at) FROM ingestion_log "
                            "WHERE source = 'obrasgov' AND status IN ('success','ok')")
                ultimo = (cur.fetchone() or [None])[0]
                if ultimo:
                    horas = (datetime.now(ultimo.tzinfo) - ultimo).total_seconds() / 3600
                    if horas < MIN_INTERVAL_H:
                        log.info("ultima coleta ha %.1fh (< %dh) — pulando. "
                                 "OBRASGOV_FORCE=1 forca.", horas, MIN_INTERVAL_H)
                        return 0

            por_uf = _alvos(cur)
            if not por_uf:
                log.info("nenhum municipio com CNPJ conhecido — nada a reconhecer")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0

            gravados = 0
            parciais = []
            # Ids dos projetos que ficaram no banco — a fase de detalhe so
            # guarda o que e da carteira e descarta o resto da base nacional.
            da_carteira: set[str] = set()
            with httpx.Client(follow_redirects=True) as client:
                for uf, municipios in sorted(por_uf.items()):
                    log.info("UF %s: %d municipio(s) na carteira", uf, len(municipios))
                    projetos, completo = varrer_uf(client, uf)
                    if not completo:
                        parciais.append(uf)
                    # Indice CNPJ -> municipio, montado uma vez (armadilha 2).
                    de_quem: dict[str, dict] = {}
                    for m in municipios:
                        for c in m["cnpjs"]:
                            de_quem[c] = m
                    # ⭐ O TERRITORIO, ANTES DO CNPJ. Para cada municipio da UF,
                    # o `/geometria?cod_ibge=` diz quais projetos ficam nele —
                    # dado do Governo, nao inferencia nossa. Ver
                    # `projetos_do_territorio`.
                    no_territorio: dict[str, set[int]] = {}
                    ibge_de: dict[int, str] = {}
                    for m in municipios:
                        if not m.get("ibge"):
                            continue
                        ibge_de[m["id"]] = m["ibge"]
                        for pid_geo in projetos_do_territorio(client, m["ibge"]):
                            no_territorio.setdefault(pid_geo, set()).add(m["id"])
                        time.sleep(PAUSA_S)
                    if no_territorio:
                        log.info("  %s: geometria aponta %d projeto(s) no territorio "
                                 "da carteira", uf, len(no_territorio))

                    # ⚠️ A VARREDURA DA UF NAO TRAZ TUDO O QUE A GEOMETRIA
                    # APONTA: ela filtra por `uf_principal`, e ha projeto cuja
                    # `uf_principal` e outra (ver `projeto_por_id`). O que falta
                    # e buscado um a um — sao poucos, e sem isso a obra some.
                    faltando = [x for x in no_territorio if x not in projetos]
                    if faltando:
                        log.info("  %s: %d projeto(s) do territorio fora da "
                                 "varredura da UF — buscando um a um", uf, len(faltando))
                        for pid_falta in faltando:
                            achado = projeto_por_id(client, pid_falta)
                            if achado:
                                projetos[pid_falta] = achado
                            time.sleep(PAUSA_S)

                    achados = 0
                    por_municipio: dict[str, int] = {}
                    nomes = {m["id"]: m["nome"] for m in municipios}
                    # Uniao dos dois caminhos: quem casa por CNPJ e quem so a
                    # geometria aponta. Nenhum substitui o outro.
                    for uid, p in projetos.items():
                        donos: dict[int, str] = {
                            de_quem[c]["id"]: "prefeitura"
                            for c in cnpjs_do_projeto(p) if c in de_quem}
                        for mid in no_territorio.get(uid, ()):
                            donos.setdefault(mid, "territorio")
                        if not donos:
                            continue
                        # Quantos municipios do BRASIL tem geometria deste
                        # projeto — o que separa obra local de guarda-chuva.
                        abrang = _abrangencia(client, uid) if uid in no_territorio else None
                        for mid, tipo in donos.items():
                            if tipo == "territorio" and abrang and abrang > ABRANGENCIA_MAX:
                                tipo = "abrangencia"
                            achados += 1
                            nome = nomes.get(mid, str(mid))
                            por_municipio[nome] = por_municipio.get(nome, 0) + 1
                            if dry:
                                continue
                            cur.execute(_SQL, linha(
                                mid, p, vinculo=tipo,
                                cod_ibge=ibge_de.get(mid) if tipo != "prefeitura" else None,
                                abrangencia=abrang))
                            gravados += 1
                            da_carteira.add(uid)
                    log.info("  %s: %d projeto(s) varrido(s), %d da carteira%s",
                             uf, len(projetos), achados,
                             (" — " + ", ".join(f"{k}: {v}" for k, v in
                                                sorted(por_municipio.items())))
                             if por_municipio else "")
                    if dry:
                        for p in list(projetos.values())[:3]:
                            log.info("      %s  %s", p.get("id_projeto_investimento"),
                                     (p.get("desc_nome") or "")[:60])

            if dry:
                return 0
            conn.commit()

            # --- FASE 2: o detalhe dos cinco endpoints -----------------------
            # ⚠️ DEPOIS do commit dos projetos, e de proposito: a fase de
            # detalhe faz UPDATE sobre linhas que precisam existir, e uma falha
            # dela nao pode desfazer a coleta que ja deu certo. Mesma disciplina
            # da fase de pagamentos da Transferencia Especial.
            sobra = TETO_TAREFA_S - (time.time() - t_inicio)
            if not da_carteira or os.getenv("OBRASGOV_DETALHE", "1") == "0":
                pass
            elif sobra < DETALHE_MIN_S:
                # Nao e falha: a varredura de projetos ja esta gravada e o
                # detalhe entra amanha. Melhor pular inteiro do que ser morto
                # no meio e perder o log da rodada.
                log.warning("detalhe PULADO: sobraram %.0fs do teto de %.0fs e a "
                            "fase precisa de ~%.0fs", sobra, TETO_TAREFA_S,
                            DETALHE_MIN_S)
            else:
                try:
                    with httpx.Client(follow_redirects=True) as client:
                        detalhe = coletar_detalhe(client, da_carteira)
                    n_det = 0
                    for pid, d in detalhe.items():
                        cur.execute(_SQL_DETALHE, linha_detalhe(pid, d))
                        n_det += cur.rowcount
                    conn.commit()
                    log.info("  detalhe: %d linha(s) de projeto enriquecida(s) "
                             "(de %d da carteira)", n_det, len(da_carteira))
                except Exception as e:
                    conn.rollback()
                    log.warning("detalhe falhou (a coleta de projetos ja esta "
                                "gravada): %s: %s", type(e).__name__, str(e)[:160])

            log.info("=== Obras.gov.br: %d linha(s) gravada(s)%s ===", gravados,
                     f", PARCIAL em {', '.join(parciais)}" if parciais else "")
            if parciais:
                # ⚠️ Varredura interrompida por rate limit NAO e sucesso: a
                # ausencia de uma obra pode ser nossa, nao da fonte.
                _log_ingest(cur, conn, "partial", gravados,
                            "varredura interrompida por rate limit (429) em: "
                            + ", ".join(parciais))
            else:
                _log_ingest(cur, conn, "success", gravados)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("Obras.gov.br falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    # ⚠️ SEM ISTO O LOG DA RODADA VIRA LIXO. A fase de detalhe faz ~1.278
    # requisicoes (as cinco varreduras completas), e o httpx loga cada uma em
    # INFO: o resultado da coleta ficaria enterrado sob mil linhas de
    # "HTTP Request: GET ... 200 OK". Mesmo tratamento que `sismob_obras` e
    # `run_fns_local` ja dao.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest(dry="--dry" in sys.argv)
