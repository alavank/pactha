"""Coletor do SISMOB — obras de saude do Ministerio da Saude.

A API do SISMOB Cidadao e PUBLICA: /api/public/obras responde 200 sem token,
sem cookie e sem login. Nao e scraping — e JSON com paginacao Spring Data.

    https://sismobcidadao.saude.gov.br/api/public/obras?municipioIbge=314340&size=200&page=0
    https://sismobcidadao.saude.gov.br/api/public/obras/{propostaId}

Escopo: TODOS os municipios ativos do banco DO AMBIENTE (cada tenant tem os
seus) — nada hardcoded. O parametro e o IBGE de 6 digitos.

Grava em `sismob_obras` (+ `sismob_obra_empresas`). Tabela propria: obra tem
etapa, percentual, empreiteira e prazo de norma, que nao cabem em "convenio".

TRES ARMADILHAS DA FONTE, todas silenciosas — leia antes de mexer:

  1. **A LISTAGEM e o DETALHE usam nomes DIFERENTES para o mesmo campo.**
     propostaId/coSeqProposta, situacaoObra/dsSituacaoObra, programa/dsPrograma,
     tipoObra/dsTipoObra, tipoRecurso/dsTipoRecurso, cnes/coCnes,
     nomeEstabelecimento/noEstabelecimentoCnes. Um {**listagem, **detalhe}
     produz um dict com as DUAS grafias, e quem ler a errada grava NULL sem erro
     nenhum. Por isso existe um mapa por ORIGEM (_DA_LISTAGEM / _DO_DETALHE).

  2. **IBGE de 7 digitos devolve HTTP 200 com totalElements: 0** — indistinguivel
     de "municipio sem obra". Mesma classe da armadilha que run_fns_local
     documenta para a UF. Guardas em _coletar_municipio.

  3. **O typo do MS: `vlPrimeraParcela`** (sem o "i"). No dia em que corrigirem,
     um leitor estrito passa a ler None e o KPI "ja repassado" cai para R$ 0 sem
     erro nenhum. _num() aceita as duas grafias.

E o sinal de estagnacao NAO e `dtAtualizacao`: medido, ela vale a mesma data
para obra abandonada ha 3,7 anos e para obra que se moveu ha 7 semanas. Quem
discrimina sao os timestamps das FOTOS (que so existem no detalhe) — por isso
buscamos o detalhe de TODA obra. Ver _atividade().

Uso:
    DATABASE_URL_SYNC=... python ingestion/sismob_obras.py

Env opcionais:
    SISMOB_MUNICIPIOS      ids separados por virgula, p/ rodar so alguns
    SISMOB_MIN_INTERVAL_H  intervalo minimo entre coletas (default 20)
    SISMOB_FORCE=1         ignora o intervalo minimo
    SISMOB_ENABLED=0       desliga a coleta neste tenant
    SISMOB_CONCURRENCY     obras em paralelo por municipio (default 2)
"""
from __future__ import annotations

import os
import sys
import json
import asyncio
import logging
import unicodedata
from datetime import date, datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from services.sismob_catalogo import (  # noqa: E402
    PRAZO_ATUALIZACAO_DIAS, rotulo_situacao,
)

log = logging.getLogger("sismob_obras")

BASE = "https://sismobcidadao.saude.gov.br/api/public"
PAGINA = 200          # nao usar o teto de 2000: payload maior sem ganho
TIMEOUT = 45


# --------------------------------------------------------------------------
# Banco
# --------------------------------------------------------------------------
def _db():
    import psycopg2
    url = (os.getenv("DATABASE_URL_SYNC", "")
           .replace("&channel_binding=require", "")
           .replace("?channel_binding=require", ""))
    if not url:
        raise RuntimeError("DATABASE_URL_SYNC nao configurada")
    return psycopg2.connect(url)


def _log_ingestao(status: str, n: int, erro: str = "") -> None:
    try:
        conn = _db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, error_message, finished_at) "
            "VALUES ('sismob', %s, %s, %s, NOW())",
            (status, n, (erro[:500] if erro else None)),
        )
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.warning(f"ingestion_log falhou: {str(e)[:120]}")


