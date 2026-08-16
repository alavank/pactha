"""Coletor da TRANSFERENCIA ESPECIAL / EMENDA PIX (federal) -> tabela transferegov_te.

Por que um coletor em vez de buscar ao vivo: a API "especiais"
(especiais.transferegov.sistema.gov.br/.../public/plano-acao/listagem) RATE-LIMITA
forte — bloqueia (403) depois de ~10 paginas seguidas, e concorrencia piora. Coletar
MG inteiro (~8773 planos, ~44 paginas de 200) numa request web e inviavel. Aqui, no
worker (cron), paginamos DEVAGAR com backoff no 403 e fazemos upsert incremental; se
o gateway travar no meio, o progresso ja gravado fica e a proxima rodada continua.

O RM (services/rm_builder) e a tela (routers/transferegov.buscar) leem esta tabela.

Params ATUAIS da API (mudaram — o formato antigo page/size da 403): pageNumber
(1-based) / pageSize (teto 300; 200 e estavel) / uf. Ver memory te-emenda-pix-especiais.

Rodar:  python -m ingestion.transferegov_te            (MG, default)
        TE_UF=MG TE_PAGE_DELAY=2 python -m ingestion.transferegov_te
"""
from __future__ import annotations
import os
import json
import time
import asyncio
import logging
import unicodedata

import httpx
import psycopg2

logger = logging.getLogger("transferegov_te")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

_API = ("https://especiais.transferegov.sistema.gov.br/"
        "maisbrasil-transferencia-especial-backend/api/public/plano-acao/listagem")
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/131 Safari/537.36",
    "Referer": "https://especiais.transferegov.sistema.gov.br/transferencia-especial/plano-acao/consulta",
}
_PAGE_SIZE = 200                 # teto estavel (>=400 -> 403; 300 falha na 2a pagina)
_PAGE_DELAY = float(os.getenv("TE_PAGE_DELAY", "2") or "2")   # espaco entre paginas OK
_BACKOFFS = (8, 20, 45, 90)      # esperas ao tomar 403 (o rate-limit reseta com o tempo)
_BUDGET_S = float(os.getenv("TE_BUDGET_S", "1500") or "1500")  # teto total (~25min)


def _norm(s: str) -> str:
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", s.upper())
                   if not unicodedata.combining(c)).strip()


def _sync_url() -> str:
    u = os.getenv("DATABASE_URL_SYNC", "") or os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    return u.replace("&channel_binding=require", "").replace("?channel_binding=require", "")


def _municipios_uf(cur, uf: str) -> list[tuple[str, int]]:
    """(_norm(nome), id) dos municipios da UF — para casar o beneficiario ao PACTHA.
    Ordena pelo nome mais LONGO primeiro para 'Nova Serrana' vencer 'Serrana' etc."""
    cur.execute("SELECT id, nome FROM municipios WHERE uf = %s", (uf,))
    pares = [(_norm(nome), mid) for (mid, nome) in cur.fetchall() if nome]
    pares.sort(key=lambda x: len(x[0]), reverse=True)
    return pares


def _casa_municipio(ben_norm: str, pares: list[tuple[str, int]]) -> int | None:
    """Mesma regra do routers/transferegov.buscar: beneficiario CONTEM o nome do
    municipio (ex.: 'MUNICIPIO DE NOVA SERRANA')."""
    for nome_norm, mid in pares:
        if nome_norm and (nome_norm in ben_norm or ben_norm.endswith(nome_norm)):
            return mid
    return None


async def _fetch_page(cli: httpx.AsyncClient, uf: str, page: int) -> dict | None:
    """Uma pagina, com backoff no 403 (rate-limit). None se falhar de vez."""
    params = {"pageNumber": page, "pageSize": _PAGE_SIZE, "uf": uf}
    for espera in (0, *_BACKOFFS):
        if espera:
            await asyncio.sleep(espera)
        r = await cli.get(_API, params=params, headers=_HEADERS)
        if r.status_code == 200:
            return r.json()
        logger.warning(f"  p{page}: HTTP {r.status_code} — aguardando {espera or _BACKOFFS[0]}s (rate-limit)")
    return None


