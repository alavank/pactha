"""Proxy autenticado pra busca em tempo real no consultafns.saude.gov.br.

API descoberta via inspect:
- GET /recursos/proposta/consultar?ano=YYYY&coEsfera=&coMunicipioIbge=XXXXXX&sgUf=MG&count=20&page=1
- GET /recursos/anos
- GET /recursos/ufs
- GET /recursos/municipios/uf/{uf}

Autenticacao via cookies de sessao captura via bookmarklet (cofre_senhas
sistema='Sessao FNS').
"""
import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from services.auth import get_current_user, ensure_tela
from models.user import User
from services.crypto import decrypt
# Trava de permissao em MODO AVISO — usada so em `/municipios`, onde o gate de
# uma LISTAGEM e o filtro e nao o 403. Ver o comentario la.
from services import authz
from services.registro_rotas import exige

router = APIRouter(prefix="/api/fns", tags=["fns"])
logger = logging.getLogger("fns")

# Teto de linhas de aviso por chamada de `/municipios`. Cada linha da trilha e
# uma tarefa de fundo com SESSAO PROPRIA (services/authz.py): num tenant de
# assessoria com dezenas de municipios, uma unica abertura da tela abriria
# dezenas de conexoes de uma vez so para dizer a mesma coisa. Cinco exemplos ja
# respondem "esta pessoa esta vendo municipio que nao e dela" — a lista completa
# esta no cadastro do usuario, nao na trilha.
_TETO_AVISO_MUNICIPIOS = 5

FNS_BASE = "https://consultafns.saude.gov.br"


def _parlamentares(payload: dict) -> list[dict]:
    """Os parlamentares de uma proposta, com os nomes que a TELA usa.

    O FNS entrega `noApelidoPolitico`, `sgPartido`, `coEmendaPolitica`,
    `nuAnoExercicio` e `vlIndObjeto`. A tela lê `nome`, `partido`, `nu_emenda`,
    `ano` e `valor`. Enquanto isto viveu solto dentro do endpoint de detalhe, a
    lista repassou o payload cru e mostrou os parlamentares com o nome vazio —
    o pior tipo de defeito, porque parece dado faltando na fonte.

    Aceita as duas grafias de propósito: se um dia o portal padronizar, ou se um
    payload vier de cache antigo já normalizado, nada quebra.
    """
    saida = []
    for p in (payload.get("parlamentares") or []):
        if not isinstance(p, dict):
            continue
        saida.append({
            "nome": p.get("noApelidoPolitico") or p.get("nome"),
            "partido": p.get("sgPartido") or p.get("partido") or "",
            "nu_emenda": p.get("coEmendaPolitica") or p.get("nu_emenda"),
            "ano": p.get("nuAnoExercicio") or p.get("ano"),
            "valor": float(p.get("vlIndObjeto") or p.get("valor") or 0),
        })
    return saida


def _ano_ms(epoch_ms) -> int | None:
    """epoch em ms (formato do FNS) -> ano."""
    try:
        return datetime.fromtimestamp(int(epoch_ms) / 1000).year
    except (TypeError, ValueError, OSError, OverflowError):
        return None


# O detalhe-pagamento EXIGE estes parametros presentes, mesmo vazios (faltando
# qualquer um => HTTP 400). Ver ingestion/run_fns_local.py, mesma descoberta.
_DETALHE_PGTO_VAZIOS = {
    "mes": "", "tipoConsulta": "", "blocos": "", "grupo": "", "componentes": "",
    "acoes": "", "repasse": "", "dataInicialOb": "", "dataFinalOb": "",
    "nuAcaoJudicial": "", "cpfCnpjUg": "", "processo": "", "portaria": "",
}


