"""DATA e Nº DA ORDEM DE PAGAMENTO (OB) das notas de empenho dos convenios
estaduais de MG — dado aberto da CGE (dataset CKAN `despesa` + `restos_pagar`).

E a FASE 2 do pedido do dono (15/09/2026): a Fase 1 (`segov_pagamentos.py`)
trouxe o QUANTO por nota de empenho; faltava QUANDO e QUAL OB. A fonte que tem
isso e o Portal da Transparencia (Joomla, `transparencia_mg.py`), que recusa o
IP do datacenter (403). O dataset `despesa` de dados.mg.gov.br e "o modelo
dimensional que alimenta a consulta Despesa do Portal" (notes do package_show)
— a MESMA base, publicada como CSV no MESMO CKAN que `sigcon_ckan_backfill`
ja le da VPS toda noite. Provado em 15/09/2026: a OB que o coletor Joomla mediu
em Pequi ("25/03/2026, OB 1939, R$ 938.793,55", transparencia_mg.py:351) esta
identica em `ft_despesa_2026` (id_empenho 15264190, cd_documento 1939), e os
ids de empenho/favorecido sao os mesmos que o Joomla usa (`data-idEmpenho`).

ARQUIVOS (todos `;`, UTF-8 com BOM, gzip):
  despesa/ft_despesa_{ano}      uma linha por DOCUMENTO: id_empenho, id_tempo,
                                id_tipo_documento, tp_operacao (2 normal, 1 estorno
                                com vr_pago negativo), cd_documento (= nº da OB nas
                                linhas de tipo "OP ..."), vr_pago, id_favorecido
  despesa/dm_empenho_desp_{ano} id_empenho, nr_empenho, dt_empenho, unidade_executora,
                                tipo_empenho, vr_empenho
  despesa/dm_tempo_diario       id_tempo -> data (a data da OB e chave substituta)
  despesa|restos/dm_tipo_documento  id -> nome ("OP PAGA", "OP PENDENTE", ...)
  restos_pagar/ft_restos_pagar_{ano}  OBs de restos a pagar: dt_documento direto,
                                cd_documento, vr_pago, id_empenho (OUTRO espaco de id)
  restos_pagar/dm_empenho_resto_{ano} id_empenho (do RP), nr_empenho, dt_original
                                (a data da NE de origem), vr_empenho

JUNCAO com as NEs que a SEGOV nos deu (`segov_convenios_empenhos`), sem CNPJ:
  pg: (nr_empenho, dt_empenho) em dm_empenho_desp_{ano}; empate desfeito por
      vr_empenho == valor empenhado. Medido no Estado inteiro (pg2026, 5.117
      linhas): 4.888 unicas (95,5%), 14 ambiguas, 215 sem candidato.
  rp: (nr_empenho, dt_original) em dm_empenho_resto_{ano}; medido em rp2026:
      143/160 unicas, 17 ambiguas. As OBs do RP sao penduradas na NE DE ORIGEM
      (o id do dataset `despesa` do ano original), que e a linha que o RM le.
  Ambiguo NAO escolhe — registra e cala (a doutrina de casar_convenio).

O QUE NAO VEM: a SITUACAO BANCARIA ("Acatada pelo banco"). O dicionario do
`vr_pago` diz: "pagamentos efetuados ... O efetivo pagamento pode estar
pendente de transmissao ao banco e/ou sujeito a compensacao bancaria." A
tabela de situacao existe no CKAN (`fl_despesa_pgto`) mas sem chave para
juntar a OB. DECISAO DO DONO (15/09/2026, opcao 1): a OB emitida CONTA como
desembolso — "Desembolsado: R$ X" no RM e cada OB na caixa (nº · data · valor)
com o rotulo `SIT_OB`, que diz o que falta. `pagamento_confirmado` reconhece
esse rotulo (transparencia_mg.py). O estorno (tp_operacao=1, negativo) entra
com o mesmo rotulo + "estorno" e SOMA NEGATIVO: o total liquido e o que vale.

ONDE GRAVA: em `transparencia_mg_empenhos`, com o MESMO id_empenho do portal —
por isso o RM (`_mg_pagamentos`) e o export dos Estaduais (`export_pdf.py`)
passam a mostrar data/OB sem nenhuma mudanca de leitura. O bloco `pagamentos`
leva `_fonte = "cge_despesa_ob"`, e o upsert so SOBRESCREVE um bloco que e
nosso ou nulo: se o Joomla um dia voltar a responder e gravar o bloco dele
(que tem a situacao bancaria), ele vence e nao e apagado.

ESCOPO POR RODADA: ano corrente e anterior; TODOS os anos das nossas NEs na
primeira rodada (nenhum bloco nosso na tabela) ou com CGE_OB_BACKFILL=1.
Auto-limitado a 1x/dia (CGE_OB_MIN_INTERVAL_H=20). So tenant com municipio de
MG. Pendurado no cron do SIGCON logo depois do segov_pagamentos (que produz as
NEs que este coletor resolve).

Env opcionais: CGE_OB_MIN_INTERVAL_H (20) | CGE_OB_FORCE=1 | CGE_OB_ENABLED=0 |
CGE_OB_BACKFILL=1 (todos os anos nesta rodada).

Rodar a mao:  python -m ingestion.cge_despesa_ob
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import os
import re
import sys
from datetime import date, datetime

import httpx
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from ingestion import status_coleta as _st
    from ingestion.transparencia_mg import montar_pagamentos
except ImportError:  # script solto no diretorio
    import status_coleta as _st  # type: ignore
    from transparencia_mg import montar_pagamentos  # type: ignore

log = logging.getLogger("cge_despesa_ob")

SOURCE = "cge_despesa_ob"
FONTE_BLOCO = "cge_despesa_ob"          # `pagamentos->>'_fonte'` — a marca do que e nosso
PKG_DESPESA = "https://dados.mg.gov.br/api/3/action/package_show?id=despesa"
PKG_RESTOS = "https://dados.mg.gov.br/api/3/action/package_show?id=restos_pagar"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131 Safari/537.36"

# O rotulo que o RM imprime na caixa de desembolso e que `pagamento_confirmado`
# reconhece. Diz o que E (OB emitida no SIAFI-MG) e o que FALTA (o banco).
SIT_OB = "OB emitida (SIAFI-MG, dado aberto) — confirmação bancária indisponível"
SIT_OB_ESTORNO = "OB emitida (SIAFI-MG, dado aberto) — estorno"

# Tipos de documento que SAO ordem de pagamento, pelo NOME (o id e substituto e
# pode mudar entre cargas): "OP PAGA", "OP PENDENTE" e as variantes "SEM
# DOCUMENTO DE ORIGEM". "OP PAGAMENTO DOCUMENTO FOLHA" e folha, fica de fora.
_RE_OP = re.compile(r"^OP (PAGA|PENDENTE)( SEM DOCUMENTO DE ORIGEM)?$", re.I)
# Restos a pagar: "PAGAMENTO RESTO A PAGAR (NAO )?PROCESSADO" e
# "PAGAMENTO PENDENTE DE RPP/RPNP" (medido: cd_evento 701004, vr_pago > 0).
_RE_RP = re.compile(r"^PAGAMENTO (PENDENTE DE RP|RESTO A PAGAR)", re.I)


# --------------------------------------------------------------- utilidades --
def _sync_url() -> str:
    return (os.getenv("DATABASE_URL_SYNC", "")
            .replace("&channel_binding=require", "").replace("?channel_binding=require", ""))


def _num(s) -> float | None:
    """'938793.55' (ponto decimal, como a CGE publica) ou '938793,55'. None p/ vazio."""
    s = str(s or "").strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _num0(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _br(iso) -> str:
    """'2026-03-25' -> '25/03/2026' (o formato que ops_obs/_chave_data_br usam)."""
    s = str(iso or "").strip()[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return s


def _baixar(url: str) -> bytes:
    with httpx.Client(timeout=600, follow_redirects=True, verify=False,
                      headers={"User-Agent": UA}) as cli:
        r = cli.get(url)
        r.raise_for_status()
        return r.content


def _linhas(gz_bytes: bytes):
    """Itera um csv.gz da CGE como dicts (cabecalho sem BOM)."""
    with gzip.open(io.BytesIO(gz_bytes), "rt", encoding="utf-8-sig", errors="replace") as f:
        rd = csv.DictReader(f, delimiter=";")
        rd.fieldnames = [str(c or "").strip().lstrip("﻿") for c in (rd.fieldnames or [])]
        for row in rd:
            yield row


# ------------------------------------------------------------- funcoes PURAS --
def url_recurso(pacote: dict, sufixo: str) -> str | None:
    """URL do recurso cujo download termina em `sufixo` (ex.: '/ft_despesa_2026.csv.gz').
    Pelo SUFIXO da URL, e nao pelo nome: o nome muda de grafia entre pacotes
    ('Tipo Documento' num, 'Tipo de Documento' noutro); o arquivo nao."""
    for r in ((pacote or {}).get("result") or {}).get("resources") or []:
        u = (r.get("url") or "").strip()
        if u.endswith(sufixo):
            return u
    return None


def ler_tipos(gz: bytes) -> dict:
    """{id_tipo_documento: nome}."""
    return {r["id_tipo_documento"].strip(): (r.get("nome") or "").strip().upper()
            for r in _linhas(gz) if r.get("id_tipo_documento")}


def ids_por_regex(tipos: dict, rx) -> set:
    return {i for i, nome in tipos.items() if rx.match(nome)}


def ler_tempo(gz: bytes) -> dict:
    """{id_tempo: 'dd/mm/aaaa'} — so o que a OB precisa."""
    out = {}
    for r in _linhas(gz):
        i = (r.get("id_tempo") or "").strip()
        d = (r.get("data_formatada") or "").strip()
        if i and d:
            out[i] = _br(d)
    return out


def indexar_empenhos(gz: bytes, campo_data: str = "dt_empenho") -> dict:
    """{(nr_empenho, data 'aaaa-mm-dd'): [linha, ...]} de dm_empenho_desp_{ano}
    (campo_data='dt_empenho') ou dm_empenho_resto_{ano} (campo_data='dt_original')."""
    idx: dict = {}
    for r in _linhas(gz):
        k = ((r.get("nr_empenho") or "").strip(), (r.get(campo_data) or "").strip()[:10])
        if k[0] and k[1]:
            idx.setdefault(k, []).append(r)
    return idx


def resolver(idx: dict, nr_empenho, dt, valor) -> tuple[dict | None, str]:
    """A linha da dimensao que E a nossa NE, ou (None, motivo).

    (nr, data) primeiro; havendo mais de uma (o nº e sequencial por UNIDADE
    EXECUTORA, e a SEGOV so da a UO), desempata por vr_empenho == valor. Se
    ainda sobrar mais de uma, AMBIGUO: nao escolhe. Motivos: 'casado',
    'ambiguo', 'nao_achou'."""
    dts = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt or "")[:10]
    c = idx.get((str(nr_empenho or "").strip(), dts), [])
    if len(c) == 1:
        return c[0], "casado"
    if not c:
        return None, "nao_achou"
    v = _num(valor)
    c2 = [x for x in c if v is not None and _num(x.get("vr_empenho")) == v]
    if len(c2) == 1:
        return c2[0], "casado"
    return None, "ambiguo"


def extrair_obs(gz_ft: bytes, ids_alvo: set, ids_tipo: set, tempo: dict | None) -> dict:
    """{id_empenho: [ {data, numero, situacao, valor, id_favorecido}, ... ]} das
    linhas de OB dos empenhos alvo. `tempo` None => a data esta em `dt_documento`
    (restos a pagar); senao vem por `id_tempo`.

    Linha de OB = tipo em `ids_tipo` e vr_pago != 0. tp_operacao '1' e estorno:
    o valor ja vem negativo no arquivo e entra assim — o liquido e o que vale."""
    out: dict = {}
    for r in _linhas(gz_ft):
        ide = (r.get("id_empenho") or "").strip()
        if ide not in ids_alvo or (r.get("id_tipo_documento") or "").strip() not in ids_tipo:
            continue
        v = _num(r.get("vr_pago"))
        if not v:
            continue
        estorno = (r.get("tp_operacao") or "").strip() == "1" or v < 0
        if tempo is not None:
            data = tempo.get((r.get("id_tempo") or "").strip(), "")
        else:
            data = _br(r.get("dt_documento"))
        out.setdefault(ide, []).append({
            "data": data,
            "numero": (r.get("cd_documento") or "").strip(),
            "situacao": SIT_OB_ESTORNO if estorno else SIT_OB,
            "valor": v,
            "id_favorecido": (r.get("id_favorecido") or "").strip() or None,
        })
    return out


def montar_bloco(obs: list[dict]) -> dict:
    """O bloco `pagamentos` — o formato ops_obs de `montar_pagamentos`, marcado
    com a nossa fonte. `_mg_pagamentos` ignora chaves que nao conhece."""
    b = montar_pagamentos(sorted(obs, key=lambda o: _chave_data(o.get("data"))))
    b["_fonte"] = FONTE_BLOCO
    return b


def _chave_data(v) -> str:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(v or ""))
    return (m.group(3) + m.group(2) + m.group(1)) if m else ""


# --------------------------------------------------------------------- banco --
_SQL_UPSERT = """
INSERT INTO transparencia_mg_empenhos
    (id_empenho, municipio_id, cnpj_favorecido, id_favorecido, ano_exercicio,
     nr_empenho, dt_empenho, unidade_executora, tipo_empenho, vr_empenho,
     vr_liquidado, vr_pago, convenio_id, convenio_ref, vinculo_status,
     vinculo_metodo, pagamentos, detalhe_lido_em, raw_data, updated_at)