def _upsert(cur, it: dict, mid: int | None):
    pid = it.get("planoAcaoId")
    if pid is None:
        return
    cur.execute(
        """INSERT INTO transferegov_te
             (plano_acao_id, municipio_id, uf, codigo, emenda, parlamentar, objeto,
              situacao, situacao_trabalho, valor_total, valor_investimento, valor_custeio,
              beneficiario_nome, beneficiario_cnpj, programa_codigo, raw_data, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
           ON CONFLICT (plano_acao_id) DO UPDATE SET
             municipio_id=EXCLUDED.municipio_id, uf=EXCLUDED.uf, codigo=EXCLUDED.codigo,
             emenda=EXCLUDED.emenda, parlamentar=EXCLUDED.parlamentar, objeto=EXCLUDED.objeto,
             situacao=EXCLUDED.situacao, situacao_trabalho=EXCLUDED.situacao_trabalho,
             valor_total=EXCLUDED.valor_total, valor_investimento=EXCLUDED.valor_investimento,
             valor_custeio=EXCLUDED.valor_custeio, beneficiario_nome=EXCLUDED.beneficiario_nome,
             beneficiario_cnpj=EXCLUDED.beneficiario_cnpj, programa_codigo=EXCLUDED.programa_codigo,
             raw_data=EXCLUDED.raw_data, updated_at=NOW()""",
        (
            int(pid), mid, it.get("uf"), it.get("planoAcaoCodigo"),
            it.get("codigoEmendaFormatado"),
            # parlamentar = parte apos o '-' do codigo da emenda (ex.: '...-DIMAS FABIANO')
            (it.get("codigoEmendaFormatado") or "").split("-", 1)[1].strip()
                if "-" in (it.get("codigoEmendaFormatado") or "") else None,
            it.get("objetoDescricao") or it.get("politicasPublicas"),
            it.get("planoAcaoSituacao"), it.get("planoTrabalhoSituacao"),
            float(it.get("valorTotal") or 0), float(it.get("valorInvestimento") or 0),
            float(it.get("valorCusteio") or 0),
            it.get("beneficiarioNome"), it.get("beneficiarioCnpj"),
            it.get("programaCodigo"), json.dumps(it, ensure_ascii=False),
        ),
    )


async def run(uf: str | None = None) -> dict:
    uf = (uf or os.getenv("TE_UF", "MG") or "MG").upper()
    cn = psycopg2.connect(_sync_url())
    cn.autocommit = False
    cur = cn.cursor()
    pares = _municipios_uf(cur, uf)
    logger.info(f"TE {uf}: {len(pares)} municipios para casar")
    t0 = time.time()
    total_api = None
    gravados = 0
    casados = 0
    completo = False
    async with httpx.AsyncClient(timeout=60, verify=False) as cli:
        page = 1
        while page <= 1000 and (time.time() - t0) < _BUDGET_S:
            data = await _fetch_page(cli, uf, page)
            if data is None:
                logger.warning(f"TE {uf}: parando na pagina {page} (403 persistente); retoma na proxima rodada")
                break
            lote = data.get("listaPlanosAcao") or []
            total_api = int(data.get("total") or 0)
            for it in lote:
                mid = _casa_municipio(_norm(it.get("beneficiarioNome") or ""), pares)
                if mid is not None:
                    casados += 1
                _upsert(cur, it, mid)
                gravados += 1
            cn.commit()   # grava a pagina (progresso persiste mesmo se travar depois)
            logger.info(f"TE {uf}: pagina {page} ({len(lote)} itens) | gravados={gravados}/{total_api} casados={casados}")
            if len(lote) < _PAGE_SIZE or (total_api and gravados >= total_api):
                completo = True
                break
            page += 1
            await asyncio.sleep(_PAGE_DELAY)
    cur.close(); cn.close()
    logger.info(f"TE {uf}: FIM — gravados={gravados} casados={casados} completo={completo} em {time.time()-t0:.0f}s")
    return {"uf": uf, "gravados": gravados, "casados": casados, "completo": completo, "total_api": total_api}


if __name__ == "__main__":
    asyncio.run(run())
