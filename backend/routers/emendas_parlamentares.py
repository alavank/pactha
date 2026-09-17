"""Emendas parlamentares numa tela só — Federais | Estaduais | Parlamentares.

Pedido do dono em 17/09/2026: o assunto estava em quatro itens soltos do menu
(Federais › Emendas parlamentares, Estaduais › Emendas Estaduais e Emendas
Estaduais RS, e Parlamentares) e em pedaços de mais oito telas. Este router é o
backend da tela única; a tela vem no PR seguinte.

⭐ NADA AQUI É CONSULTA NOVA SOBRE DADO VELHO. Cada aba lê pelas funções das
telas que já existem — `emendas_federais.buscar`, `parlamentares.
aggregate_parlamentares`, `parcerias.carregar_proposta`, `transferegov.
carregar_plano_acao`/`carregar_voluntaria`, `emendas_estaduais.
SQL_EMENDAS_COM_CONVENIO`. Duas consultas "equivalentes" são como duas telas
passam a mostrar números diferentes para a mesma emenda.

⚠️⚠️ PERMISSÃO: CADA ABA COBRA A CHAVE QUE JÁ EXISTIA (decisão do dono,
17/09/2026). Não há tela `emendas_parlamentares` no catálogo:

    Federais ....... emendas_federais.ver + tela emendas_federais
    Estaduais ...... MG: emendas · RS: emendas_rs · GO: repasses
    Parlamentares .. parlamentares.ver + tela parlamentares

Ninguém ganha nem perde acesso com a troca, e não existe migration de acesso
para falhar no deploy (a lição de 05/09/2026, ver skill `authz`). Quem só tinha
Emendas Federais abre a tela nova e vê só a aba Federais.

⚠️ O DETALHE DE UMA EMENDA FEDERAL ABRE PELA ABA, E NÃO PELA TELA DE ORIGEM. Quem
tem Emendas Federais e não tem Especiais abre o plano de ação da emenda Pix por
aqui — é o pedido ("cada emenda clicável com o detalhe inteiro"). O município
continua vindo DA LINHA, nunca do parâmetro: id federal solto abriria plano de
qualquer município do Brasil.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from routers.emendas_estaduais import SQL_EMENDAS_COM_CONVENIO
from routers.emendas_federais import buscar as buscar_carteira, linha_do_tempo
from routers.parcerias import carregar_proposta
from routers.parlamentares import aggregate_parlamentares
from routers.transferegov import carregar_plano_acao, carregar_voluntaria
from services import authz
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.bi import anos_list
from services.cadastro_parlamentar import cadastros_por_nome
from services.conteudo_rs import AVISO_EMENDAS, EMENDAS
from services.emendas_unificadas import filtrar, totais, unificar_federais
from services.natureza import e_municipal
from services.registro_rotas import declarado, exige

router = APIRouter(prefix="/api/emendas-parlamentares", tags=["emendas-parlamentares"])

# UF -> a tela que já dava acesso às emendas estaduais daquele estado.
TELA_ESTADUAL_POR_UF = {"MG": "emendas", "RS": "emendas_rs", "GO": "repasses"}

# ⚠️ Estado sem fonte ganha FRASE, nunca lista vazia muda: lista vazia é lida
# como "o município não recebeu emenda estadual".
MOTIVO_SEM_FONTE = {
    "ES": ("O Espírito Santo publica os convênios (GConv), mas sem o autor da "
           "emenda. Por isso ainda não dá para separar aqui o que veio de "
           "deputado estadual. Os convênios aparecem em Estaduais › Convênios."),
    "GO": ("Goiás publica o PAGAMENTO, e não a emenda. O autor só aparece quando a "
           "descrição do repasse o cita, então esta lista mostra parte das emendas "
           "estaduais do município, e não todas."),
}
MOTIVO_OUTRA_UF = ("As emendas parlamentares estaduais deste estado ainda não são "
                   "coletadas pelo PACTHA.")

# As origens que abrem pela aba Federais.
ORIGENS_FEDERAIS = ("federal", "te", "parcerias", "indicacao", "voluntaria")


def _f(v) -> Optional[float]:
    return float(v) if v is not None else None


async def _uf(db: AsyncSession, municipio_id: int) -> str:
    uf = (await db.execute(text(
        "SELECT upper(coalesce(uf, '')) FROM municipios WHERE id = :m"),
        {"m": municipio_id})).scalar()
    if uf is None:
        raise HTTPException(404, "Município não encontrado")
    return uf


async def _consulta(db: AsyncSession, sql: str, params: dict) -> list[dict]:
    """Lista de dicts, ou [] quando a tabela não existe num tenant atrasado.
    Uma fonte a menos não derruba a aba — o mesmo padrão das telas de origem."""
    try:
        return [dict(r) for r in (await db.execute(text(sql), params)).mappings().all()]
    except Exception:
        await db.rollback()
        return []


def _com_parlamentar(linhas: list[dict], cadastros: dict, campo: str = "autores") -> None:
    for l in linhas:
        nomes = l.get(campo) or []
        l["parlamentares"] = [{"nome": n, "cadastro": cadastros.get(n)} for n in nomes]


# ---------------------------------------------------------------------------
# Aba FEDERAIS
# ---------------------------------------------------------------------------

async def _fontes_federais(db: AsyncSession, municipio_id: int) -> dict:
    m = {"m": municipio_id}
    carteira = await buscar_carteira(db, municipio_id)
    # ⚠️ O MESMO filtro de CNPJ da aba Parlamentares (bloco 4 do agregado): o
    # coletor da TE casa beneficiário por substring de nome, e sem isto a emenda
    # Pix de "Paraíso do Tocantins" cai no município mineiro "Tocantins".
    te = await _consulta(db, """
        SELECT te.plano_acao_id, te.emenda, te.parlamentar, te.objeto, te.situacao,
               te.valor_total
          FROM transferegov_te te
          LEFT JOIN municipios mu ON mu.id = te.municipio_id
         WHERE te.municipio_id = :m
           AND (te.beneficiario_cnpj IS NULL OR mu.cnpj IS NULL
                OR regexp_replace(te.beneficiario_cnpj, '[^0-9]', '', 'g')
                   = regexp_replace(mu.cnpj, '[^0-9]', '', 'g'))
    """, m)
    parcerias = await _consulta(db, """
        SELECT id_proposta, numero_emenda, parlamentar, tipo_emenda, objeto, situacao,
               valor_emenda, valor_total, ano_proposta AS ano, natureza_juridica
          FROM parcerias_propostas
         WHERE municipio_id = :m AND numero_emenda IS NOT NULL
    """, m)
    indicadas = await _consulta(db, """
        SELECT numero_emenda, ano_emenda AS ano, parlamentar, tipo_emenda AS tipo,
               valor_total, natureza_juridica
          FROM parcerias_emendas_indicadas WHERE municipio_id = :m
    """, m)
    voluntarias = await _consulta(db, """
        SELECT numero_proposta, id_proposta_siconv, parlamentar, objeto, situacao,
               valor_emenda, valor_repasse, municipal
          FROM transferegov_propostas
         WHERE municipio_id = :m
           AND (parlamentar IS NOT NULL OR coalesce(valor_emenda, 0) > 0)
    """, m)
    for lst, cols in ((te, ("valor_total",)),
                      (parcerias, ("valor_emenda", "valor_total")),
                      (indicadas, ("valor_total",)),
                      (voluntarias, ("valor_emenda", "valor_repasse"))):
        for r in lst:
            for c in cols:
                r[c] = _f(r.get(c))
    # A regra de "é da prefeitura" de cada fonte, a mesma das telas de origem.
    for r in parcerias + indicadas:
        r["municipal"] = e_municipal(r.get("natureza_juridica"))
    for r in voluntarias:
        r["municipal"] = r.get("municipal") is not False
    return {"carteira": carteira, "te": te, "parcerias": parcerias,
            "indicadas": indicadas, "voluntarias": voluntarias}


@router.get("/federais", dependencies=[exige("emendas_federais.ver")])
async def federais(
    municipio_id: int = Query(...),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    autor: Optional[str] = Query(None, description="parte do nome do parlamentar"),
    tipo: Optional[str] = Query(None, description="INDIVIDUAL | BANCADA | COMISSAO | RELATOR GERAL"),
    origem: Optional[str] = Query(None, description="federal | te | parcerias | indicacao | voluntaria"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Uma linha por emenda federal do município, com os instrumentos dela.

    Os filtros vêm antes dos totais: cartão e lista saem do mesmo conjunto."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "emendas_federais")
    f = await _fontes_federais(db, municipio_id)
    carteira = f["carteira"]
    todas = unificar_federais(carteira.get("items") or [], f["te"], f["parcerias"],
                              f["indicadas"], f["voluntarias"])
    linhas = filtrar(todas, anos=anos_list((anos or []) + ([ano] if ano else [])),
                     autor=autor, tipo=tipo, origem=origem)
    cadastros = await cadastros_por_nome(
        db, {n for l in linhas if not l["colegiado"] for n in l["autores"]})
    for l in linhas:
        l["parlamentares"] = [{"nome": n, "cadastro": None if l["colegiado"] else cadastros.get(n)}
                              for n in l["autores"]]
    return {
        "tem_dados": bool(todas),
        # O estado e o aviso da CARTEIRA continuam valendo: dizem se a execução
        # CGU foi consultada, e isso a unificação não muda.
        "estado": carteira.get("estado"), "aviso": carteira.get("aviso"),
        "coleta_em": carteira.get("coleta_em"), "coleta_falhas": carteira.get("coleta_falhas"),
        "execucao": carteira.get("execucao"),
        "totais": totais(linhas),
        "items": linhas,
        # As opções dos filtros saem da base INTEIRA, para o filtro não sumir
        # com a opção que acabou de ser escolhida.
        "anos": sorted({l["ano"] for l in todas if l["ano"]}, reverse=True),
        "tipos": sorted({l["tipo"] for l in todas if l["tipo"]}),
        "origens": sorted({o for l in todas for o in l["origens"]}),
        "autores": sorted({n for l in todas for n in l["autores"]}),
    }


# ---------------------------------------------------------------------------
# Aba ESTADUAIS
# ---------------------------------------------------------------------------

def _pode_estadual(current: User, uf: str) -> Optional[str]:
    """Cobra a tela estadual da UF do município. Devolve a tela, ou None para UF
    sem fonte — que só recebe a frase explicando, e nenhum dado."""
    tela = TELA_ESTADUAL_POR_UF.get(uf)
    if tela:
        authz.exigir(current, f"{tela}.ver")
        ensure_tela(current, tela)
    return tela


@router.get("/estaduais",
            dependencies=[declarado("emendas.ver", "emendas_rs.ver", "repasses.ver")])
async def estaduais(
    municipio_id: int = Query(...),
    anos: Optional[list[int]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """As emendas estaduais do município, conforme o que o estado dele publica.

    ⚠️ A PERMISSÃO DEPENDE DA UF, por isso `declarado` e a checagem no corpo:
    MG cobra `emendas`, RS `emendas_rs`, GO `repasses` — as telas que já davam
    esse dado. UF sem fonte (ES, TO…) não devolve dado nenhum, só a frase."""
    ensure_municipio_access(current, municipio_id)
    uf = await _uf(db, municipio_id)
    _pode_estadual(current, uf)
    base = {"uf": uf, "fonte": None, "items": [], "motivo": None, "conteudo": None,
            "totais": {"emendas": 0, "valor": 0.0}}

    if uf == "MG":
        onde, p = "emendas_estaduais.municipio_id = :m", {"m": municipio_id}
        if anos:
            onde += " AND emendas_estaduais.ano = ANY(:anos)"
            p["anos"] = list(anos)
        itens = await _consulta(db, f"""
            {SQL_EMENDAS_COM_CONVENIO}
            WHERE {onde}
            ORDER BY ano DESC NULLS LAST, valor_indicacao DESC NULLS LAST
        """, p)
        for it in itens:
            it["valor_indicacao"] = _f(it.get("valor_indicacao"))
            it["origem"], it["chave"] = "sigcon", f"sigcon:{it['id']}"
            it["autores"] = [n.strip() for n in str(it.get("nome_responsavel") or "").split(",")
                             if len(n.strip()) >= 3]
        _com_parlamentar(itens, await cadastros_por_nome(
            db, {n for it in itens for n in it["autores"]}))
        base.update(fonte="SIGCON-MG", items=itens, totais={
            "emendas": len(itens),
            "valor": round(sum(it["valor_indicacao"] or 0 for it in itens), 2)})
        if not itens:
            base["motivo"] = ("Nenhuma emenda estadual coletada no SIGCON-MG para este "
                              "município.")
        return base

    if uf == "RS":
        # O Estado publica em Power BI fechado: o conteúdo curado, com o aviso.
        base.update(motivo=AVISO_EMENDAS, conteudo=EMENDAS)
        return base

    if uf == "GO":
        onde, p = "r.municipio_id = :m AND r.emenda_autor IS NOT NULL", {"m": municipio_id}
        if anos:
            onde += " AND r.ano = ANY(:anos)"
            p["anos"] = list(anos)
        itens = await _consulta(db, f"""
            SELECT r.id, r.data_repasse, r.valor, r.credor, r.orgao, r.descricao,
                   r.emenda_numero, r.emenda_autor, r.ano, r.fonte
              FROM repasses_estaduais r WHERE {onde}
             ORDER BY r.data_repasse DESC NULLS LAST, r.id DESC
        """, p)
        for it in itens:
            it["valor"] = _f(it.get("valor"))
            it["data_repasse"] = it["data_repasse"].isoformat() if it.get("data_repasse") else None
            it["origem"], it["chave"] = "go", f"go:{it['id']}"
            it["autores"] = [it["emenda_autor"].strip()]
        _com_parlamentar(itens, await cadastros_por_nome(
            db, {n for it in itens for n in it["autores"]}))
        base.update(fonte="Transferências voluntárias GO", items=itens,
                    motivo=MOTIVO_SEM_FONTE["GO"], totais={
                        "emendas": len(itens),
                        "valor": round(sum(it["valor"] or 0 for it in itens), 2)})
        return base

    base["motivo"] = MOTIVO_SEM_FONTE.get(uf, MOTIVO_OUTRA_UF)
    return base


# ---------------------------------------------------------------------------
# Aba PARLAMENTARES
# ---------------------------------------------------------------------------

@router.get("/parlamentares", dependencies=[exige("parlamentares.ver")])
async def parlamentares(
    municipio_id: int = Query(...),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    q: Optional[str] = Query(None),
    tipo: str = Query("parlamentar", description="parlamentar | outro | todos"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """O ranking da tela Parlamentares, com partido, cargo e foto.

    ⚠️ O NÚMERO É O MESMO DE `/api/parlamentares`, do BI e do Painel: a soma sai
    de `aggregate_parlamentares`, sem uma linha a mais. O que muda é só o
    cadastro ao lado do nome ("mesmo dado, mesma conta em toda tela").

    ⚠️ Parcerias AINDA NÃO ENTRA NA SOMA. A proposta de saúde de lá é, em boa
    parte, a mesma do FNS (bloco 6 do agregado), e nenhuma das duas traz uma
    chave comum que permita descontar. Somar sem medir inflaria o ranking do BI
    e do Painel junto — fica para depois da medição nos tenants."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "parlamentares")
    dados = await aggregate_parlamentares(
        db, municipio_id=municipio_id, q=q,
        ano=anos_list((anos or []) + ([ano] if ano else [])), tipo=tipo)
    cadastros = await cadastros_por_nome(
        db, {i["nome_display"] for i in dados["items"] if i["tipo"] == "parlamentar"})
    for i in dados["items"]:
        i["cadastro"] = cadastros.get(i["nome_display"]) if i["tipo"] == "parlamentar" else None
    dados["com_cadastro"] = sum(1 for i in dados["items"] if i.get("cadastro"))
    return dados


