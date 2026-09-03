"""
TCE-RS / LicitaCon — licitacoes e contratos do municipio (RIO GRANDE DO SUL).

O convenio federal ou estadual termina numa licitacao e num contrato, e e ai que
o prazo escorre. O TransfereGov mostra a execucao pelo lado do REPASSE; o
LicitaCon mostra pelo lado da COMPRA — que e o lado que o Tribunal fiscaliza.

Medido em Nova Palma (02/09/2026): **864 licitacoes e 1.201 contratos** de 2016 a
2026; so em 2026 sao 103 licitacoes e 96 contratos somando **R$ 19,1 milhoes**,
o maior deles a "construcao de 25 casas de alvenaria" (R$ 3,64 mi). Numa
prefeitura de 5,6 mil habitantes.

⛔⛔ **A COLETA PODE ESTAR BLOQUEADA POR IP, E ISSO NAO E DEFEITO DESTE ARQUIVO.**
Medido em 17/08 e reconfirmado em 29/08/2026: `dados.tce.rs.gov.br` devolve
**403** para o IP da VPS (54.232.208.118) e **200** para IP residencial —
bloqueio de faixa de datacenter, com e sem User-Agent de navegador. Enquanto
isso valer, o coletor grava `ingestion_log` com status `partial` e a nota do
bloqueio, e **nao trata 403 como "municipio sem licitacao"**. As saidas sao
liberacao junto ao TCE (pedido institucional/LAI), proxy de saida, ou rodar esta
coleta de outro ponto. Conferir com `scripts/reconhecimento_fontes_vps.sh`.

O ENDERECO E PREVISIVEL a partir do codigo do orgao no TCE (nao e o IBGE):

    dados/licitacon/licitacao/orgao/{orgao}.csv.zip   1,6 MB (Nova Palma)
    dados/licitacon/contrato/orgao/{orgao}.csv.zip    0,6 MB

AS ARMADILHAS, todas medidas contra a fonte em 02/09/2026:

1. ⚠️ **O CODIGO DO ORGAO NAO E O IBGE.** Nova Palma = **53100**, Santa Maria =
   **56900**. E a Camara Municipal tem codigo proprio (53101 / 56901) e **nao e
   o cliente** — mesma separacao que o SICONFI e o CHE exigem. Quando
   `municipios.tce_orgao_codigo` esta vazio, este coletor DESCOBRE o codigo pelo
   CKAN (o dataset se chama `licitacoes-pm-de-<municipio>`) e grava, em vez de
   ficar mudo esperando alguem digitar.

2. ⚠️ **O ZIP NAO TEM UM CSV, TEM TREZE** (licitacao, item, lote, proposta,
   licitante, comissao, evento, dotacao, documento, pessoas...). O de contratos
   tem nove. Abrir "o primeiro arquivo do zip" pega `comissao.csv` — que existe,
   tem cabecalho e parseia sem erro, e nao e o que se procura.

3. ⚠️ **BOM DE UTF-8, CONTEUDO EM UTF-8 — E O CONSOLE DO WINDOWS MENTE SOBRE
   ISSO.** Os bytes de "Aquisicao" sao `c3 a7`, que e UTF-8 correto. Lido com
   `latin-1`, vira `Ã§` (mojibake) — mas o console cp1252 RENDERIZA o mojibake
   como se estivesse certo e o UTF-8 correto como caixinhas. Quem "conferir pelo
   terminal" conclui exatamente o contrario da verdade e grava texto corrompido
   na tela do cliente. E `utf-8-sig`, e o BOM precisa ser comido (senao a
   primeira coluna vira `﻿CD_ORGAO` e o DictReader nao a acha).

4. ⚠️ **O SEPARADOR E VIRGULA**, apesar de o arquivo ser brasileiro e os
   numeros usarem PONTO decimal (`3489.30`). `parse_decimal_br` estragaria o
   valor. Nao ha campo com virgula decimal neste dump.

5. ⚠️ **DOIS VALORES NA LICITACAO, e a diferenca e a informacao:**
   `VL_LICITACAO` e o estimado e `VL_HOMOLOGADO` e o que saiu. Em muitas linhas
   o homologado vem VAZIO (certame ainda em andamento, ou fracassado) — vazio
   NAO e zero, e mostrar zero afirmaria que a prefeitura contratou de graca.

6. ⚠️ **O NUMERO REINICIA POR ANO E POR MODALIDADE.** A chave do LicitaCon sao
   quatro campos (orgao, numero, ano, modalidade); (numero, ano) sozinho faz um
   pregao colidir com uma concorrencia do mesmo numero. No contrato, o mesmo com
   `TP_INSTRUMENTO`: existe contrato 15 e ata 15 no mesmo ano.

Rodavel por Scheduled Task no worker de tenant com municipio do RS, ou a mao:
    python -u ingestion/tce_rs.py            # coleta de verdade
    python -u ingestion/tce_rs.py --dry      # baixa, parseia e mostra
"""
import csv
import io
import json
import logging
import os
import re
import sys
import unicodedata
import zipfile
from datetime import datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("tce_rs")