def _contas_por_pagamento(cookies: dict, uf: str, cod_ibge: str,
                          nu_proposta: str, anos: list[int]) -> dict:
    """{numeroDocumentoSiafi (a OB): {conta, banco, agencia}} de uma proposta.

    O `obter-proposta` traz a data e a OB de cada pagamento mas NAO a conta; o
    numero da conta (contaCorrente) so vem do `detalhe-pagamento` da Consulta
    Detalhada, ao lado de codigoBanco/codigoAgencia. Chaveia pela OB para casar
    com o `nuOb` do obter-proposta na hora de montar cada parcela. Sincrono de
    proposito (roda via asyncio.to_thread, como consultar_fns). Falha => {}."""
    out: dict = {}
    with httpx.Client(cookies=cookies, timeout=20, verify=False) as cli:
        for ano_pg in anos:
            try:
                r = cli.get(
                    f"{FNS_BASE}/recursos/consulta-detalhada/detalhe-pagamento",
                    params={"ano": ano_pg, "estado": uf, "municipio": cod_ibge,
                            "proposta": nu_proposta, "page": 1, "count": 50,
                            **_DETALHE_PGTO_VAZIOS},
                    headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0",
                             "Referer": f"{FNS_BASE}/"},
                )
                if r.status_code != 200 or "json" not in r.headers.get("content-type", "").lower():
                    continue
                for d in ((r.json().get("resultado", {}) or {}).get("dados", []) or []):
                    ob = (d.get("numeroDocumentoSiafi") or "").strip()
                    if not ob:
                        continue
                    out[ob] = {
                        "conta": (d.get("contaCorrente") or "").strip() or None,
                        "banco": (d.get("codigoBanco") or "").strip() or None,
                        "agencia": (d.get("codigoAgencia") or "").strip() or None,
                    }
            except Exception:
                continue
    return out


# Codigos IBGE FNS dos municipios PACTHA (6 digitos, sem digito verificador)
FNS_CODE_OVERRIDE = {
    "ARAUJOS": "310390",
    "NOVA SERRANA": "314520",
    "BOM DESPACHO": "310740",
    "SAO TIAGO": "316500",
    "TOLEDO": "316910",
    "PIRACEMA": "315060",
}


async def _ensure_fns_municipio(current, municipio: str, db: AsyncSession) -> None:
    """Non-admin so consulta FNS de municipio no seu escopo (casa por nome ou IBGE)."""
    ensure_tela(current, "fns")
    allowed = getattr(current, "allowed_municipio_ids", None)
    if allowed is None:  # admin -> todos
        return
    if not allowed:
        raise HTTPException(403, "Você não tem municípios atribuídos")
    rows = await db.execute(
        text("SELECT nome, ibge_code FROM municipios WHERE id = ANY(:ids)"),
        {"ids": list(allowed)},
    )
    alvo = (municipio or "").strip().upper()
    for nome, ibge in rows.fetchall():
        n = (nome or "").strip().upper()
        ib = (ibge or "").strip()
        if alvo in (n, ib, ib[:6]) or FNS_CODE_OVERRIDE.get(n) == alvo:
            return
    raise HTTPException(403, "Voce nao tem acesso a este municipio")


async def _resolver_uf(db: AsyncSession, municipio: str, uf_pedida: str | None) -> str:
    """A UF vem do CADASTRO do municipio, nao de um default.

    O default era `Query("MG")`: consulta sem uf explicita caia em Minas e
    devolvia vazio EM SILENCIO para municipio de outro estado. O cadastro e a
    fonte da verdade e GANHA do parametro; o parametro so vale para municipio
    fora do cadastro (admin consultando cidade que o tenant nao atende)."""
    alvo = (municipio or "").strip().upper()
    ufs = sorted({u for u in (await db.execute(text(
        "SELECT upper(coalesce(uf, '')) FROM municipios WHERE active = true "
        "AND (upper(nome) = :alvo OR ibge_code = :alvo OR left(ibge_code, 6) = :alvo)"
    ), {"alvo": alvo})).scalars().all() if u})
    pedida = (uf_pedida or "").strip().upper()[:2]
    if len(ufs) == 1:
        return ufs[0]
    if ufs:
        # HOMONIMO dentro do mesmo tenant (ex.: "Bom Jesus" existe em varios
        # estados). Um LIMIT 1 escolheria em silencio — aqui o parametro
        # desempata, e sem ele o erro aponta as opcoes.
        if pedida in ufs:
            return pedida
        raise HTTPException(400, f"municipio ambíguo entre {', '.join(ufs)} — informe ?uf=XX")
    if pedida:
        return pedida
    raise HTTPException(400, "uf obrigatoria: municipio fora do cadastro — informe ?uf=XX")


