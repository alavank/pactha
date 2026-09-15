"""Empenhos e PAGAMENTOS do Estado de MG por convenio — dado aberto da SEGOV.

Pedido do dono (15/09/2026): "falta agora as informacoes de pagamentos" nos
convenios estaduais do RM. O banco/agencia/conta tinham acabado de aparecer
(SIGCON logado, `ler_conta_especifica`); o pagamento continuava em branco.

POR QUE EM BRANCO. A unica fonte ligada a caixa de desembolso dos estaduais e o
Portal da Transparencia (`transparencia_mg.py`), que recusa o IP do datacenter
(403 — ver docs/MAPA_RS.md e a auditoria) e nao tem task. Em producao a tabela
`transparencia_mg_empenhos` fica vazia e o RM cala.

A SAIDA: o dataset CKAN `portal_convenios_saida` da SEGOV (semanal; medido vivo
em 15/09/2026, republicado no mesmo dia):
    pagamento{ano}.csv     empenho do exercicio, com valor EMPENHADO, LIQUIDADO
                           e PAGO (valor_pago_financeiro), por nota de empenho
    pagamentorp{ano}.csv   restos a pagar (liquidado, pago processado/nao processado)
Chaveados por `contratoconvenio_saida` = nº SIAFI do convenio. ⚠️ O que a
auditoria MEDIU (bloco 3, 11/09/2026) foi a juncao desse campo com
`convenios_saida.numero_siafi` — o outro recurso do MESMO dataset da SEGOV —,
100% (5.049/5.049 em 2026). A juncao com o `nr_siafi` que o scraper do SIGCON
grava em `convenios_estadual` e HIPOTESE ate a primeira carga: o log desta
funcao imprime "N de M convenios com SIAFI casaram" — e esse o numero a olhar.
`;` como delimitador, UTF-8 com BOM, dinheiro "5209543,86", data "2026-06-24 00:00:00".

⚠️ O ARQUIVO TEM COLUNAS DE ITEM DE DESPESA/FONTE, entao uma NE com dois itens
PODERIA vir em duas linhas com o mesmo (SIAFI, NE, UO). Medido em 15/09/2026
nos arquivos vivos: pg2026 5.117 linhas = 5.117 chaves, rp2026 160 = 160 —
hoje nao acontece. A identidade da tabela e a da NOTA, e as linhas sao
AGREGADAS (`agregar_por_chave`) antes do upsert como DEFESA: se um dia vier
uma NE em duas linhas, o "SOBRESCREVE" do ON CONFLICT ficaria so com a ultima
e o empenhado/pago daquela NE sairia menor, em silencio.

⚠️ O QUE O CSV NAO TEM: data do pagamento, nº da OB e situacao da ordem de
pagamento. So o QUANTO. Por isso o RM grava o total pago em `valor_desembolsado`
e as NEs em `nes` — e NAO inventa lancamento com data (a data que existe e a do
REGISTRO DO EMPENHO, e po-la na caixa de desembolso diria que o dinheiro saiu
naquele dia). Onde o Joomla responder, ele continua valendo mais (rm_builder).

⚠️ WAF do dados.mg.gov.br: o UA padrao do curl recebe 403 "Request forbidden
by administrative rules"; UA de navegador passa (o mesmo do
sigcon_ckan_backfill; o httpx padrao tambem passou em 15/09, mas nao se aposta). Os IDs de recurso sao resolvidos por `package_show` a
cada carga, em vez de fixados: o dataset e republicado toda semana e um UUID
trocado quebraria calado.

ONDE RODA: pendurado no cron do SIGCON (run_sigcon_cron / run_queue_sigcon),
logo depois do backfill do CKAN — mesma janela noturna, sem task nova no
Coolify. O proprio ingest() se auto-limita (SEGOV_MIN_INTERVAL_H=20): a fonte e
semanal e o cron passa varias vezes por noite.

Env opcionais:
    SEGOV_MIN_INTERVAL_H   intervalo minimo entre cargas (default 20)
    SEGOV_FORCE=1          ignora o intervalo minimo
    SEGOV_ENABLED=0        desliga a carga neste tenant

Rodar a mao:  python -m ingestion.segov_pagamentos
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import sys
from datetime import datetime

import httpx
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from ingestion import status_coleta as _st
except ImportError:  # script solto no diretorio
    import status_coleta as _st  # type: ignore

log = logging.getLogger("segov_pagamentos")

SOURCE = "segov_pagamentos"
PACKAGE_URL = "https://dados.mg.gov.br/api/3/action/package_show?id=portal_convenios_saida"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131 Safari/537.36"

# Nome do recurso no CKAN -> tipo. "Pagamentos 2026" / "Restos a Pagar 2026".
_RE_RECURSO = re.compile(r"^\s*(pagamentos|restos a pagar)\s+((?:19|20)\d{2})\s*$", re.I)


# --------------------------------------------------------------- utilidades --
def _sync_url() -> str:
    return (os.getenv("DATABASE_URL_SYNC", "")
            .replace("&channel_binding=require", "").replace("?channel_binding=require", ""))


def _limpa(c) -> str:
    """Cabecalho sem BOM nem espaco. O arquivo e UTF-8 COM BOM: lido com
    `utf-8-sig` o BOM some, mas a defesa fica (a licao esta em
    sigcon_ckan_backfill._clean_col — o BOM colado na primeira coluna faz todo
    .get() devolver None, sem erro nenhum)."""
    return str(c or "").strip().lstrip("ï»¿﻿ ").strip()


def _money(s):
    """'5209543,86' -> 5209543.86; '0,0' -> 0.0; '' -> None. Tolera '1.234,56'.

    ⚠️ O contrato da fonte e VIRGULA decimal (medido nos tres CSVs). '1.000'
    sem virgula e ambiguo — mil, ou um ponto decimal? — e devolve None, que e
    "nao medido", em vez de apostar e sair mil vezes menor, calado."""
    s = str(s or "").strip().replace("R$", "").strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "." in s:
        return None
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _num0(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _dt(s):
    """'2026-06-24 00:00:00' -> date; tolera dd/mm/aaaa; None para vazio/lixo."""
    s = str(s or "").strip()[:10]
    for f in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def chave_siafi(s) -> str:
    """Chave de juncao: so digitos, sem zeros a esquerda. Os dois lados escrevem
    o mesmo numero ('9301439'); a normalizacao e defesa contra um zero a
    esquerda ou um espaco que fariam a juncao inteira sair vazia, calada."""
    d = re.sub(r"\D", "", str(s or ""))
    return d.lstrip("0") or d


def _baixar(url: str) -> bytes:
    with httpx.Client(timeout=180, follow_redirects=True, verify=False,
                      headers={"User-Agent": UA}) as cli:
        r = cli.get(url)
        r.raise_for_status()
        return r.content


# ------------------------------------------------------------- funcoes PURAS --
def resolver_recursos(pacote: dict) -> list[tuple[str, int, str]]:
    """[(tipo, ano, url)] a partir do JSON do `package_show`.

    'Pagamentos 2026' -> ('pg', 2026, url); 'Restos a Pagar 2026' -> ('rp', 2026, url).
    `convenios_saida.csv` e `datapackage.json` ficam de fora. Ordem: ano, tipo —
    o log fica legivel e o upsert nao depende dela."""
    out = []
    res = ((pacote or {}).get("result") or {}).get("resources") or []
    for r in res:
        m = _RE_RECURSO.match(str(r.get("name") or ""))
        url = (r.get("url") or "").strip()
        if not m or not url:
            continue
        tipo = "pg" if m.group(1).lower().startswith("pag") else "rp"
        out.append((tipo, int(m.group(2)), url))
    return sorted(out, key=lambda t: (t[1], t[0]))


def ler_csv(dados: bytes):
    """Itera o CSV como dicts (cabecalho limpo, valores sem espaco)."""
    txt = dados.decode("utf-8-sig", errors="replace")
    rd = csv.DictReader(io.StringIO(txt), delimiter=";")
    rd.fieldnames = [_limpa(c) for c in (rd.fieldnames or [])]
    for row in rd:
        yield {_limpa(k): str(v or "").strip() for k, v in row.items() if k is not None}


def linha_para_empenho(row: dict, tipo: str, ano: int) -> dict | None:
    """Uma linha do CSV -> as colunas de `segov_convenios_empenhos`. None quando
    a linha nao tem SIAFI ou numero de empenho (nao ha o que gravar).

    ⚠️ `vr_empenhado` e NULO no restos a pagar: aquele arquivo nao traz a
    coluna, e gravar 0 diria "nao houve empenho" sobre um RP que e, por
    definicao, empenho de outro exercicio. O pago do RP e a SOMA de processado
    e nao processado; fica None se as duas colunas vierem vazias."""
    siafi = (row.get("contratoconvenio_saida") or "").strip()
    numero = (row.get("numero_empenho") or "").strip()
    if not siafi or not numero:
        return None
    if tipo == "rp":
        vr_emp = None
        p1, p2 = row.get("valor_pago_processado"), row.get("valor_pago_nao_processado")
        vr_pago = round(_num0(_money(p1)) + _num0(_money(p2)), 2) if (p1 or p2) else None
    else:
        vr_emp = _money(row.get("valor_despesa_empenhada"))
        vr_pago = _money(row.get("valor_pago_financeiro"))
    return {
        "nr_siafi": siafi[:30],
        "ano_arquivo": int(ano),
        "tipo": tipo,
        "numero_empenho": numero[:40],
        "dt_empenho": _dt(row.get("data_registro_doc_empenho")),
        "credor_nome": (row.get("razao_social_credor") or "")[:300] or None,
        "credor_doc": (row.get("cnpj_cpf_credor_formatado") or "")[:20] or None,
        "uo_sigla": (row.get("unidade_orcamentaria_sigla") or "")[:30] or None,
        "uo_nome": (row.get("unidade_orcamentaria_nome") or "") or None,
        "fonte_recurso": (row.get("fonte_recurso_descricao") or "") or None,
        "vr_empenhado": vr_emp,
        "vr_liquidado": _money(row.get("valor_despesa_liquidada")),
        "vr_pago": vr_pago,
        "raw_data": json.dumps(row, ensure_ascii=False),
    }


def indice_convenios(linhas) -> dict:
    """{chave_siafi: (convenio_id, municipio_id)} a partir de
    (id, municipio_id, nr_siafi) de `convenios_estadual`. Chave repetida (dois
    convenios com o mesmo SIAFI nao deveria existir — `fix_duplicatas_chave_
    natural.sql` cuida disso) fica com o primeiro."""
    out: dict = {}
    for cid, mid, siafi in (linhas or []):
        k = chave_siafi(siafi)
        if k and k not in out:
            out[k] = (cid, mid)
    return out


def agregar_por_chave(empenhos) -> list[dict]:
    """Funde as linhas do CSV que caem na MESMA identidade da tabela
    (nr_siafi, ano_arquivo, tipo, numero_empenho, uo_sigla).

    O arquivo e por ITEM de despesa/fonte: uma NE com dois itens vem em duas
    linhas, e o upsert (que SOBRESCREVE) ficaria so com a ultima — o
    empenhado/liquidado/pago daquela NE sairiam menores, em silencio, com
    status 'success'. Soma os tres valores (None + None = None; None + x = x),
    guarda os itens em `raw_data` como LISTA e fica com data/credor da
    primeira linha. Ordem de chegada preservada."""
    out: dict = {}
    for e in empenhos:
        k = (e["nr_siafi"], e["ano_arquivo"], e["tipo"], e["numero_empenho"], e.get("uo_sigla") or "")
        if k not in out:
            a = dict(e)
            a["_itens"] = [e["raw_data"]]
            out[k] = a
            continue
        a = out[k]
        for c in ("vr_empenhado", "vr_liquidado", "vr_pago"):
            if e.get(c) is not None:
                a[c] = round(_num0(a.get(c)) + _num0(e[c]), 2)
        a["_itens"].append(e["raw_data"])
    res = []
    for a in out.values():
        itens = a.pop("_itens")
        a["raw_data"] = ("[" + ",".join(itens) + "]") if len(itens) > 1 else itens[0]
        res.append(a)
    return res


def casar(empenhos, por_siafi: dict) -> list[dict]:
    """So os empenhos cujo SIAFI e de um convenio nosso, ja com convenio_id e
    municipio_id. O resto do Estado e descartado aqui."""
    out = []
    for e in empenhos:
        alvo = por_siafi.get(chave_siafi(e.get("nr_siafi")))
        if not alvo:
            continue
        e = dict(e)
        e["convenio_id"], e["municipio_id"] = alvo
        out.append(e)
    return out


# --------------------------------------------------------------------- banco --
_SQL_UPSERT = """
INSERT INTO segov_convenios_empenhos
    (municipio_id, convenio_id, nr_siafi, ano_arquivo, tipo, numero_empenho, dt_empenho,
     credor_nome, credor_doc, uo_sigla, uo_nome, fonte_recurso,
     vr_empenhado, vr_liquidado, vr_pago, raw_data, updated_at)
