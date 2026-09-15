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
identica em `ft_despesa_2026` (id_empenho 15264190, cd_documento 1939); o id
de empenho e o mesmo que o Joomla usa (`data-idEmpenho`) — provado em 1 NE de
1 municipio (Pequi); a generalizacao e hipotese.

ARQUIVOS (todos `;`, UTF-8 com BOM, gzip):
  despesa/ft_despesa_{ano}      uma linha por DOCUMENTO: id_empenho, id_tempo,
                                id_tipo_documento, tp_operacao (2 normal, 1 estorno
                                com vr_pago negativo), cd_documento (= nº da OB nas
                                linhas de tipo "OP ..."), vr_pago, vr_empenhado
                                (nas linhas EMPENHO/REFORCO/ANULACAO), id_favorecido
  despesa/dm_empenho_desp_{ano} id_empenho, nr_empenho, dt_empenho, unidade_executora,
                                tipo_empenho, vr_empenho
  despesa/dm_favorecido         id_favorecido -> CNPJ (PJ vem inteiro, sem zeros a esquerda)
  despesa/dm_tempo_diario       id_tempo -> data (a data da OB e chave substituta)
  despesa|restos/dm_tipo_documento  id -> nome ("OP PAGA", "OP PENDENTE", ...)
  restos_pagar/ft_restos_pagar_{ano}  OBs de restos a pagar: dt_documento direto,
                                cd_documento, vr_pago, id_empenho (OUTRO espaco de id)
  restos_pagar/dm_empenho_resto_{ano} id_empenho (do RP), nr_empenho, dt_original
                                (a data da NE de origem), unidade_executora, vr_empenho

JUNCAO com as NEs que a SEGOV nos deu (`segov_convenios_empenhos`):
  ⚠️ O Nº DA NE E SEQUENCIAL POR UNIDADE EXECUTORA, e a SEGOV so da a UO. Por
  (nr_empenho, dt_empenho) em dm_empenho_desp_{ano}, 1.764 das 5.117 NEs do
  pg2026 tem mais de um candidato — e 22 tem UM candidato que e OUTRA NE (a NE
  981 de 13/05/2026 de uma pessoa fisica, R$ 35,70, no lugar da NE 981 de PM
  Catugi, R$ 801 mil). A revisao adversarial pegou isso antes de subir: aceitar
  o candidato unico sem conferir gravaria OB de terceiros no convenio da
  prefeitura. Por isso a escolha CONFERE O FAVORECIDO: o `id_favorecido` das
  linhas do proprio ft, traduzido pelo `dm_favorecido` para CNPJ, tem de ser o
  credor da SEGOV. Favorecido igual aceita (mesmo com valor diferente — empenho
  ESTIMADO com reforco); favorecido diferente rejeita; favorecido desconhecido
  so com valor igual (vr_empenho, ou a soma das linhas EMPENHO/REFORCO/ANULACAO
  do ft). Medido no pg2026 (5.117 NEs) com ESTE resolver, 15/09/2026: 4.990
  casadas (97,5%), 23 rejeitadas por favorecido diferente, 104 sem candidato,
  ZERO ambiguas — a conferencia de favorecido/soma resolveu as 125 que antes
  empatavam; cobertura por valor pago 96,7%. E, NE a NE, a soma das OBs bate
  com o `valor_pago` da SEGOV em 4.989 das 4.990 (a que sobra tem uma segunda
  OB ainda fora do dump). O resolver anterior (sem favorecido) casava 4.888 e
  22 delas eram de OUTRO credor.
  Restos a pagar: o RP e resolvido em dm_empenho_resto_{ano} por (nr,
  dt_original) + favorecido, e a NE DE ORIGEM (onde a OB e pendurada, no id do
  `despesa`) por (nr, dt_original, unidade_executora) — chave exata, sem valor.
  Medido no rp2026 (160): 158 casados, 2 ambiguos, 158/158 iguais a SEGOV.
  Ambiguo NAO escolhe — registra e cala (a doutrina de casar_convenio).