async def _get_cookies(db: AsyncSession) -> dict:
    """Cookies da sessao FNS — OPCIONAIS. A API do ConsultaFNS
    (consultafns.saude.gov.br/recursos/...) e PUBLICA: funciona sem login.
    Se houver uma sessao valida no cofre, usa (belt-and-suspenders); senao {}."""
    try:
        r = await db.execute(text("SELECT senha_hash FROM cofre_senhas WHERE sistema = 'Sessao FNS' LIMIT 1"))
        row = r.first()
        if not row:
            return {}
        data = json.loads(decrypt(row[0]) or "{}")
        cookies = data.get("cookies", [])
        return {c["name"]: c["value"] for c in cookies if "name" in c}
    except Exception:
        return {}


async def _resolve_cod(municipio: str, uf: str, db: AsyncSession) -> Optional[str]:
    """Nome do municipio -> codigo IBGE 6 digitos (FNS). Usa a tabela `municipios`
    do AMBIENTE (ibge_code sem o digito verificador). Fallbacks: override legado
    e a API de municipios do FNS. Funciona em qualquer ambiente/instalacao."""
    m = (municipio or "").strip()
    if m.isdigit():
        return m
    # A UF entra no WHERE: homonimo em outro estado do MESMO tenant faria o
    # coMunicipioIbge sair de uma cidade e o sgUf de outra.
    row = (await db.execute(
        text("SELECT ibge_code FROM municipios WHERE upper(nome) = upper(:m) "
             "AND (:uf = '' OR upper(coalesce(uf, '')) = :uf) LIMIT 1"),
        {"m": m, "uf": (uf or "").strip().upper()[:2]})).first()
    if row and row[0]:
        return str(row[0])[:6]
    cod = FNS_CODE_OVERRIDE.get(m.upper())
    if cod:
        return cod
    try:
        cookies = await _get_cookies(db)
        with httpx.Client(cookies=cookies, timeout=15, verify=False) as cli:
            r = cli.get(f"{FNS_BASE}/recursos/municipios/uf/{uf}",
                        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
            for mm in r.json().get("resultado", []):
                if (mm.get("noMunicipio", "") or "").upper().strip() == m.upper():
                    return mm.get("coMunicipioIbge")
    except Exception:
        pass
    return None


@router.get("/buscar", dependencies=[exige("fns.ver")])
async def buscar(
    municipio: str = Query(..., description="Nome do municipio (ex: ARAUJOS) ou codigo IBGE 6 digitos"),
    ano: int = Query(...),
    uf: str | None = Query(None),
    nr_proposta: Optional[str] = Query(None),
    tipo_emenda: Optional[str] = Query(None, description="TODOS, INDIVIDUAL, BANCADA, COMISSAO, BANCADA OBRIGATORIA"),
    pagina: int = Query(1, ge=1),
    tamanho: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Busca propostas FAF no FNS em tempo real."""
    await _ensure_fns_municipio(current, municipio, db)
    uf = await _resolver_uf(db, municipio, uf)
    return await consultar_fns(db, municipio, ano, uf, nr_proposta, tipo_emenda, pagina, tamanho)


async def consultar_fns(
    db: AsyncSession,
    municipio: str,
    ano: int,
    uf: str,
    nr_proposta: Optional[str] = None,
    tipo_emenda: Optional[str] = None,
    pagina: int = 1,
    tamanho: int = 50,
) -> dict:
    """Nucleo da consulta FNS, SEM gate de auth. Reusado pelo endpoint /api/fns/buscar
    (apos _ensure_fns_municipio) e pelo Painel de Indicadores (gated por escopo em
    /api/bi/fns), que consulta VARIOS anos de uma vez."""
    # Resolve codigo IBGE FNS (tabela municipios do ambiente + fallbacks)
    cod = await _resolve_cod(municipio, uf, db)
    if not cod:
        raise HTTPException(404, f"Município '{municipio}' não mapeado")

    cookies = await _get_cookies(db)
    params = {
        "ano": str(ano),
        "coEsfera": "",
        "coMunicipioIbge": cod,
        "count": str(tamanho),
        "page": str(pagina),
        "sgUf": uf,
    }
    if nr_proposta:
        params["nuProposta"] = nr_proposta
    # Filtro de emenda: o FNS usa o parametro `tpEmenda` com o valor exato do
    # portal (INDIVIDUAL, BANCADA, BANCADA OBRIGATÓRIA com acento, COMISSAO,
    # RELATOR). dsTipoRecurso NAO filtra (e ignorado pelo servidor).
    if tipo_emenda and tipo_emenda.upper() != "TODOS":
        params["tpEmenda"] = tipo_emenda

    # httpx.Client e SINCRONO: roda numa thread p/ nao travar o event loop
    # (o Painel de Indicadores dispara varios anos de uma vez).
    def _fetch() -> dict:
        with httpx.Client(cookies=cookies, timeout=30, verify=False) as cli:
            r = cli.get(
                f"{FNS_BASE}/recursos/proposta/consultar",
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0",
                    "Referer": f"{FNS_BASE}/",
                },
            )
            if r.status_code == 401 or "login" in r.text[:200].lower():
                raise HTTPException(401, "Sessão FNS expirada. Re-capture via bookmarklet.")
            r.raise_for_status()
            return r.json()

    try:
        data = await asyncio.to_thread(_fetch)
    except HTTPException as e:
        # NAO propagar 401 daqui: o interceptor do frontend trata 401 como sessao
        # do PACTHA expirada e desloga o usuario. Sessao do FNS != sessao do app.
        raise HTTPException(502, f"Falha FNS: {e.status_code}: {e.detail}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"FNS: {e.response.text[:200]}")
    except Exception as e:
        raise HTTPException(502, f"Falha FNS: {e}")

    resultado = data.get("resultado", {}) or {}
    items = resultado.get("itensPagina", []) or []
    normalized = []
    for it in items:
        normalized.append({
            "tipo_proposta": it.get("coTipoProposta"),
            "tipo_recurso": it.get("dsTipoRecurso"),
            "nu_processo": it.get("nuProcesso"),
            "valor_proposta": float(it.get("vlProposta") or 0),
            "valor_pago": float(it.get("vlPago") or 0),
            "valor_pagar": float(it.get("vlPagar") or 0),
            "constituido_processo": it.get("constituidoProcesso"),
            # ⚠️ Era `it.get("parlamentares", [])` — o payload do FNS repassado
            # CRU. O portal chama os campos de `noApelidoPolitico` e `sgPartido`;
            # a tela lê `nome` e `partido`. Resultado: a lista mostrava o bloco
            # de parlamentares com os nomes EM BRANCO, e o gestor concluía que o
            # dado não tinha sido coletado — quando estava ali, com outro nome.
            # O detalhe já normalizava; só a lista não. Agora as duas usam a
            # mesma função, que é o único jeito de isto não divergir de novo.
            "parlamentares": _parlamentares(it),
            "pagamentos_count": len(it.get("pagamentos", []) or []),
        })
    return {
        "items": normalized,
        "params": {"municipio": municipio, "cod_ibge": cod, "ano": ano, "uf": uf},
        "total": len(normalized),
        "totais": {
            "valor_proposta": sum(i["valor_proposta"] for i in normalized),
            "valor_pago": sum(i["valor_pago"] for i in normalized),
            "valor_pagar": sum(i["valor_pagar"] for i in normalized),
        },
    }


@router.get("/anos", dependencies=[exige("fns.ver")])
async def anos(db: AsyncSession = Depends(get_db),
               current: User = Depends(get_current_user)):
    """Anos disponiveis no FNS."""
    # So a tela: a resposta e a lista de exercicios que o portal federal aceita,
    # igual para todo mundo — nao ha municipio no pedido nem na resposta.
    # `/buscar` e `/listar-individuais`, que tem, ja passam pelo
    # `_ensure_fns_municipio` (tela + escopo de municipio).
    authz.exigir_tela(current, "fns")
    cookies = await _get_cookies(db)
    try:
        with httpx.Client(cookies=cookies, timeout=15, verify=False) as cli:
            r = cli.get(f"{FNS_BASE}/recursos/anos",
                        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return [a.get("valor") for a in r.json().get("resultado", [])]
    except Exception as e:
        # Fallback: range
        from datetime import datetime
        return [str(y) for y in range(datetime.now().year, 2018, -1)]


@router.get("/municipios", dependencies=[exige("fns.ver")])
async def municipios_pacta(db: AsyncSession = Depends(get_db),
                           current: User = Depends(get_current_user)):
    """Lista os municipios do AMBIENTE com codigo IBGE FNS
    (6 digitos = ibge_code sem o digito verificador) + UF, ordenados por nome."""
    authz.exigir_tela(current, "fns")
    rows = (await db.execute(text(
        "SELECT id, nome, ibge_code, uf FROM municipios WHERE active = true "
        "AND ibge_code IS NOT NULL ORDER BY nome"))).fetchall()

    # ESCOPO — a copia que esqueceu de filtrar.
    #
    # `GET /api/municipios` (routers/municipios.py) faz esta MESMA consulta e
    # filtra por `allowed_municipio_ids`; esta aqui nunca filtrou. Resultado: a
    # tela do FNS entregava a lista INTEIRA do cliente para quem enxerga um
    # municipio so — e num tenant de assessoria isso e o nome de todas as
    # prefeituras atendidas aparecendo para quem nao atende nenhuma.
    #
    # O GATE DE UMA LISTAGEM E O FILTRO, NAO O 403. Devolver 403 aqui derrubaria
    # a tela de quem tem escopo legitimo — o oposto do que este incremento quer.
    # Por isso `authz.negar` nao decide o corte: ele so escreve a linha da
    # trilha, e so no modo em que nao levanta.
    allowed = getattr(current, "allowed_municipio_ids", None)
    if allowed is not None:
        fora = [r for r in rows if r[0] not in allowed]
        if fora:
            if authz.modo() == authz.MODO_BLOQUEIO:
                rows = [r for r in rows if r[0] in allowed]
            else:
                # MODO AVISO: a resposta sai IDENTICA a de hoje (lista inteira) e
                # o vazamento vira linha na trilha. Uma linha por municipio, e
                # nao uma so, porque "quem viu o que" e a pergunta da semana de
                # observacao; o dedupe do authz segura a repeticao dentro da
                # janela e o teto acima segura a rajada da primeira chamada.
                for r in fora[:_TETO_AVISO_MUNICIPIOS]:
                    authz.negar(
                        current, tipo="municipio", exigido=r[0], possui=allowed,
                        # Nunca chega ao cliente: em modo aviso `negar` so
                        # registra. Fica igual a das outras negativas para o dia
                        # em que alguem precise dela.
                        mensagem="Voce nao tem acesso a este municipio")
    return [{"id": i, "nome": n, "cod_ibge": str(ib)[:6], "uf": uf} for i, n, ib, uf in rows]


@router.get("/proposta/{nu_proposta}", dependencies=[exige("fns.ver")])
async def detalhe_proposta(
    nu_proposta: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Detalhe completo de uma proposta individual.

    Endpoint upstream:
      GET /recursos/proposta/obter-proposta?nuProposta=XXX
      GET /recursos/proposta/obter-proposta-etapa  (mapa de 12 etapas)
    """
    # SO A TELA, e o que falta esta declarado de proposito.
    #
    # A proposta nao e dado do tenant: ela mora no portal federal (publico) e o
    # unico sinal de municipio na resposta e `noMunicipio`, texto livre vindo de
    # la. Casar esse texto com os municipios do escopo — que e o que
    # `_ensure_fns_municipio` faz por NOME — significaria negar por divergencia
    # de acentuacao ("MONTE SIAO" x "MONTE SIÃO"): um 403 novo, para usuario
    # legitimo, no dia em que o bloqueio for ligado. E o apagao de segunda-feira
    # que este incremento existe para evitar, so que atrasado uma semana.
    #
    # Fica registrado como buraco conhecido: quem tem a tela `fns` consegue ler
    # o detalhe de qualquer numero de proposta. Fecha-lo direito pede o municipio
    # do proprio pedido (o frontend ja sabe qual e) e uma comparacao por codigo
    # IBGE, nao por nome — mudanca de contrato do endpoint, nao acrescimo de gate.
    authz.exigir_tela(current, "fns")
    cookies = await _get_cookies(db)
    try:
        with httpx.Client(cookies=cookies, timeout=20, verify=False) as cli:
            # Detalhe principal
            r1 = cli.get(
                f"{FNS_BASE}/recursos/proposta/obter-proposta",
                params={"nuProposta": nu_proposta},
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0",
                         "Referer": f"{FNS_BASE}/"},
            )
            r1.raise_for_status()
            d = r1.json().get("resultado", {}) or {}

            # Etapas
            # Sem nuProposta o portal devolve 400 e o mapa de etapas vinha vazio
            # (o erro era engolido pelo except) -> a trilha de 12 etapas nunca
            # aparecia no detalhe.
            r2 = cli.get(
                f"{FNS_BASE}/recursos/proposta/obter-proposta-etapa",
                params={"nuProposta": nu_proposta},
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0",
                         "Referer": f"{FNS_BASE}/"},
            )
            etapas_map = r2.json().get("resultado", {}) if r2.status_code == 200 else {}
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"FNS: {e.response.text[:200]}")
    except Exception as e:
        raise HTTPException(502, f"Falha FNS: {e}")

    # Determina workflow ativo (Contrato de Repasse, Outros Tipos, etc)
    # Por padrao, usa Contrato de Repasse (12 etapas)
    workflow_key = "Contrato de Repasse"
    etapas_list = etapas_map.get(workflow_key, []) or []
    sit_cod = (d.get("situacao") or {}).get("codigoSituacaoProjeto")
    current_etapa = None
    for et in etapas_list:
        if sit_cod and sit_cod in (et.get("situacoes") or []):
            current_etapa = et.get("etapa")
            break

    # CONTA (domicilio bancario) por pagamento — o obter-proposta nao a traz, so
    # o detalhe-pagamento da Consulta Detalhada. Resolve o IBGE6 pelo municipio/UF
    # da propria proposta e busca por ano de PAGAMENTO (id.ano no portal). Sem
    # pagamento nao ha chamada extra; falha => pagamentos sem conta (a data e a OB
    # continuam vindo do obter-proposta).
    pgs_raw = d.get("pagamentos") or []
    contas_por_ob: dict = {}
    if pgs_raw:
        anos_pg = sorted({a for a in (_ano_ms(pg.get("dtCriacaoSiafi")) for pg in pgs_raw) if a})
        if not anos_pg and d.get("nuAnoProposta"):
            try:
                anos_pg = [int(d["nuAnoProposta"])]
            except (TypeError, ValueError):
                anos_pg = []
        uf_prop = (d.get("sgUf") or "").strip().upper()
        cod_ibge = await _resolve_cod(d.get("noMunicipio") or "", uf_prop, db)
        if cod_ibge and anos_pg:
            try:
                contas_por_ob = await asyncio.to_thread(
                    _contas_por_pagamento, cookies, uf_prop, str(cod_ibge)[:6],
                    str(nu_proposta), anos_pg)
            except Exception:
                contas_por_ob = {}

    def _conta_do_pg(pg: dict) -> dict:
        ob = (pg.get("nuOb") or "").strip()
        if ob:
            for k, v in contas_por_ob.items():
                if k and (ob.endswith(k) or k in ob):
                    return v
        return {}

    pagamentos_norm = []
    for pg in pgs_raw:
        conta_pg = _conta_do_pg(pg)
        pagamentos_norm.append({
            "parcela": pg.get("nuParcela"),
            "data": pg.get("dtCriacaoSiafi"),  # ms epoch
            "valor": float(pg.get("vlLiquido") or 0),
            "valor_acumulado": float(pg.get("vlAcumulado") or 0),
            "ordem_bancaria": pg.get("nuOb"),
            "nu_processo": pg.get("nuProcesso"),
            "localizacao": pg.get("localizacao"),
            # do detalhe-pagamento (pode faltar se a 2a consulta falhar)
            "conta": conta_pg.get("conta"),
            "banco": conta_pg.get("banco"),
            "agencia": conta_pg.get("agencia"),
        })

    return {
        "nu_proposta": d.get("nuProposta"),
        "uf": d.get("sgUf"),
        "municipio": d.get("noMunicipio"),
        "cnpj": d.get("cnpjFormatado") or d.get("cnpj"),
        "entidade": d.get("noEntidade"),
        "tipo_proposta": d.get("coTipoProposta"),
        "valor_proposta": float(d.get("vlProposta") or 0),
        "ano": d.get("nuAnoProposta"),
        "tipo_recurso": d.get("dsTipoRecurso"),
        "esfera": d.get("coEsfera"),
        "nu_portaria": d.get("nuPortaria") or None,
        "nu_processo": d.get("nuProcesso"),
        "situacao_descricao": (d.get("situacao") or {}).get("descricaoSituacaoproposta"),
        "situacao_data": (d.get("situacao") or {}).get("dataSituacaoProjeto"),  # ms epoch
        "vl_empenhado": float(d.get("vlEmpenhado") or 0),
        "vl_pago": float(d.get("vlPago") or 0),
        "vl_pagar": float(d.get("vlPagar") or 0),
        "parlamentares": _parlamentares(d),
        # Pagamentos: data/OB/valores do obter-proposta + banco/agencia/CONTA do
        # detalhe-pagamento (montado acima). Upstream: dtCriacaoSiafi (ms),
        # nuParcela, localizacao, nuProcesso, nuOb, vlLiquido, vlAcumulado.
        "pagamentos": pagamentos_norm,
        "data_portaria": d.get("dtPortaria"),  # ms epoch
        "constituido_processo": d.get("constituidoProcesso"),
        "situacao_ultima_analise": d.get("situacaoUltimaAnalise"),
        "ultimo_processo": d.get("ultimoProcesso"),
        "etapas": [
            {
                "numero": et.get("etapa"),
                "descricao": et.get("descricao"),
                "completada": (et.get("etapa") or 0) <= (current_etapa or 0),
                "atual": et.get("etapa") == current_etapa,
            }
            for et in etapas_list
        ],
        "etapa_atual": current_etapa,
    }


