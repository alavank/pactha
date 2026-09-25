"""Gera `backend/services/municipios_rs_codigo_estadual.py` — o de-para entre o
CÓDIGO ESTADUAL de município do RS (o "Cód. Município" das planilhas da SES-RS,
que é o `Cod_Municipio` da CAGE/SEFAZ) e o IBGE.

⚠️ NÃO É PARTE DA APLICAÇÃO. Roda à mão, raramente (município novo no RS é raro:
o último foi instalado em 2013), e o resultado vai versionado. A coleta noturna do
FES (`ingestion/fes_rs.py`) só lê a tabela — baixar ~120 MB de despesa do Estado
por noite para refazer a mesma conta seria desperdício.

⚠️ SEM NOME. A regra do projeto é que a chave de município é IBGE ou CNPJ, nunca
o nome (a lição da Santa Maria do Herval). A cadeia é de CÓDIGOS e CNPJs, cada
elo numa fonte oficial:

    1. Planilha do FES (saude.rs.gov.br/pagamentos-mes): em cada código de
       município, o credor que recebe "Transferências a Municípios - Fundo a
       Fundo" (modalidade 41) é o FUNDO MUNICIPAL DE SAÚDE — pelo `Cód. Credor`.
    2. Despesa do Estado (dados.rs.gov.br, `<ano>-despesa-do-estado`):
       `Cod_Credor` -> `CNPJ` do favorecido. Dá o CNPJ do fundo.
    3. Portal FNS (REPASSE-FAF-COM-POPULACAO-<ano>): `CNPJ` do fundo municipal ->
       `CO_MUNICIPIO_IBGE` (6 dígitos). É o CNPJ em que o Ministério deposita.
    4. SICONFI (`/tt/entes`): IBGE de 6 -> 7 dígitos (o 7º é verificador).

    Medido em 24/09/2026: 497 de 497 códigos, nenhum IBGE repetido.

⚠️ O CAMINHO ÓBVIO FALHA, e em cliente: casar o CNPJ da PREFEITURA (SICONFI) com
o `Cod_Municipio` das linhas de despesa em que ela é favorecida. Ali o código é o
LOCAL do gasto, não o do favorecido — um algoritmo guloso sobre essa contagem deu
"96 = Santa Maria" (96 é Porto Alegre), porque a prefeitura de Santa Maria tem
mais linhas lançadas na capital do que em casa. O fundo municipal não tem esse
ruído (conferido: o código que a despesa dá ao credor-fundo é o da SES em todos).
Essa contagem fica só como CONFERÊNCIA impressa (`concordam`/`discordam`).

⚠️ O SERVIDOR DO CKAN CORTA DOWNLOAD NO MEIO (~10 MB). Só completa com retomada
por `Range` — é o que `_baixar` faz, conferindo o zip no fim.

USO:
    python scripts/gerar_depara_municipios_rs.py --cache <pasta temporária>
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import os
import re
import sys
import unicodedata
import zipfile
from datetime import date

import httpx

CKAN = "https://dados.rs.gov.br/api/3/action/package_show?id={}-despesa-do-estado"
PAGINA_FES = "https://saude.rs.gov.br/pagamentos-mes"
PAGINA_FNS = "https://portalfns.saude.gov.br/downloads/"
SICONFI_ENTES = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/entes"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131 Safari/537.36"}
SAIDA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "backend", "services", "municipios_rs_codigo_estadual.py")


def _dig(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _chave_nome(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").upper())
    return re.sub(r"[^A-Z]", "", "".join(c for c in s if not unicodedata.combining(c)))


def _baixar(client: httpx.Client, url: str, destino: str, zip_: bool = True) -> str:
    for _ in range(15):
        tam = os.path.getsize(destino) if os.path.exists(destino) else 0
        if tam and not zip_:
            return destino
        try:
            if zip_ and zipfile.ZipFile(destino).testzip() is None:
                return destino
        except Exception:
            pass
        h = {**UA, **({"Range": f"bytes={tam}-"} if tam else {})}
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
            print(f"   corte em {os.path.basename(destino)} ({type(e).__name__}); retomando")
    raise RuntimeError(f"não completou {url}")


def fundos_da_planilha_fes(planilhas: list[str]) -> tuple[dict[int, str], dict[int, str]]:
    """({código: Cód. Credor do fundo}, {código: nome na SES}) — elo 1.

    ⚠️ TODAS as planilhas do ano, não só a do mês: em setembro de 2026 dois
    municípios não tinham recebido nenhum fundo a fundo ainda (495 de 497)."""
    import xlrd
    votos = collections.defaultdict(collections.Counter)
    nomes: dict[int, str] = {}
    for xls in planilhas:
        s = xlrd.open_workbook(xls).sheet_by_index(0)
        h = [str(x).strip() for x in s.row_values(4)]
        ic, icc, imod, im = (h.index("Cód. Município"), h.index("Cód. Credor"),
                             h.index("Cód. Modalidade"), h.index("Município"))
        for r in range(5, s.nrows):
            v = s.row_values(r)
            if not str(v[ic]).strip().isdigit():
                continue
            cod = int(v[ic])
            nomes[cod] = str(v[im]).strip()
            if str(v[imod]).strip() == "41":
                votos[cod][str(v[icc]).strip().lstrip("0")] += 1
    return {cod: c.most_common(1)[0][0] for cod, c in votos.items()}, nomes


def varre_despesa(zips: list[str], prefeituras: dict[str, int]):
    """({Cod_Credor: CNPJ}, {ibge: Counter(Cod_Municipio)} das transferências a
    município recebidas pela prefeitura — esta última só para conferência)."""
    csv.field_size_limit(1 << 30)
    credor_cnpj: dict[str, str] = {}
    pref = collections.defaultdict(collections.Counter)
    for arq in zips:
        z = zipfile.ZipFile(arq)
        with z.open(z.infolist()[0].filename) as f:
            r = csv.reader(io.TextIOWrapper(f, encoding="cp1252", newline=""), delimiter=";")
            h = next(r)
            ix = {k: i for i, k in enumerate(h)}
            for row in r:
                if len(row) < len(h):
                    continue
                cc = row[ix["Cod_Credor"]].strip().lstrip("0")
                cnpj = _dig(row[ix["CNPJ"]])
                if len(cnpj) == 14:
                    credor_cnpj.setdefault(cc, cnpj)
                ibge = prefeituras.get(cnpj)
                cm = row[ix["Cod_Municipio"]].strip()
                if ibge and cm.isdigit() and row[ix["Cod_Modalidade"]].strip() in ("40", "41"):
                    pref[ibge][int(cm)] += 1
        print(f"   lido {os.path.basename(arq)}")
    return credor_cnpj, pref


def fundos_do_fns(xlsx: str) -> dict[str, str]:
    """{CNPJ do fundo municipal: IBGE de 6 dígitos} do RS — elo 3."""
    import openpyxl
    ws = openpyxl.load_workbook(xlsx, read_only=True).worksheets[0]
    it = ws.iter_rows(values_only=True)
    for row in it:
        h = [str(x or "").strip() for x in row]
        if "CNPJ" in h:
            break
    ix = {k: i for i, k in enumerate(h)}
    votos = collections.defaultdict(collections.Counter)
    for row in it:
        ib = _dig(row[ix["CO_MUNICIPIO_IBGE"]])
        if ib.startswith("43") and str(row[ix["TP_REPASSE"]] or "").upper() != "ESTADUAL":
            votos[_dig(row[ix["CNPJ"]]).zfill(14)][ib[:6]] += 1
    return {cnpj: c.most_common(1)[0][0] for cnpj, c in votos.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--ano", type=int, default=date.today().year)
    a = ap.parse_args()
    os.makedirs(a.cache, exist_ok=True)
    with httpx.Client(timeout=300, follow_redirects=True) as c:
        # Elo 1: as planilhas do FES do ano. Link antigo republicado dá 404
        # (janeiro/2026 aparece duas vezes na página) — pula.
        html = c.get(PAGINA_FES, headers=UA).text
        fes = []
        for href in re.findall(rf'href="(/upload/arquivos/[^"]+-{a.ano}-fesgeral\.xls)"', html):
            try:
                fes.append(_baixar(c, "https://saude.rs.gov.br" + href,
                                   os.path.join(a.cache, href.rsplit("/", 1)[-1]), zip_=False))
            except httpx.HTTPStatusError as e:
                print(f"   {href}: HTTP {e.response.status_code} — pulado")
        # Elo 2: os meses do ano na despesa do Estado.
        zips = []
        for rec in c.get(CKAN.format(a.ano)).json()["result"]["resources"]:
            if rec["url"].endswith(".zip"):
                zips.append(_baixar(c, rec["url"], os.path.join(
                    a.cache, f"despesa_{rec['url'].rsplit('-', 1)[-1]}")))
        # Elo 3: o arquivo FAF mais novo do FNS.
        urls = re.findall(r'https?://[^"]*REPASSE-FAF-COM-POPULACAO[^"]*\.xlsx',
                          c.get(PAGINA_FNS, headers=UA).text)
        faf_url = max(urls, key=lambda u: re.findall(r"(20\d{2})", u)[-1])
        faf = _baixar(c, faf_url, os.path.join(a.cache, faf_url.rsplit("/", 1)[-1]), zip_=False)
        # Elo 4.
        entes = [e for e in c.get(SICONFI_ENTES).json()["items"]
                 if e["uf"] == "RS" and e["esfera"] == "M"]
    ibge7 = {str(e["cod_ibge"])[:6]: int(e["cod_ibge"]) for e in entes}
    nomes = {int(e["cod_ibge"]): e["ente"] for e in entes}
    prefeituras = {_dig(e["cnpj"]): int(e["cod_ibge"]) for e in entes}

    fundo, nomes_ses = fundos_da_planilha_fes(fes)
    credor_cnpj, pref = varre_despesa(zips, prefeituras)
    fns = fundos_do_fns(faf)
    print(f"FES: {len(fundo)} códigos; despesa: {len(credor_cnpj)} credores; "
          f"FNS: {len(fns)} fundos do RS; SICONFI: {len(entes)} municípios")

    depara: dict[int, int] = {}
    sem: list[str] = []
    for cod, credor in sorted(fundo.items()):
        cnpj = credor_cnpj.get(credor)
        i6 = fns.get(cnpj or "")
        if not cnpj or not i6 or i6 not in ibge7:
            sem.append(f"{cod} {nomes_ses.get(cod)} (credor {credor}, CNPJ {cnpj}, IBGE6 {i6})")
            continue
        depara[cod] = ibge7[i6]
    repetidos = [i for i, n in collections.Counter(depara.values()).items() if n > 1]
    if repetidos:
        # Um IBGE com dois códigos é defeito da cadeia, não da fonte: nada sai.
        raise SystemExit(f"IBGE repetido na tabela: {repetidos}")
    for s_ in sem:
        print("   sem cadeia completa:", s_)

    # CONFERÊNCIAS impressas para um humano — nenhuma decide nada.
    concordam = discordam = 0
    for cod, ibge in depara.items():
        if pref.get(ibge):
            if pref[ibge].most_common(1)[0][0] == cod:
                concordam += 1
            else:
                discordam += 1
    print(f"   conferência pela prefeitura (modalidades 40/41, código mais votado): "
          f"{concordam} concordam, {discordam} discordam (o código ali é o local do gasto)")
    for cod, ibge in sorted(depara.items()):
        if _chave_nome(nomes_ses.get(cod, "")) != _chave_nome(nomes[ibge]):
            print(f"   nome diverge (conferir): {cod} {nomes_ses.get(cod)!r} -> {nomes[ibge]!r}")

    faltam = sorted(set(nomes) - set(depara.values()))
    linhas = [
        '"""CÓDIGO ESTADUAL de município do RS (o "Cód. Município" das planilhas da\n',
        "SES-RS, que é o `Cod_Municipio` da CAGE/SEFAZ) -> IBGE.\n",
        "\n",
        "GERADO por `scripts/gerar_depara_municipios_rs.py` — não editar à mão; o método\n",
        "e as armadilhas estão lá. Cadeia sem nome: fundo municipal na planilha do FES\n",
        "(Cód. Credor) -> CNPJ na despesa do Estado (dados.rs.gov.br) -> IBGE no arquivo\n",
        "REPASSE-FAF do Portal FNS -> 7 dígitos pelo SICONFI.\n",
        "\n",
        f"Gerado em {date.today():%d/%m/%Y}: {len(depara)} de {len(nomes)} municípios.\n",
    ]
    if faltam:
        linhas.append("Fora da tabela (o coletor avisa se um município do cliente cair aqui):\n")
        linhas += [f"    {nomes[i]} ({i})\n" for i in faltam]
    linhas += ['"""\n', "\n", "CODIGO_ESTADUAL_PARA_IBGE: dict[int, int] = {\n"]
    linhas += [f"    {cod}: {ibge},  # {nomes[ibge]}\n" for cod, ibge in sorted(depara.items())]
    linhas += ["}\n"]
    # ⚠️ newline='' — o repo é LF; no Windows o modo texto gravaria CRLF.
    with open(SAIDA, "w", encoding="utf-8", newline="") as f:
        f.writelines(linhas)
    print(f"gravado {SAIDA}: {len(depara)} de {len(nomes)}")


if __name__ == "__main__":
    sys.exit(main())