BASE = "https://dados.tce.rs.gov.br"
CKAN = f"{BASE}/api/3/action"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 dados abertos TCE-RS)"}
FONTE = "TCE-RS"
UF = "RS"
TIMEOUT = 180

# Os dois arquivos DENTRO do zip que interessam (armadilha 2).
ARQUIVO_LICITACAO = "licitacao.csv"
ARQUIVO_CONTRATO = "contrato.csv"

# ⚠️ Frase unica do bloqueio de IP, para o log e para o `ingestion_log` dizerem
# a MESMA coisa — e para ninguem ler "erro" e sair procurando defeito no parser.
NOTA_403 = ("TCE-RS respondeu 403 a este IP (bloqueio de faixa de datacenter, "
            "medido em 17/08 e 29/08/2026). Nao e ausencia de dado: o municipio "
            "pode ter licitacoes. Saidas: liberacao junto ao TCE, proxy de "
            "saida, ou coleta de outro ponto.")


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn")


def _slug(nome: str) -> str:
    """'Nova Palma' -> 'nova-palma', como o CKAN do TCE nomeia os datasets."""
    s = _sem_acento(nome).lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")


def url_licitacoes(orgao: str) -> str:
    return f"{BASE}/dados/licitacon/licitacao/orgao/{orgao}.csv.zip"


def url_contratos(orgao: str) -> str:
    return f"{BASE}/dados/licitacon/contrato/orgao/{orgao}.csv.zip"


def descobrir_orgao(client: httpx.Client, nome_municipio: str) -> str | None:
    """Codigo do orgao no TCE a partir do nome do municipio (armadilha 1).

    O dataset se chama `licitacoes-pm-de-<slug>` e o recurso aponta para
    `.../orgao/<codigo>.csv.zip` — o codigo sai da propria URL. `pm-` e
    deliberado: `cm-` e a CAMARA, que tem codigo proprio e nao e o cliente."""
    pacote = f"licitacoes-pm-de-{_slug(nome_municipio)}"
    try:
        r = client.get(f"{CKAN}/package_show", params={"id": pacote},
                       headers=UA, timeout=60)
        if r.status_code != 200:
            return None
        d = r.json()
        if not d.get("success"):
            return None
        for rec in (d.get("result") or {}).get("resources", []):
            m = re.search(r"/orgao/(\d+)\.csv", rec.get("url") or "")
            if m:
                return m.group(1)
    except Exception as e:
        log.warning("  descoberta do orgao de %s falhou: %s: %s",
                    nome_municipio, type(e).__name__, str(e)[:100])
    return None


def linhas_do_zip(conteudo: bytes, arquivo: str) -> list[dict]:
    """Le UM csv de dentro do zip (armadilhas 2, 3 e 4)."""
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        if arquivo not in z.namelist():
            raise ValueError(
                f"'{arquivo}' nao esta no zip (tem: {', '.join(z.namelist())})")
        with z.open(arquivo) as f:
            texto = io.TextIOWrapper(f, encoding="utf-8-sig", newline="")
            return list(csv.DictReader(texto, delimiter=","))