def _municipios(cur) -> list[dict]:
    """Municipios ativos com o IBGE de 6 digitos que a API pede.

    left(ibge_code,6) e a fonte PRIMARIA aqui — o parametro do SISMOB e o IBGE,
    nao o codigo do FNS. `fns_code` entra so como ultimo recurso (municipio em
    que a Central preencheu o codigo e o ibge_code ficou vazio). E a ordem
    INVERSA de run_fns_local.py, e de proposito."""
    cur.execute(
        "SELECT id, nome, uf, "
        "       COALESCE(NULLIF(left(ibge_code, 6), ''), NULLIF(fns_code, '')) "
        "FROM municipios WHERE active = true ORDER BY id"
    )
    muns = [{"id": r[0], "nome": r[1], "uf": r[2], "ibge6": (r[3] or "").strip()}
            for r in cur.fetchall()]
    filtro = os.getenv("SISMOB_MUNICIPIOS", "").strip()
    if filtro:
        ids = {int(x) for x in filtro.split(",") if x.strip().isdigit()}
        muns = [m for m in muns if m["id"] in ids]
    return muns


# --------------------------------------------------------------------------
# Normalizacao
# --------------------------------------------------------------------------
def _norm(s) -> str:
    n = unicodedata.normalize("NFKD", str(s or ""))
    return " ".join("".join(c for c in n if not unicodedata.combining(c)).upper().split())


def _num(p: dict, *nomes):
    """Primeiro nome presente.

    Existe por causa do typo do MS (`vlPrimeraParcela`, sem o "i"): aceitar as
    duas grafias custa uma linha e evita que a correcao deles zere nosso KPI de
    repasse sem erro nenhum."""
    for n in nomes:
        v = p.get(n)
        if v is not None:
            return v
    return None


def _dt(v) -> date | None:
    if not v:
        return None
    s = str(v)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        try:
            return datetime.strptime(s, "%d/%m/%Y").date()
        except ValueError:
            return None


def _ts(v) -> datetime | None:
    if not v:
        return None
    s = str(v).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        d = _dt(v)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) if d else None


def _digitos(s) -> str | None:
    d = "".join(c for c in str(s or "") if c.isdigit())
    return d or None


