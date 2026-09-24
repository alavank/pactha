"""
Convênios do ESTADO DO TOCANTINS com o município -> convenios_estadual (fonte TRANSFERE-TO).

O TRANSFERE.TO é o sistema de convênios e parcerias do Estado (CGE-TO). A área do
convenente pede login, mas a PESQUISA EXTERNA é aberta, sem login e sem captcha:

    https://convenio.to.gov.br/PesquisaExterna/VisualizarConvenio.aspx?idConvenio=N

Uma página por convênio (~40 KB, 0,45 s medido da VPS em 23/09/2026), com número,
situação, órgão concedente, CNPJ e nome do convenente, objeto, ação orçamentária,
vigência, valor, contrapartida depositada, aditivos, prestação de contas e — o que
nenhuma outra fonte estadual nossa tem — a PROGRAMAÇÃO FINANCEIRA: nota de empenho,
liquidação, programa de desembolso e ORDEM BANCÁRIA, cada uma com data e valor. O
repasse real do Estado é a soma das OBs.

AS ARMADILHAS, todas medidas contra a fonte em 23/09/2026:

1. ⚠️ **O CARTÃO DO RELATÓRIO APONTA DUAS PORTAS ERRADAS.** `gestao.cge.to.gov.br/
   convenioseparcerias` cai no LOGIN; o Portal da Transparência (`transparencia.to.gov.br`)
   é um app Vaadin que devolve 403 a navegador headless. A pesquisa externa só aparece
   atrás do botão "CONSULTA DE EMENDAS" do portal — e `ConsultarConvenios.aspx`, ao lado,
   foi achada por tentativa. A listagem é WebForms com VIEWSTATE e leva ~24 s por página
   de 10; o detalhe por id é GET simples. Por isso a coleta VARRE os ids.

2. ⚠️ **ID INEXISTENTE É 302 PARA /erro_500.aspx**, não 404. Os ids não são
   contíguos: a varredura para depois de `FOLGA` ids seguidos sem convênio além do
   último achado (e nunca antes de `ID_MINIMO`, o teto medido na carga).

3. ⚠️ **A PÁGINA MISTURA CODIFICAÇÕES.** Os campos do topo vêm em UTF-8 ("PRODUÇÃO")
   e as grades em Latin-1 ("LIQUIDA\\xc7\\xc3O"), na MESMA resposta. `decodifica` lê
   UTF-8 e cai para cp1252 só nos bytes inválidos.

4. ⚠️ **"VALOR DO CONVÊNIO" JÁ INCLUI A CONTRAPARTIDA.** Crixás, id 1200: R$ 135.000,00
   = R$ 100.000,00 do Estado (a OB) + R$ 35.000,00 depositados pela prefeitura. Por isso
   ele vai em `valor_total`, e `valor_concedente` fica vazio: a fonte não publica a
   parte do Estado separada. O repassado é a soma das OBs.

5. ⚠️ **NÃO HÁ MUNICÍPIO NA PÁGINA — SÓ CNPJ E NOME DO CONVENENTE.** A prefeitura é
   ligada pelo CNPJ (`municipios.cnpj`, que o SICONFI preenche). O que não casa pelo
   CNPJ (fundo municipal, entidade) é ligado pelo NOME contra os 139 municípios do TO
   do IBGE, escolhendo o MAIS LONGO que aparece como palavra inteira: "SÃO VALÉRIO DA
   NATIVIDADE" contém "NATIVIDADE", que também é município. Ente municipal (prefeitura,
   município, fundo municipal) entra em `convenios_estadual`; o resto (APAE, associação)
   vai para `convenios_estadual_outros`, fora das somas — a regra do dono: nada é
   descartado, nada entra na conta como se fosse da prefeitura. Sem a lista do IBGE, só
   a regra do CNPJ vale e a rodada é `partial`.

6. ⚠️ **O DETALHE NÃO DIZ O TIPO DE INSTRUMENTO** (a listagem diz "TERMO DE PARCERIA"
   para convênios de prefeitura). `tp_instrumento` fica vazio em vez de chutar
   "Convênio".

7. ⚠️ **O REPASSADO PODE PASSAR DO "VALOR DO CONVÊNIO" — e está certo.** O valor é o
   ORIGINAL; emenda posterior soma recurso sem atualizá-lo. Id 104: R$ 120.000,00 de
   valor, uma 2ª emenda (010412.00140/2022) e OBs de R$ 121.125,00. Foram 12 de 280 na
   primeira amostra. A soma das OBs é o dinheiro que saiu; não é "corrigida".

8. ⭐ **O VÍNCULO COM A EMENDA ESTADUAL ESTÁ NA GRADE "ORIGEM"** (tipo `EMENDA`, com o
   número da emenda no TRANSFERE.TO — 351 linhas nos primeiros 280 convênios). Vai em
   `raw_data.emendas` (sem repetição: a fonte lista a mesma emenda duas vezes).

9. ⚠️ **A ASSINATURA MAIS RECENTE É A DO ÚLTIMO ADITIVO, NÃO A DA CELEBRAÇÃO.** A grade
   "Registro de Assinatura" tem um par por ato, fora de ordem. Usar a maior data pôs o
   convênio 29010.000015/2020 (id 104) em 2022 — e errava o ano em 364 de 1.629
   convênios. `data_da_celebracao` pega o primeiro par; com ela, o ano bate com o do
   número do convênio em 1.621 dos 1.629.

Rodável por Scheduled Task no worker de tenant com município do TO, ou à mão:
    python -u ingestion/convenios_to.py            # coleta de verdade
    python -u ingestion/convenios_to.py --dry      # varre, casa e mostra
Envs: CONVENIOS_TO_BUDGET_S (3000), CONVENIOS_TO_PAUSA_S (0.1).
"""
from __future__ import annotations

