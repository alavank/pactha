"""Coletor do FNS (Fundo Nacional de Saude) — roda no job/cron de coleta do FNS.

A API REST do consultafns.saude.gov.br e PUBLICA: /recursos/... responde 200
sem nenhum cookie. Por isso este coletor NAO depende de sessao capturada.
(Ate 07/2026 ele abortava com "Nenhuma sessao FNS no Cofre" e ficou ~20 dias
coletando zero em silencio — a sessao do bookmarklet expirava e ninguem via.)
Se houver uma sessao valida no Cofre ela e usada como belt-and-suspenders,
mas a ausencia dela NAO impede a coleta.

Escopo: TODOS os municipios ativos do banco DO AMBIENTE (cada tenant tem os
seus) — nada hardcoded. O codigo FNS de 6 digitos vem de municipios.fns_code
quando a Central o configurou; quando fns_code esta vazio ele e derivado de
ibge_code[:6] (o FNS usa o IBGE sem o digito verificador — mesma derivacao que
routers/fns.py usa). A UF vem do proprio municipio.

Grava em convenios_estadual com fonte='FNS'.

Uso:
    DATABASE_URL_SYNC=... python ingestion/run_fns_local.py

Env opcionais:
    FNS_ANO_MIN       ano inicial da varredura (default 2010)
    FNS_CONCURRENCY   municipios em paralelo (default 4)
    FNS_MUNICIPIOS    ids separados por virgula, p/ rodar so alguns
"""
import os
import sys
import json
import asyncio
import hashlib
import logging
from datetime import datetime
import httpx
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import crypto

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fns_local")
# httpx loga 1 linha por request (~6k por rodada) e afoga o log do cron.
logging.getLogger("httpx").setLevel(logging.WARNING)

BASE = "https://consultafns.saude.gov.br"

ANO_MIN = int(os.getenv("FNS_ANO_MIN", "2010"))
ANOS = list(range(ANO_MIN, datetime.now().year + 1))
CONC = max(1, int(os.getenv("FNS_CONCURRENCY", "4")))


def _db():
    url = (os.getenv("DATABASE_URL_SYNC", "")
           .replace("&channel_binding=require", "")
           .replace("?channel_binding=require", ""))
    return psycopg2.connect(url)


# Prefixo do IBGE -> UF. Usado quando municipios.uf esta vazio: mandar a UF
# errada NAO da erro, o portal responde 200 com lista VAZIA — falha silenciosa.
_UF_POR_IBGE = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}

# fns_code (gerido pela Central, add_fns_code.sql) tem prioridade; se estiver
# vazio cai na derivacao ibge_code[:6]. Antes o coletor SO rodava os municipios
# com fns_code preenchido (ou um mapa hardcoded de 6 ids de MG) — quem nunca
# passou pela Central simplesmente nao era coletado.
_SQL_MUNICIPIOS = (
    "SELECT id, nome, COALESCE(NULLIF(fns_code, ''), left(ibge_code, 6)), "
    "       COALESCE(NULLIF(upper(uf), ''), '') "
    "FROM municipios "
    "WHERE active = true "
    "  AND (COALESCE(NULLIF(fns_code, ''), '') <> '' "
    "       OR (ibge_code IS NOT NULL AND length(ibge_code) >= 6)) "
    "ORDER BY id"
)

# Fallback p/ banco onde add_fns_code.sql ainda nao rodou (coluna inexistente).
_SQL_MUNICIPIOS_SEM_FNS_CODE = (
    "SELECT id, nome, left(ibge_code, 6), COALESCE(NULLIF(upper(uf), ''), '') "
    "FROM municipios WHERE active = true AND ibge_code IS NOT NULL "
    "AND length(ibge_code) >= 6 ORDER BY id"
)