# ---------------------------------------------------------------------------
# DETALHE de uma emenda
# ---------------------------------------------------------------------------

def _confere_linha(current: User, municipio_da_linha, municipio_id: int) -> None:
    """A linha tem de ser do município pedido, e o usuário tem de enxergá-lo.
    ⚠️ 404 e não 403 quando não bate: dizer "existe, mas não é seu" confirmaria
    que o id existe em outro município."""
    if municipio_da_linha != municipio_id:
        raise HTTPException(404, "Emenda não encontrada neste município")
    ensure_municipio_access(current, municipio_da_linha)


@router.get("/emenda/{origem}/{ident:path}",
            dependencies=[declarado("emendas_federais.ver", "emendas.ver",
                                    "repasses.ver")])
async def detalhe(
    origem: str,
    ident: str,
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """O detalhe inteiro de UMA emenda, pela origem da linha da lista.

    Para `te`, `parcerias` e `voluntaria`, `dados` é EXATAMENTE o payload do
    modal da tela de origem — a tela reusa aqueles componentes em vez de
    reescrever a árvore (plano de trabalho, empenho, OB, extrato, pareceres).
    `federal` junta a carteira, a execução CGU, a linha do tempo e os
    instrumentos ligados; `sigcon` e `go` trazem a linha e o que ela gerou."""
    ensure_municipio_access(current, municipio_id)
    if origem in ORIGENS_FEDERAIS:
        authz.exigir(current, "emendas_federais.ver")
        ensure_tela(current, "emendas_federais")
    elif origem == "sigcon":
        authz.exigir(current, "emendas.ver")
        ensure_tela(current, "emendas")
    elif origem == "go":
        authz.exigir(current, "repasses.ver")
        ensure_tela(current, "repasses")
    else:
        raise HTTPException(404, "Origem desconhecida")

    resposta: dict = {"origem": origem, "id": ident, "dados": None,
                      "parlamentares": [], "codigo_emenda": None}

    if origem == "te":
        achado = await carregar_plano_acao(db, _inteiro(ident))
        if achado is None:
            raise HTTPException(404, "Plano de ação não encontrado nesta base")
        _confere_linha(current, achado[0], municipio_id)
        plano = achado[1].get("plano") or {}
        autor = plano.get("nome_parlamentar_emenda_plano_acao")
        resposta.update(dados=achado[1], autores=[autor] if autor else [])
    elif origem == "parcerias":
        achado = await carregar_proposta(db, _inteiro(ident))
        if achado is None:
            raise HTTPException(404, "Proposta não encontrada nesta base")
        _confere_linha(current, achado[0], municipio_id)
        linha = (await _consulta(db, "SELECT parlamentar FROM parcerias_propostas "
                                     "WHERE id_proposta = :p LIMIT 1",
                                 {"p": _inteiro(ident)}))
        resposta.update(dados=achado[1],
                        autores=[linha[0]["parlamentar"]] if linha and linha[0]["parlamentar"] else [])
    elif origem == "voluntaria":
        dados = await carregar_voluntaria(db, municipio_id, ident)
        if dados is None:
            raise HTTPException(404, "Proposta não encontrada neste município")
        resposta.update(dados=dados, autores=[
            n.strip() for n in str(dados.get("parlamentar") or "").split(",") if len(n.strip()) >= 3])
    elif origem == "indicacao":
        linhas = await _consulta(db, """
            SELECT numero_emenda, ano_emenda, parlamentar, tipo_emenda, valor_gnd3,
                   valor_gnd4, valor_total, nome_beneficiario, cnpj_beneficiario,
                   natureza_juridica, indicacoes, id_programa
              FROM parcerias_emendas_indicadas
             WHERE municipio_id = :m
               AND regexp_replace(numero_emenda, '[^0-9]', '', 'g') = :c
        """, {"m": municipio_id, "c": ident})
        if not linhas:
            raise HTTPException(404, "Indicação não encontrada neste município")
        for l in linhas:
            for c in ("valor_gnd3", "valor_gnd4", "valor_total"):
                l[c] = _f(l.get(c))
        resposta.update(dados={"indicacoes": linhas}, codigo_emenda=ident,
                        autores=sorted({l["parlamentar"] for l in linhas if l["parlamentar"]}))
    elif origem == "federal":
        resposta.update(await _detalhe_federal(db, municipio_id, ident))
    elif origem == "sigcon":
        resposta.update(await _detalhe_sigcon(db, municipio_id, _inteiro(ident)))
    elif origem == "go":
        linhas = await _consulta(db, """
            SELECT id, data_repasse, valor, credor, orgao, formalidade, elemento,
                   sub_elemento, processo, processo_alt, fonte_recursos, descricao,
                   emenda_numero, emenda_autor, ano, fonte
              FROM repasses_estaduais WHERE id = :i AND municipio_id = :m
        """, {"i": _inteiro(ident), "m": municipio_id})
        if not linhas:
            raise HTTPException(404, "Repasse não encontrado neste município")
        r = linhas[0]
        r["valor"] = _f(r.get("valor"))
        r["data_repasse"] = r["data_repasse"].isoformat() if r.get("data_repasse") else None
        resposta.update(dados=r, autores=[r["emenda_autor"]] if r.get("emenda_autor") else [])

    autores = resposta.pop("autores", []) or []
    cadastros = await cadastros_por_nome(db, autores)
    resposta["parlamentares"] = [{"nome": n, "cadastro": cadastros.get(n)} for n in autores]
    return resposta


def _inteiro(ident: str) -> int:
    try:
        return int(ident)
    except (TypeError, ValueError):
        raise HTTPException(404, "Identificador inválido")


async def _detalhe_federal(db: AsyncSession, municipio_id: int, codigo: str) -> dict:
    """A emenda da carteira: indicação por beneficiário, execução CGU, linha do
    tempo e os instrumentos que ela gerou (cada um abre pela própria origem)."""
    carteira = await buscar_carteira(db, municipio_id)
    linhas = [e for e in carteira.get("items") or [] if e.get("codigo_emenda") == codigo]
    if not linhas:
        raise HTTPException(404, "Emenda não encontrada neste município")
    f = await _fontes_federais(db, municipio_id)
    unificadas = unificar_federais(linhas, f["te"], f["parcerias"], f["indicadas"],
                                   f["voluntarias"])
    instrumentos = [i for u in unificadas if u["origem"] == "federal"
                    for i in u["instrumentos"]]
    base = linhas[0]
    return {
        "codigo_emenda": codigo,
        "dados": {
            # ⚠️ Uma linha POR BENEFICIÁRIO: a mesma emenda pode ir à prefeitura e
            # ao hospital da cidade, e o valor de cada um é dele.
            "beneficiarios": linhas,
            "resumo": {k: base.get(k) for k in (
                "codigo_emenda", "numero_emenda", "ano", "autor", "tipo", "impositiva",
                "orgao", "funcao", "subfuncao", "localidade_gasto", "grupo", "motivo",
                "alertas", "url_fonte", "execucao_consultada", "encontrada")},
            # Da emenda INTEIRA, nacional — a tela rotula; nunca somar ao indicado.
            "execucao": {k: base.get(k) for k in (
                "valor_empenhado", "valor_liquidado", "valor_pago",
                "valor_resto_inscrito", "valor_resto_cancelado", "valor_resto_pago")},
            "linha_do_tempo": await linha_do_tempo(db, codigo, municipio_id),
            "instrumentos": instrumentos,
        },
        "autores": [base["autor"]] if base.get("autor") else [],
    }


async def _detalhe_sigcon(db: AsyncSession, municipio_id: int, emenda_id: int) -> dict:
    """A indicação do SIGCON-MG e o convênio que ela gerou, quando já casado.

    ⚠️ SEM PAGAMENTO POR EMENDA: o SIGCON não publica. O convênio traz valor e
    vigência; a tela diz isso em vez de mostrar uma aba de pagamentos vazia."""
    linhas = await _consulta(db, f"""
        {SQL_EMENDAS_COM_CONVENIO}
        WHERE emendas_estaduais.id = :i AND emendas_estaduais.municipio_id = :m
    """, {"i": emenda_id, "m": municipio_id})
    if not linhas:
        raise HTTPException(404, "Emenda não encontrada neste município")
    e = linhas[0]
    e["valor_indicacao"] = _f(e.get("valor_indicacao"))
    convenio = None
    if e.get("conv_id"):
        conv = await _consulta(db, """
            SELECT id, nr_sigcon, nr_proposta, nr_siafi, objeto, situacao, valor_total,
                   valor_concedente, dt_vigencia_inicial, dt_vigencia_final, orgao_concedente,
                   ano
              FROM convenios_estadual WHERE id = :c AND municipio_id = :m
        """, {"c": e["conv_id"], "m": municipio_id})
        if conv:
            convenio = conv[0]
            for c in ("valor_total", "valor_concedente"):
                convenio[c] = _f(convenio.get(c))
            for c in ("dt_vigencia_inicial", "dt_vigencia_final"):
                convenio[c] = str(convenio[c]) if convenio.get(c) else None
    return {
        "dados": {"emenda": e, "convenio": convenio,
                  "sem_pagamento_motivo": ("O SIGCON-MG não publica o pagamento por "
                                           "emenda; o valor e a vigência são os do "
                                           "convênio ligado.")},
        "autores": [n.strip() for n in str(e.get("nome_responsavel") or "").split(",")
                    if len(n.strip()) >= 3],
    }
