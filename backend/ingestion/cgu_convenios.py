"""
CGU / Portal da Transparência — os convênios do Executivo federal, pela planilha.

A pergunta que esta fonte responde e o TransfereGov não: **que dinheiro federal o
município tem por instrumento que NÃO passou pelo TransfereGov?** Medido em
22/09/2026, cruzando pelo CNPJ da prefeitura com o dump `siconv_convenio.zip`:

    Nova Palma   116 na CGU, 47 no TransfereGov — 10 vigentes só aqui, R$ 23,7 mi
    Santa Maria  373 na CGU, 178 no TransfereGov — 26 vigentes só aqui, R$ 178 mi
    Monte Sião / Juranda — só histórico (anterior a 2009, do SIAFI)

Os vigentes que só a CGU tem são TODOS **transferências legais da Defesa Civil**
(Lei 12.340, ações de resposta e recuperação pelo S2iD): o Obras.gov tem as OBRAS
delas, mas não o repasse — valor, quanto foi liberado, vigência e cada ordem
bancária. É esse o conteúdo novo; o resto é o histórico que o SICONV não alcança.

Fonte (sem login, sem token):
    https://portaldatransparencia.gov.br/download-de-dados/convenios   (a data)
    https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/convenios/{AAAAMMDD}_Convenios.zip
        {data}_Convenios.csv                 622.038 instrumentos (339 MB)
        {data}_Convenios_OrdensBancarias.csv 1.180.321 OBs (86 MB)

AS ARMADILHAS, medidas em 22/09/2026:

1. ⚠️ **O CARTÃO DO RELATÓRIO PROMETIA O VÍNCULO CONVÊNIO↔EMENDA, E ELE NÃO
   EXISTE.** Nem a API (`ConvenioDTO`, conferido no `/v3/api-docs` de 22/09) nem a
   planilha (27 colunas) têm campo de emenda — a auditoria de 06/09 já dizia isso
   em `portal_transparencia.py`. Não procure aqui.

2. **A API COM TOKEN NÃO ACRESCENTA NADA À PLANILHA** (mesmos campos; o filtro
   `codigoIBGE` é a única vantagem, e casar por CNPJ em memória resolve). O token
   é do CPF de uma pessoa e só existe em dois tenants — a planilha vale nos sete.

3. ⚠️ **A PLANILHA NÃO É DIÁRIA.** Em 22/09/2026 a mais recente era a de 11/09
   (gerada em 16/09). O nome do arquivo NÃO é "hoje": a data sai da página de
   download (`arquivos.push({"ano":..,"mes":..,"dia":..})`), e um dia sem arquivo
   devolve **403** no host de download — não 404. Por isso 403 NUNCA é lido como
   bloqueio sem antes perguntar à página qual é a data.

4. ⚠️ **NÃO HÁ IBGE, HÁ O CÓDIGO SIAFI DO MUNICÍPIO** ("8765" é Nova Palma). Ele
   não é deduzido do nome: sai das linhas cujo `CÓDIGO CONVENENTE` é o CNPJ da
   prefeitura (`municipios.cnpj`) — uma origem, não um palpite. Com ele entram os
   outros convenentes do município: fundo municipal (Juranda: Fundo Municipal de
   Saúde), hospital, APAE — marcados `municipal = false` quando não são a
   prefeitura (regra do dono: nada é descartado, mas fica fora dos totais).

5. ⚠️ **"TIPO ENTE CONVENENTE = Municipal" É ONDE FICA, NÃO QUEM É.** Em Santa
   Maria, sob o mesmo código SIAFI: a UFSM (206 instrumentos, "Agentes
   Intermediários"), fundações, cooperativas e PESSOAS FÍSICAS. Quem é municipal
   sai de `TIPO CONVENENTE` + CNPJ (`e_municipal`). Pessoa física não entra
   (CPF com nome, e não é dinheiro do município).

6. **O NÚMERO NÃO É ÚNICO NO PAÍS** (6 repetidos): a chave é (município, número,
   documento do convenente). **E A ORDEM BANCÁRIA NÃO TEM CHAVE** — o par
   (convênio, OB) aparece duas vezes em 850 casos: a lista do município é trocada
   inteira a cada carga.

7. **"SÓ NA CGU" = O NÚMERO NÃO ESTÁ NO `siconv_convenio.zip`** do TransfereGov
   (18 MB, todos os NR_CONVENIO do país), baixado na mesma rodada. Sem ele a
   marca fica NULA ("não deu para conferir"), nunca "falso".

8. **CABEÇALHO CONFERIDO** (`COLUNAS`): coluna renomeada é `partial` com o nome,
   nunca "zero instrumento". Arquivo sem linha do município com banco cheio não
   apaga nada.

Rodável por Scheduled Task em todo worker (federal), ou à mão:
    python -u ingestion/cgu_convenios.py                 # coleta de verdade
    python -u ingestion/cgu_convenios.py --dry --cnpj 88488358000156
Envs: CGU_CONV_FORCE=1 relê mesmo com o arquivo já carregado.
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import os
import re
import sys
import tempfile
import time
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("cgu_convenios")

PAGINA = "https://portaldatransparencia.gov.br/download-de-dados/convenios"
ARQUIVO = ("https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/"
           "convenios/{}_Convenios.zip")
TG_CONVENIOS = ("https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov/"
                "siconv_convenio.zip")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128 Safari/537.36 PACTHA/1.0"}
FONTE = "cgu_convenios"
TIMEOUT = 300
FORCAR = (os.getenv("CGU_CONV_FORCE") or "").strip() == "1"

COLUNAS = (
    "NÚMERO CONVÊNIO", "UF", "CÓDIGO SIAFI MUNICÍPIO", "NOME MUNICÍPIO",
    "SITUAÇÃO CONVÊNIO", "NÚMERO ORIGINAL", "NÚMERO PROCESSO DO CONVÊNIO",
    "OBJETO DO CONVÊNIO", "CÓDIGO ÓRGÃO SUPERIOR", "NOME ÓRGÃO SUPERIOR",
    "CÓDIGO ÓRGÃO CONCEDENTE", "NOME ÓRGÃO CONCEDENTE", "CÓDIGO UG CONCEDENTE",
    "NOME UG CONCEDENTE", "CÓDIGO CONVENENTE", "TIPO CONVENENTE", "NOME CONVENENTE",
    "TIPO ENTE CONVENENTE", "TIPO INSTRUMENTO", "VALOR CONVÊNIO", "VALOR LIBERADO",
    "DATA PUBLICAÇÃO", "DATA INÍCIO VIGÊNCIA", "DATA FINAL VIGÊNCIA",
    "VALOR CONTRAPARTIDA", "DATA ÚLTIMA LIBERAÇÃO", "VALOR ÚLTIMA LIBERAÇÃO")
COLUNAS_OB = ("NÚMERO CONVÊNIO", "DATA EMISSÃO OB", "NÚMERO DA ORDEM BANCÁRIA",
              "VALOR LIBERADO")


class CabecalhoMudou(Exception):
    """A planilha perdeu uma coluna que o coletor lê (armadilha 8)."""


# ---------------------------------------------------------------------------
# Campos
# ---------------------------------------------------------------------------
def _txt(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


def _dec(v: str | None) -> Decimal | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return Decimal(v.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def _data(v: str | None) -> date | None:
    try:
        return datetime.strptime((v or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _doc(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def e_municipal(doc: str, tipo: str | None, nome: str | None, cnpj_prefeitura: str) -> bool:
    """O convenente é a administração MUNICIPAL? (armadilha 5)

    A prefeitura pelo CNPJ; outro órgão municipal pelo tipo ("Administração
    Pública Municipal" — câmara, autarquia com CNPJ próprio); o fundo municipal,
    que a CGU classifica só como "Administração Pública", pelo nome."""
    if doc == cnpj_prefeitura:
        return True
    t = (tipo or "").strip().lower()
    if t.startswith("administração pública municipal"):
        return True
    if t == "administração pública":
        n = (nome or "").upper()
        return any(m in n for m in ("MUNICIP", "PREFEIT", "CAMARA MUNICIPAL",
                                    "CÂMARA MUNICIPAL"))
    return False


def linha_convenio(x: dict, municipio_id: int, cnpj_prefeitura: str, arquivo: str,
                   no_tg: set | None) -> dict:
    doc = _doc(x["CÓDIGO CONVENENTE"])
    numero = (x["NÚMERO CONVÊNIO"] or "").strip()
    return {
        "municipio_id": municipio_id,
        "numero": numero,
        "numero_original": _txt(x["NÚMERO ORIGINAL"]),
        "numero_processo": _txt(x["NÚMERO PROCESSO DO CONVÊNIO"]),
        "situacao": _txt(x["SITUAÇÃO CONVÊNIO"]),
        "objeto": _txt(x["OBJETO DO CONVÊNIO"]),
        "orgao_superior_codigo": _txt(x["CÓDIGO ÓRGÃO SUPERIOR"]),
        "orgao_superior": _txt(x["NOME ÓRGÃO SUPERIOR"]),
        "orgao_concedente_codigo": _txt(x["CÓDIGO ÓRGÃO CONCEDENTE"]),
        "orgao_concedente": _txt(x["NOME ÓRGÃO CONCEDENTE"]),
        "ug_concedente_codigo": _txt(x["CÓDIGO UG CONCEDENTE"]),
        "ug_concedente": _txt(x["NOME UG CONCEDENTE"]),
        "convenente_doc": doc,
        "convenente_nome": _txt(x["NOME CONVENENTE"]),
        "tipo_convenente": _txt(x["TIPO CONVENENTE"]),
        "municipal": e_municipal(doc, x["TIPO CONVENENTE"], x["NOME CONVENENTE"],
                                 cnpj_prefeitura),
        "tipo_instrumento": _txt(x["TIPO INSTRUMENTO"]),
        "valor": _dec(x["VALOR CONVÊNIO"]),
        "valor_liberado": _dec(x["VALOR LIBERADO"]),
        "valor_contrapartida": _dec(x["VALOR CONTRAPARTIDA"]),
        "data_publicacao": _data(x["DATA PUBLICAÇÃO"]),
        "data_inicio_vigencia": _data(x["DATA INÍCIO VIGÊNCIA"]),
        "data_final_vigencia": _data(x["DATA FINAL VIGÊNCIA"]),
        "data_ultima_liberacao": _data(x["DATA ÚLTIMA LIBERAÇÃO"]),
        "valor_ultima_liberacao": _dec(x["VALOR ÚLTIMA LIBERAÇÃO"]),
        # Armadilha 7: sem o dump do TransfereGov, NULO — não "falso".
        "no_transferegov": None if no_tg is None else numero in no_tg,
        "arquivo": arquivo,
    }


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
_RX_DATA = re.compile(r'arquivos\.push\(\{"ano"\s*:\s*"(\d{4})",\s*"mes"\s*:\s*"(\d{2})",'
                      r'\s*"dia"\s*:\s*"(\d{2})"')


def data_do_arquivo(pagina_html: str) -> str | None:
    """A data do arquivo mais recente (AAAAMMDD) que a página de download lista."""
    datas = ["".join(m) for m in _RX_DATA.findall(pagina_html)]
    return max(datas) if datas else None


def baixar(client: httpx.Client, url: str, destino) -> int:
    with client.stream("GET", url, headers=UA, timeout=TIMEOUT) as r:
        r.raise_for_status()
        n = 0
        for bloco in r.iter_bytes(1 << 20):
            destino.write(bloco)
            n += len(bloco)
    destino.flush()
    destino.seek(0)
    return n


def leitor(z: zipfile.ZipFile, sufixo: str, obrigatorias: tuple):
    """DictReader do membro que termina em `sufixo`, com o cabeçalho conferido."""
    nome = next((n for n in z.namelist() if n.endswith(sufixo)), None)
    if nome is None:
        raise CabecalhoMudou(f"o zip não tem *{sufixo} ({z.namelist()})")
    texto = io.TextIOWrapper(z.open(nome), encoding="latin-1", newline="")
    r = csv.DictReader(texto, delimiter=";")
    faltando = [c for c in obrigatorias if c not in (r.fieldnames or [])]
    if faltando:
        raise CabecalhoMudou(f"{nome} sem as colunas {faltando}")
    return r


def numeros_transferegov(z: zipfile.ZipFile) -> set[str]:
    nome = z.namelist()[0]
    r = csv.reader(io.TextIOWrapper(z.open(nome), encoding="utf-8-sig", newline=""),
                   delimiter=";")
    h = next(r)
    if "NR_CONVENIO" not in h:
        raise CabecalhoMudou(f"{nome} sem NR_CONVENIO")
    i = h.index("NR_CONVENIO")
    return {row[i].strip() for row in r if len(row) > i and row[i].strip()}


def _chave_siafi(x: dict) -> tuple[str, str]:
    return ((x["CÓDIGO SIAFI MUNICÍPIO"] or "").strip(), (x["UF"] or "").strip())


def codigos_siafi(convenios, alvos: dict[str, dict]) -> dict[str, tuple]:
    """1ª passada: o (código SIAFI, UF) de cada prefeitura, pelas linhas em que ELA
    é a convenente (armadilha 4). O mais frequente vence: Santa Maria tem 372
    linhas no 8841 e 1 no 8801."""
    cont: dict[str, dict] = {}
    for x in convenios:
        doc = _doc(x["CÓDIGO CONVENENTE"])
        if doc in alvos:
            c = cont.setdefault(doc, {})
            k = _chave_siafi(x)
            c[k] = c.get(k, 0) + 1
    return {cnpj: max(c, key=c.get) for cnpj, c in cont.items()}


def selecionar(convenios, alvos: dict[str, dict], codigos: dict[str, tuple]) -> dict[int, list]:
    """2ª passada: as linhas de cada município — o código SIAFI dele, mais a própria
    prefeitura e as entidades de `municipio_entidades` que estejam em OUTRO código.
    Pessoa física não entra (armadilha 5). Guarda só o que é do município: a
    planilha inteira na memória passaria de 1 GB."""
    por_codigo = {k: alvos[c]["id"] for c, k in codigos.items()}
    por_doc: dict[str, int] = {}
    for cnpj, a in alvos.items():
        por_doc[cnpj] = a["id"]
        for e in a.get("extras") or ():
            por_doc.setdefault(e, a["id"])
    linhas: dict[int, list] = {a["id"]: [] for a in alvos.values()}
    vistos: set = set()
    for x in convenios:
        if (x["TIPO CONVENENTE"] or "").strip() == "Pessoa Física":
            continue
        doc = _doc(x["CÓDIGO CONVENENTE"])
        mids = {m for m in (por_codigo.get(_chave_siafi(x)), por_doc.get(doc))
                if m is not None}
        for mid in mids:
            k = (mid, (x["NÚMERO CONVÊNIO"] or "").strip(), doc)
            if k not in vistos:
                vistos.add(k)
                linhas[mid].append(dict(x))
    return linhas


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
def _alvos(cur) -> dict[str, dict]:
    cur.execute("""
        SELECT m.id, m.nome, regexp_replace(coalesce(m.cnpj, ''), '\\D', '', 'g'),
               c.arquivo
          FROM municipios m LEFT JOIN cgu_convenios_carga c ON c.municipio_id = m.id
         WHERE m.active
    """)
    alvos = {}
    for mid, nome, cnpj, arquivo in cur.fetchall():
        if len(cnpj) == 14:
            alvos[cnpj] = {"id": mid, "nome": nome, "arquivo": arquivo, "extras": set()}
    cur.execute("SELECT municipio_id, regexp_replace(cnpj, '\\D', '', 'g') "
                "FROM municipio_entidades")
    por_id = {a["id"]: a for a in alvos.values()}
    for mid, cnpj in cur.fetchall():
        if mid in por_id and len(cnpj) == 14:
            por_id[mid]["extras"].add(cnpj)
    return alvos


_COLS = ("municipio_id", "numero", "numero_original", "numero_processo", "situacao",
         "objeto", "orgao_superior_codigo", "orgao_superior", "orgao_concedente_codigo",
         "orgao_concedente", "ug_concedente_codigo", "ug_concedente", "convenente_doc",
         "convenente_nome", "tipo_convenente", "municipal", "tipo_instrumento", "valor",
         "valor_liberado", "valor_contrapartida", "data_publicacao",
         "data_inicio_vigencia", "data_final_vigencia", "data_ultima_liberacao",
         "valor_ultima_liberacao", "no_transferegov", "arquivo")


def grava_municipio(cur, mid: int, linhas: list[dict], obs: list[dict],
                    arquivo: str, codigo: str | None) -> tuple[int, bool]:
    """(instrumentos gravados, recusou_apagar). Troca o município inteiro — a planilha
    é a foto completa — exceto quando ela vem sem nada e o banco tem linhas."""
    cur.execute("SELECT count(*) FROM cgu_convenios WHERE municipio_id = %s", (mid,))
    no_banco = cur.fetchone()[0]
    if not linhas and no_banco:
        return 0, True
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLS[3:])
    sql = (f"INSERT INTO cgu_convenios ({', '.join(_COLS)}, atualizado_em) VALUES "
           f"({', '.join('%(' + c + ')s' for c in _COLS)}, NOW()) "
           "ON CONFLICT (municipio_id, numero, convenente_doc) DO UPDATE SET "
           f"numero_original = EXCLUDED.numero_original, {sets}, atualizado_em = NOW()")
    for x in linhas:
        cur.execute(sql, x)
    chaves = [(x["numero"], x["convenente_doc"]) for x in linhas]
    cur.execute("""
        DELETE FROM cgu_convenios WHERE municipio_id = %s
           AND (numero, convenente_doc) NOT IN (SELECT * FROM unnest(%s::text[], %s::text[]))
    """, (mid, [c[0] for c in chaves], [c[1] for c in chaves]))
    cur.execute("DELETE FROM cgu_convenios_ob WHERE municipio_id = %s", (mid,))
    for o in obs:
        cur.execute("""
            INSERT INTO cgu_convenios_ob (municipio_id, numero, ordem_bancaria,
                data_emissao, valor) VALUES (%s, %s, %s, %s, %s)
        """, (mid, o["numero"], o["ordem_bancaria"], o["data_emissao"], o["valor"]))
    cur.execute("""
        INSERT INTO cgu_convenios_carga (municipio_id, arquivo, siafi_municipio,
            instrumentos, ordens_bancarias, carregado_em)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (municipio_id) DO UPDATE SET arquivo = EXCLUDED.arquivo,
            siafi_municipio = EXCLUDED.siafi_municipio,
            instrumentos = EXCLUDED.instrumentos,
            ordens_bancarias = EXCLUDED.ordens_bancarias, carregado_em = NOW()
    """, (mid, arquivo, codigo, len(linhas), len(obs)))
    return len(linhas), False


def _log_ingest(cur, conn, status: str, n: int, nota: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
            (FONTE, status, n, nota))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("ingestion_log falhou: %s", str(e)[:120])


# ---------------------------------------------------------------------------
# Rodada
# ---------------------------------------------------------------------------
def ler_fonte(client: httpx.Client, alvos: dict, arquivo: str, notas: list):
    """Baixa e lê a planilha (e o dump do TransfereGov). Devolve
    (linhas por município já convertidas, OBs por município, códigos SIAFI)."""
    no_tg: set | None
    with tempfile.TemporaryFile() as tg:
        try:
            baixar(client, TG_CONVENIOS, tg)
            no_tg = numeros_transferegov(zipfile.ZipFile(tg))
            log.info("TransfereGov: %d números de convênio no dump", len(no_tg))
        except Exception as e:
            no_tg = None
            notas.append(f"sem o dump do TransfereGov ({type(e).__name__}): "
                         "'só na CGU' ficou sem conferir")
            log.warning("siconv_convenio.zip falhou: %s", str(e)[:200])
    with tempfile.TemporaryFile() as f:
        t0 = time.monotonic()
        tam = baixar(client, ARQUIVO.format(arquivo), f)
        log.info("CGU %s: %.1f MB em %.0f s", arquivo, tam / 1e6, time.monotonic() - t0)
        z = zipfile.ZipFile(f)
        siafi = codigos_siafi(leitor(z, "_Convenios.csv", COLUNAS), alvos)
        brutas = selecionar(leitor(z, "_Convenios.csv", COLUNAS), alvos, siafi)
        codigos = {alvos[c]["id"]: k[0] for c, k in siafi.items()}
        por_cnpj = {a["id"]: cnpj for cnpj, a in alvos.items()}
        linhas = {mid: [linha_convenio(x, mid, por_cnpj[mid], arquivo, no_tg) for x in xs]
                  for mid, xs in brutas.items()}
        quem = {}
        for mid, xs in linhas.items():
            for x in xs:
                quem.setdefault(x["numero"], set()).add(mid)
        obs: dict[int, list] = {mid: [] for mid in linhas}
        for o in leitor(z, "_OrdensBancarias.csv", COLUNAS_OB):
            num = (o["NÚMERO CONVÊNIO"] or "").strip()
            for mid in quem.get(num, ()):
                obs[mid].append({"numero": num,
                                 "ordem_bancaria": (o["NÚMERO DA ORDEM BANCÁRIA"] or "").strip(),
                                 "data_emissao": _data(o["DATA EMISSÃO OB"]),
                                 "valor": _dec(o["VALOR LIBERADO"])})
    return linhas, obs, codigos


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = _alvos(cur)
            if not alvos:
                log.info("nenhum município ativo com CNPJ — nada a casar")
                if not dry:
                    _log_ingest(cur, conn, "success", 0, "nenhum município com CNPJ")
                return 0
            with httpx.Client(follow_redirects=True) as client:
                r = client.get(PAGINA, headers=UA, timeout=60)
                r.raise_for_status()
                arquivo = data_do_arquivo(r.text)
                if not arquivo:
                    raise RuntimeError("a página de download não listou arquivo de convênios")
                pendentes = {c: a for c, a in alvos.items()
                             if FORCAR or a["arquivo"] != arquivo}
                if not pendentes:
                    log.info("arquivo %s já carregado em todos — nada a fazer", arquivo)
                    if not dry:
                        _log_ingest(cur, conn, "success", 0, f"arquivo {arquivo} já carregado")
                    return 0
                notas: list[str] = []
                linhas, obs, codigos = ler_fonte(client, pendentes, arquivo, notas)
            gravados, parcial = 0, bool(notas)
            for cnpj, a in pendentes.items():
                ls = linhas.get(a["id"], [])
                if a["id"] not in codigos:
                    parcial = True
                    notas.append(f"{a['nome']}: CNPJ {cnpj} sem nenhuma linha na planilha")
                if dry:
                    log.info("  %s: %d instrumento(s), %d OB(s), só na CGU %s", a["nome"],
                             len(ls), len(obs.get(a["id"], [])),
                             sum(1 for x in ls if x["no_transferegov"] is False))
                    continue
                n, recusou = grava_municipio(cur, a["id"], ls, obs.get(a["id"], []),
                                             arquivo, codigos.get(a["id"]))
                if recusou:
                    parcial = True
                    notas.append(f"{a['nome']}: planilha sem linha e banco cheio — nada apagado")
                conn.commit()
                gravados += n
                log.info("  %s: %d instrumento(s), %d OB(s)", a["nome"], n,
                         len(obs.get(a["id"], [])))
            if dry:
                return 0
            status = "partial" if parcial else "success"
            nota = " | ".join([f"arquivo {arquivo}"] + notas)[:400]
            log.info("=== CGU convênios: %d instrumento(s), status=%s ===", gravados, status)
            _log_ingest(cur, conn, status, gravados, nota)
            return gravados
        except CabecalhoMudou as e:
            conn.rollback()
            log.error("CGU convênios: layout mudou: %s", e)
            _log_ingest(cur, conn, "partial", 0, f"layout mudou: {str(e)[:300]}")
            return 0
        except Exception as e:
            conn.rollback()
            log.error("CGU convênios falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


def ensaio_sem_banco(cnpj: str) -> None:
    """`--dry --cnpj`: baixa, casa e resume sem banco — para conferir a fonte."""
    alvos = {cnpj: {"id": 0, "nome": cnpj, "arquivo": None, "extras": set()}}
    with httpx.Client(follow_redirects=True) as client:
        arquivo = data_do_arquivo(client.get(PAGINA, headers=UA, timeout=60).text)
        notas: list[str] = []
        linhas, obs, codigos = ler_fonte(client, alvos, arquivo, notas)
    ls = linhas.get(0, [])
    hoje = date.today()
    vig = [x for x in ls if x["data_final_vigencia"] and x["data_final_vigencia"] >= hoje]
    so = [x for x in vig if x["no_transferegov"] is False]
    log.info("arquivo %s | SIAFI %s | %d instrumento(s) (%d municipais) | %d OB(s) | "
             "vigentes %d, só na CGU %d (R$ %s) | %s", arquivo, codigos.get(0), len(ls),
             sum(1 for x in ls if x["municipal"]), len(obs.get(0, [])), len(vig), len(so),
             f"{sum(x['valor'] or 0 for x in so):,.2f}", notas or "")
    for x in so[:10]:
        log.info("  %s %s | %s | %s | %s liberado de %s", x["numero"], x["tipo_instrumento"],
                 (x["orgao_concedente"] or "")[:40], x["situacao"], x["valor_liberado"],
                 x["valor"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true")
    p.add_argument("--cnpj", help="com --dry: casa só este CNPJ de prefeitura, sem banco")
    a = p.parse_args()
    if a.dry and a.cnpj:
        ensaio_sem_banco(_doc(a.cnpj))
    else:
        ingest(dry=a.dry)