def _municipios() -> list[tuple[int, str, str, str]]:
    """(id, nome, codigo FNS 6 digitos, uf) de todos os municipios do ambiente.

    Validado: o codigo de 6 digitos casa 1:1 com /recursos/municipios/uf/{uf}.
    Os ambientes tem municipios de UFs diferentes (MG, ES, GO, TO), entao a UF
    vem do proprio municipio — nunca fixa."""
    only = {int(x) for x in os.getenv("FNS_MUNICIPIOS", "").replace(" ", "").split(",") if x.isdigit()}
    conn = _db(); cur = conn.cursor()
    try:
        try:
            cur.execute(_SQL_MUNICIPIOS)
            rows = cur.fetchall()
        except Exception as e:
            log.warning(f"municipios.fns_code indisponivel ({str(e)[:80]}) — derivando de ibge_code")
            conn.rollback()
            cur.execute(_SQL_MUNICIPIOS_SEM_FNS_CODE)
            rows = cur.fetchall()
    finally:
        cur.close(); conn.close()
    out = []
    for mid, nome, cod, uf in rows:
        if only and mid not in only:
            continue
        cod = (cod or "").strip()
        if len(cod) < 6:
            log.warning(f"  {nome} (id={mid}): sem fns_code/ibge_code utilizavel — pulado")
            continue
        uf = uf or _UF_POR_IBGE.get(cod[:2], "")
        if not uf:
            log.warning(f"  {nome} (id={mid}): sem UF e IBGE '{cod}' desconhecido — pulado")
            continue
        out.append((mid, nome, cod, uf))
    return out


