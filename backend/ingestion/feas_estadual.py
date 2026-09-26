"""
FEAS — o cofinanciamento ESTADUAL da assistência social: o que o Fundo Estadual de
Assistência Social pagou ao município (ao fundo municipal ou à prefeitura), OB a OB.
MG (Piso Mineiro) e RS (Piso Gaúcho e programas), pela despesa aberta de cada Estado.

    MG  dados.mg.gov.br, pacote `despesa` (CGE): ft_despesa_{ano} + dm_empenho_desp_{ano}
        + dm_favorecido + dm_acao + dm_tipo_documento + dm_tempo_diario (csv.gz, `;`)
    RS  dados.rs.gov.br, pacote `{ano}-despesa-do-estado` (CAGE): um ZIP por mês
        (`despesas-do-estado-AAAAMM.zip`, ~15 MB, Latin-1, `;`)

Os mesmos arquivos que `cge_despesa_ob.py` (MG) e `scripts/gerar_depara_municipios_rs.py`
(RS) já leem — a VPS alcança os dois CKANs.

O CARTÃO (p.34 do relatório de fontes) mandava raspar os portais das secretarias.
Não precisa: o pagamento está na despesa do Estado, com o CNPJ de quem recebeu.

AS ARMADILHAS, medidas em 26/09/2026:

1. **QUEM É O FEAS.** MG: a unidade executora do EMPENHO `1480004 - SEDESE/FEAS/SUBAS`
   (a ação 4431 é o Piso Mineiro); as outras UEs da SEDESE (1480071 "CONVÊNIO
   PARCERIAS"...) são convênio — já estão na tela de Convênios. RS: `Cod_UO = 2178`
   ("Fundo Estadual de Assistencia Social", órgão 21, SEDES); a UO 2101 (gabinete)
   paga o Prato Gaúcho do Funrigs, que é outra tela.

2. ⚠️ **O DINHEIRO NÃO VAI SÓ AO FUNDO.** O Piso Mineiro cai no CNPJ do FUNDO
   MUNICIPAL (Monte Sião: 13.474.332/0001-50, não o da prefeitura); no RS o Piso
   Gaúcho cai no fundo (Santa Maria, 06/2026, R$ 25 mil) e as emendas/programas do
   FEAS na PREFEITURA ("Municipio de Tuparendi", modalidade 40). O alvo é a união
   dos dois CNPJs: o da prefeitura (`municipios.cnpj`) e o do fundo, que vem do
   painel do FNAS (`fnas_saldo_conta`, tipo FUNDO MUNICIPAL — `fnas_suas.py`).
   Sem o FNAS carregado, só a prefeitura casa, e a rodada diz isso (nota).
   Nunca por nome: há Santa Maria, Santa Maria do Herval e Santa Maria Madalena.

3. **O CNPJ VEM EM FORMATOS DIFERENTES.** MG: dígitos sem os zeros à esquerda
   (`dm_favorecido.nr_documento_anonimizado`); RS: "14.841.318/0001-00". Os dois
   lados são comparados em 14 dígitos com zfill.

4. **MG: PAGAMENTO É O DOCUMENTO "OP ..." COM `vr_pago` ≠ 0** (`_RE_OP` do
   `cge_despesa_ob`); estorno vem negativo e entra negativo. Pagamento de restos a
   pagar (pacote `restos_pagar`) NÃO é lido: o Piso Mineiro de 2026 foi pago no
   próprio ano (Monte Sião: jan-mar juntos em 27/04, R$ 25.560, depois R$ 8.520/mês).

5. **RS: `FaseGasto = 'Pagamento'`, valor com vírgula, data "dd/mm/aaaa"**, número
   do pagamento em `Pagamento`. O arquivo do mês sai com ~1 mês de atraso (em 26/09
   o mais novo era 07/2026) e o servidor CORTA o download (~10 MB) — ou pára de
   mandar bytes sem fechar (1ª carga, 2025/08: 10 min parado): timeout de leitura
   de 90 s e retomada por `Range`, zip conferido no fim (como o `_baixar` do script
   do de-para).

6. **O ARQUIVO É A VERDADE DO PERÍODO.** MG: um arquivo por ano — o (município, ano)
   é trocado inteiro; ano que já teve pagamento e voltou vazio é `partial`, nada
   apagado. RS: um arquivo por mês — o (município, mês) é trocado inteiro, e mês
   vazio é resposta válida (o RS paga pouco e irregular: R$ 2,6 mi fundo a fundo no
   Estado inteiro de janeiro a julho de 2026). Arquivo com menos linhas que o mínimo
   ou cabeçalho mudado é recusado (`partial`, com o nome).

7. **SÓ BAIXA O QUE MUDOU.** `feas_carga` guarda, por recurso, o `last_modified` do
   CKAN e o conjunto de CNPJs procurados; recurso igual para o mesmo conjunto não é
   baixado de novo.

Rodável por Scheduled Task ou à mão:
    python -u ingestion/feas_estadual.py            # coleta de verdade
    python -u ingestion/feas_estadual.py --dry      # lê e mostra, não grava
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("feas_estadual")

FONTE = "feas_estadual"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131 Safari/537.36"}
BRT = timezone(timedelta(hours=-3))
UFS = ("MG", "RS")

PKG_MG = "https://dados.mg.gov.br/api/3/action/package_show?id=despesa"
UE_FEAS_MG = "1480004"
MIN_LINHAS_MG = 200_000          # ft_despesa_2026 em 09/2026: milhões de linhas

PKG_RS = "https://dados.rs.gov.br/api/3/action/package_show?id={ano}-despesa-do-estado"
UO_FEAS_RS = "2178"
MIN_LINHAS_RS = 100_000          # 07/2026: 404.946 linhas
COLUNAS_RS = ("Exercicio", "Mes", "FaseGasto", "CNPJ", "Favorecido", "Cod_UO", "UO",
              "Cod_Acao", "Acao", "Cod_Modalidade", "Data", "Valor", "Pagamento")

_RE_OP = re.compile(r"^OP (PAGA|PENDENTE)( SEM DOCUMENTO DE ORIGEM)?$", re.I)


class ArquivoRecusado(ValueError):
    """Arquivo cortado, vazio ou com cabeçalho mudado — nada é apagado."""


# ---------------------------------------------------------------------------
# Puro
# ---------------------------------------------------------------------------
def cnpj14(v) -> str:
    d = re.sub(r"\D", "", str(v or ""))
    return d.zfill(14) if d else ""


def valor_br(v) -> Decimal:
    s = str(v or "").strip()
    if not s:
        return Decimal("0")
    try:
        return Decimal(s.replace(".", "").replace(",", ".")) if "," in s else Decimal(s)
    except InvalidOperation:
        return Decimal("0")


def data_br(v) -> date | None:
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", str(v or ""))
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def assinatura(cnpjs) -> str:
    return hashlib.sha1(",".join(sorted(cnpjs)).encode()).hexdigest()[:16]


def _csv_gz(conteudo: bytes):
    import gzip
    if not conteudo:
        return
    with gzip.open(io.BytesIO(conteudo), "rt", encoding="utf-8-sig", errors="replace") as f:
        rd = csv.DictReader(f, delimiter=";")
        rd.fieldnames = [str(c or "").strip().lstrip("﻿") for c in (rd.fieldnames or [])]
        yield from rd


def linhas_rs(conteudo_zip: bytes):
    """Itera o CSV do ZIP mensal do RS (Latin-1; UTF-8 com BOM se vier)."""
    csv.field_size_limit(1 << 30)            # `Historico` passa de 128 KB em algumas linhas
    zf = zipfile.ZipFile(io.BytesIO(conteudo_zip))
    nomes = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    if not nomes:
        raise ArquivoRecusado(f"ZIP sem CSV ({zf.namelist()[:3]})")
    # Em FLUXO: o CSV de um mês passa de 150 MB descompactado, e ler + decodificar +
    # copiar de uma vez deu MemoryError na 1ª carga (medido em 26/09/2026).
    with zf.open(nomes[0]) as f:
        bom = f.read(3) == b"\xef\xbb\xbf"
    fluxo = io.TextIOWrapper(zf.open(nomes[0]), encoding="utf-8-sig" if bom else "latin-1",
                             newline="")
    rd = csv.DictReader(fluxo, delimiter=";")
    faltam = [c for c in COLUNAS_RS if c not in (rd.fieldnames or [])]
    if faltam:
        raise ArquivoRecusado(f"colunas ausentes na despesa do RS: {faltam}")
    yield from rd


def pagamentos_rs(linhas, alvos: dict[str, int]) -> tuple[list[dict], int]:
    """(pagamentos do FEAS-RS aos CNPJs alvo, linhas lidas). `alvos`: {cnpj14: mid}."""
    out, n = [], 0
    for r in linhas:
        n += 1
        if (r.get("Cod_UO") or "").strip() != UO_FEAS_RS or (r.get("FaseGasto") or "").strip() != "Pagamento":
            continue
        doc = cnpj14(r.get("CNPJ"))
        mid = alvos.get(doc)
        if not mid:
            continue
        d = data_br(r.get("Data"))
        out.append({
            "mid": mid, "uf": "RS", "ano": int(r.get("Exercicio") or (d.year if d else 0)),
            "mes": int(r.get("Mes") or (d.month if d else 0)), "data": d,
            "documento": (r.get("Pagamento") or "").strip() or None,
            "favorecido_cnpj": doc, "favorecido_nome": (r.get("Favorecido") or "").strip() or None,
            "unidade": f"{UO_FEAS_RS} - {(r.get('UO') or '').strip()}",
            "acao": f"{(r.get('Cod_Acao') or '').strip()} {(r.get('Acao') or '').strip()}".strip(),
            "modalidade": (r.get("Cod_Modalidade") or "").strip() or None,
            "valor": valor_br(r.get("Valor")),
        })
    return out, n


def pagamentos_mg(ft, empenho_ue: dict[str, str], favs: dict[str, str], alvos: dict[str, int],
                  ids_op: set, acoes: dict, tempo: dict, nomes: dict) -> tuple[list[dict], int]:
    """(pagamentos do FEAS-MG, linhas lidas do ft). `favs`: {id_favorecido: cnpj14}
    dos alvos; `empenho_ue`: {id_empenho: UE} só dos empenhos do FEAS."""
    out, n = [], 0
    for r in ft:
        n += 1
        fav = (r.get("id_favorecido") or "").strip()
        if fav not in favs:
            continue
        emp = (r.get("id_empenho") or "").strip()
        if emp not in empenho_ue or (r.get("id_tipo_documento") or "").strip() not in ids_op:
            continue
        v = valor_br(r.get("vr_pago"))
        if not v:
            continue
        d = tempo.get((r.get("id_tempo") or "").strip())
        doc = favs[fav]
        out.append({
            "mid": alvos[doc], "uf": "MG", "ano": d.year if d else int(r.get("ano_particao") or 0),
            "mes": d.month if d else None, "data": d,
            "documento": (r.get("cd_documento") or "").strip() or None,
            "favorecido_cnpj": doc, "favorecido_nome": nomes.get(fav),
            "unidade": empenho_ue[emp], "acao": acoes.get((r.get("id_acao") or "").strip()),
            "modalidade": None, "valor": v,
        })
    return out, n


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
@dataclass
class Rodada:
    gravadas: int = 0
    parcial: bool = False
    notas: list[str] = field(default_factory=list)


def alvos_por_uf(cur) -> tuple[dict[str, dict[str, int]], list[str]]:
    """{uf: {cnpj14: municipio_id}} da prefeitura e do fundo (FNAS), e os municípios
    sem o CNPJ do fundo (armadilha 2)."""
    cur.execute("SELECT id, nome, upper(coalesce(uf, '')), coalesce(cnpj, '') FROM municipios "
                "WHERE active AND upper(coalesce(uf, '')) = ANY(%s)", (list(UFS),))
    mun = cur.fetchall()
    cur.execute("SELECT DISTINCT municipio_id, cnpj FROM fnas_saldo_conta "
                "WHERE tipo_entidade = 'FUNDO MUNICIPAL'")
    fundos: dict[int, set] = {}
    for mid, c in cur.fetchall():
        fundos.setdefault(mid, set()).add(cnpj14(c))
    out: dict[str, dict[str, int]] = {uf: {} for uf in UFS}
    sem_fundo = []
    for mid, nome, uf, cnpj in mun:
        if cnpj14(cnpj):
            out[uf][cnpj14(cnpj)] = mid
        for c in fundos.get(mid, ()):
            out[uf][c] = mid
        if not fundos.get(mid):
            sem_fundo.append(nome)
    return out, sem_fundo


def _versao(cur, uf: str, recurso: str) -> tuple | None:
    cur.execute("SELECT versao, alvos FROM feas_carga WHERE uf = %s AND recurso = %s", (uf, recurso))
    return cur.fetchone()


def _registra(cur, uf: str, recurso: str, versao: str, alvos: str, linhas: int) -> None:
    cur.execute("""
        INSERT INTO feas_carga (uf, recurso, versao, alvos, linhas, lido_em)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (uf, recurso) DO UPDATE SET versao = EXCLUDED.versao,
            alvos = EXCLUDED.alvos, linhas = EXCLUDED.linhas, lido_em = NOW()
    """, (uf, recurso, versao, alvos, linhas))


_INS = """
INSERT INTO feas_pagamento (municipio_id, uf, ano, mes, data, documento, favorecido_cnpj,
    favorecido_nome, unidade, acao, modalidade, valor, arquivo)