O QUE NAO VEM: a SITUACAO BANCARIA ("Acatada pelo banco"). O dicionario do
`vr_pago` diz: "pagamentos efetuados ... O efetivo pagamento pode estar
pendente de transmissao ao banco e/ou sujeito a compensacao bancaria." A
tabela de situacao existe no CKAN (`fl_despesa_pgto`) mas sem chave para
juntar a OB. DECISAO DO DONO (15/09/2026, opcao 1): a OB emitida CONTA como
desembolso — "Desembolsado: R$ X" no RM e cada OB na caixa (nº · data · valor)
com o rotulo `SIT_OB`, que diz o que falta. `pagamento_confirmado` reconhece
esse rotulo (transparencia_mg.py). O estorno (tp_operacao=1, negativo) entra
com o mesmo prefixo + "estorno" e SOMA NEGATIVO: o total liquido e o que vale.

ONDE GRAVA: em `transparencia_mg_empenhos`, com o id_empenho do `despesa` — o
RM (`_mg_pagamentos`) e o export dos Estaduais (`export_pdf.py`) passam a
mostrar data/OB sem nenhuma mudanca de leitura. O bloco `pagamentos` leva
`_fonte = "cge_despesa_ob"`, e o upsert so SOBRESCREVE um bloco que e nosso ou
nulo: se o Joomla um dia responder e gravar o bloco dele (com a situacao
bancaria), ele vence. ⚠️ Honestidade: isso so vale para linha que o Joomla ja
leu antes de nos — a nossa nasce com `detalhe_lido_em` carimbado e nao entra na
fila dele (a fila e cara, 2 GET por empenho, e o Joomla esta fora do ar). Numa
linha do Joomla ainda nao lida o upsert NAO toca em `detalhe_lido_em`.

ESCOPO POR RODADA: OBs do exercicio (ft_despesa, ~40 MB gz por ano) so do ano
corrente e do anterior; restos a pagar (pequenos) idem; a DIMENSAO de empenhos
(dm, 4-10 MB) de todo ano de ORIGEM de RP na janela, porque e nela que a OB do
RP e pendurada — sem isso 38% dos RP (NE mais velha que o ano anterior) nunca
ganhariam OB depois da primeira rodada. Primeira rodada (nenhum success/partial
no ingestion_log) ou CGE_OB_BACKFILL=1: todos os anos das nossas NEs — medido
para NEs 2022-2026: ~400 MB de download; rodada normal ~120 MB. Um indice de
dimensao por vez na memoria (o de 2026 tem 400 mil linhas). Quando o exercicio
de uma NE NAO e re-varrido (origem fora da janela), as OBs ja gravadas dela
sao PRESERVADAS e so as de RP sao refeitas.

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

# O rotulo que o RM imprime em CADA OB da caixa de desembolso e que
# `pagamento_confirmado` reconhece pelo prefixo "ob emitida". Curto de
# proposito: com 70 caracteres a linha quebrava e deixava "indisponivel" orfao
# 12 vezes na mesma caixa (medido no PDF). Diz o que E e o que FALTA.
SIT_OB = "OB emitida (SIAFI-MG) — sem confirmação bancária"
SIT_OB_ESTORNO = "OB emitida (SIAFI-MG) — estorno"

# Tipos de documento pelo NOME (o id e substituto e pode mudar entre cargas).
# OB = "OP PAGA"/"OP PENDENTE" e as variantes "SEM DOCUMENTO DE ORIGEM"; "OP
# PAGAMENTO DOCUMENTO FOLHA" e folha, fica de fora.
_RE_OP = re.compile(r"^OP (PAGA|PENDENTE)( SEM DOCUMENTO DE ORIGEM)?$", re.I)
# Restos a pagar: "PAGAMENTO RESTO A PAGAR (NAO )?PROCESSADO" e "PAGAMENTO
# PENDENTE DE RPP/RPNP" (medido: cd_evento 701004, vr_pago > 0).
_RE_RP = re.compile(r"^PAGAMENTO (PENDENTE DE RP|RESTO A PAGAR)", re.I)
# As linhas que compoem o VALOR EMPENHADO da NE no ft (para desempate por soma:
# empenho estimado + reforcos - anulacoes == valor da SEGOV).
_RE_EMP = re.compile(r"^(EMPENHO|REFORCO|ANULACAO)$", re.I)


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


def _iso(dt) -> str:
    return dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt or "")[:10]


def _digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _baixar(url: str) -> bytes:
    with httpx.Client(timeout=600, follow_redirects=True, verify=False,
                      headers={"User-Agent": UA}) as cli:
        r = cli.get(url)
        r.raise_for_status()
        return r.content