def _cookies() -> dict:
    """Sessao FNS do Cofre — OPCIONAL. Qualquer falha => {} (API e publica)."""
    try:
        conn = _db(); cur = conn.cursor()
        cur.execute(
            "SELECT senha_hash FROM cofre_senhas "
            "WHERE automation_key = 'fns' OR sistema = 'Sessao FNS' "
            "ORDER BY updated_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row:
            return {}
        dec = crypto.decrypt(row[0]) or ""
        if not dec.startswith("{"):
            return {}
        return {c["name"]: c["value"] for c in json.loads(dec).get("cookies", []) if c.get("name")}
    except Exception as e:
        log.info(f"sessao FNS indisponivel ({str(e)[:60]}) — seguindo em modo publico")
        return {}


def _upsert_items(items: list[dict]) -> int:
    if not items:
        return 0
    conn = _db(); cur = conn.cursor()
    sql = """
        INSERT INTO convenios_estadual
            (municipio_id, nr_sigcon, objeto, situacao, valor_total,
             valor_concedente, valor_repassado, ano, fonte, orgao_concedente,
             nr_proposta, tipo_programa, raw_data, created_at, updated_at)
        VALUES (%(municipio_id)s, %(nr_proposta)s, %(objeto)s, %(situacao)s,
                %(valor)s, %(valor)s, %(valor_repassado)s,
                %(ano)s, %(fonte)s, %(orgao_concedente)s,
                %(nr_proposta)s, %(tipo_programa)s, %(raw_data)s::jsonb,
                NOW(), NOW())
        ON CONFLICT (nr_sigcon) DO UPDATE SET
            situacao = EXCLUDED.situacao,
            valor_total = COALESCE(EXCLUDED.valor_total, convenios_estadual.valor_total),
            valor_concedente = COALESCE(EXCLUDED.valor_concedente, convenios_estadual.valor_concedente),
            valor_repassado = COALESCE(EXCLUDED.valor_repassado, convenios_estadual.valor_repassado),
            objeto = COALESCE(EXCLUDED.objeto, convenios_estadual.objeto),
            raw_data = EXCLUDED.raw_data,
            updated_at = NOW()
    """
    n = 0
    for it in items:
        try:
            cur.execute(sql, {**it, "raw_data": json.dumps(it.get("raw_data", {}), ensure_ascii=False)})
            n += 1
        except Exception as e:
            log.warning(f"upsert falhou {it.get('nr_proposta')}: {str(e)[:100]}")
            conn.rollback()
            continue
    conn.commit(); cur.close(); conn.close()
    return n


def chave_fns(cod_fns: str, ano: int, tipo: str, recurso: str, nu_proc: str) -> str:
    """Chave ESTAVEL do agregado FNS (grupo ano/tipo/recurso/processo).

    PEGADINHA HISTORICA: o hash era do payload INTEIRO — bastava o vlPago mudar
    (250k -> 450k) pra chave mudar e o ON CONFLICT nao casar, criando uma linha
    duplicada a cada repasse. Agora o hash e so da IDENTIDADE do grupo, entao a
    mesma proposta cai sempre na mesma linha. O hash continua necessario porque
    o prefixo legivel trunca tipo/recurso ('INCREMENTO PAP' e 'INCREMENTO MAC'
    colapsam nos mesmos 8 primeiros caracteres)."""
    ident = f"{cod_fns}|{ano}|{tipo}|{recurso}|{nu_proc}"
    h = hashlib.md5(ident.encode("utf-8")).hexdigest()[:8]
    return f"FNS-{cod_fns}-{ano}-{tipo[:8]}-{recurso[:6]}-{nu_proc[:8]}-{h}".replace(" ", "_")[:60]


def _normalize(p: dict, ano: int, mun_id: int, cod_fns: str) -> dict:
    tipo = (p.get("coTipoProposta") or "PROPOSTA").strip()
    recurso = (p.get("dsTipoRecurso") or "").strip()
    vl_prop = float(p.get("vlProposta") or 0)
    vl_pago = float(p.get("vlPago") or 0)
    vl_pagar = float(p.get("vlPagar") or 0)
    sit = ("Pago" if vl_pago > 0 and vl_pagar == 0
           else "Empenhado" if vl_pagar > 0
           else "Em analise" if vl_prop > 0
           else "Pendente")
    nu_proc = p.get("nuProcesso") or "NA"
    return {
        "municipio_id": mun_id,
        "nr_proposta": chave_fns(cod_fns, ano, tipo, recurso, nu_proc),
        "objeto": (f"{tipo} - {recurso}".strip(" -") + (f" — Proc {nu_proc}" if nu_proc not in ("NA", "N/A") else ""))[:500],
        "tipo_programa": tipo[:100],
        # ⚠️ `vl_prop` PRIMEIRO. Era `vl_pago or vl_prop`, e o `or` do Python
        # devolve o pago sempre que ele nao e zero — entao `valor_total` (e
        # `valor_concedente`, que recebe o mesmo parametro) significava "valor da
        # PROPOSTA" nas linhas pagas por inteiro e "valor PAGO" nas pagas pela
        # metade, sem nada na linha dizendo qual dos dois era.
        #
        # No pagamento integral os dois numeros sao iguais e o defeito e
        # invisivel — 28 das 43 linhas de Araujos. Medido nas 2 parciais:
        #   FNS-310390-2019-INCREMEN  proposta 500.000,00  pago 400.000,00
        #   FNS-310390-2026-CUSTEIO_  proposta 800.000,00  pago 200.000,00
        # A tela mostrava 400.000 e 200.000 como valor total: R$ 700.000,00 de
        # valor proposto sumindo, com as duas linhas rotuladas "Empenhado".
        #
        # A raiz era falta de lugar para o pago: `valor_repassado` estava NULO em
        # 43 de 43 linhas FNS (so o backfill do CKAN escrevia nela, e ele nao
        # trata FNS). Sem coluna para o pago, o pago ocupava a do proposto.
        "valor": vl_prop or vl_pago or None,
        # O pago ganha coluna propria. `or None` e nao `or 0`: zero aqui seria a
        # afirmacao "nada foi pago", e o FNS omite `vlPago` tambem quando so nao
        # informa — a mesma disciplina do resto do repo para medido x ausente.
        "valor_repassado": vl_pago or None,
        "situacao": sit,
        "ano": ano,
        "fonte": "FNS",
        "orgao_concedente": "MS - FNS",
        "raw_data": p,
    }


def _ano_ms(epoch_ms) -> int | None:
    """epoch em ms (formato do FNS) -> ano."""
    try:
        return datetime.fromtimestamp(int(epoch_ms) / 1000).year
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _data_br_ms(epoch_ms) -> str | None:
    """epoch em ms -> 'dd/mm/aaaa'. Usado p/ o obter-proposta, que devolve a data
    do pagamento em ms (o detalhe-pagamento ja devolve a string pronta)."""
    try:
        return datetime.fromtimestamp(int(epoch_ms) / 1000).strftime("%d/%m/%Y")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _ord_data_br(s) -> tuple:
    """'dd/mm/aaaa' -> (aaaa, mm, dd) p/ ordenar pagamentos; ausencia vai pro fim
    (conta como o mais antigo)."""
    try:
        d, m, y = str(s or "").split("/")
        return (int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return (0, 0, 0)


async def _get_json_retry(client: httpx.AsyncClient, url: str, params: dict,
                          timeout: float = 25, tentativas: int = 3):
    """GET que tolera o 500 TRANSITORIO do FNS. O portal responde, ~1 vez em 3,
    HTTP 500 'could not extract ResultSet' (Hibernate) e acerta na tentativa
    seguinte — medido a mao no obter-proposta desta mesma proposta (500,200,200).
    Uma tentativa unica descartava em silencio a situacao e a data de ~1/3 das
    propostas. Retorna o dict `resultado` (ou {}), ou None se esgotar/for 4xx
    definitivo. Nunca levanta."""
    for i in range(tentativas):
        try:
            r = await client.get(url, params=params, timeout=timeout)
        except Exception:
            await asyncio.sleep(0.4 * (i + 1))
            continue
        if r.status_code == 200 and "json" in r.headers.get("content-type", "").lower():
            try:
                return r.json().get("resultado", {}) or {}
            except Exception:
                return {}
        # 4xx (fora 429) e definitivo: proposta inexistente/param invalido nao
        # melhora ao repetir. So 5xx/429 e a janela ruim do portal, que readianta.
        if r.status_code < 500 and r.status_code != 429:
            return None
        await asyncio.sleep(0.4 * (i + 1))
    return None


# O detalhe-pagamento do portal EXIGE estes parametros presentes, mesmo vazios:
# faltando qualquer um, responde HTTP 400 (nao 404). Descobertos lendo as chamadas
# da propria tela /#/detalhada (app/pages/detalhada/services/detalhadaService.js,
# metodo recuperarPagamentos -> 'consulta-detalhada/detalhe-pagamento'). Mesma
# licao do fns_faf.py: quando a API nao responde, abra a tela e leia o que ela chama.
_DETALHE_PGTO_VAZIOS = {
    "mes": "", "tipoConsulta": "", "blocos": "", "grupo": "", "componentes": "",
    "acoes": "", "repasse": "", "dataInicialOb": "", "dataFinalOb": "",
    "nuAcaoJudicial": "", "cpfCnpjUg": "", "processo": "", "portaria": "",
}


async def _detalhe_pagamento(client: httpx.AsyncClient, uf: str, cod_fns: str,
                             nuprop: str, anos: list[int]) -> list[dict]:
    """DATA do pagamento + DOMICILIO BANCARIO (banco/agencia/CONTA) de cada
    pagamento de UMA proposta, do endpoint publico
    /recursos/consulta-detalhada/detalhe-pagamento.

    ⚠️ Por que este endpoint, e nao o obter-proposta. O obter-proposta traz os
    pagamentos com a data (dtCriacaoSiafi) e a Ordem Bancaria (nuOb), mas NAO o
    numero da conta — varri o payload inteiro e nao ha banco/agencia/conta em
    lugar nenhum. A conta so aparece nesta tela detalhada (o `contaCorrente`,
    ao lado de `codigoBanco`/`codigoAgencia`), a mesma que o gestor abre no olho
    da consulta detalhada.

    ⚠️ O parametro `ano` e o ano do PAGAMENTO (id.ano), nao o da proposta: uma
    proposta de 2019 paga em 2019 responde com ano=2019 e vazio com 2020/2021.
    Por isso recebe os anos ja descobertos no obter-proposta (anos_pg) — assim
    uma proposta paga num ano posterior ao de cadastro nao se perde.

    Falha (400/500/rede/JSON) => [] silencioso: a data ja ficou em
    `data_pagamento` (via obter-proposta) e conta ausente e "nao coletada", nao
    a afirmacao "sem conta" — a mesma disciplina de medido x ausente do repo."""
    rows: list[dict] = []
    for ano_pg in anos:
        res = await _get_json_retry(
            client, f"{BASE}/recursos/consulta-detalhada/detalhe-pagamento",
            {"ano": ano_pg, "estado": uf, "municipio": cod_fns,
             "proposta": nuprop, "page": 1, "count": 50, **_DETALHE_PGTO_VAZIOS},
        )
        for d in ((res or {}).get("dados", []) or []):
            try:
                rows.append({
                    "data": (d.get("dataCriacaoSiafi") or "").strip() or None,  # dd/mm/aaaa
                    "conta": (d.get("contaCorrente") or "").strip() or None,
                    "banco": (d.get("codigoBanco") or "").strip() or None,
                    "agencia": (d.get("codigoAgencia") or "").strip() or None,
                    "ob": (d.get("numeroDocumentoSiafi") or "").strip() or None,
                    "valor": float(d.get("valorLiquido") or 0),
                    "competencia": (d.get("competencia") or "").strip() or None,
                })
            except (TypeError, ValueError, AttributeError):
                continue
    rows.sort(key=lambda x: _ord_data_br(x.get("data")))
    return rows


async def _fetch_individuais(client: httpx.AsyncClient, cod_fns: str, ano: int, uf: str,
                             tipo: str, recurso: str) -> list[dict]:
    """Propostas INDIVIDUAIS (Nº SIPA) de um grupo tipo/recurso. O portal usa
    tpProposta/tpRecurso (em vez de co.../ds...) p/ destravar o agrupamento e
    retornar 1 item por proposta, cada um com nuProposta."""
    if not tipo:
        return []
    try:
        r = await client.get(
            f"{BASE}/recursos/proposta/consultar",
            params={"ano": ano, "coEsfera": "", "coMunicipioIbge": cod_fns,
                    "count": 200, "page": 1, "sgUf": uf,
                    "tpProposta": tipo, "tpRecurso": recurso},
            timeout=30,
        )
        if r.status_code != 200:
            return []
        its = r.json().get("resultado", {}).get("itensPagina", []) or []
        out = []
        for it in its:
            nup = it.get("nuProposta")
            if not nup:
                continue
            # A situacao REAL do portal e as DATAS de pagamento nao vem na
            # listagem — so no detalhe (obter-proposta). 1 chamada por proposta.
            # O ano do ultimo pagamento e o que diz se uma proposta antiga ainda
            # se moveu no ano de referencia (usado pela regra de ano do RM).
            sit_desc = dt_sit = ano_pgto = None
            anos_pg: list[int] = []
            dt_pgto = None
            parls_det = []
            try:
                dd = await _get_json_retry(
                    client, f"{BASE}/recursos/proposta/obter-proposta",
                    {"nuProposta": nup}, timeout=20,
                )
                if dd:
                    sit_desc = (dd.get("situacao") or {}).get("descricaoSituacaoproposta")
                    dt_sit = _ano_ms((dd.get("situacao") or {}).get("dataSituacaoProjeto"))
                    mss = [pg.get("dtCriacaoSiafi") for pg in (dd.get("pagamentos") or [])]
                    anos_pg = [a for a in (_ano_ms(m) for m in mss) if a]
                    ano_pgto = max(anos_pg) if anos_pg else None
                    # DATA (dia) do ultimo pagamento, direto do ms do obter-proposta.
                    # Fica salva mesmo que o detalhe-pagamento (que traz a CONTA)
                    # falhe — a data nunca depende da segunda chamada.
                    ms_ok = [int(m) for m in mss if isinstance(m, (int, float))
                             or (isinstance(m, str) and m.strip().isdigit())]
                    dt_pgto = _data_br_ms(max(ms_ok)) if ms_ok else None
                    # PARLAMENTAR: a LISTAGEM sempre devolve parlamentares=[] — por
                    # isso o RM/tela caiam no rotulo do tipo de recurso e mostravam
                    # "EMENDA INDIVIDUAL" onde deveria estar o NOME de quem indicou.
                    # O detalhe (obter-proposta) traz os parlamentares de verdade, e
                    # esta chamada JA e feita aqui (custo de rede: zero a mais).
                    parls_det = (dd.get("parlamentares")
                                 or dd.get("emendas")
                                 or (dd.get("proposta") or {}).get("parlamentares")
                                 or [])
            except Exception:
                pass
            # CONTA + banco/agencia + DATA do pagamento, do detalhe-pagamento
            # (o obter-proposta nao traz a conta). So quando ha pagamento:
            #  - anos_pg: os anos de pagamento que o obter-proposta revelou (cobre
            #    pagamento em ano posterior ao da proposta);
            #  - `ano` do grupo (= ano da proposta) quando vlPago>0: FALLBACK para
            #    quando o obter-proposta falhou (500 transitorio) mas a listagem ja
            #    diz que houve repasse. Cobre o caso comum (pago no proprio ano) sem
            #    depender da 2a chamada — e por ele a proposta paga do print entra
            #    mesmo com o obter-proposta fora do ar. Set => sem chamada repetida.
            vl_pago_it = float(it.get("vlPago") or 0)
            anos_conta = set(anos_pg)
            if vl_pago_it > 0:
                anos_conta.add(ano)
            pagamentos_det = []
            if anos_conta:
                pagamentos_det = await _detalhe_pagamento(
                    client, uf, cod_fns, str(nup), sorted(anos_conta))
            ult = pagamentos_det[-1] if pagamentos_det else {}
            out.append({
                "nuProposta": nup,
                "entidade": it.get("noEntidade") or "FUNDO MUNICIPAL DE SAUDE",
                "nuProcesso": it.get("nuProcesso"),
                "vlProposta": float(it.get("vlProposta") or 0),
                "vlPago": float(it.get("vlPago") or 0),
                "vlPagar": float(it.get("vlPagar") or 0),
                # detalhe primeiro (a listagem vem sempre vazia — ver acima)
                "parlamentares": parls_det or (it.get("parlamentares") or []),
                "situacao_desc": sit_desc,
                "ano_ultimo_pagamento": ano_pgto,
                "ano_situacao": dt_sit,
                # ── Pagamento (data + CONTA), o que o RM da Saude precisa nas pagas ──
                # `data_pagamento`: dia do ultimo pagamento (dd/mm/aaaa). Prefere a
                # data do detalhe-pagamento; cai na do obter-proposta se o detalhe
                # falhar (a data nunca se perde). `conta_corrente`/codigo_banco/
                # codigo_agencia: domicilio bancario do ultimo pagamento. `pagamentos`:
                # lista completa (uma proposta pode ter varias parcelas/contas).
                "data_pagamento": (ult.get("data") if ult else None) or dt_pgto,
                "conta_corrente": ult.get("conta"),
                "codigo_banco": ult.get("banco"),
                "codigo_agencia": ult.get("agencia"),
                "pagamentos": pagamentos_det,
            })
        return out
    except Exception as ex:
        log.warning(f"  individuais {tipo}/{recurso} {ano}: {str(ex)[:80]}")
        return []


async def collect_for_municipio(client: httpx.AsyncClient, mun_id: int, cod_fns: str,
                                nome: str, uf: str) -> list[dict]:
    items: list[dict] = []
    for ano in ANOS:
        pagina = 1
        while pagina < 30:
            try:
                r = await client.get(
                    f"{BASE}/recursos/proposta/consultar",
                    params={
                        "ano": ano,
                        "coEsfera": "",
                        "coMunicipioIbge": cod_fns,
                        "sgUf": uf,
                        "count": 200,
                        "page": pagina,
                    },
                    timeout=30,
                )
                if r.status_code != 200:
                    log.warning(f"  {nome} ano={ano} pag={pagina}: HTTP {r.status_code}")
                    break
                j = r.json().get("resultado", {})
                propostas = j.get("itensPagina", []) or []
                if not propostas:
                    break
                for p in propostas:
                    # Enriquece o agregado com as propostas INDIVIDUAIS (Nº SIPA)
                    # p/ o RM mostrar o numero real de cada proposta.
                    p["linhaPropostas"] = await _fetch_individuais(
                        client, cod_fns, ano, uf,
                        (p.get("coTipoProposta") or "").strip(),
                        (p.get("dsTipoRecurso") or "").strip(),
                    )
                    items.append(_normalize(p, ano, mun_id, cod_fns))
                if len(propostas) < 200:
                    break
                pagina += 1
            except Exception as e:
                log.error(f"  {nome} ano={ano} pag={pagina}: {str(e)[:100]}")
                break
        await asyncio.sleep(0.2)  # gentil com o portal
    return items


def _log_ingestao(status: str, n: int, erro: str = "") -> None:
    try:
        conn = _db(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, error_message, finished_at) "
            "VALUES ('fns', %s, %s, %s, NOW())",
            (status, n, (erro or None)),
        )
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.warning(f"ingestion_log falhou: {str(e)[:120]}")


async def main() -> int:
    muns = _municipios()
    if not muns:
        log.error("Nenhum municipio ativo com fns_code/ibge_code no banco deste ambiente.")
        _log_ingestao("error", 0, "sem municipios")
        return 1

    cookies = _cookies()
    log.info(f"{len(muns)} municipios | anos {ANOS[0]}-{ANOS[-1]} | concorrencia {CONC} "
             f"| sessao FNS: {'sim' if cookies else 'nao (API publica)'}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/131",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://consultafns.saude.gov.br/",
    }
    total = 0
    falhas: list[str] = []
    sem = asyncio.Semaphore(CONC)

    async with httpx.AsyncClient(cookies=cookies, headers=headers, verify=False,
                                 limits=httpx.Limits(max_connections=CONC * 2)) as client:
        async def um(mun_id: int, nome: str, cod_fns: str, uf: str):
            async with sem:
                try:
                    items = await collect_for_municipio(client, mun_id, cod_fns, nome, uf)
                    # Persiste por municipio (nao all-or-nothing): se um falhar no
                    # meio, o que ja foi coletado fica no banco.
                    n = _upsert_items(items)
                    log.info(f"  {nome} (mun={mun_id} fns={cod_fns}/{uf}): {len(items)} coletadas, {n} gravadas")
                    return n
                except Exception as e:
                    log.error(f"  {nome}: FALHOU {str(e)[:120]}")
                    falhas.append(nome)
                    return 0

        res = await asyncio.gather(*[um(i, n, c, u) for i, n, c, u in muns])
        total = sum(res)

    ok = len(muns) - len(falhas)
    log.info(f"=== TOTAL: {total} propostas FNS gravadas em {ok}/{len(muns)} municipios ===")
    if falhas:
        log.warning(f"falharam: {', '.join(falhas[:20])}")

    if total == 0:
        _log_ingestao("error", 0, "coleta retornou zero propostas")
        log.error("Coleta retornou ZERO — falha real, nao sucesso vazio.")
        return 1
    _log_ingestao("partial" if falhas else "success", total,
                  f"falhas: {', '.join(falhas[:10])}" if falhas else "")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