def _dec(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# Mapa por ORIGEM. Ver armadilha 1 no topo do modulo.
_DA_LISTAGEM = {
    "proposta_id": ("propostaId",), "numero_proposta": ("numeroProposta",),
    "situacao": ("situacaoObra",), "co_situacao_obra": ("coSituacaoObra",),
    "programa": ("programa",), "rede_programa": ("redePrograma",),
    "tipo_obra": ("tipoObra",), "co_tipo_obra": ("coTipoObra",),
    "tipo_recurso": ("tipoRecurso",),
    "estabelecimento": ("nomeEstabelecimento",), "co_cnes": ("cnes",),
    "bairro": ("novoBairro", "bairro"),
    "latitude": ("nuLatitude",), "longitude": ("nuLongitude",),
    "vl_proposta": ("vlProposta",), "vl_percentual_executado": ("vlPercentualExecutado",),
}

_DO_DETALHE = {
    "proposta_id": ("coSeqProposta", "propostaId"),
    "numero_proposta": ("nuProposta", "numeroProposta"),
    "situacao": ("dsSituacaoObra",), "co_situacao_obra": ("coSituacaoObra",),
    "programa": ("dsPrograma",), "co_programa": ("coPrograma",),
    "rede_programa": ("dsRedePrograma", "redePrograma"),
    "tipo_obra": ("dsTipoObra",), "co_tipo_obra": ("coTipoObra",),
    "tipo_recurso": ("dsTipoRecurso",), "co_tipo_recurso": ("coTipoRecurso",),
    "porte_programa": ("dsPortePrograma",),
    "ano_referencia": ("nuAnoReferencia",),
    "etapa": ("dsEtapaProposta",),
    "co_fase_projeto": ("coFaseProjeto",), "fase_projeto": ("dsFaseProjeto",),
    "justificativa": ("dsJustificativa",),
    "nu_cnpj": ("nuCnpj",), "entidade": ("noPadronizadoEntidade",),
    "estabelecimento": ("noEstabelecimentoCnes", "noEstabelecimentoProposta"),
    "co_cnes": ("coCnes",), "nu_cnes": ("nuCnes",),
    # noBairro e o nome REAL no detalhe — descoberto pelo detector de campos
    # desconhecidos na primeira execucao. Sem ele o bairro ia para NULL calado.
    "bairro": ("noBairro", "dsBairro", "novoBairro", "bairro"),
    "logradouro": ("dsLogradouro",), "cep": ("nuCep",),
    "latitude": ("nuLatitude",), "longitude": ("nuLongitude",),
    "vl_proposta": ("vlProposta",), "vl_total_contrato": ("vlTotalContrato",),
    "vl_percentual_executado": ("vlPercentualExecutado",),
    "nu_portaria": ("nuPortaria",),
    "st_aditivo_contratual": ("stAditivoContratual",),
    "possui_etapa_funcionamento": ("stPossuiEtapaFuncionamento",),
}

_DATAS_DETALHE = {
    "dt_portaria": ("dtPortaria",), "dt_cadastro": ("dtCadastro",),
    "dt_mudanca_situacao": ("dtMudancaSituacao",),
    "dt_inicio_projeto": ("dtInicioProjeto",), "dt_conclusao_projeto": ("dtConclusaoProjeto",),
    "dt_ordem_servico": ("dtOrdemServico",), "dt_inicio_obra": ("dtInicioObra",),
    "dt_provavel_execucao": ("dtProvavelExecucao",), "dt_execucao": ("dtExecucao",),
    "dt_provavel_conclusao_final": ("dtProvavelConclusaoFinal",),
    "dt_conclusao_final": ("dtConclusaoFinal",),
    "dt_inicio_funcionamento": ("dtInicioFuncionamento",),
    "dt_inauguracao": ("dtInauguracao",),
    "dt_atualizacao_fonte": ("dtAtualizacao",),
}

_TEXTO = {"numero_proposta", "situacao", "programa", "rede_programa", "tipo_obra",
          "tipo_recurso", "porte_programa", "etapa", "fase_projeto", "justificativa",
          "entidade", "estabelecimento", "bairro", "logradouro"}
_INTEIRO = {"proposta_id", "co_situacao_obra", "co_programa", "co_tipo_obra",
            "co_tipo_recurso", "co_fase_projeto", "ano_referencia"}
_DECIMAL = {"latitude", "longitude", "vl_proposta", "vl_total_contrato",
            "vl_percentual_executado"}

# Campos que a fonte pode acrescentar sem avisar. Guardamos o delta em
# raw_data._pactha para detectar deriva de contrato (ver §riscos do plano).
_CONHECIDOS_DETALHE = set()
for _m in (_DO_DETALHE, _DATAS_DETALHE):
    for _v in _m.values():
        _CONHECIDOS_DETALHE.update(_v)
_CONHECIDOS_DETALHE.update({"gruposFotografias", "empresas", "noMunicipio",
                            "noMunicipioAcentuado", "sgUf", "nuEndereco",
                            "dsComplemento", "coUnidade", "coEsferaAdministrativa",
                            "dsEsferaAdministrativa", "dsTipoRecursoFiltro",
                            "coTipoExecucaoProjeto", "dsTipoFormaExecucaoProjeto",
                            "dtPrevistaInicioProjeto", "dtPrevistaConclusaoProjeto",
                            "dtPrevistaInicioFuncionamento", "dtPrevistaInauguracao",
                            "coBairro", "noBairro",
                            "vlPrimeraParcela", "vlPrimeiraParcela", "dtPrimeiraParcela",
                            "vlSegundaParcela", "dtSegundaParcela",
                            "vlTerceiraParcela", "dtTerceiraParcela",
                            "vlQuartaParcela", "dtQuartaParcela"})


def _aplicar(dest: dict, origem: dict, mapa: dict, datas: bool = False) -> None:
    for col, nomes in mapa.items():
        v = _num(origem, *nomes)
        if v in (None, ""):
            continue
        if datas:
            dest[col] = _dt(v)
        elif col in _INTEIRO:
            try:
                dest[col] = int(v)
            except (TypeError, ValueError):
                pass
        elif col in _DECIMAL:
            dest[col] = _dec(v)
        elif col in _TEXTO:
            dest[col] = str(v).strip() or None
        else:
            dest[col] = v


def _maior_ts(no, achados: list) -> None:
    """Percorre a arvore de fotos atras de QUALQUER dtAtualizacao.

    Recursivo de proposito: hoje vem `gruposFotografias[].fotos[].dtAtualizacao`,
    mas se um dia a forma mudar (grupo com data, ou nivel a mais), o walk
    continua achando em vez de silenciosamente zerar o sinal de atividade."""
    if isinstance(no, dict):
        for k, v in no.items():
            if k == "dtAtualizacao" and v:
                t = _ts(v)
                if t:
                    achados.append(t)
            else:
                _maior_ts(v, achados)
    elif isinstance(no, list):
        for item in no:
            _maior_ts(item, achados)


def _fotos(det: dict) -> tuple[int, int, datetime | None]:
    grupos = det.get("gruposFotografias") or []
    total = 0
    for g in grupos:
        fotos = (g or {}).get("fotos") or []
        total += len(fotos)
    achados: list[datetime] = []
    _maior_ts(grupos, achados)
    return len(grupos), total, (max(achados) if achados else None)


def _parcelas(det: dict) -> dict:
    """Parcelas 1..4, todas opcionais, e o regime DERIVADO.

    Nao existe "1a/2a/3a parcela" fixa: a norma vigente e parcela unica, e o
    regime antigo (medido nesta base) veio 20% + 80% em duas parcelas — nem o
    "20/60/20" que se repete por ai confere. Por isso nada e assumido."""
    nomes = (("dtPrimeiraParcela", ("vlPrimeraParcela", "vlPrimeiraParcela")),
             ("dtSegundaParcela", ("vlSegundaParcela",)),
             ("dtTerceiraParcela", ("vlTerceiraParcela",)),
             ("dtQuartaParcela", ("vlQuartaParcela",)))
    # Decimal, nao float: somar 13670.51 + 54682.04 em float devolve
    # 68352.55000000001 e o round por obra faz o total perder centavo. E dinheiro.
    out, pagas, soma = {}, 0, Decimal("0")
    for i, (dt_key, vl_keys) in enumerate(nomes, start=1):
        rot = {1: "primeira", 2: "segunda", 3: "terceira", 4: "quarta"}[i]
        d = _dt(det.get(dt_key))
        v = _dec(_num(det, *vl_keys))
        out[f"dt_{rot}_parcela"] = d
        out[f"vl_{rot}_parcela"] = v
        if d:
            pagas += 1
            soma += Decimal(str(v)) if v is not None else Decimal("0")
    out["parcelas_pagas"] = pagas
    out["repasse_total"] = soma.quantize(Decimal("0.01"))
    out["regime_parcelas"] = ("sem_repasse" if pagas == 0
                              else "unica" if pagas == 1 else "multipla")
    return out


def _atividade(obra: dict, fotos_ultima: datetime | None,
               pct_anterior, pct_mudou_anterior: date | None, hoje: date) -> dict:
    """ultima_atividade_em = GREATEST(foto, mudanca de situacao, mudanca de %).

    NAO usa `dtAtualizacao`: medido em producao, ela vale a mesma data para uma
    obra abandonada ha 3,7 anos e para uma que se moveu ha 7 semanas (houve
    toque em lote na base do MS), e e NULL em pelo menos uma obra. Usa-la faria
    o painel pintar de verde exatamente as obras paradas com dinheiro na conta."""
    pct_novo = obra.get("vl_percentual_executado")
    if pct_anterior is not None and pct_novo is not None and float(pct_anterior) != float(pct_novo):
        pct_mudou = hoje
    else:
        pct_mudou = pct_mudou_anterior

    candidatos = [d for d in (
        fotos_ultima.date() if fotos_ultima else None,
        obra.get("dt_mudanca_situacao"),
        pct_mudou,
    ) if d]
    return {"pct_mudou_em": pct_mudou,
            "ultima_atividade_em": max(candidatos) if candidatos else None}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
async def _listar(client, ibge6: str) -> tuple[list[dict], int]:
    itens, pagina, total = [], 0, 0
    while pagina < 40:
        r = await client.get(f"{BASE}/obras",
                             params={"municipioIbge": ibge6, "size": PAGINA, "page": pagina})
        r.raise_for_status()
        d = r.json()
        total = d.get("totalElements") or 0
        itens += d.get("content") or []
        if pagina + 1 >= (d.get("totalPages") or 1):
            break
        pagina += 1
    return itens, total


async def _detalhe(client, proposta_id) -> dict | None:
    try:
        r = await client.get(f"{BASE}/obras/{proposta_id}")
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"    detalhe {proposta_id} falhou: {type(e).__name__}: {str(e)[:90]}")
        return None


