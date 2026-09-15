"""Fundo a Fundo — o plano de acao por tras do repasse que o FNS ja conta.

Le `faf_planos_acao`, alimentada por `ingestion/faf_planos.py` a partir de
`api-publica.transferegov.gestao.gov.br/fundoafundo`.

⭐ O QUE ESTA TELA MOSTRA E O ConsultaFNS NAO PUBLICA. A tela de Fundo Nacional
de Saude conta o repasse consolidado por bloco: **o dinheiro que entra**. Aqui
esta o que o justifica — diagnostico, objetivos, vigencia e, sobretudo, a
DECOMPOSICAO do valor entre emenda parlamentar, repasse especifico, repasse
voluntario, recursos proprios e rendimentos de aplicacao. So por aqui o gestor
sabe QUANTO daquele repasse veio de emenda.

⚠️ E NAO E SO SAUDE, apesar do nome sugerir SUS. Os quatro planos de Nova Palma
(R$ 413.420,20) sao do MINISTERIO DA CULTURA, Lei Aldir Blanc, com o Fundo
Nacional da Cultura como repassador. Por isso a tela mostra o orgao repassador
em cada linha, e nao assume o Ministerio da Saude em lugar nenhum.

⭐ E TRAZ PRESTACAO DE CONTAS ESTRUTURADA, que preenche um buraco conhecido do
modelo: `prestacao_contas` e DROPADA a cada boot (`drop_lean_tables.sql`), e
hoje prestacao de contas so existe como texto dentro de um campo de situacao.
Os relatorios de gestao vem em `relatorios_gestao` com valor executado, valor
pendente, resultados alcancados e a situacao de cada um.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Municipio
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/faf-planos", tags=["faf-planos"])

# A fonte publica o plano; o link deixa qualquer numero conferivel por quem
# duvidar dele — mesma disciplina do `url_fonte` das Obras e das Parcerias.
URL_FONTE = ("https://api-publica.transferegov.gestao.gov.br/fundoafundo/"
             "planos-acao?id_plano_acao=")

MOTIVO_SEM_COLETA = (
    "A coleta dos planos de ação Fundo a Fundo ainda não rodou para este "
    "município. Ela é diária."
)

# ⭐ AS CINCO ORIGENS DO DINHEIRO, na ordem em que interessam ao gestor: a
# emenda primeiro, porque é a pergunta que ele faz, e os recursos próprios por
# último, porque são os que ele já sabia que tinha.
ORIGENS = (
    ("emenda", "Emenda parlamentar", "valor_repasse_emenda"),
    ("especifico", "Repasse específico", "valor_repasse_especifico"),
    ("voluntario", "Repasse voluntário", "valor_repasse_voluntario"),
    ("proprios", "Recursos próprios", "valor_recursos_proprios"),
    ("rendimentos", "Rendimentos de aplicação", "valor_rendimentos"),
)


def _f(v) -> Optional[float]:
    """`None` continua `None`. ⚠️ Plano sem valor declarado não é plano de
    R$ 0,00 — zero na tela seria uma afirmação que a fonte não faz."""
    return float(v) if v is not None else None


def _d(v) -> Optional[str]:
    return v.isoformat() if v is not None else None


def _relatorios(bruto) -> list[dict]:
    """Os relatórios de gestão, achatados para a tela.

    ⚠️ NULO E `[]` SIGNIFICAM COISAS DIFERENTES aqui, e o coletor grava a
    distinção de propósito: `NULL` é "não perguntei/não consegui", `[]` seria
    "perguntei e não há". A tela nunca diz «sem prestação de contas» a partir
    de um nulo — ela simplesmente não mostra o bloco.
    """
    if not bruto:
        return []
    fora = []
    for r in bruto:
        if not isinstance(r, dict):
            continue
        fora.append({
            "id": r.get("id_relatorio_gestao"),
            "data": r.get("data_relatorio_gestao"),
            "tipo": r.get("tipo_relatorio_gestao"),
            "situacao": r.get("situacao_relatorio_gestao"),
            "valor_executado": _f(r.get("valor_executado_relatorio_gestao")),
            "valor_pendente": _f(r.get("valor_pendente_relatorio_gestao")),
            "resultados": r.get("resultados_alcancados_metas_relatorio_gestao"),
        })
    # Mais recente primeiro: é o que responde "como está a prestação hoje".
    return sorted(fora, key=lambda r: (r["data"] or ""), reverse=True)


async def fetch_faf_planos(db: AsyncSession, municipio_id: int) -> dict:
    """Núcleo da consulta, SEM gate de auth — mesmo desenho de
    `fetch_parcerias` e `fetch_obras_federais`, para o Painel de Indicadores
    poder reusar a agregação sem duplicá-la."""
    # `detalhe->'_resumo'` e o que o coletor calculou da arvore do plano
    # (`ingestion/faf_planos.resumo_do_plano`): meta, situacao atual, ultimo
    # relatorio, saldo das contas do plano. So o resumo — a arvore inteira vai
    # pelo detalhe, um plano por vez.
    linhas = (await db.execute(text("""
        SELECT id_plano_acao, codigo_plano_acao, id_programa, situacao,
               data_inicio_vigencia, data_fim_vigencia, diagnostico, objetivos,
               valor_total, valor_repasse_emenda, valor_repasse_especifico,
               valor_repasse_voluntario, valor_recursos_proprios,
               valor_rendimentos, valor_custeio, valor_investimento,
               valor_saldo_disponivel, orgao_repassador,
               sigla_orgao_repassador, fundo_repassador, nome_ente_recebedor,
               cnpj_ente_recebedor, tipo_unidade_recebedora, relatorios_gestao,
               detalhe->'_resumo' AS resumo, detalhe IS NOT NULL AS detalhe_coletado,
               atualizado_em
          FROM faf_planos_acao
         WHERE municipio_id = :m
         ORDER BY data_fim_vigencia DESC NULLS LAST, valor_total DESC NULLS LAST
    """), {"m": municipio_id})).mappings().all()

    if not linhas:
        return {"tem_dados": False, "motivo": MOTIVO_SEM_COLETA}

    contas = await _contas_do_municipio(db, municipio_id)
    # plano -> as contas dele, com quantos planos dividem cada uma
    contas_do_plano: dict[str, list[dict]] = {}
    for c in contas:
        for pid in c["planos"]:
            contas_do_plano.setdefault(str(pid), []).append(
                {"id_agencia_conta": c["id_agencia_conta"], "n_planos": len(c["planos"])})

    itens: list[dict] = []
    # ⚠️ AGREGADOS EM PYTHON, e não num segundo GROUP BY: a tela precisa da
    # lista E dos resumos na mesma resposta, e somar de novo no banco o que já
    # está em memória seria trabalho pago duas vezes.
    por_origem = {k: 0.0 for k, _, _ in ORIGENS}
    por_orgao: dict[str, dict] = {}
    total = saldo = custeio = investimento = 0.0
    for p in linhas:
        vl = _f(p["valor_total"])
        total += vl or 0
        saldo += _f(p["valor_saldo_disponivel"]) or 0
        custeio += _f(p["valor_custeio"]) or 0
        investimento += _f(p["valor_investimento"]) or 0
        for chave, _, coluna in ORIGENS:
            por_origem[chave] += _f(p[coluna]) or 0

        # A sigla é o que cabe na linha; o nome inteiro fica no `title`. Quando
        # a fonte não dá sigla, o nome vira a própria chave — melhor um rótulo
        # longo do que um agrupamento "None" com planos de órgãos diferentes.
        sigla = p["sigla_orgao_repassador"] or p["orgao_repassador"] or "—"
        e = por_orgao.setdefault(sigla, {"sigla": sigla,
                                         "orgao": p["orgao_repassador"],
                                         "planos": 0, "valor": 0.0})
        e["planos"] += 1
        e["valor"] += vl or 0

        rels = _relatorios(p["relatorios_gestao"])
        itens.append({
            "id_plano_acao": p["id_plano_acao"],
            "codigo": p["codigo_plano_acao"],
            "id_programa": p["id_programa"],
            # `detalhe_coletado` falso = a arvore ainda nao foi colhida; o
            # resumo nulo nesse caso e "nao medido", nunca "nada aconteceu".
            "resumo": p["resumo"] if isinstance(p["resumo"], dict) else None,
            "detalhe_coletado": bool(p["detalhe_coletado"]),
            "contas": contas_do_plano.get(str(p["id_plano_acao"]), []),
            "situacao": p["situacao"],
            "inicio_vigencia": _d(p["data_inicio_vigencia"]),
            "fim_vigencia": _d(p["data_fim_vigencia"]),
            "diagnostico": p["diagnostico"],
            "objetivos": p["objetivos"],
            "valor_total": vl,
            "valor_emenda": _f(p["valor_repasse_emenda"]),
            "valor_especifico": _f(p["valor_repasse_especifico"]),
            "valor_voluntario": _f(p["valor_repasse_voluntario"]),
            "valor_proprios": _f(p["valor_recursos_proprios"]),
            "valor_rendimentos": _f(p["valor_rendimentos"]),
            "valor_custeio": _f(p["valor_custeio"]),
            "valor_investimento": _f(p["valor_investimento"]),
            "valor_saldo": _f(p["valor_saldo_disponivel"]),
            "orgao": p["orgao_repassador"],
            "sigla_orgao": p["sigla_orgao_repassador"],
            "fundo": p["fundo_repassador"],
            "ente_recebedor": p["nome_ente_recebedor"],
            "cnpj_recebedor": p["cnpj_ente_recebedor"],
            "tipo_unidade": p["tipo_unidade_recebedora"],
            "relatorios": rels,
            "url_fonte": URL_FONTE + str(p["id_plano_acao"]),
        })

    return {
        "tem_dados": True,
        "itens": itens,
        "total": len(itens),
        "valor_total": round(total, 2),
        "valor_saldo": round(saldo, 2),
        "valor_custeio": round(custeio, 2),
        "valor_investimento": round(investimento, 2),
        # ⭐ A DECOMPOSIÇÃO É O PRODUTO DESTA TELA. Origens zeradas saem da
        # lista: uma barra de R$ 0,00 não informa nada e empurra para baixo as
        # que informam.
        "por_origem": [{"chave": k, "rotulo": r, "valor": round(por_origem[k], 2)}
                       for k, r, _ in ORIGENS if por_origem[k] > 0],
        "por_orgao": sorted(por_orgao.values(), key=lambda e: -e["valor"]),
        "com_relatorio": sum(1 for i in itens if i["relatorios"]),
        "execucao": _execucao(contas, itens),
        "atualizado_em": max((p["atualizado_em"] for p in linhas
                              if p["atualizado_em"]), default=None),
    }


async def _contas_do_municipio(db: AsyncSession, municipio_id: int) -> list[dict]:
    """As contas do municipio (`faf_contas`), SEM o extrato — a listagem so
    precisa do saldo, do resumo e de quem usa cada conta.

    [] se a tabela ainda nao existe (a API sobe antes da migration): a tela
    segue inteira, so sem os numeros de execucao."""
    try:
        linhas = (await db.execute(text("""
            SELECT id_agencia_conta, saldo_final, planos, resumo, n_lancamentos,
                   ultimo_lancamento, situacao
              FROM faf_contas
             WHERE municipio_id = :m
        """), {"m": municipio_id})).mappings().all()
    except Exception:
        await db.rollback()
        return []
    return [{
        "id_agencia_conta": r["id_agencia_conta"],
        "saldo": _f(r["saldo_final"]),
        "planos": list(r["planos"] or []),
        "resumo": r["resumo"] if isinstance(r["resumo"], dict) else {},
        "n_lancamentos": r["n_lancamentos"],
        "ultimo_lancamento": _d(r["ultimo_lancamento"]),
        "situacao": r["situacao"],
    } for r in linhas]


def _execucao(contas: list[dict], itens: list[dict]) -> dict:
    """O que aconteceu com o dinheiro do municipio, somado POR CONTA.

    ⚠️ NUNCA POR PLANO. A mesma conta serve a varios planos (Goiania: cinco
    planos em 1126-8216), e o `_resumo` de cada plano traz a conta inteira —
    somar planos daria R$ 21,7 mi de saldo em Goiania, onde ha R$ 11,6 mi."""
    saldo = pago = devolvido = recebido = 0.0
    com_saldo = beneficiarios = divididas = 0
    for c in contas:
        if c["saldo"] is not None:
            saldo += c["saldo"]
            com_saldo += 1
        r = c["resumo"] or {}
        pago += r.get("pago_a_beneficiarios") or 0.0
        devolvido += r.get("devolvido_uniao") or 0.0
        recebido += r.get("recebido_ob") or 0.0
        beneficiarios += r.get("n_beneficiarios") or 0
        if len(c["planos"]) > 1:
            divididas += 1
    return {
        # quantos planos ja tem a arvore colhida — o denominador honesto
        "medidos": sum(1 for i in itens if i["detalhe_coletado"]),
        "n_contas": len(contas),
        "contas_com_saldo": com_saldo,
        "contas_divididas": divididas,
        "saldo_em_conta": round(saldo, 2),
        "recebido_ob": round(recebido, 2),
        "pago_a_beneficiarios": round(pago, 2),
        # soma por conta: a mesma pessoa paga por duas contas conta duas vezes
        "pagamentos_a_beneficiarios": beneficiarios,
        "devolvido_uniao": round(devolvido, 2),
    }


# Tipo do beneficiario -> qual das tres janelas do programa vale para ele.
_JANELA = {
    "ESPECIFICO": ("janela_especificos_ini", "janela_especificos_fim"),
    "EMENDA": ("janela_emendas_ini", "janela_emendas_fim"),
    "VOLUNTARIO": ("janela_voluntarios_ini", "janela_voluntarios_fim"),
}


def _janela_do_tipo(tipo) -> tuple[str, str] | None:
    t = str(tipo or "").upper()
    for chave, cols in _JANELA.items():
        if t.startswith(chave):
            return cols
    return None


async def fetch_faf_beneficiarios(db: AsyncSession, municipio_id: int,
                                  programas_com_plano: set[str],
                                  hoje: date | None = None) -> list[dict]:
    """Quanto cada programa DESTINA ao municipio (`/programas-beneficiarios`),
    TENHA PLANO DE ACAO OU NAO.

    ⭐ A PERGUNTA NOVA: "tem dinheiro reservado para nos que ainda nao pedimos?".
    `tem_plano` casa o programa com os planos coletados; `janela_aberta` diz se
    ainda da tempo de enviar o plano (a janela do programa, pelo tipo do
    beneficiario: especifico, emenda ou voluntario).

    [] se a tabela ainda nao existe (a API sobe antes da migration)."""
    hoje = hoje or date.today()
    try:
        linhas = (await db.execute(text("""
            SELECT b.id_programa, b.cnpj_beneficiario, b.nome_beneficiario,
                   b.tipo_beneficiario, b.valor, b.numero_emenda, b.parlamentar,
                   p.nome AS programa, p.ano, p.sigla_orgao, p.nome_orgao, p.situacao,
                   p.janela_especificos_ini, p.janela_especificos_fim,
                   p.janela_emendas_ini, p.janela_emendas_fim,
                   p.janela_voluntarios_ini, p.janela_voluntarios_fim
              FROM faf_programas_beneficiarios b
              LEFT JOIN faf_programas p ON p.id_programa = b.id_programa
             WHERE b.municipio_id = :m
             ORDER BY p.ano DESC NULLS LAST, b.valor DESC NULLS LAST
        """), {"m": municipio_id})).mappings().all()
    except Exception:
        await db.rollback()
        return []
    fora = []
    for r in linhas:
        cols = _janela_do_tipo(r["tipo_beneficiario"])
        ini = r[cols[0]] if cols else None
        fim = r[cols[1]] if cols else None
        fora.append({
            "id_programa": r["id_programa"],
            "programa": r["programa"],
            "ano": r["ano"],
            "sigla_orgao": r["sigla_orgao"],
            "orgao": r["nome_orgao"],
            "situacao_programa": r["situacao"],
            "beneficiario": r["nome_beneficiario"],
            "cnpj_beneficiario": r["cnpj_beneficiario"],
            "tipo": r["tipo_beneficiario"],
            "valor": _f(r["valor"]),
            "numero_emenda": r["numero_emenda"],
            "parlamentar": r["parlamentar"],
            "janela_ini": _d(ini),
            "janela_fim": _d(fim),
            "janela_aberta": bool(ini and fim and ini <= hoje <= fim),
            "tem_plano": r["id_programa"] is not None
            and str(r["id_programa"]) in programas_com_plano,
        })
    return fora


@router.get("", dependencies=[exige("faf_planos.ver")])
async def listar(
    municipio_id: int = Query(..., description="ID do municipio PACTHA"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Planos de ação Fundo a Fundo, com a decomposição do valor por origem."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "faf_planos")
    mun = (await db.execute(
        select(Municipio).where(Municipio.id == municipio_id))).scalar_one_or_none()
    if not mun:
        raise HTTPException(404, "Município não encontrado")
    dados = await fetch_faf_planos(db, municipio_id)
    dados["municipio"] = {"id": mun.id, "nome": mun.nome, "uf": mun.uf}
    # Os beneficiarios vem mesmo sem plano coletado: municipio sem plano nenhum
    # pode ter programa destinando dinheiro a ele — e esse e o caso que importa.
    com_plano = {str(i["id_programa"]) for i in dados.get("itens") or []
                 if i.get("id_programa") is not None}
    dados["beneficiarios"] = await fetch_faf_beneficiarios(db, municipio_id, com_plano)
    return dados


@router.get("/plano/{id_plano_acao}", dependencies=[exige("faf_planos.ver")])
async def detalhe_plano(
    id_plano_acao: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Um plano INTEIRO, do banco: o registro da fonte (`raw_data`), a arvore
    (`detalhe`: metas, historico, parecer, termo, relatorios com % fisico), as
    CONTAS que ele usa com o extrato e quem recebeu, e o programa.

    Nenhuma requisicao de saida: tudo foi colhido pelo coletor noturno. `detalhe`
    NULO significa "ainda nao colhido", nunca "o plano nao tem nada".

    ⚠️ O MUNICIPIO VEM DA LINHA. `id_plano_acao` e id federal; o que impede quem
    so ve um municipio de abrir plano de outro e a checagem sobre o
    `municipio_id` gravado. Mesmo desenho do detalhe de Parcerias.
    """
    ensure_tela(current, "faf_planos")
    row = (await db.execute(text(
        "SELECT municipio_id, raw_data, detalhe, detalhe_atualizado_em, atualizado_em, "
        "       id_programa "
        "  FROM faf_planos_acao WHERE id_plano_acao = :p "
        " ORDER BY atualizado_em DESC NULLS LAST LIMIT 1"
    ), {"p": str(id_plano_acao)})).first()
    if not row:
        raise HTTPException(404, "Plano de ação não encontrado nesta base")
    ensure_municipio_access(current, row[0])

    contas: list[dict] = []
    try:
        contas = [dict(c) for c in (await db.execute(text("""
            SELECT id_agencia_conta, codigo_banco, nome_banco, agencia, dv_agencia,
                   conta, dv_conta, situacao, data_abertura, programa_agil,
                   saldo_final, planos, cabecalho, lancamentos, resumo,
                   n_lancamentos, ultimo_lancamento, atualizado_em
              FROM faf_contas
             WHERE municipio_id = :m AND :p = ANY(planos)
             ORDER BY id_agencia_conta
        """), {"m": row[0], "p": str(id_plano_acao)})).mappings().all()]
    except Exception:
        await db.rollback()
    for c in contas:
        c["saldo_final"] = _f(c["saldo_final"])
        for k in ("data_abertura", "ultimo_lancamento", "atualizado_em"):
            c[k] = _d(c[k])
        c["planos"] = list(c["planos"] or [])

    programa = None
    fonte_em = None
    try:
        if row[5] is not None:
            p = (await db.execute(text(
                "SELECT raw_data, gestao_agil FROM faf_programas WHERE id_programa = :i"
            ), {"i": int(row[5])})).first()
            if p and isinstance(p[0], dict):
                programa = {**p[0], "gestao_agil": p[1] if isinstance(p[1], list) else []}
        fonte_em = (await db.execute(text(
            "SELECT data_fonte FROM fonte_atualizacao WHERE fonte = 'transferegov_fundoafundo'"
        ))).scalar_one_or_none()
    except Exception:
        await db.rollback()
    return {
        "plano": row[1] if isinstance(row[1], dict) else None,
        "detalhe": row[2] if isinstance(row[2], dict) else None,
        "contas": contas,
        "programa": programa,
        "detalhe_atualizado_em": _d(row[3]),
        "atualizado_em": _d(row[4]),
        "fonte_atualizada_em": _d(fonte_em),
        "url_fonte": URL_FONTE + str(id_plano_acao),
    }
