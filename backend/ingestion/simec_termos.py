"""TERMOS DE COMPROMISSO do SIMEC/PAR (MEC) -> tabela simec_termos.

O que o PACTHA ja tinha do SIMEC era `simec_par_liberacoes`: os PAGAMENTOS (OB,
data, valor). Faltava o INSTRUMENTO — o Termo de Compromisso: processo, tipo,
vigencia e valor. E o que o relatorio precisa para dizer "o municipio tem um TC
com clausula suspensiva de R$ 3,1 mi vencido ha 595 dias".

FONTE (publica, SEM login — verificado ao vivo 17/08/2026):
    POST https://simec.mec.gov.br/par/carregaTermos.php
    form-data: estuf=<UF>&muncod=<codigo IBGE>&requisicao=
O GET devolve so o formulario (~30KB); o POST com o municipio devolve a pagina
com as tabelas (~110KB). O campo `requisicao` existe no form mas o valor nao
altera o resultado — mandamos vazio.

TABELAS: a pagina traz mais de uma (PAR/PAC/aditivos), TODAS com o mesmo cabecalho
util: Termo de Compromisso | Processo | Nº do Documento | Tipo de Documento |
Tipo do Objeto | Data da Validacao | Periodo do Pagamento | Vigencia |
Valor do Termo (ou Quantidade de Obra). Lemos todas e deduplicamos por
(processo, nº documento) — o portal repete a MESMA linha varias vezes.

Rodar:  python -m ingestion.simec_termos
        SIMEC_TERMOS_LOTE=5 python -m ingestion.simec_termos   (so N municipios)
"""
from __future__ import annotations
import os
import re
import json
import time
import logging
from datetime import datetime

import httpx
import psycopg2

logger = logging.getLogger("simec_termos")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

_URL = "https://simec.mec.gov.br/par/carregaTermos.php"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/131 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Content-Type": "application/x-www-form-urlencoded",
}
_DELAY = float(os.getenv("SIMEC_TERMOS_DELAY", "1.5") or "1.5")
_BUDGET_S = float(os.getenv("SIMEC_TERMOS_BUDGET_S", "1500") or "1500")

# Cabecalho util (o resto da pagina tem tabelas de layout, sem estes rotulos)
_COLS = {
    "processo": ("processo",),
    "nr_documento": ("documento",),          # "Nº do Documento"
    "tipo_documento": ("tipo de documento",),
    "tipo_objeto": ("tipo do objeto", "tipo de objeto"),
    "dt_validacao": ("data da valida",),
    "periodo_pagamento": ("per", "pagamento"),   # "Período do Pagamento"
    "vigencia_txt": ("vig",),
    "valor_termo": ("valor do termo",),
    "quantidade_obra": ("quantidade de obra",),
}


def _sync_url() -> str:
    u = os.getenv("DATABASE_URL_SYNC", "") or os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    return u.replace("&channel_binding=require", "").replace("?channel_binding=require", "")


def _txt(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _data(s: str):
    """Primeira data dd/mm/aaaa do texto (as celulas trazem varias, separadas por
    virgula, e a que interessa e a primeira)."""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(0), "%d/%m/%Y").date()
    except ValueError:
        return None