# --------------------------------------------------------------------------
# Persistencia
# --------------------------------------------------------------------------
_COLS = [
    "proposta_id", "municipio_id", "numero_proposta", "nu_cnpj", "entidade",
    "co_programa", "programa", "rede_programa", "co_tipo_obra", "tipo_obra",
    "co_tipo_recurso", "tipo_recurso", "porte_programa", "ano_referencia",
    "co_situacao_obra", "situacao", "etapa", "co_fase_projeto", "fase_projeto",
    "dt_mudanca_situacao", "justificativa",
    "bairro", "logradouro", "cep", "latitude", "longitude",
    "co_cnes", "nu_cnes", "estabelecimento",
    "vl_proposta", "vl_total_contrato", "vl_percentual_executado",
    "dt_primeira_parcela", "vl_primeira_parcela",
    "dt_segunda_parcela", "vl_segunda_parcela",
    "dt_terceira_parcela", "vl_terceira_parcela",
    "dt_quarta_parcela", "vl_quarta_parcela",
    "repasse_total", "parcelas_pagas", "regime_parcelas",
    "nu_portaria", "dt_portaria", "dt_cadastro",
    "dt_inicio_projeto", "dt_conclusao_projeto", "dt_ordem_servico", "dt_inicio_obra",
    "dt_provavel_execucao", "dt_execucao", "dt_provavel_conclusao_final",
    "dt_conclusao_final", "dt_inicio_funcionamento", "dt_inauguracao",
    "st_aditivo_contratual", "possui_etapa_funcionamento",
    "fotos_grupos", "fotos_total", "fotos_ultima_em",
    "dt_atualizacao_fonte", "pct_mudou_em", "ultima_atividade_em", "raw_data",
]
# Colunas que o UPSERT NAO sobrescreve com EXCLUDED: pct_mudou_em tem regra
# propria (so avanca quando o % muda de verdade), e as de controle sao nossas.
_NAO_SOBRESCREVE = {"proposta_id", "pct_mudou_em"}