import codecs
import html as htmllib
import json
import logging
import os
import re
import sys
import time
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("convenios_to")

BASE = "https://convenio.to.gov.br/PesquisaExterna"
IBGE_TO = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/TO/municipios"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0; dados abertos TO)"}
UF = "TO"
FONTE = "TRANSFERE-TO"     # procedência gravada em convenios_estadual.fonte
SOURCE = "convenios_to"    # nome no ingestion_log
TIMEOUT = 60
ID_MINIMO = 3200           # teto medido em 23/09/2026: a varredura nunca para antes
FOLGA = 300                # ids seguidos sem convênio, além do último achado
ERROS_SEGUIDOS_MAX = 20    # falha de rede em sequência = portal fora; para a rodada
MINIMO_CONVENIOS = 1500    # metade da base de 23/09/2026: abaixo disso, a página mudou
ORCAMENTO_S = int(os.getenv("CONVENIOS_TO_BUDGET_S") or "3000")
PAUSA_S = float(os.getenv("CONVENIOS_TO_PAUSA_S") or "0.1")


# ── leitura da página ────────────────────────────────────────────────────────

def _cp1252_nos_bytes_ruins(e: UnicodeDecodeError):
    return e.object[e.start:e.end].decode("cp1252", errors="replace"), e.end


codecs.register_error("pactha_cp1252", _cp1252_nos_bytes_ruins)


def decodifica(conteudo: bytes) -> str:
    """UTF-8 com os bytes Latin-1 das grades recuperados (armadilha 3)."""
    return conteudo.decode("utf-8", errors="pactha_cp1252")


def _limpa(s: str | None) -> str:
    t = htmllib.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return " ".join(t.split())


def _campo(pagina: str, ident: str) -> str | None:
    m = re.search(rf'id="MainContent_{ident}"[^>]*>(.*?)</(?:span|td)>', pagina, re.S)
    return (_limpa(m.group(1)) or None) if m else None


def _grade(pagina: str, ident: str) -> list[list[str]] | None:
    """Linhas de dados de uma grade (sem o cabeçalho). None = a grade não existe na
    página (≠ lista vazia, que é "NÃO HÁ REGISTROS")."""
    m = re.search(rf'<table[^>]*id="MainContent_{ident}".*?</table>', pagina, re.S)
    if not m:
        return None
    linhas = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.S):
        cel = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if cel:
            linhas.append([_limpa(c) for c in cel])
    return linhas