def _linhas(gz_bytes: bytes):
    """Itera um csv.gz da CGE como dicts (cabecalho sem BOM). Vazio -> nada."""
    if not gz_bytes:
        return
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
    """{id_tipo_documento: NOME}."""
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
    """{(nr_empenho, 'aaaa-mm-dd'): [(id, vr_empenho, unidade_executora, tipo, ano), ...]}
    de dm_empenho_desp_{ano} (campo_data='dt_empenho') ou dm_empenho_resto_{ano}
    (campo_data='dt_original'). TUPLAS, nao dicts: o indice de 2026 tem 400 mil
    linhas e com o dict inteiro passava de 300 MB."""
    idx: dict = {}
    for r in _linhas(gz):
        k = ((r.get("nr_empenho") or "").strip(), (r.get(campo_data) or "").strip()[:10])
        if k[0] and k[1]:
            idx.setdefault(k, []).append((
                (r.get("id_empenho") or "").strip(), _num(r.get("vr_empenho")),
                (r.get("unidade_executora") or "").strip(),
                (r.get("tipo_empenho") or "").strip(), (r.get("ano_exercicio") or "").strip()))
    return idx


def candidatos(idx: dict, nr_empenho, dt) -> list:
    return list(idx.get((str(nr_empenho or "").strip(), _iso(dt)), []))


def varrer_ft(gz_ft: bytes, ids_alvo: set, ids_ob: set, ids_emp: set, tempo: dict | None) -> dict:
    """{id_empenho: {"fav": id_favorecido|None, "soma": float|None, "obs": [...]}}
    para os ids alvo, numa passada. `ids_ob` = tipos de OB (OP, ou pagamento de
    RP); `ids_emp` = tipos que compoem o empenhado (soma de vr_empenhado, para
    desempate); `tempo` None => a data esta em `dt_documento` (restos a pagar).

    Linha de OB = tipo em `ids_ob` e vr_pago != 0. tp_operacao '1' e estorno:
    o valor ja vem negativo e entra assim — o liquido e o que vale."""
    out: dict = {}
    for r in _linhas(gz_ft):
        ide = (r.get("id_empenho") or "").strip()
        if ide not in ids_alvo:
            continue
        d = out.setdefault(ide, {"fav": None, "soma": None, "obs": []})
        fav = (r.get("id_favorecido") or "").strip()
        if fav and not d["fav"]:
            d["fav"] = fav
        t = (r.get("id_tipo_documento") or "").strip()
        if t in ids_emp:
            ve = _num(r.get("vr_empenhado"))
            if ve is not None:
                d["soma"] = round(_num0(d["soma"]) + ve, 2)
        if t in ids_ob:
            v = _num(r.get("vr_pago"))
            if not v:
                continue
            estorno = (r.get("tp_operacao") or "").strip() == "1" or v < 0
            if tempo is not None:
                data = tempo.get((r.get("id_tempo") or "").strip(), "")
            else:
                data = _br(r.get("dt_documento"))
            d["obs"].append({"data": data, "numero": (r.get("cd_documento") or "").strip(),
                             "situacao": SIT_OB_ESTORNO if estorno else SIT_OB, "valor": v})
    return out


def ler_favorecidos(gz: bytes, ids_alvo: set) -> dict:
    """{id_favorecido: digitos do documento} so para os ids alvo. Para PJ o CNPJ
    vem inteiro (0 de 960 favorecidos nossos anonimizados, medido), sem zeros a
    esquerda — a comparacao tira os zeros dos dois lados."""
    out: dict = {}
    if not ids_alvo:
        return out
    for r in _linhas(gz):
        i = (r.get("id_favorecido") or "").strip()
        if i in ids_alvo:
            out[i] = _digitos(r.get("nr_documento_anonimizado"))
    return out


def _cnpj_bate(doc_fav, doc_credor) -> bool | None:
    a, b = _digitos(doc_fav).lstrip("0"), _digitos(doc_credor).lstrip("0")
    if not a or not b:
        return None
    return a == b