VALUES
    (%(municipio_id)s, %(convenio_id)s, %(nr_siafi)s, %(ano_arquivo)s, %(tipo)s,
     %(numero_empenho)s, %(dt_empenho)s,
     %(credor_nome)s, %(credor_doc)s, %(uo_sigla)s, %(uo_nome)s, %(fonte_recurso)s,
     %(vr_empenhado)s, %(vr_liquidado)s, %(vr_pago)s, %(raw_data)s::jsonb, NOW())
ON CONFLICT (nr_siafi, ano_arquivo, tipo, numero_empenho, COALESCE(uo_sigla, ''))
DO UPDATE SET
    municipio_id  = EXCLUDED.municipio_id,
    convenio_id   = EXCLUDED.convenio_id,
    dt_empenho    = EXCLUDED.dt_empenho,
    credor_nome   = EXCLUDED.credor_nome,
    credor_doc    = EXCLUDED.credor_doc,
    uo_nome       = EXCLUDED.uo_nome,
    fonte_recurso = EXCLUDED.fonte_recurso,
    -- ⚠️ SOBRESCREVE, nao COALESCE: empenhado/liquidado/pago MUDAM a cada carga
    -- semanal. Um COALESCE congelaria o numero da semana em que a linha nasceu
    -- — o mesmo erro que ja custou o #328 no simec_termos.
    vr_empenhado  = EXCLUDED.vr_empenhado,
    vr_liquidado  = EXCLUDED.vr_liquidado,
    vr_pago       = EXCLUDED.vr_pago,
    raw_data      = EXCLUDED.raw_data,
    updated_at    = NOW()