def _dinheiro(v: str | None) -> Decimal | None:
    s = re.sub(r"[^\d,.-]", "", v or "")
    if not s:
        return None
    try:
        return Decimal(s.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def _data(v: str | None) -> date | None:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", v or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _so_digitos(v: str | None) -> str:
    return "".join(c for c in (v or "") if c.isdigit())


def data_da_celebracao(assinaturas: list[date]) -> date | None:
    """A data em que o convênio foi celebrado, das assinaturas em ORDEM (armadilha 9).

    A grade traz um PAR por ato (Estado + convenente): a celebração e depois cada
    aditivo, fora de ordem. A celebração é o 2º assinante do primeiro par — se ele
    veio até 30 dias depois do 1º; senão o 1º par está incompleto e fica a 1ª data."""
    if not assinaturas:
        return None
    if len(assinaturas) > 1 and (assinaturas[1] - assinaturas[0]).days <= 30:
        return assinaturas[1]
    return assinaturas[0]


def ler_detalhe(pagina: str, id_convenio: int) -> dict | None:
    """A página de um convênio -> dict. None se não for página de convênio."""
    numero = _campo(pagina, "lblNumero")
    conveniado = _campo(pagina, "lblConveniado")
    if not numero or not conveniado:
        return None
    m = re.match(r"\s*([\d./-]{14,20})\s*-\s*(.+)", conveniado)
    cnpj, nome = (_so_digitos(m.group(1)), m.group(2).strip()) if m else (None, conveniado)
    vig = _campo(pagina, "lblDataVigencia") or ""
    datas = re.findall(r"\d{2}/\d{2}/\d{4}", vig)

    prog = []
    for ln in _grade(pagina, "grd_programacao_financeira") or []:
        if len(ln) >= 4:
            prog.append({"tipo": ln[0], "numero": ln[1], "data": ln[2],
                         "valor": str(_dinheiro(ln[3])) if _dinheiro(ln[3]) is not None else None})
    obs = [p for p in prog if "ORDEM BANC" in p["tipo"].upper()]
    nes = [p for p in prog if "EMPENHO" in p["tipo"].upper()]
    contra = [{"data": ln[0], "valor": str(_dinheiro(ln[1])) if _dinheiro(ln[1]) is not None else None,
               "forma": ln[2]} for ln in (_grade(pagina, "grd_contrapartidas") or []) if len(ln) >= 3]
    origem = [{"tipo": ln[0], "numero": ln[1], "data": ln[2]}
              for ln in (_grade(pagina, "grd_origem") or []) if len(ln) >= 3]
    assinaturas = sorted(d for d in (_data(ln[0]) for ln in
                                     (_grade(pagina, "grd_assinaturas") or []) if ln) if d)

    if obs:
        repassado = sum((Decimal(o["valor"]) for o in obs if o["valor"]), Decimal("0"))
    elif (_grade(pagina, "grd_programacao_financeira") is not None
          or 'id="MainContent_panSemRegistroProgramacaoFinanceira"' in pagina):
        # A fonte AFIRMA que não há OB (grade só com NE/NL, ou o aviso "NÃO HÁ
        # REGISTROS"): zero é o dado. Sem grade E sem aviso, a página mudou de
        # forma — aí fica vazio, não zero.
        repassado = Decimal("0")
    else:
        repassado = None

    pc_num = _campo(pagina, "td_prestacao_contas_numero")
    return {
        "id_convenio": id_convenio,
        "numero": numero,
        "cnpj": cnpj if cnpj and len(cnpj) == 14 else None,
        "convenente": nome,
        "situacao": _campo(pagina, "lblSituacao"),
        "orgao": _campo(pagina, "lblOrgaoConcedente"),
        "objeto": _campo(pagina, "lblFinalidade"),
        "acao": _campo(pagina, "lblAcaoOrcamentaria"),
        "abertura": _data(_campo(pagina, "lblDataAbertura")),
        "vig_ini": _data(datas[0]) if datas else None,
        "vig_fim": _data(datas[1]) if len(datas) > 1 else None,
        "valor": _dinheiro(_campo(pagina, "lblValorConvenio")),
        "repassado": repassado,
        "assinatura": data_da_celebracao(assinaturas),
        "dt_empenho": min((_data(n["data"]) for n in nes if _data(n["data"])), default=None),
        "dt_desembolso": max((_data(o["data"]) for o in obs if _data(o["data"])), default=None),
        "programacao_financeira": prog,
        "contrapartidas": contra,
        "origem": origem,
        "prestacao_contas": {
            "numero": pc_num,
            "situacao": _campo(pagina, "td_prestacao_contas_situacao"),
        } if pc_num else None,
    }


# ── de quem é o convênio ─────────────────────────────────────────────────────

def _norm(s: str | None) -> str:
    t = unicodedata.normalize("NFD", (s or "").upper())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", t).split())


def e_ente_municipal(nome: str | None) -> bool:
    t = _norm(nome)
    # "FMS DE CRIXÁS" é o Fundo Municipal de Saúde; "FUNDO MUNICIAL" é erro de
    # digitação da fonte; a secretaria municipal é a própria prefeitura (carga de
    # 23/09/2026). A CÂMARA fica de fora, como no PR: não é o Executivo.
    return t.startswith(("MUNICIPIO", "PREFEITURA", "FUNDO MUNIC", "FMS ",
                         "SECRETARIA MUNICIPAL"))


def apelidos(nomes: list[str]) -> dict[str, str]:
    """{apelido: nome oficial}. O convenente escreve "MARIANÓPOLIS", "CRIXAS -TOCANTINS",
    "PINDORAMA" para municípios que o IBGE chama de "... DO TOCANTINS": o nome sem o
    sufixo vira apelido — desde que não seja o nome de OUTRO município."""
    oficiais = set(nomes)
    mapa = {n: n for n in nomes}
    for n in nomes:
        if n.endswith(" DO TOCANTINS"):
            base = n[: -len(" DO TOCANTINS")]
            if base and base not in oficiais:
                mapa.setdefault(base, n)
    return mapa


def municipio_do_nome(nome: str | None, catalogo: dict[str, str],
                      com_apelidos: bool = True) -> str | None:
    """O município do TO citado no nome do convenente — o do apelido MAIS LONGO que
    aparece como palavra inteira (armadilha 5). `catalogo` vem de `apelidos`.

    ⚠️ `com_apelidos=False` para ENTIDADE: o apelido sem "do Tocantins" acerta em
    "FUNDO MUNICIPAL DE SAÚDE DE MIRACEMA", mas pôs a "Associação ... SÃO MIGUEL
    ARCANJO" em São Miguel do Tocantins e a "Comunidade Kolping SANTA TEREZINHA do
    Bico do Papagaio" em Santa Terezinha do Tocantins (carga de 23/09/2026)."""
    t = _norm(nome)
    achados = [a for a, oficial in catalogo.items()
               if a and (com_apelidos or a == oficial)
               and re.search(rf"\b{re.escape(a)}\b", t)]
    return catalogo[max(achados, key=len)] if achados else None


def catalogo_to(client: httpx.Client) -> dict[str, str] | None:
    """Os 139 municípios do TO pelo IBGE, com apelidos. Falha devolve None."""
    try:
        r = client.get(IBGE_TO, headers=UA, timeout=60)
        r.raise_for_status()
        nomes = [_norm(x["nome"]) for x in r.json()]
    except Exception as e:
        log.warning("lista de municípios do TO no IBGE indisponível (%s) — só a regra "
                    "do CNPJ nesta rodada", type(e).__name__)
        return None
    return apelidos(nomes) if len(nomes) > 130 else None


def classifica(det: dict, alvos: list[dict], catalogo: dict[str, str] | None
               ) -> tuple[dict | None, bool]:
    """(alvo, municipal?) do convênio; (None, False) se não é de município nosso."""
    if det.get("cnpj"):
        for a in alvos:
            if a["cnpj"] and a["cnpj"] == det["cnpj"]:
                return a, True
    if catalogo is None:
        return None, False
    municipal = e_ente_municipal(det.get("convenente"))
    m = municipio_do_nome(det.get("convenente"), catalogo, com_apelidos=municipal)
    if not m:
        return None, False
    for a in alvos:
        if _norm(a["nome"]) == m:
            return a, municipal
    return None, False


# ── gravação ─────────────────────────────────────────────────────────────────

def registro(det: dict, municipio_id: int) -> dict:
    raw = {
        "id_convenio": det["id_convenio"],
        # A tela de Convênios lê o número publicado em `raw_data.nr_instrumento`.
        "nr_instrumento": det["numero"],
        "cnpj_convenente": det["cnpj"],
        "acao_orcamentaria": det["acao"],
        "data_abertura": det["abertura"].isoformat() if det["abertura"] else None,
        "programacao_financeira": det["programacao_financeira"],
        "contrapartidas": det["contrapartidas"],
        "origem": det["origem"],
        "emendas": sorted({o["numero"] for o in det["origem"]
                           if o["tipo"].upper() == "EMENDA" and o["numero"]}),
        "prestacao_contas": det["prestacao_contas"],
        "url": f"{BASE}/VisualizarConvenio.aspx?idConvenio={det['id_convenio']}",
    }
    ano_de = det["assinatura"] or det["vig_ini"] or det["abertura"]
    return {
        "nr": f"TO-{det['id_convenio']}",
        "mid": municipio_id,
        "convenente": (det["convenente"] or "")[:500] or None,
        "orgao": (det["orgao"] or "")[:500] or None,
        "objeto": det["objeto"],
        "situacao": (det["situacao"] or "")[:200] or None,
        "programa": (det["acao"] or "")[:100] or None,
        # Armadilha 4: o valor publicado é o total, com a contrapartida dentro.
        "v_conc": None, "v_contra": None, "v_total": det["valor"],
        "v_repassado": det["repassado"],
        "dt_pub": None,
        "dt_ini": det["vig_ini"], "dt_fim": det["vig_fim"],
        "dt_ass": det["assinatura"],
        "dt_empenho": det["dt_empenho"], "dt_desembolso": det["dt_desembolso"],
        "ano": ano_de.year if ano_de else None,
        "fonte": FONTE,
        "raw": json.dumps(raw, ensure_ascii=False),
    }


_SQL = """
INSERT INTO convenios_estadual (
    nr_sigcon, municipio_id, convenente_nome, orgao_concedente, objeto, situacao,
    tp_instrumento, tipo_programa, valor_concedente, valor_contrapartida,
    valor_total, valor_repassado, dt_publicacao, dt_vigencia_inicial,
    dt_vigencia_final, dt_vigencia_atual, dt_assinatura, dt_empenho, dt_desembolso,
    ano, fonte, raw_data, created_at, updated_at)
VALUES (
    %(nr)s, %(mid)s, %(convenente)s, %(orgao)s, %(objeto)s, %(situacao)s,
    NULL, %(programa)s, %(v_conc)s, %(v_contra)s, %(v_total)s,
    %(v_repassado)s, %(dt_pub)s, %(dt_ini)s, %(dt_fim)s, %(dt_fim)s, %(dt_ass)s,
    %(dt_empenho)s, %(dt_desembolso)s, %(ano)s, %(fonte)s, %(raw)s::jsonb, NOW(), NOW())
ON CONFLICT (nr_sigcon) DO UPDATE SET
    municipio_id = EXCLUDED.municipio_id,
    convenente_nome = EXCLUDED.convenente_nome,
    orgao_concedente = EXCLUDED.orgao_concedente,
    objeto = EXCLUDED.objeto, situacao = EXCLUDED.situacao,
    tipo_programa = EXCLUDED.tipo_programa,
    valor_total = EXCLUDED.valor_total,
    valor_repassado = EXCLUDED.valor_repassado,
    dt_vigencia_inicial = EXCLUDED.dt_vigencia_inicial,
    dt_vigencia_final = EXCLUDED.dt_vigencia_final,
    dt_vigencia_atual = EXCLUDED.dt_vigencia_atual,
    dt_assinatura = EXCLUDED.dt_assinatura,
    dt_empenho = EXCLUDED.dt_empenho,
    dt_desembolso = EXCLUDED.dt_desembolso,
    ano = EXCLUDED.ano,
    -- ⚠️ `fonte` NÃO entra no UPDATE (a regra do convenios_rs): só o INSERT
    -- define a procedência. O prefixo "TO-" já impede colisão com outra fonte.
    raw_data = EXCLUDED.raw_data,
    updated_at = NOW()
"""

_SQL_OUTROS = """
INSERT INTO convenios_estadual_outros (
    municipio_id, fonte, chave, convenente_nome, orgao_concedente, objeto, situacao,
    valor_concedente, valor_contrapartida, valor_total, valor_repassado,
    dt_assinatura, dt_vigencia_inicial, dt_vigencia_final, raw_data, atualizado_em)
VALUES (
    %(mid)s, %(fonte)s, %(nr)s, %(convenente)s, %(orgao)s, %(objeto)s, %(situacao)s,
    %(v_conc)s, %(v_contra)s, %(v_total)s, %(v_repassado)s,
    %(dt_ass)s, %(dt_ini)s, %(dt_fim)s, %(raw)s::jsonb, NOW())
ON CONFLICT (fonte, chave) DO UPDATE SET
    municipio_id = EXCLUDED.municipio_id,
    convenente_nome = EXCLUDED.convenente_nome,
    orgao_concedente = EXCLUDED.orgao_concedente,
    objeto = EXCLUDED.objeto, situacao = EXCLUDED.situacao,
    valor_total = EXCLUDED.valor_total,
    valor_repassado = EXCLUDED.valor_repassado,
    dt_assinatura = EXCLUDED.dt_assinatura,
    dt_vigencia_inicial = EXCLUDED.dt_vigencia_inicial,
    dt_vigencia_final = EXCLUDED.dt_vigencia_final,
    raw_data = EXCLUDED.raw_data,
    atualizado_em = NOW()
"""


def _alvos(cur) -> list[dict]:
    cur.execute("""
        SELECT id, nome, cnpj FROM municipios
         WHERE active AND upper(coalesce(uf, '')) = %s ORDER BY nome
    """, (UF,))
    return [{"id": r[0], "nome": r[1], "cnpj": _so_digitos(r[2]) or None}
            for r in cur.fetchall()]


def _log_ingest(cur, conn, status: str, n: int, nota: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
            (SOURCE, status, n, nota))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("ingestion_log falhou: %s", str(e)[:120])


# ── varredura ────────────────────────────────────────────────────────────────

def buscar(client: httpx.Client, id_convenio: int) -> dict | None | bool:
    """dict = convênio; None = id sem convênio (302); False = falha de rede/servidor."""
    for tentativa in (1, 2):
        try:
            r = client.get(f"{BASE}/VisualizarConvenio.aspx",
                           params={"idConvenio": id_convenio}, headers=UA, timeout=TIMEOUT)
        except httpx.HTTPError:
            if tentativa == 2:
                return False
            time.sleep(2)
            continue
        if r.status_code in (301, 302, 303, 404):
            return None
        if r.status_code != 200:
            if tentativa == 2:
                return False
            time.sleep(2)
            continue
        return ler_detalhe(decodifica(r.content), id_convenio)
    return False


def varrer(client: httpx.Client, alvos: list[dict], catalogo: dict[str, str] | None
           ) -> tuple[dict, dict, list[str], dict]:
    """Varre os ids e devolve ({nr: registro}, {nr: registro de outros}, falhas, stats).

    `falhas` não vazia = a varredura NÃO chegou ao fim (orçamento, portal fora): o
    que foi lido é gravado, mas nada é apagado."""
    achados: dict[str, dict] = {}
    outros: dict[str, dict] = {}
    falhas: list[str] = []
    st = {"ids": 0, "convenios": 0, "falhas_id": 0, "ultimo": 0}
    inicio = time.monotonic()
    i, ultimo, erros_seguidos = 1, 0, 0
    while i <= max(ID_MINIMO, ultimo + FOLGA):
        if time.monotonic() - inicio > ORCAMENTO_S:
            falhas.append(f"orçamento de {ORCAMENTO_S}s esgotado no id {i}")
            break
        det = buscar(client, i)
        st["ids"] += 1
        if det is False:
            st["falhas_id"] += 1
            erros_seguidos += 1
            if erros_seguidos >= ERROS_SEGUIDOS_MAX:
                falhas.append(f"portal fora: {erros_seguidos} falhas seguidas até o id {i}")
                break
        else:
            erros_seguidos = 0
            if det:
                ultimo = i
                st["convenios"] += 1
                alvo, municipal = classifica(det, alvos, catalogo)
                if alvo:
                    reg = registro(det, alvo["id"])
                    (achados if municipal else outros)[reg["nr"]] = reg
        i += 1
        if PAUSA_S:
            time.sleep(PAUSA_S)
    st["ultimo"] = ultimo
    if st["falhas_id"] and not falhas:
        falhas.append(f"{st['falhas_id']} id(s) sem resposta — ficam para a próxima rodada")
    # Página que mudou de forma (ou 302 para um login novo) viraria "id sem convênio"
    # em TODOS os ids: rodada `success` com zero e o bloco de entidades apagado. A
    # base tinha ~3.100 convênios em 23/09/2026; ler menos da metade é defeito.
    if not falhas and st["convenios"] < MINIMO_CONVENIOS:
        falhas.append(f"só {st['convenios']} convênio(s) lido(s) em {st['ids']} ids — "
                      "a página mudou de forma? nada foi apagado")
    return achados, outros, falhas, st


def grava_outros(cur, outros: dict, alvos: list[dict], completa: bool) -> int:
    """Grava as entidades e apaga as que a fonte deixou de publicar — MAS só com a
    varredura completa: uma interrompida esconderia linhas que continuam lá."""
    for reg in outros.values():
        cur.execute(_SQL_OUTROS, reg)
    if completa:
        for a in alvos:
            chaves = [k for k, r in outros.items() if r["mid"] == a["id"]]
            cur.execute("""
                DELETE FROM convenios_estadual_outros
                 WHERE fonte = %s AND municipio_id = %s AND NOT (chave = ANY(%s))
            """, (FONTE, a["id"], chaves))
    return len(outros)


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = _alvos(cur)
            if not alvos:
                log.info("nenhum município do TO — convênios do TO não se aplicam")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0
            with httpx.Client(follow_redirects=False) as client:
                catalogo = catalogo_to(client)
                achados, outros, falhas, st = varrer(client, alvos, catalogo)
            if catalogo is None:
                falhas.append("lista do IBGE indisponível: fundos e entidades não "
                              "foram ligados pelo nome nesta rodada")
            log.info("varridos %d id(s), %d convênio(s) no TRANSFERE.TO (último id %d)",
                     st["ids"], st["convenios"], st["ultimo"])
            for a in alvos:
                n = sum(1 for r in achados.values() if r["mid"] == a["id"])
                o = sum(1 for r in outros.values() if r["mid"] == a["id"])
                log.info("  %s: %d convênio(s) do município, %d de outro convenente "
                         "(fora das contas)", a["nome"], n, o)
            if dry:
                for reg in sorted(achados.values(), key=lambda x: str(x["dt_ass"])):
                    log.info("    %s %s | %s | %s | repassado %s de %s", reg["nr"],
                             reg["dt_ass"], (reg["orgao"] or "")[:30], reg["situacao"],
                             reg["v_repassado"], reg["v_total"])
                return 0
            for reg in achados.values():
                cur.execute(_SQL, reg)
            grava_outros(cur, outros, alvos, completa=not falhas)
            conn.commit()
            status = "partial" if falhas else "success"
            log.info("=== Convênios TO: %d gravado(s), status=%s ===", len(achados), status)
            _log_ingest(cur, conn, status, len(achados), " | ".join(falhas)[:400] or None)
            return len(achados)
        except Exception as e:
            conn.rollback()
            log.error("Convênios TO falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest(dry="--dry" in sys.argv)