def _valor(s: str):
    """'R$3.157.096,83' -> 3157096.83"""
    m = re.search(r"([\d.]+,\d{2})", (s or "").replace("\xa0", " "))
    if not m:
        return None
    try:
        return float(m.group(1).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _mapa_colunas(cab: list[str]) -> dict:
    """indice de cada coluna util, casando por FRAGMENTO do cabecalho (os rotulos
    do portal tem acento e variam entre as tabelas)."""
    idx = {}
    for i, c in enumerate(cab):
        cl = (c or "").strip().casefold()
        for campo, frags in _COLS.items():
            if campo in idx:
                continue
            if all(f in cl for f in frags) if campo == "periodo_pagamento" else any(f in cl for f in frags):
                idx[campo] = i
    return idx


def parse_termos(html: str) -> list[dict]:
    """Todas as linhas de termo da pagina, deduplicadas. Funcao PURA (testavel)."""
    achados: dict[tuple, dict] = {}
    for tabela in re.findall(r"<table.*?</table>", html, re.S | re.I):
        linhas = re.findall(r"<tr.*?</tr>", tabela, re.S | re.I)
        if len(linhas) < 2:
            continue
        cab = [_txt(x) for x in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", linhas[0], re.S | re.I)]
        idx = _mapa_colunas(cab)
        # so vale a tabela que tem processo E documento (as de layout nao tem)
        if "processo" not in idx or "nr_documento" not in idx:
            continue
        for ln in linhas[1:]:
            cels = [_txt(x) for x in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", ln, re.S | re.I)]
            if not any(cels):
                continue
            def g(campo):
                i = idx.get(campo)
                return cels[i] if i is not None and i < len(cels) else ""
            proc, doc = g("processo"), g("nr_documento")
            if not (proc or doc):
                continue
            chave = (proc, doc)
            if chave in achados:      # o portal repete a MESMA linha
                continue
            achados[chave] = {
                "processo": proc or None,
                "nr_documento": doc or None,
                "tipo_documento": g("tipo_documento") or None,
                "tipo_objeto": g("tipo_objeto") or None,
                "dt_validacao": _data(g("dt_validacao")),
                "periodo_pagamento": g("periodo_pagamento") or None,
                "vigencia_txt": g("vigencia_txt") or None,
                "dt_vigencia": _data(g("vigencia_txt")),
                "valor_termo": _valor(g("valor_termo")),
                "quantidade_obra": (g("quantidade_obra") or None),
                "raw": {k: g(k) for k in _COLS},
            }
    return list(achados.values())


def _upsert(cur, mid: int, t: dict):
    cur.execute(
        """INSERT INTO simec_termos
             (municipio_id, processo, nr_documento, tipo_documento, tipo_objeto,
              dt_validacao, periodo_pagamento, vigencia_txt, dt_vigencia,
              valor_termo, quantidade_obra, raw_data, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
           ON CONFLICT (municipio_id, COALESCE(processo, ''), COALESCE(nr_documento, ''))
           DO UPDATE SET
             tipo_documento=EXCLUDED.tipo_documento, tipo_objeto=EXCLUDED.tipo_objeto,
             dt_validacao=EXCLUDED.dt_validacao, periodo_pagamento=EXCLUDED.periodo_pagamento,
             vigencia_txt=EXCLUDED.vigencia_txt, dt_vigencia=EXCLUDED.dt_vigencia,
             valor_termo=EXCLUDED.valor_termo, quantidade_obra=EXCLUDED.quantidade_obra,
             raw_data=EXCLUDED.raw_data, updated_at=NOW()""",
        (mid, t["processo"], t["nr_documento"], t["tipo_documento"], t["tipo_objeto"],
         t["dt_validacao"], t["periodo_pagamento"], t["vigencia_txt"], t["dt_vigencia"],
         t["valor_termo"], t["quantidade_obra"], json.dumps(t["raw"], ensure_ascii=False)),
    )


def run(lote: int | None = None) -> dict:
    cn = psycopg2.connect(_sync_url())
    cur = cn.cursor()
    _lote = lote or int(os.getenv("SIMEC_TERMOS_LOTE", "0") or "0")
    # rodizio: o mais desatualizado primeiro (mesma ideia dos outros coletores)
    cur.execute("""
        SELECT m.id, m.nome, m.ibge_code, m.uf
        FROM municipios m
        LEFT JOIN (SELECT municipio_id, MAX(updated_at) u FROM simec_termos GROUP BY 1) t
               ON t.municipio_id = m.id
        WHERE m.ibge_code IS NOT NULL AND btrim(m.ibge_code) <> ''
        ORDER BY t.u NULLS FIRST, m.nome
    """)
    muns = cur.fetchall()
    if _lote:
        muns = muns[:_lote]
    logger.info(f"SIMEC termos: {len(muns)} municipio(s)")
    t0, total, com = time.time(), 0, 0
    with httpx.Client(timeout=60, verify=False, follow_redirects=True) as cli:
        cli.get(_URL, headers=_HEADERS)   # cookie de sessao do PHP
        for mid, nome, ibge, uf in muns:
            if (time.time() - t0) > _BUDGET_S:
                logger.warning("orcamento estourou — o resto entra na proxima rodada")
                break
            try:
                r = cli.post(_URL, data={"requisicao": "", "estuf": (uf or "MG"), "muncod": ibge},
                             headers=_HEADERS)
                if r.status_code != 200:
                    logger.warning(f"  {nome}: HTTP {r.status_code}")
                    continue
                termos = parse_termos(r.text)
                for t in termos:
                    _upsert(cur, mid, t)
                cn.commit()
                total += len(termos)
                com += 1 if termos else 0
                logger.info(f"  {nome}: {len(termos)} termo(s)")
            except Exception as ex:
                cn.rollback()
                logger.warning(f"  {nome}: {str(ex)[:120]}")
            time.sleep(_DELAY)
    cur.close(); cn.close()
    logger.info(f"SIMEC termos: FIM — {total} termos em {com} municipio(s), {time.time()-t0:.0f}s")
    return {"termos": total, "municipios_com_termo": com}


if __name__ == "__main__":
    run()