def escolher(cands: list, valor, credor_doc, info: dict, cnpj_por_fav: dict) -> tuple:
    """A NE certa entre os candidatos por (nr, data), ou (None, motivo).

    Favorecido IGUAL ao credor da SEGOV aceita (mesmo com valor diferente:
    empenho ESTIMADO ganha reforcos); favorecido DIFERENTE rejeita — e o caso
    das 22 NEs erradas; favorecido DESCONHECIDO (sem linha no ft) so com valor
    igual (vr_empenho ou a soma EMPENHO+REFORCO+ANULACAO do ft). Um aceito =
    'casado'; nenhum = 'favorecido_diverge' (se algum foi rejeitado por
    documento) ou 'nao_casou'; mais de um = 'ambiguo', e ambiguo nao escolhe."""
    if not cands:
        return None, "nao_achou"
    aceitos, divergiu = [], False
    for c in cands:
        i = info.get(c[0]) or {}
        fm = _cnpj_bate(cnpj_por_fav.get(i.get("fav") or ""), credor_doc)
        if fm is False:
            divergiu = True
            continue
        v = _num(valor)
        vm = v is not None and (c[1] == v or i.get("soma") == v)
        if fm is True or vm:
            aceitos.append(c)
    if len(aceitos) == 1:
        return aceitos[0], "casado"
    if not aceitos:
        return None, ("favorecido_diverge" if divergiu else "nao_casou")
    return None, "ambiguo"


def escolher_rp(cands: list, credor_doc, info_rp: dict, cnpj_por_fav: dict) -> tuple:
    """O RP certo entre os candidatos por (nr, dt_original): so o favorecido
    decide (o CSV de restos nao traz o empenhado). Sem linha paga no ft nao ha
    favorecido — e tambem nao ha OB a pendurar, entao nao faz falta."""
    if not cands:
        return None, "nao_achou"
    aceitos = [c for c in cands
               if _cnpj_bate(cnpj_por_fav.get((info_rp.get(c[0]) or {}).get("fav") or ""), credor_doc) is True]
    if len(aceitos) == 1:
        return aceitos[0], "casado"
    return None, ("ambiguo" if len(aceitos) > 1 else "nao_casou")


def origem_da_rp(cands_origem: list, unidade_executora: str) -> tuple:
    """A NE de origem (id do `despesa`) de um RP: (nr, dt_original) ja filtrados,
    a unidade executora do proprio RP fecha a chave. Unico sem filtro tambem
    serve; ambiguo nao escolhe."""
    if not cands_origem:
        return None, "nao_achou"
    ue = (unidade_executora or "").strip()
    por_ue = [c for c in cands_origem if ue and c[2] == ue]
    if len(por_ue) == 1:
        return por_ue[0], "casado"
    if not por_ue and len(cands_origem) == 1:
        return cands_origem[0], "casado"
    return None, "ambiguo"


def montar_bloco(obs: list[dict]) -> dict:
    """O bloco `pagamentos` — o formato ops_obs de `montar_pagamentos`, marcado
    com a nossa fonte, sem OB repetida. `_mg_pagamentos` ignora chaves que nao
    conhece."""
    vistos, unicos = set(), []
    for o in obs:
        k = (o.get("numero"), o.get("data"), o.get("valor"), o.get("situacao"))
        if k in vistos:
            continue
        vistos.add(k)
        unicos.append(o)
    b = montar_pagamentos(sorted(unicos, key=lambda o: _chave_data(o.get("data"))))
    b["_fonte"] = FONTE_BLOCO
    return b


def obs_do_bloco(bloco) -> list[dict]:
    """As OBs de um bloco ja gravado, no formato de entrada de `montar_bloco`."""
    if isinstance(bloco, str):
        try:
            bloco = json.loads(bloco)
        except ValueError:
            return []
    if not isinstance(bloco, dict):
        return []
    return [{"data": o.get("data_emissao_ob"), "numero": o.get("numero_ob"),
             "situacao": o.get("situacao"), "valor": o.get("valor")}
            for o in (bloco.get("obs") or []) if isinstance(o, dict)]


def _chave_data(v) -> str:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(v or ""))
    return (m.group(3) + m.group(2) + m.group(1)) if m else ""