VALUES %s
"""


def troca(cur, uf: str, periodo: tuple, mids: set[int], regs: list[dict], arquivo: str,
          vazio_e_valido: bool) -> tuple[int, list[str]]:
    """Troca o período (('ano', 2026) ou ('mes', 2026, 7)) de cada município alvo.
    (gravadas, municípios recusados por voltar vazio onde havia dado)."""
    import psycopg2.extras
    por: dict[int, list] = {m: [] for m in mids}
    for r in regs:
        por.setdefault(r["mid"], []).append(r)
    recusados, n = [], 0
    for mid, lst in por.items():
        cond, args = ("ano = %s", [periodo[1]]) if periodo[0] == "ano" else \
            ("ano = %s AND mes = %s", [periodo[1], periodo[2]])
        if not lst and not vazio_e_valido:
            cur.execute(f"SELECT 1 FROM feas_pagamento WHERE municipio_id = %s AND uf = %s AND {cond} LIMIT 1",
                        [mid, uf, *args])
            if cur.fetchone():
                recusados.append(str(mid))
                continue
        cur.execute(f"DELETE FROM feas_pagamento WHERE municipio_id = %s AND uf = %s AND {cond}",
                    [mid, uf, *args])
        if lst:
            psycopg2.extras.execute_values(cur, _INS, [(
                r["mid"], r["uf"], r["ano"], r["mes"], r["data"], r["documento"],
                r["favorecido_cnpj"], r["favorecido_nome"], r["unidade"], r["acao"],
                r["modalidade"], r["valor"], arquivo) for r in lst], page_size=500)
            n += len(lst)
    return n, recusados


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def _get_json(client: httpx.Client, url: str) -> dict:
    ult = None
    for _ in range(4):
        try:
            r = client.get(url)
            if r.status_code >= 500:
                ult = f"HTTP {r.status_code}"
                continue
            r.raise_for_status()
            return r.json()
        except (httpx.TransportError, ValueError) as e:
            ult = type(e).__name__
    raise RuntimeError(f"catálogo indisponível ({ult}): {url}")


def _recursos(pkg: dict) -> list[dict]:
    return ((pkg or {}).get("result") or {}).get("resources") or []


def _url(pkg: dict, sufixo: str) -> tuple[str | None, str]:
    for r in _recursos(pkg):
        u = (r.get("url") or "").strip()
        if u.endswith(sufixo):
            return u, str(r.get("last_modified") or r.get("metadata_modified") or r.get("size") or "")
    return None, ""


def baixar(client: httpx.Client, url: str, zip_: bool = False) -> bytes:
    """GET inteiro; com `zip_`, retomada por Range até o ZIP fechar (armadilha 5)."""
    if not zip_:
        r = client.get(url)
        r.raise_for_status()
        return r.content
    with tempfile.TemporaryDirectory() as tmp:
        destino = os.path.join(tmp, "a.zip")
        for _ in range(15):
            tam = os.path.getsize(destino) if os.path.exists(destino) else 0
            if tam:
                try:
                    if zipfile.ZipFile(destino).testzip() is None:
                        with open(destino, "rb") as f:
                            return f.read()
                except Exception:
                    pass
            h = {"Range": f"bytes={tam}-"} if tam else {}
            try:
                with client.stream("GET", url, headers=h) as r:
                    if r.status_code == 416:
                        os.remove(destino)
                        continue
                    r.raise_for_status()
                    with open(destino, "ab" if r.status_code == 206 else "wb") as f:
                        for ch in r.iter_bytes(1 << 16):
                            f.write(ch)
            except httpx.TransportError as e:
                log.info("   corte no download (%s); retomando", type(e).__name__)
    raise ArquivoRecusado(f"o ZIP não fechou depois de 15 tentativas: {url}")


# ---------------------------------------------------------------------------
# Estados
# ---------------------------------------------------------------------------
def rodar_mg(cur, conn, client, alvos: dict[str, int], anos: list[int], rod: Rodada, dry: bool) -> None:
    if not alvos:
        return
    pkg = _get_json(client, PKG_MG)
    sig = assinatura(alvos)
    pend = []
    for ano in anos:
        url, versao = _url(pkg, f"/ft_despesa_{ano}.csv.gz")
        if not url:
            if ano == anos[-1]:
                rod.parcial = True
                rod.notas.append(f"MG {ano}: ft_despesa não está no catálogo")
            continue
        if not dry and _versao(cur, "MG", f"ft_despesa_{ano}") == (versao, sig):
            log.info("MG %s: sem mudança desde a última leitura", ano)
            continue
        pend.append((ano, url, versao))
    if not pend:
        return
    dims = {}
    for nome in ("dm_favorecido", "dm_acao", "dm_tipo_documento", "dm_tempo_diario"):
        u, _ = _url(pkg, f"/{nome}.csv.gz")
        if not u:
            raise ArquivoRecusado(f"MG: {nome} não está no catálogo")
        dims[nome] = baixar(client, u)
    favs, nomes = {}, {}
    for r in _csv_gz(dims["dm_favorecido"]):
        if (r.get("tp_documento") or "").strip() == "2":
            doc = cnpj14(r.get("nr_documento_anonimizado"))
            if doc in alvos:
                i = (r.get("id_favorecido") or "").strip()
                favs[i], nomes[i] = doc, (r.get("nome_anonimizado") or "").strip() or None
    acoes = {(r.get("id_acao") or "").strip(): f"{(r.get('cd_acao') or '').strip()} {(r.get('nome') or '').strip()}"
             for r in _csv_gz(dims["dm_acao"])}
    ids_op = {(r.get("id_tipo_documento") or "").strip() for r in _csv_gz(dims["dm_tipo_documento"])
              if _RE_OP.match((r.get("nome") or "").strip())}
    tempo = {(r.get("id_tempo") or "").strip(): data_br(r.get("data_formatada"))
             for r in _csv_gz(dims["dm_tempo_diario"])}
    if not ids_op:
        raise ArquivoRecusado("MG: nenhum tipo de documento 'OP ...' em dm_tipo_documento")
    log.info("MG: %d CNPJ(s) alvo, %d achado(s) em dm_favorecido", len(alvos), len(favs))
    for ano, url, versao in pend:
        u_emp, _ = _url(pkg, f"/dm_empenho_desp_{ano}.csv.gz")
        if not u_emp:
            rod.parcial = True
            rod.notas.append(f"MG {ano}: dm_empenho_desp não está no catálogo")
            continue
        empenho_ue = {(r.get("id_empenho") or "").strip(): (r.get("unidade_executora") or "").strip()
                      for r in _csv_gz(baixar(client, u_emp))
                      if (r.get("unidade_executora") or "").strip().startswith(UE_FEAS_MG)}
        regs, n = pagamentos_mg(_csv_gz(baixar(client, url)), empenho_ue, favs, alvos, ids_op,
                                acoes, tempo, nomes)
        if n < MIN_LINHAS_MG:
            rod.parcial = True
            rod.notas.append(f"MG {ano}: ft_despesa com só {n} linha(s) — cortado?")
            continue
        log.info("MG %s: %d linhas lidas, %d empenho(s) do FEAS, %d pagamento(s) aos alvos",
                 ano, n, len(empenho_ue), len(regs))
        if dry:
            _mostra(regs)
            continue
        gravadas, recusados = troca(cur, "MG", ("ano", ano), set(alvos.values()), regs,
                                    url.rsplit("/", 1)[-1], vazio_e_valido=False)
        if recusados:
            rod.parcial = True
            rod.notas.append(f"MG {ano}: {len(recusados)} município(s) com pagamento antes e nenhum "
                             "agora — nada apagado")
        _registra(cur, "MG", f"ft_despesa_{ano}", versao, sig, n)
        conn.commit()
        rod.gravadas += gravadas


def rodar_rs(cur, conn, client, alvos: dict[str, int], anos: list[int], rod: Rodada, dry: bool) -> None:
    if not alvos:
        return
    sig = assinatura(alvos)
    for ano in anos:
        pkg = _get_json(client, PKG_RS.format(ano=ano))
        meses = sorted((re.search(r"(\d{6})\.zip$", (r.get("url") or "")) or [None, None])[1]
                       for r in _recursos(pkg) if re.search(r"\d{6}\.zip$", r.get("url") or ""))
        for am in meses:
            url, versao = _url(pkg, f"{am}.zip")
            if not dry and _versao(cur, "RS", am) == (versao, sig):
                continue
            try:
                regs, n = pagamentos_rs(linhas_rs(baixar(client, url, zip_=True)), alvos)
            except ArquivoRecusado as e:
                rod.parcial = True
                rod.notas.append(f"RS {am}: {e}")
                continue
            if n < MIN_LINHAS_RS:
                rod.parcial = True
                rod.notas.append(f"RS {am}: só {n} linha(s) — cortado?")
                continue
            log.info("RS %s: %d linhas lidas, %d pagamento(s) do FEAS aos alvos", am, n, len(regs))
            if dry:
                _mostra(regs)
                continue
            gravadas, _ = troca(cur, "RS", ("mes", int(am[:4]), int(am[4:])), set(alvos.values()),
                                regs, url.rsplit("/", 1)[-1], vazio_e_valido=True)
            _registra(cur, "RS", am, versao, sig, n)
            conn.commit()
            rod.gravadas += gravadas


def _mostra(regs: list[dict]) -> None:
    for r in sorted(regs, key=lambda x: (x["mid"], x["data"] or date.min))[:30]:
        log.info("   mid %s %s %s %s %s R$ %s", r["mid"], r["data"], r["documento"],
                 (r["favorecido_nome"] or "")[:30], (r["acao"] or "")[:40], r["valor"])


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


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    rod = Rodada()
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos, sem_fundo = alvos_por_uf(cur)
            if not any(alvos.values()):
                if not dry:
                    _log_ingest(cur, conn, "success", 0, "nenhum município de MG ou RS neste tenant")
                return 0
            if sem_fundo:
                rod.notas.append(f"{len(sem_fundo)} município(s) sem o CNPJ do fundo (FNAS ainda "
                                 f"não lido): só a prefeitura casa ({', '.join(sem_fundo[:3])})")
            hoje = datetime.now(BRT).date()
            anos = [hoje.year - 1, hoje.year]
            # Timeout de LEITURA curto (90 s): o servidor do RS às vezes para de
            # mandar bytes sem fechar a conexão — com 600 s, cada travada custava 10
            # min (medido na 1ª carga, 2025/08). A retomada por Range continua dali.
            with httpx.Client(follow_redirects=True, headers=UA,
                              timeout=httpx.Timeout(90, connect=30)) as client:
                for uf, fn in (("MG", rodar_mg), ("RS", rodar_rs)):
                    try:
                        fn(cur, conn, client, alvos[uf], anos, rod, dry)
                    except (ArquivoRecusado, RuntimeError, httpx.HTTPError) as e:
                        conn.rollback()
                        rod.parcial = True
                        rod.notas.append(f"{uf}: {type(e).__name__}: {str(e)[:160]}")
                        log.warning("%s falhou: %s", uf, e)
            if dry:
                return 0
            status = "partial" if rod.parcial else "success"
            nota = "; ".join(rod.notas)[:480] or None
            _log_ingest(cur, conn, status, rod.gravadas, nota)
            return rod.gravadas
        except Exception as e:
            conn.rollback()
            log.error("FEAS falhou: %s: %s", type(e).__name__, str(e)[:200])
            if not dry:
                _log_ingest(cur, conn, "error", rod.gravadas, f"{type(e).__name__}: {str(e)[:380]}")
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest(dry="--dry" in sys.argv)