"""


def _pular(cur) -> str | None:
    """Motivo para NAO carregar agora, ou None. Mesmo desenho do sismob: a fonte
    e semanal e o cron do sigcon passa varias vezes por noite — sem isto, dez
    CSVs seriam baixados a cada passagem.

    ⚠️ 'partial' CONTA como rodada aqui, DE PROPOSITO — divergencia deliberada
    em relacao ao watchdog/freshness, que so aceitam 'success' (a mesma do
    simec_termos.py). Sem isso um unico CSV que nao baixou faria baixar os dez
    em toda passagem do cron. O preco: uma noite 'partial' segura a proxima
    tentativa por 20h. Nao "corrija" um lado sem o outro."""
    if os.getenv("SEGOV_FORCE"):
        return None
    horas = float(os.getenv("SEGOV_MIN_INTERVAL_H", "20") or "20")
    try:
        cur.execute("SELECT EXTRACT(EPOCH FROM (NOW() - max(finished_at)))/3600 "
                    "FROM ingestion_log WHERE source = %s AND status IN ('success', 'partial')",
                    (SOURCE,))
        idade = cur.fetchone()[0]
        if idade is not None and float(idade) < horas:
            return f"ultima carga ha {float(idade):.1f}h (< {horas}h)"
    except Exception:
        pass  # na duvida, carrega
    return None


def ingest() -> int:
    """Baixa os CSVs da SEGOV, casa por SIAFI com os convenios estaduais do
    tenant e faz o upsert. Devolve o nº de linhas gravadas."""
    if (os.getenv("SEGOV_ENABLED", "1") or "1").strip().lower() in ("0", "false", "no"):
        log.info("SEGOV desligada neste tenant (SEGOV_ENABLED=0)")
        return 0
    url = _sync_url()
    if not url:
        log.error("DATABASE_URL_SYNC ausente")
        return 0
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    try:
        # Tenant sem municipio de MG nao tem convenio SIGCON para casar — baixar
        # o Estado inteiro seria desperdicio (mesma guarda do backfill do CKAN).
        cur.execute("SELECT count(*) FROM municipios "
                    "WHERE active = true AND upper(coalesce(uf, '')) = 'MG'")
        if (cur.fetchone() or [0])[0] == 0:
            log.info("nenhum municipio de MG neste tenant — CSV da SEGOV nao baixado")
            return 0
        motivo = _pular(cur)
        if motivo:
            log.info(f"SEGOV: pulando — {motivo}")
            return 0
        cur.execute("SELECT id, municipio_id, nr_siafi FROM convenios_estadual "
                    "WHERE nr_siafi IS NOT NULL AND nr_siafi <> ''")
        nossos = cur.fetchall()
        por_siafi = indice_convenios(nossos)

        try:
            recursos = resolver_recursos(json.loads(_baixar(PACKAGE_URL)))
        except Exception as e:
            log.error(f"package_show falhou: {str(e)[:120]}")
            recursos = []
        ok = grav = falhas = 0
        casados: set = set()
        for tipo, ano, rurl in recursos:
            try:
                dados = _baixar(rurl)
            except Exception as e:
                log.warning(f"{tipo}{ano}: download falhou: {str(e)[:100]}")
                continue
            ok += 1
            n_arq = 0
            for e in agregar_por_chave(casar(
                    (x for x in (linha_para_empenho(r, tipo, ano) for r in ler_csv(dados)) if x),
                    por_siafi)):
                casados.add(chave_siafi(e["nr_siafi"]))
                cur.execute("SAVEPOINT sp_seg")
                try:
                    cur.execute(_SQL_UPSERT, e)
                    cur.execute("RELEASE SAVEPOINT sp_seg")
                    grav += 1
                    n_arq += 1
                except Exception as ex:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_seg")
                    falhas += 1
                    if falhas <= 5:
                        log.warning(f"{tipo}{ano} siafi={e.get('nr_siafi')} "
                                    f"NE={e.get('numero_empenho')}: {str(ex)[:110]}")
            conn.commit()
            log.info(f"{tipo}{ano}: {n_arq} linha(s) gravadas")

        status, erro = _st.segov_pagamentos(ok, len(recursos), len(por_siafi), len(casados))
        if falhas and status == "success":
            status, erro = "partial", f"{falhas} linha(s) nao gravadas (ver log)"
        try:
            cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, "
                        "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
                        (SOURCE, status, grav, erro))
            conn.commit()
        except Exception:
            conn.rollback()
        log.info(f"SEGOV: {grav} empenho(s) gravados | {len(casados)} de {len(por_siafi)} "
                 f"convenios com SIAFI casaram | {ok}/{len(recursos)} CSVs | status={status}")
        return grav
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ingest()