def anos_alvo(nes: list[dict], ja_rodou: bool, hoje: date | None = None,
              backfill: bool = False) -> tuple[set, set, set]:
    """(anos de ft_despesa a varrer, anos de restos a pagar a ler, anos de
    dm_empenho_desp a indexar).

    Rodada normal: ft e RP do ano corrente e do anterior. Primeira rodada
    (nunca houve success/partial) ou CGE_OB_BACKFILL=1: todos os anos das
    nossas NEs. A DIMENSAO de empenhos entra para todo ano de ft E para todo
    ano de ORIGEM dos RP da rodada — e nela que a OB do RP e pendurada, e ela
    e pequena; o que se poupa na janela e so o ft."""
    hoje = hoje or date.today()
    pg = {int(n["ano_arquivo"]) for n in nes if n["tipo"] == "pg"}
    rp = {int(n["ano_arquivo"]) for n in nes if n["tipo"] == "rp"}
    if not (backfill or not ja_rodou):
        janela = {hoje.year, hoje.year - 1}
        pg, rp = pg & janela, rp & janela
    orig = {n["dt_empenho"].year for n in nes
            if n["tipo"] == "rp" and int(n["ano_arquivo"]) in rp and hasattr(n.get("dt_empenho"), "year")}
    return pg, rp, (pg | orig)


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
    -- ⚠️ NAO se toca no carimbo de leitura de uma linha que JA EXISTIA: se e
    -- do Joomla e ainda nao foi lida, ela continua na fila dele.
    detalhe_lido_em   = transparencia_mg_empenhos.detalhe_lido_em,
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


def _log(cur, conn, status: str, n: int, erro: str | None) -> None:
    try:
        cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, "
                    "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
                    (SOURCE, status, n, erro))
        conn.commit()
    except Exception:
        conn.rollback()


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
        try:
            return _rodada(cur, conn)
        except Exception as ex:
            # ⚠️ Uma excecao fora do SAVEPOINT (parse, gzip truncado) perdia a
            # rodada inteira SEM linha no ingestion_log — e o cron seguinte
            # baixava tudo de novo. Agora vira 'error' com a mensagem.
            conn.rollback()
            log.exception("CGE OB: rodada abortada")
            _log(cur, conn, "error", 0, f"rodada abortada: {str(ex)[:180]}")
            return 0
    finally:
        cur.close()
        conn.close()