VALUES
    (%(id_empenho)s, %(municipio_id)s, %(cnpj_favorecido)s, %(id_favorecido)s,
     %(ano_exercicio)s, %(nr_empenho)s, %(dt_empenho)s, %(unidade_executora)s,
     %(tipo_empenho)s, %(vr_empenho)s, %(vr_liquidado)s, %(vr_pago)s,
     %(convenio_id)s, %(convenio_ref)s, 'casado', 'segov_ne',
     %(pagamentos)s::jsonb, NOW(), %(raw_data)s::jsonb, NOW())
ON CONFLICT (id_empenho) DO UPDATE SET
    -- ⚠️ O BLOCO DO JOOMLA VENCE. So se sobrescreve `pagamentos` quando o que
    -- esta la e NOSSO (`_fonte`) ou nulo: o bloco do portal tem a situacao
    -- bancaria, que o dado aberto nao tem, e nao pode ser apagado por uma
    -- recarga diaria. O mesmo vale para vr_pago e raw_data.
    pagamentos = CASE WHEN transparencia_mg_empenhos.pagamentos IS NULL
                        OR transparencia_mg_empenhos.pagamentos->>'_fonte' = %(fonte)s
                      THEN EXCLUDED.pagamentos ELSE transparencia_mg_empenhos.pagamentos END,
    vr_pago    = CASE WHEN transparencia_mg_empenhos.pagamentos IS NULL
                        OR transparencia_mg_empenhos.pagamentos->>'_fonte' = %(fonte)s
                      THEN EXCLUDED.vr_pago ELSE transparencia_mg_empenhos.vr_pago END,
    raw_data   = CASE WHEN transparencia_mg_empenhos.pagamentos IS NULL
                        OR transparencia_mg_empenhos.pagamentos->>'_fonte' = %(fonte)s
                      THEN EXCLUDED.raw_data ELSE transparencia_mg_empenhos.raw_data END,
    -- O vinculo: o nosso e por SIAFI (SEGOV), o mais solido que ha; preenche
    -- o que o portal nao casou, sem desfazer o que ele casou.
    convenio_id    = COALESCE(transparencia_mg_empenhos.convenio_id, EXCLUDED.convenio_id),
    convenio_ref   = COALESCE(transparencia_mg_empenhos.convenio_ref, EXCLUDED.convenio_ref),
    vinculo_status = CASE WHEN transparencia_mg_empenhos.convenio_id IS NULL
                          THEN 'casado' ELSE transparencia_mg_empenhos.vinculo_status END,
    vinculo_metodo = CASE WHEN transparencia_mg_empenhos.convenio_id IS NULL
                          THEN 'segov_ne' ELSE transparencia_mg_empenhos.vinculo_metodo END,
    nr_empenho        = COALESCE(transparencia_mg_empenhos.nr_empenho, EXCLUDED.nr_empenho),
    dt_empenho        = COALESCE(transparencia_mg_empenhos.dt_empenho, EXCLUDED.dt_empenho),
    unidade_executora = COALESCE(transparencia_mg_empenhos.unidade_executora, EXCLUDED.unidade_executora),
    tipo_empenho      = COALESCE(transparencia_mg_empenhos.tipo_empenho, EXCLUDED.tipo_empenho),
    vr_empenho        = COALESCE(transparencia_mg_empenhos.vr_empenho, EXCLUDED.vr_empenho),
    vr_liquidado      = COALESCE(transparencia_mg_empenhos.vr_liquidado, EXCLUDED.vr_liquidado),
    cnpj_favorecido   = COALESCE(transparencia_mg_empenhos.cnpj_favorecido, EXCLUDED.cnpj_favorecido),
    id_favorecido     = COALESCE(transparencia_mg_empenhos.id_favorecido, EXCLUDED.id_favorecido),
    detalhe_lido_em   = COALESCE(transparencia_mg_empenhos.detalhe_lido_em, NOW()),
    updated_at        = NOW()