@router.get("/listar-individuais", dependencies=[exige("fns.ver")])
async def listar_individuais(
    municipio: str = Query(...),
    ano: int = Query(...),
    uf: str | None = Query(None),
    tipo_proposta: str = Query(..., description="Ex: EQUIPAMENTO, CUSTEIO MAC, INCREMENTO PAP"),
    tipo_recurso: str = Query(..., description="PROGRAMA / EMENDA INDIVIDUAL / etc"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Lista propostas individuais de um grupo (nivel 1 do detalhamento).

    Descoberto via portalCtrl.grid2() do FNS: quando o usuario clica no
    botao olho, o portal chama /recursos/proposta/consultar com OS MESMOS
    params da listagem MAS substitui `coTipoProposta/dsTipoRecurso` por
    `tpProposta/tpRecurso` (URL-encoded). Esses dois parametros
    "destravam" o agrupamento: a resposta vem com 1 item POR PROPOSTA
    individual (cada um com nuProposta), ao inves do agregado.
    """
    await _ensure_fns_municipio(current, municipio, db)
    uf = await _resolver_uf(db, municipio, uf)
    cod = await _resolve_cod(municipio, uf, db) or municipio
    cookies = await _get_cookies(db)
    params = {
        "ano": str(ano), "coEsfera": "", "coMunicipioIbge": cod,
        "count": "200", "page": "1", "sgUf": uf,
        # Note: httpx faz urlencode automaticamente
        "tpProposta": tipo_proposta, "tpRecurso": tipo_recurso,
    }
    try:
        with httpx.Client(cookies=cookies, timeout=20, verify=False) as cli:
            r = cli.get(f"{FNS_BASE}/recursos/proposta/consultar", params=params,
                        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0",
                                 "Referer": f"{FNS_BASE}/"})
            r.raise_for_status()
            res = r.json().get("resultado", {}) or {}
    except Exception as e:
        raise HTTPException(502, f"Falha FNS: {e}")

    items = res.get("itensPagina", []) or []
    individuais = []
    for it in items:
        individuais.append({
            "tipo_proposta": it.get("coTipoProposta"),
            "tipo_recurso": it.get("dsTipoRecurso"),
            "nu_proposta": it.get("nuProposta"),
            "entidade": it.get("noEntidade") or "FUNDO MUNICIPAL DE SAUDE",
            "municipio": it.get("noMunicipio"),
            "nu_processo": it.get("nuProcesso"),
            "valor_proposta": float(it.get("vlProposta") or 0),
            "valor_pago": float(it.get("vlPago") or 0),
            "valor_pagar": float(it.get("vlPagar") or 0),
            "constituido_processo": it.get("constituidoProcesso"),
            "qtd_parlamentares": len(it.get("parlamentares") or []),
            "qtd_pagamentos": len(it.get("pagamentos") or []),
        })
    return {"items": individuais, "total": len(individuais),
            "grupo": {"tipo_proposta": tipo_proposta, "tipo_recurso": tipo_recurso,
                      "municipio": municipio, "ano": ano, "uf": uf}}