def _rodada(cur, conn) -> int:
    cur.execute("""
        SELECT id, municipio_id, convenio_id, nr_siafi, ano_arquivo, tipo, numero_empenho,
               dt_empenho, vr_empenhado, vr_liquidado, credor_doc
          FROM segov_convenios_empenhos
         WHERE convenio_id IS NOT NULL AND dt_empenho IS NOT NULL
         ORDER BY tipo, ano_arquivo, numero_empenho
    """)
    cols = ("id", "municipio_id", "convenio_id", "nr_siafi", "ano_arquivo", "tipo",
            "numero_empenho", "dt_empenho", "vr_empenhado", "vr_liquidado", "credor_doc")
    # ⚠️ pg ANTES de rp, sempre — a linha pg e a que tem o empenhado e o ano do
    # arquivo, e a mesma NE existe nas duas (pg do ano + rp do ano seguinte).
    nes = sorted((dict(zip(cols, r)) for r in cur.fetchall()),
                 key=lambda n: (0 if n["tipo"] == "pg" else 1, int(n["ano_arquivo"]), str(n["numero_empenho"])))
    cur.execute("SELECT count(*) FROM ingestion_log WHERE source = %s AND status IN ('success', 'partial')",
                (SOURCE,))
    ja_rodou = (cur.fetchone() or [0])[0] > 0
    backfill = (os.getenv("CGE_OB_BACKFILL", "0") or "0").strip() in ("1", "true", "yes")
    anos_ft, anos_rp, anos_dm = anos_alvo(nes, ja_rodou, backfill=backfill)
    if not nes:
        log.info("CGE OB: nenhuma NE da SEGOV para resolver (segov_pagamentos ainda nao rodou?)")

    arquivos = {"total": 0, "ok": 0}
    try:
        pk_desp = json.loads(_baixar(PKG_DESPESA))
        pk_rp = json.loads(_baixar(PKG_RESTOS)) if anos_rp else {}
    except Exception as e:
        log.error(f"package_show falhou: {str(e)[:120]}")
        pk_desp, pk_rp = {}, {}

    def _pega(pk, sufixo) -> bytes | None:
        # ⚠️ Recurso AUSENTE conta como arquivo pedido e nao obtido: sem isso
        # um dm_tipo_documento sumido do CKAN dava rodada 'success' com zero OB.
        arquivos["total"] += 1
        u = url_recurso(pk, sufixo)
        if not u:
            log.warning(f"recurso ausente no CKAN: {sufixo}")
            return None
        try:
            b = _baixar(u)
            arquivos["ok"] += 1
            return b
        except Exception as e:
            log.warning(f"{sufixo}: download falhou: {str(e)[:100]}")
            return None

    tipos = ler_tipos(_pega(pk_desp, "/dm_tipo_documento.csv.gz") or b"") if pk_desp else {}
    tempo = ler_tempo(_pega(pk_desp, "/dm_tempo_diario.csv.gz") or b"") if pk_desp else {}
    if nes and (not tipos or not tempo):
        _log(cur, conn, "error", 0, "dm_tipo_documento/dm_tempo_diario vazios ou ausentes — sem como ler as OBs")
        log.error("CGE OB: dimensoes basicas ausentes; rodada encerrada")
        return 0
    ids_op, ids_rp, ids_emp = (ids_por_regex(tipos, _RE_OP), ids_por_regex(tipos, _RE_RP),
                               ids_por_regex(tipos, _RE_EMP))

    # ---- passo 1: candidatos + varredura dos ft (um indice de cada vez) ----
    cands_rp: dict = {}      # segov id (rp) -> candidatos em dm_empenho_resto
    info_rp: dict = {}       # id do RP -> {fav, obs}
    for Z in sorted(anos_rp):
        gz_dm = _pega(pk_rp, f"/dm_empenho_resto_{Z}.csv.gz")
        gz_ft = _pega(pk_rp, f"/ft_restos_pagar_{Z}.csv.gz")
        if not gz_dm or not gz_ft:
            continue
        idx = indexar_empenhos(gz_dm, "dt_original")
        ids: set = set()
        for n in nes:
            if n["tipo"] == "rp" and int(n["ano_arquivo"]) == Z:
                cands_rp[n["id"]] = candidatos(idx, n["numero_empenho"], n["dt_empenho"])
                ids.update(c[0] for c in cands_rp[n["id"]])
        del idx
        info_rp.update(varrer_ft(gz_ft, ids, ids_rp, set(), None))

    cands_pg: dict = {}      # segov id (pg) -> candidatos em dm_empenho_desp
    cands_orig: dict = {}    # segov id (rp) -> candidatos da NE DE ORIGEM em dm_empenho_desp
    info: dict = {}          # id do despesa -> {fav, soma, obs}
    varridos: set = set()    # anos cujo ft foi lido nesta rodada
    for Y in sorted(anos_dm):
        gz_dm = _pega(pk_desp, f"/dm_empenho_desp_{Y}.csv.gz")
        if not gz_dm:
            continue
        idx = indexar_empenhos(gz_dm, "dt_empenho")
        ids: set = set()
        for n in nes:
            if n["tipo"] == "pg" and int(n["ano_arquivo"]) == Y and Y in anos_ft:
                cands_pg[n["id"]] = candidatos(idx, n["numero_empenho"], n["dt_empenho"])
                ids.update(c[0] for c in cands_pg[n["id"]])
            elif n["tipo"] == "rp" and int(n["ano_arquivo"]) in anos_rp and n["dt_empenho"].year == Y:
                cands_orig[n["id"]] = candidatos(idx, n["numero_empenho"], n["dt_empenho"])
                ids.update(c[0] for c in cands_orig[n["id"]])
        del idx
        if Y in anos_ft and ids:
            gz_ft = _pega(pk_desp, f"/ft_despesa_{Y}.csv.gz")
            if gz_ft:
                info.update(varrer_ft(gz_ft, ids, ids_op, ids_emp, tempo))
                varridos.add(Y)

    favs = {d["fav"] for d in list(info.values()) + list(info_rp.values()) if d.get("fav")}
    cnpj_por_fav = ler_favorecidos(_pega(pk_desp, "/dm_favorecido.csv.gz") or b"", favs) if favs else {}

    # ---- passo 2: escolha (pg primeiro; o rp pendura na NE de origem) ----
    resolvidas: dict = {}    # id do despesa -> {"ne", "dm", "obs", "exercicio_varrido"}
    motivos = {"casado": 0, "ambiguo": 0, "nao_achou": 0, "nao_casou": 0, "favorecido_diverge": 0}
    rp_stats = {"casado": 0, "sem_rp": 0, "sem_origem": 0}
    for n in nes:
        if n["tipo"] != "pg" or n["id"] not in cands_pg:
            continue
        c, m = escolher(cands_pg[n["id"]], n["vr_empenhado"], n["credor_doc"], info, cnpj_por_fav)
        motivos[m] += 1
        if not c:
            continue
        e = resolvidas.setdefault(c[0], {"ne": n, "dm": c, "obs": [], "exercicio_varrido": False})
        if not e["exercicio_varrido"]:
            e["obs"].extend((info.get(c[0]) or {}).get("obs") or [])
            e["exercicio_varrido"] = True
    for n in nes:
        if n["tipo"] != "rp" or n["id"] not in cands_rp:
            continue
        c_rp, _m = escolher_rp(cands_rp[n["id"]], n["credor_doc"], info_rp, cnpj_por_fav)
        if not c_rp:
            rp_stats["sem_rp"] += 1
            continue
        o, _m2 = origem_da_rp(cands_orig.get(n["id"], []), c_rp[2])
        if not o:
            rp_stats["sem_origem"] += 1
            continue
        rp_stats["casado"] += 1
        e = resolvidas.setdefault(o[0], {"ne": n, "dm": o, "obs": [], "exercicio_varrido": False})
        if not e["exercicio_varrido"] and int(o[4] or 0) in varridos:
            e["obs"].extend((info.get(o[0]) or {}).get("obs") or [])
            e["exercicio_varrido"] = True
        e["obs"].extend((info_rp.get(c_rp[0]) or {}).get("obs") or [])

    # ---- passo 3: preserva as OBs ja gravadas de quem nao teve o exercicio re-varrido ----
    pendentes = [i for i, d in resolvidas.items() if not d["exercicio_varrido"]]
    if pendentes:
        cur.execute("SELECT id_empenho, pagamentos FROM transparencia_mg_empenhos "
                    "WHERE id_empenho = ANY(%s) AND pagamentos->>'_fonte' = %s",
                    ([int(i) for i in pendentes], FONTE_BLOCO))
        for ide, bloco in cur.fetchall():
            resolvidas[str(ide)]["obs"].extend(obs_do_bloco(bloco))

    # ---- passo 4: grava quem tem OB ----
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
                "cnpj_favorecido": (_digitos(n.get("credor_doc")) or None),
                "id_favorecido": (info.get(ide) or {}).get("fav"),
                "ano_exercicio": int(dm[4] or n["dt_empenho"].year),
                "nr_empenho": str(n["numero_empenho"]),
                "dt_empenho": n["dt_empenho"],
                "unidade_executora": dm[2] or None,
                "tipo_empenho": dm[3] or None,
                "vr_empenho": dm[1],
                "vr_liquidado": n.get("vr_liquidado"),
                "vr_pago": bloco.get("valor_desembolsado"),
                "convenio_id": n["convenio_id"],
                "convenio_ref": n.get("nr_siafi"),
                "pagamentos": json.dumps(bloco, ensure_ascii=False),
                "raw_data": json.dumps({"_source": SOURCE, "segov_id": n["id"],
                                        "dm": {"id_empenho": dm[0], "vr_empenho": dm[1],
                                               "unidade_executora": dm[2], "tipo_empenho": dm[3],
                                               "ano_exercicio": dm[4]},
                                        "qtd_obs": len(bloco.get("obs") or [])}, ensure_ascii=False),
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

    nes_pg = sum(1 for n in nes if n["tipo"] == "pg" and int(n["ano_arquivo"]) in anos_ft)
    nes_rp = sum(1 for n in nes if n["tipo"] == "rp" and int(n["ano_arquivo"]) in anos_rp)
    status, erro = _st.cge_despesa_ob(arquivos["ok"], arquivos["total"], nes_pg, motivos["casado"],
                                      nes_rp, rp_stats["casado"])
    if falhas and status == "success":
        status, erro = "partial", f"{falhas} empenho(s) nao gravados (ver log)"
    _log(cur, conn, status, grav, erro)
    log.info(f"CGE OB: {grav} empenho(s) com OB gravados | NEs {motivos} | RP {rp_stats} | "
             f"{arquivos['ok']}/{arquivos['total']} arquivos | anos ft={sorted(anos_ft)} "
             f"rp={sorted(anos_rp)} dm={sorted(anos_dm)} | status={status}")
    return grav


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ingest()