"""


def _pular(cur) -> str | None:
    """Motivo para NAO carregar agora, ou None (20h; 'partial' conta como rodada,
    a mesma divergencia deliberada do segov_pagamentos/simec_termos)."""
    if os.getenv("CGE_OB_FORCE"):
        return None
    horas = float(os.getenv("CGE_OB_MIN_INTERVAL_H", "20") or "20")
    try:
        cur.execute("SELECT EXTRACT(EPOCH FROM (NOW() - max(finished_at)))/3600 "
                    "FROM ingestion_log WHERE source = %s AND status IN ('success', 'partial')",
                    (SOURCE,))
        idade = cur.fetchone()[0]
        if idade is not None and float(idade) < horas:
            return f"ultima carga ha {float(idade):.1f}h (< {horas}h)"
    except Exception:
        pass
    return None


def anos_alvo(nes: list[dict], anos_ja_carregados: set, hoje: date | None = None,
              backfill: bool = False) -> tuple[set, set]:
    """(anos de NE a resolver em `despesa`, anos de RP a ler em `restos_pagar`).

    Rodada normal: ano corrente e anterior. Primeira rodada (nenhum bloco nosso
    na tabela) ou CGE_OB_BACKFILL=1: todos os anos que as nossas NEs tocam.
    A NE de origem de um RP entra nos anos de `despesa` porque e nela que a OB
    do RP e pendurada."""
    hoje = hoje or date.today()
    pg = {int(n["ano_arquivo"]) for n in nes if n["tipo"] == "pg"}
    rp = {int(n["ano_arquivo"]) for n in nes if n["tipo"] == "rp"}
    orig = {n["dt_empenho"].year for n in nes if n["tipo"] == "rp" and hasattr(n.get("dt_empenho"), "year")}
    if backfill or not anos_ja_carregados:
        return (pg | orig), rp
    janela = {hoje.year, hoje.year - 1}
    return ((pg | orig) & janela), (rp & janela)


def ingest() -> int:
    """Resolve as NEs da SEGOV nos dumps da CGE, extrai as OBs e grava o bloco
    `pagamentos` em transparencia_mg_empenhos. Devolve o nº de empenhos gravados."""
    if (os.getenv("CGE_OB_ENABLED", "1") or "1").strip().lower() in ("0", "false", "no"):
        log.info("CGE OB desligada neste tenant (CGE_OB_ENABLED=0)")
        return 0
    url = _sync_url()
    if not url:
        log.error("DATABASE_URL_SYNC ausente")
        return 0
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    try:
        cur.execute("SELECT count(*) FROM municipios "
                    "WHERE active = true AND upper(coalesce(uf, '')) = 'MG'")
        if (cur.fetchone() or [0])[0] == 0:
            log.info("nenhum municipio de MG neste tenant — dumps da CGE nao baixados")
            return 0
        motivo = _pular(cur)
        if motivo:
            log.info(f"CGE OB: pulando — {motivo}")
            return 0
        cur.execute("""
            SELECT id, municipio_id, convenio_id, nr_siafi, ano_arquivo, tipo, numero_empenho,
                   dt_empenho, vr_empenhado, vr_liquidado, credor_doc
              FROM segov_convenios_empenhos
             WHERE convenio_id IS NOT NULL AND dt_empenho IS NOT NULL
        """)
        nes = [dict(zip(("id", "municipio_id", "convenio_id", "nr_siafi", "ano_arquivo", "tipo",
                         "numero_empenho", "dt_empenho", "vr_empenhado", "vr_liquidado",
                         "credor_doc"), r)) for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT ano_exercicio FROM transparencia_mg_empenhos "
                    "WHERE pagamentos->>'_fonte' = %s", (FONTE_BLOCO,))
        ja = {r[0] for r in cur.fetchall() if r[0]}
        backfill = (os.getenv("CGE_OB_BACKFILL", "0") or "0").strip() in ("1", "true", "yes")
        anos_ne, anos_rp = anos_alvo(nes, ja, backfill=backfill)
        if not nes:
            log.info("CGE OB: nenhuma NE da SEGOV para resolver (segov_pagamentos ainda nao rodou?)")
        arquivos_total = arquivos_ok = 0
        try:
            pk_desp = json.loads(_baixar(PKG_DESPESA))
            pk_rp = json.loads(_baixar(PKG_RESTOS)) if anos_rp else {}
        except Exception as e:
            log.error(f"package_show falhou: {str(e)[:120]}")
            pk_desp, pk_rp = {}, {}

        def _pega(pk, sufixo):
            nonlocal arquivos_total, arquivos_ok
            u = url_recurso(pk, sufixo)
            if not u:
                log.warning(f"recurso ausente no CKAN: {sufixo}")
                return None
            arquivos_total += 1
            try:
                b = _baixar(u)
                arquivos_ok += 1
                return b
            except Exception as e:
                log.warning(f"{sufixo}: download falhou: {str(e)[:100]}")
                return None

        tipos = ler_tipos(_pega(pk_desp, "/dm_tipo_documento.csv.gz") or b"") if pk_desp else {}
        tempo = ler_tempo(_pega(pk_desp, "/dm_tempo_diario.csv.gz") or b"") if pk_desp else {}
        ids_op, ids_rp = ids_por_regex(tipos, _RE_OP), ids_por_regex(tipos, _RE_RP)

        # 1) NEs de exercicio (pg) e NEs de ORIGEM dos RP -> id do `despesa`
        resolvidas: dict = {}      # id_empenho (despesa) -> dado da NE (nossa linha + dm)
        chave_ne: dict = {}        # (municipio_id, nr_empenho, dt) -> id_empenho (p/ pendurar RP)
        motivos = {"casado": 0, "ambiguo": 0, "nao_achou": 0}
        dms: dict = {}
        for ano in sorted(anos_ne):
            gz = _pega(pk_desp, f"/dm_empenho_desp_{ano}.csv.gz")
            if not gz:
                continue
            dms[ano] = indexar_empenhos(gz, "dt_empenho")
        for n in nes:
            ano = int(n["ano_arquivo"]) if n["tipo"] == "pg" else n["dt_empenho"].year
            if ano not in dms:
                continue
            row, motivo = resolver(dms[ano], n["numero_empenho"], n["dt_empenho"], n["vr_empenhado"])
            if n["tipo"] == "pg":
                motivos[motivo] += 1
            if not row:
                continue
            ide = row["id_empenho"].strip()
            k = (n["municipio_id"], str(n["numero_empenho"]).strip(), n["dt_empenho"])
            chave_ne[k] = ide
            resolvidas.setdefault(ide, {"ne": n, "dm": row, "obs": []})

        # 2) OBs do exercicio (ft_despesa_{ano}) para os ids resolvidos daquele ano
        for ano in sorted(anos_ne):
            alvo = {i for i, d in resolvidas.items() if d["ne"]["tipo"] == "pg"
                    and int(d["ne"]["ano_arquivo"]) == ano}
            if not alvo:
                continue
            gz = _pega(pk_desp, f"/ft_despesa_{ano}.csv.gz")
            if not gz:
                continue
            for ide, obs in extrair_obs(gz, alvo, ids_op, tempo).items():
                resolvidas[ide]["obs"].extend(obs)

        # 3) OBs de restos a pagar: resolve no dm_empenho_resto (id do RP) e
        #    pendura na NE de origem (id do despesa) pela (municipio, nr, dt_original)
        rp_sem_origem = 0
        for ano in sorted(anos_rp):
            gz_dm = _pega(pk_rp, f"/dm_empenho_resto_{ano}.csv.gz")
            gz_ft = _pega(pk_rp, f"/ft_restos_pagar_{ano}.csv.gz")
            if not gz_dm or not gz_ft:
                continue
            idx_rp = indexar_empenhos(gz_dm, "dt_original")
            id_rp_para_ne: dict = {}
            for n in nes:
                if n["tipo"] != "rp" or int(n["ano_arquivo"]) != ano:
                    continue
                row, _m = resolver(idx_rp, n["numero_empenho"], n["dt_empenho"], n["vr_liquidado"])
                if not row:
                    continue
                ide_origem = chave_ne.get((n["municipio_id"], str(n["numero_empenho"]).strip(), n["dt_empenho"]))
                if not ide_origem:
                    rp_sem_origem += 1
                    continue
                id_rp_para_ne[row["id_empenho"].strip()] = ide_origem
            if not id_rp_para_ne:
                continue
            for id_rp, obs in extrair_obs(gz_ft, set(id_rp_para_ne), ids_rp, None).items():
                resolvidas[id_rp_para_ne[id_rp]]["obs"].extend(obs)

        # 4) grava quem tem OB
        grav = falhas = 0
        for ide, d in resolvidas.items():
            if not d["obs"]:
                continue
            n, dm = d["ne"], d["dm"]
            bloco = montar_bloco(d["obs"])
            cur.execute("SAVEPOINT sp_ob")
            try:
                cur.execute(_SQL_UPSERT, {
                    "id_empenho": int(ide),
                    "municipio_id": n["municipio_id"],
                    "cnpj_favorecido": (re.sub(r"\D", "", str(n.get("credor_doc") or "")) or None),
                    "id_favorecido": next((o.get("id_favorecido") for o in d["obs"] if o.get("id_favorecido")), None),
                    "ano_exercicio": int(dm.get("ano_exercicio") or n["dt_empenho"].year),
                    "nr_empenho": str(n["numero_empenho"]),
                    "dt_empenho": n["dt_empenho"],
                    "unidade_executora": (dm.get("unidade_executora") or None),
                    "tipo_empenho": (dm.get("tipo_empenho") or None),
                    "vr_empenho": _num(dm.get("vr_empenho")),
                    "vr_liquidado": n.get("vr_liquidado"),
                    "vr_pago": bloco.get("valor_desembolsado"),
                    "convenio_id": n["convenio_id"],
                    "convenio_ref": n.get("nr_siafi"),
                    "pagamentos": json.dumps(bloco, ensure_ascii=False),
                    "raw_data": json.dumps({"_source": SOURCE, "segov_id": n["id"],
                                            "dm": dm, "qtd_obs": len(d["obs"])}, ensure_ascii=False),
                    "fonte": FONTE_BLOCO,
                })
                cur.execute("RELEASE SAVEPOINT sp_ob")
                grav += 1
            except Exception as ex:
                cur.execute("ROLLBACK TO SAVEPOINT sp_ob")
                falhas += 1
                if falhas <= 5:
                    log.warning(f"id_empenho={ide} NE={n['numero_empenho']}: {str(ex)[:110]}")
        conn.commit()

        nes_pg = sum(1 for n in nes if n["tipo"] == "pg" and (int(n["ano_arquivo"]) in anos_ne))
        status, erro = _st.cge_despesa_ob(arquivos_ok, arquivos_total, nes_pg, motivos["casado"])
        if falhas and status == "success":
            status, erro = "partial", f"{falhas} empenho(s) nao gravados (ver log)"
        try:
            cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, "
                        "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
                        (SOURCE, status, grav, erro))
            conn.commit()
        except Exception:
            conn.rollback()
        log.info(f"CGE OB: {grav} empenho(s) com OB gravados | NEs {motivos} | "
                 f"RP sem NE de origem: {rp_sem_origem} | {arquivos_ok}/{arquivos_total} arquivos | "
                 f"anos NE={sorted(anos_ne)} RP={sorted(anos_rp)} | status={status}")
        return grav
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ingest()