def _upsert(cur, obra: dict) -> None:
    cols = [c for c in _COLS if c in obra]
    valores = [json.dumps(obra[c], ensure_ascii=False, default=str)
               if c == "raw_data" else obra[c] for c in cols]
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in _NAO_SOBRESCREVE)
    # `pct_mudou_em` JA vem em `cols` (esta em _COLS) — nao repetir na lista de
    # colunas, senao o Postgres recusa com "specified more than once". Ele fica
    # fora de `sets` (via _NAO_SOBRESCREVE) porque tem regra propria logo abaixo.
    cur.execute(
        f"INSERT INTO sismob_obras ({', '.join(cols)}, visto_em, updated_at) "
        f"VALUES ({', '.join(['%s'] * len(cols))}, NOW(), NOW()) "
        f"ON CONFLICT (proposta_id) DO UPDATE SET {sets}, "
        # Guarda: se a fonte devolver NULL numa rodada ruim, nao perdemos a data
        # que ja tinhamos.
        f"  pct_mudou_em = COALESCE(EXCLUDED.pct_mudou_em, sismob_obras.pct_mudou_em), "
        f"  ausente_desde = NULL, visto_em = NOW(), updated_at = NOW()",
        valores,
    )


def _upsert_empresas(cur, proposta_id, empresas: list[dict]) -> None:
    """Substituicao total: a fonte devolve a lista completa a cada chamada, e
    empresa removida (contrato rescindido) tem que sumir. NUNCA chamar quando o
    detalhe falhou — senao um 500 do MS apaga o contrato."""
    cur.execute("DELETE FROM sismob_obra_empresas WHERE proposta_id = %s", (proposta_id,))
    for e in empresas or []:
        cnpj = _digitos((e or {}).get("cnpj"))
        if not cnpj:
            continue
        cur.execute(
            "INSERT INTO sismob_obra_empresas "
            "  (proposta_id, cnpj, numero_contrato, razao_social, valor_final_licitado) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (proposta_id, cnpj, numero_contrato) DO UPDATE SET "
            "  razao_social = EXCLUDED.razao_social, "
            "  valor_final_licitado = EXCLUDED.valor_final_licitado, "
            "  atualizado_em = NOW()",
            (proposta_id, cnpj, str(e.get("numeroContrato") or "").strip(),
             (e.get("razaoSocial") or "").strip() or None,
             _dec(e.get("valorFinalLicitado"))),
        )