# ---------------------------------------------------------------------------
# Conversores. Nao reusa `ingestion/base.py` de proposito: aquele arquivo e
# codigo morto (zero imports em todo o repo) e o `parse_decimal_br` dele trata
# ponto como separador de MILHAR — aqui o ponto e DECIMAL (armadilha 4).
# ---------------------------------------------------------------------------
def _dec(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def _data(v):
    if not v or not str(v).strip():
        return None
    try:
        return datetime.strptime(str(v).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _int(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(str(v).strip())
    except ValueError:
        return None


def _txt(v, limite=None):
    s = (v or "").strip()
    if not s:
        return None
    return s[:limite] if limite else s


_SQL_LIC = """
INSERT INTO tce_rs_licitacoes (
    municipio_id, cd_orgao, nm_orgao, nr_licitacao, ano_licitacao,
    cd_tipo_modalidade, nr_processo, ano_processo, tp_objeto,
    cd_tipo_fase_atual, ds_objeto, vl_licitacao, vl_homologado,
    dt_abertura, dt_homologacao, dt_adjudicacao,
    tp_documento_vencedor, nr_documento_vencedor, link_licitacon,
    raw_data, atualizado_em)
VALUES (%(mid)s, %(orgao)s, %(nm)s, %(nr)s, %(ano)s, %(mod)s, %(proc)s,
        %(ano_proc)s, %(tp_obj)s, %(fase)s, %(obj)s, %(vl)s, %(vl_hom)s,
        %(dt_ab)s, %(dt_hom)s, %(dt_adj)s, %(tp_venc)s, %(nr_venc)s,
        %(link)s, %(raw)s::jsonb, NOW())
ON CONFLICT (cd_orgao, nr_licitacao, ano_licitacao, cd_tipo_modalidade)
DO UPDATE SET
    municipio_id = EXCLUDED.municipio_id, nm_orgao = EXCLUDED.nm_orgao,
    nr_processo = EXCLUDED.nr_processo, ano_processo = EXCLUDED.ano_processo,
    tp_objeto = EXCLUDED.tp_objeto,
    cd_tipo_fase_atual = EXCLUDED.cd_tipo_fase_atual,
    ds_objeto = EXCLUDED.ds_objeto, vl_licitacao = EXCLUDED.vl_licitacao,
    vl_homologado = EXCLUDED.vl_homologado, dt_abertura = EXCLUDED.dt_abertura,
    dt_homologacao = EXCLUDED.dt_homologacao,
    dt_adjudicacao = EXCLUDED.dt_adjudicacao,
    tp_documento_vencedor = EXCLUDED.tp_documento_vencedor,
    nr_documento_vencedor = EXCLUDED.nr_documento_vencedor,
    link_licitacon = EXCLUDED.link_licitacon, raw_data = EXCLUDED.raw_data,
    atualizado_em = NOW()
"""

_SQL_CON = """
INSERT INTO tce_rs_contratos (
    municipio_id, cd_orgao, nm_orgao, nr_contrato, ano_contrato, tp_instrumento,
    nr_licitacao, ano_licitacao, cd_tipo_modalidade, nr_processo, ano_processo,
    tp_documento, nr_documento, ds_objeto, vl_contrato, dt_assinatura,
    dt_inicio_vigencia, dt_final_vigencia, nr_dias_prazo, link_licitacon,
    raw_data, atualizado_em)
VALUES (%(mid)s, %(orgao)s, %(nm)s, %(nr)s, %(ano)s, %(tp)s, %(nr_lic)s,
        %(ano_lic)s, %(mod)s, %(proc)s, %(ano_proc)s, %(tp_doc)s, %(nr_doc)s,
        %(obj)s, %(vl)s, %(dt_ass)s, %(dt_ini)s, %(dt_fim)s, %(dias)s,
        %(link)s, %(raw)s::jsonb, NOW())
ON CONFLICT (cd_orgao, nr_contrato, ano_contrato, tp_instrumento)
DO UPDATE SET
    municipio_id = EXCLUDED.municipio_id, nm_orgao = EXCLUDED.nm_orgao,
    nr_licitacao = EXCLUDED.nr_licitacao, ano_licitacao = EXCLUDED.ano_licitacao,
    cd_tipo_modalidade = EXCLUDED.cd_tipo_modalidade,
    nr_processo = EXCLUDED.nr_processo, ano_processo = EXCLUDED.ano_processo,
    tp_documento = EXCLUDED.tp_documento, nr_documento = EXCLUDED.nr_documento,
    ds_objeto = EXCLUDED.ds_objeto, vl_contrato = EXCLUDED.vl_contrato,
    dt_assinatura = EXCLUDED.dt_assinatura,
    dt_inicio_vigencia = EXCLUDED.dt_inicio_vigencia,
    dt_final_vigencia = EXCLUDED.dt_final_vigencia,
    nr_dias_prazo = EXCLUDED.nr_dias_prazo,
    link_licitacon = EXCLUDED.link_licitacon, raw_data = EXCLUDED.raw_data,
    atualizado_em = NOW()
"""


def linha_licitacao(mid: int, r: dict) -> dict:
    return {
        "mid": mid,
        "orgao": _txt(r.get("CD_ORGAO"), 10),
        "nm": _txt(r.get("NM_ORGAO")),
        "nr": _txt(r.get("NR_LICITACAO"), 20),
        "ano": _int(r.get("ANO_LICITACAO")),
        "mod": _txt(r.get("CD_TIPO_MODALIDADE"), 10),
        "proc": _txt(r.get("NR_PROCESSO"), 20),
        "ano_proc": _int(r.get("ANO_PROCESSO")),
        "tp_obj": _txt(r.get("TP_OBJETO"), 10),
        "fase": _txt(r.get("CD_TIPO_FASE_ATUAL"), 10),
        "obj": _txt(r.get("DS_OBJETO")),
        "vl": _dec(r.get("VL_LICITACAO")),
        # ⚠️ Vazio continua vazio (armadilha 5): certame em andamento ou
        # fracassado nao homologou nada, e gravar 0 diria que contratou de graca.
        "vl_hom": _dec(r.get("VL_HOMOLOGADO")),
        "dt_ab": _data(r.get("DT_ABERTURA")),
        "dt_hom": _data(r.get("DT_HOMOLOGACAO")),
        "dt_adj": _data(r.get("DT_ADJUDICACAO")),
        "tp_venc": _txt(r.get("TP_DOCUMENTO_VENCEDOR"), 4),
        "nr_venc": _txt(r.get("NR_DOCUMENTO_VENCEDOR"), 20),
        "link": _txt(r.get("LINK_LICITACON_CIDADAO")),
        "raw": json.dumps(r, ensure_ascii=False),
    }


def linha_contrato(mid: int, r: dict) -> dict:
    return {
        "mid": mid,
        "orgao": _txt(r.get("CD_ORGAO"), 10),
        "nm": _txt(r.get("NM_ORGAO")),
        "nr": _txt(r.get("NR_CONTRATO"), 20),
        "ano": _int(r.get("ANO_CONTRATO")),
        "tp": _txt(r.get("TP_INSTRUMENTO"), 4) or "C",
        "nr_lic": _txt(r.get("NR_LICITACAO"), 20),
        "ano_lic": _int(r.get("ANO_LICITACAO")),
        "mod": _txt(r.get("CD_TIPO_MODALIDADE"), 10),
        "proc": _txt(r.get("NR_PROCESSO"), 20),
        "ano_proc": _int(r.get("ANO_PROCESSO")),
        "tp_doc": _txt(r.get("TP_DOCUMENTO"), 4),
        "nr_doc": _txt(r.get("NR_DOCUMENTO"), 20),
        "obj": _txt(r.get("DS_OBJETO")),
        "vl": _dec(r.get("VL_CONTRATO")),
        "dt_ass": _data(r.get("DT_ASSINATURA")),
        "dt_ini": _data(r.get("DT_INICIO_VIGENCIA")),
        "dt_fim": _data(r.get("DT_FINAL_VIGENCIA")),
        "dias": _int(r.get("NR_DIAS_PRAZO")),
        "link": _txt(r.get("LINK_LICITACON_CIDADAO")),
        "raw": json.dumps(r, ensure_ascii=False),
    }


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
def _alvos(cur) -> list[dict]:
    cur.execute("""
        SELECT id, nome, uf, coalesce(tce_orgao_codigo, '')
          FROM municipios
         WHERE active AND upper(coalesce(uf,'')) = %s
         ORDER BY nome
    """, (UF,))
    return [{"id": r[0], "nome": r[1], "uf": r[2], "orgao": (r[3] or "").strip()}
            for r in cur.fetchall()]


def _gravar_orgao(cur, municipio_id: int, orgao: str) -> None:
    cur.execute("UPDATE municipios SET tce_orgao_codigo = %s WHERE id = %s",
                (orgao, municipio_id))


def _log_ingest(cur, conn, status: str, n: int, erro: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES ('tce_rs', %s, %s, %s, NOW())",
            (status, n, erro))
        conn.commit()
    except Exception as e:
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def ingest(dry: bool = False) -> int:
    from ingestion._http_cache import baixar_se_mudou
    from ingestion._resilience import get_sync_db_url, neon_connect

    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = _alvos(cur)
            if not alvos:
                log.info("nenhum municipio do RS — TCE-RS nao se aplica a este tenant")
                if not dry:
                    _log_ingest(cur, conn, "success", 0)
                return 0

            gravados = 0
            bloqueado = False
            falhas = 0
            with httpx.Client(follow_redirects=True, headers=UA) as client:
                for a in alvos:
                    orgao = a["orgao"]
                    if not orgao:
                        orgao = descobrir_orgao(client, a["nome"]) or ""
                        if orgao:
                            log.info("  %s/%s: orgao no TCE descoberto -> %s",
                                     a["nome"], a["uf"], orgao)
                            if not dry:
                                _gravar_orgao(cur, a["id"], orgao)
                        else:
                            # Fato sobre a fonte, nao erro nosso: nem todo ente
                            # gaucho tem dataset no CKAN do TCE.
                            log.info("  %s/%s: sem codigo de orgao no TCE — pulado",
                                     a["nome"], a["uf"])
                            continue

                    for rotulo, url, arquivo, sql, monta in (
                        ("licitacoes", url_licitacoes(orgao), ARQUIVO_LICITACAO,
                         _SQL_LIC, linha_licitacao),
                        ("contratos", url_contratos(orgao), ARQUIVO_CONTRATO,
                         _SQL_CON, linha_contrato),
                    ):
                        try:
                            res = baixar_se_mudou(cur, client, url, fonte="tce_rs",
                                                  timeout=TIMEOUT, forcar=dry)
                        except httpx.HTTPStatusError as e:
                            if e.response.status_code == 403:
                                # ⛔ NAO e "municipio sem licitacao". Ver o topo.
                                bloqueado = True
                                log.error("  %s/%s %s: %s", a["nome"], a["uf"],
                                          rotulo, NOTA_403)
                            else:
                                falhas += 1
                                log.warning("  %s/%s %s: HTTP %s", a["nome"],
                                            a["uf"], rotulo, e.response.status_code)
                            continue
                        except Exception as e:
                            falhas += 1
                            log.warning("  %s/%s %s: %s: %s", a["nome"], a["uf"],
                                        rotulo, type(e).__name__, str(e)[:120])
                            continue

                        if res.nao_mudou:
                            log.info("  %s/%s %s: sem novidade na fonte",
                                     a["nome"], a["uf"], rotulo)
                            if not dry:
                                res.confirmar(cur)
                            continue

                        linhas = linhas_do_zip(res.conteudo, arquivo)
                        log.info("  %s/%s %s: %d registro(s)", a["nome"], a["uf"],
                                 rotulo, len(linhas))
                        if dry:
                            for r in linhas[-3:]:
                                m = monta(a["id"], r)
                                log.info("      %s/%s  %s  %s",
                                         m["nr"], m["ano"],
                                         (m.get("vl") if m.get("vl") is not None else "-"),
                                         (m.get("obj") or "")[:60])
                            continue
                        for r in linhas:
                            cur.execute(sql, monta(a["id"], r))
                            gravados += 1
                        # ⚠️ SO AGORA o selo e gravado — depois de processar sem
                        # erro. Gravar antes faria a proxima rodada responder 304
                        # sobre um arquivo que nunca entrou no banco.
                        res.confirmar(cur)

            if dry:
                return 0
            conn.commit()
            log.info("=== TCE-RS: %d linha(s) gravada(s), %d falha(s)%s ===",
                     gravados, falhas, ", BLOQUEADO POR IP" if bloqueado else "")
            if bloqueado:
                _log_ingest(cur, conn, "partial", gravados, NOTA_403)
            else:
                _log_ingest(cur, conn, "success" if not falhas else "partial",
                            gravados)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("TCE-RS falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ingest(dry="--dry" in sys.argv)