# --------------------------------------------------------------------------
# Coleta
# --------------------------------------------------------------------------
async def _coletar_municipio(client, cur, mun: dict, hoje: date) -> tuple[int, str | None]:
    ibge6 = mun["ibge6"]

    # GUARDA 1 — codigo de 6 digitos ou pula. Mandar o IBGE de 7 devolve
    # HTTP 200 com totalElements: 0, indistinguivel de "nao tem obra".
    if len(ibge6) != 6 or not ibge6.isdigit():
        return 0, f"IBGE de 6 digitos ausente/invalido ({ibge6!r})"

    itens, total = await _listar(client, ibge6)

    # GUARDA 2 — confere que voltou o municipio pedido. Um codigo errado que por
    # acaso exista devolveria as obras de OUTRA cidade com HTTP 200.
    alvo = _norm(mun["nome"])
    fora = [i for i in itens if i.get("municipio") and _norm(i["municipio"]) != alvo]
    if fora:
        return 0, (f"a fonte devolveu {len(fora)} obra(s) de outro municipio "
                   f"(ex.: {fora[0].get('municipio')!r}) — codigo {ibge6} suspeito")

    # GUARDA 3 — zero e erro quando a base ja tinha linhas.
    cur.execute("SELECT count(*) FROM sismob_obras "
                "WHERE municipio_id = %s AND ausente_desde IS NULL", (mun["id"],))
    ja_tinha = cur.fetchone()[0] or 0
    if total == 0 and ja_tinha > 0:
        return 0, f"a fonte devolveu 0 obras mas a base tem {ja_tinha} — nao vou apagar"

    # Estado anterior, para detectar mudanca de percentual.
    cur.execute("SELECT proposta_id, vl_percentual_executado, pct_mudou_em "
                "FROM sismob_obras WHERE municipio_id = %s", (mun["id"],))
    antes = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    sem = asyncio.Semaphore(int(os.getenv("SISMOB_CONCURRENCY", "2")))
    desconhecidos: set[str] = set()

    async def _uma(item: dict) -> dict | None:
        obra: dict = {"municipio_id": mun["id"]}
        _aplicar(obra, item, _DA_LISTAGEM)
        pid = obra.get("proposta_id")
        if not pid:
            return None
        async with sem:
            await asyncio.sleep(0.25)   # host burstable; nao ha pressa
            det = await _detalhe(client, pid)
        if det:
            _aplicar(obra, det, _DO_DETALHE)
            _aplicar(obra, det, _DATAS_DETALHE, datas=True)
            obra.update(_parcelas(det))
            g, t, ultima = _fotos(det)
            obra.update({"fotos_grupos": g, "fotos_total": t, "fotos_ultima_em": ultima})
            obra["nu_cnpj"] = _digitos(obra.get("nu_cnpj"))
            obra["cep"] = _digitos(obra.get("cep"))
            desconhecidos.update(set(det) - _CONHECIDOS_DETALHE)
            obra["_empresas"] = det.get("empresas") or []
            obra["raw_data"] = {**det, "_pactha": {
                "coletado_em": datetime.now(timezone.utc).isoformat(),
                "origem": "detalhe",
                "campos_desconhecidos": sorted(set(det) - _CONHECIDOS_DETALHE),
            }}
        else:
            # Sem detalhe: grava o que a listagem deu e diz de onde veio. Nao
            # inventa parcela nem foto.
            obra["raw_data"] = {**item, "_pactha": {
                "coletado_em": datetime.now(timezone.utc).isoformat(),
                "origem": "listagem",
            }}
        # O detalhe devolve situacao so como codigo; a listagem tem o rotulo.
        obra["situacao"] = rotulo_situacao(obra.get("co_situacao_obra"),
                                           obra.get("situacao"))
        pct_ant, pct_mud = antes.get(obra["proposta_id"], (None, None))
        obra.update(_atividade(obra, obra.get("fotos_ultima_em"), pct_ant, pct_mud, hoje))
        return obra

    obras = [o for o in await asyncio.gather(*[_uma(i) for i in itens]) if o]

    vistos = []
    for obra in obras:
        empresas = obra.pop("_empresas", None)
        _upsert(cur, obra)
        if empresas is not None:      # None = detalhe falhou; nao mexer
            _upsert_empresas(cur, obra["proposta_id"], empresas)
        vistos.append(obra["proposta_id"])

    # Obra que some NUNCA e apagada: so marcada. A listagem ja se comporta de
    # forma imprevisivel com parametro errado, e uma rodada com bug apagaria o
    # historico. Marcada, sai das telas e alertas (todos filtram ausente_desde
    # IS NULL) mas o dado fica — e virar ausente e, em si, um sinal.
    #
    # GUARDA 4 — antes de marcar, checar se `vistos` merece credito.
    #
    # A GUARDA 3 la em cima so cobre `total == 0`, que e o caso extremo. Duas
    # rotas passavam por ela e chegavam aqui marcando obra VIVA como ausente,
    # com a rodada gravada como 'success':
    #
    #   (a) `_uma()` devolve None em silencio quando `proposta_id` vem falsy, e
    #       `_DA_LISTAGEM` le `propostaId` de UMA chave so, sem fallback (o
    #       detalhe tem o par coSeqProposta/propostaId; a listagem nao). Se o MS
    #       renomear esse campo — e o docstring deste arquivo existe justamente
    #       porque essa fonte usa nomes diferentes para o mesmo campo —, TODA
    #       obra sai de `vistos` com total > 0, e o UPDATE marca a carteira
    #       inteira. Vale lembrar que psycopg2 adapta lista vazia para '{}' e
    #       `NOT (proposta_id = ANY('{}'))` e TRUE para todas as linhas.
    #   (b) a listagem so encolher (7 -> 3) ja bastava para as outras 4 sumirem.
    #
    # Obra ausente sai da tela, do BI, da TV e dos alertas de uma vez (todos
    # filtram ausente_desde IS NULL). O dano se auto-cura na coleta seguinte
    # (o ON CONFLICT devolve ausente_desde = NULL), mas a janela e de ate 20h
    # por causa do auto-throttle — um dia inteiro de painel mentindo.
    #
    # Duas condicoes, nenhuma heuristica:
    #   1. item descartado => `vistos` e sabidamente incompleto e nao serve de
    #      referencia. Mata a rota (a) por construcao, sem adivinhar nada.
    #   2. piso proporcional: sumir mais de 1/5 da carteira nao e reconciliacao,
    #      e sintoma. Vira erro da rodada, e o erro ja impede o commit.
    # `SISMOB_ALLOW_SHRINK=1` destrava quando o encolhimento for legitimo —
    # sem a valvula, trocariamos uma falha silenciosa por uma travada.
    # Conta com o MESMO WHERE do UPDATE — nao dá para deduzir de `antes`, que
    # nao filtra ausente_desde e inclui obra ja marcada em rodada anterior.
    descartados = len(itens) - len(obras)
    cur.execute("SELECT count(*) FROM sismob_obras "
                "WHERE municipio_id = %s AND NOT (proposta_id = ANY(%s)) "
                "  AND ausente_desde IS NULL", (mun["id"], vistos))
    sumiriam = cur.fetchone()[0] or 0
    if not os.getenv("SISMOB_ALLOW_SHRINK") and sumiriam > 0:
        if descartados:
            return 0, (f"a fonte devolveu {len(itens)} itens mas {descartados} nao tinham "
                       f"proposta_id — nao vou marcar {sumiriam} obra(s) como ausente(s) "
                       f"com uma listagem incompleta")
        if sumiriam > max(1, ja_tinha // 5):
            return 0, (f"a fonte devolveu {len(vistos)} obra(s) de {ja_tinha} — "
                       f"{sumiriam} sumiriam de uma vez; nao vou marcar como ausentes "
                       f"(use SISMOB_ALLOW_SHRINK=1 se o encolhimento for real)")

    cur.execute("UPDATE sismob_obras SET ausente_desde = COALESCE(ausente_desde, NOW()) "
                "WHERE municipio_id = %s AND NOT (proposta_id = ANY(%s)) "
                "  AND ausente_desde IS NULL", (mun["id"], vistos))
    sumiram = cur.rowcount or 0

    if desconhecidos:
        log.warning("    %s: campos NOVOS no detalhe (contrato pode ter mudado): %s",
                    mun["nome"], ", ".join(sorted(desconhecidos))[:200])
    if sumiram:
        log.info("    %s: %d obra(s) sumiram da fonte e foram marcadas como ausentes",
                 mun["nome"], sumiram)
    return len(obras), None


def _deve_pular() -> str | None:
    """Auto-throttle: o cron hospedeiro (run_dadosabertos, via run_sigcon) roda
    4x/dia, mas a fonte muda a cada ~60 dias por obra. Sem uma Scheduled Task
    propria no Coolify, o intervalo mora aqui."""
    if os.getenv("SISMOB_FORCE"):
        return None
    horas = float(os.getenv("SISMOB_MIN_INTERVAL_H", "20"))
    try:
        conn = _db(); cur = conn.cursor()
        cur.execute("SELECT EXTRACT(EPOCH FROM (NOW() - max(finished_at)))/3600 "
                    "FROM ingestion_log WHERE source = 'sismob' AND status = 'success'")
        idade = cur.fetchone()[0]
        cur.close(); conn.close()
        if idade is not None and float(idade) < horas:
            return f"ultima coleta ha {float(idade):.1f}h (< {horas}h)"
    except Exception:
        pass       # na duvida, coleta
    return None


async def _rodar() -> int:
    import httpx
    conn = _db(); cur = conn.cursor()
    hoje = date.today()
    try:
        muns = _municipios(cur)
        if not muns:
            log.error("Nenhum municipio ativo com IBGE no banco deste ambiente.")
            _log_ingestao("error", 0, "sem municipios")
            return 0
        log.info("SISMOB: %d municipio(s) ativos", len(muns))

        total, falhas = 0, []
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                     headers={"User-Agent": "PACTHA/1.0"}) as client:
            for mun in muns:
                try:
                    n, erro = await _coletar_municipio(client, cur, mun, hoje)
                except Exception as e:
                    conn.rollback()
                    n, erro = 0, f"{type(e).__name__}: {str(e)[:120]}"
                if erro:
                    conn.rollback()
                    falhas.append(f"{mun['nome']}: {erro}")
                    log.warning("  %s: %s", mun["nome"], erro)
                    continue
                conn.commit()
                total += n
                log.info("  %s: %d obra(s)", mun["nome"], n)

        # "Coleta zero e erro, nao sucesso vazio" — licao literal do FNS, que
        # ficou ~20 dias coletando nada em silencio.
        if total == 0:
            _log_ingestao("error", 0, "; ".join(falhas)[:500] or "nenhuma obra coletada")
        elif falhas:
            _log_ingestao("partial", total, "; ".join(falhas)[:500])
        else:
            _log_ingestao("success", total)
        log.info("=== SISMOB: %d obra(s), %d municipio(s) com falha ===", total, len(falhas))
        return total
    finally:
        cur.close(); conn.close()


def ingest() -> int:
    """Entrypoint do agregador de dados abertos (run_dadosabertos_cron)."""
    if os.getenv("SISMOB_ENABLED", "1") == "0":
        log.info("SISMOB: desligado neste tenant (SISMOB_ENABLED=0)")
        return 0
    motivo = _deve_pular()
    if motivo:
        log.info("SISMOB: %s — pulando (use SISMOB_FORCE=1 para forcar)", motivo)
        return 0
    return asyncio.run(_rodar())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest()
