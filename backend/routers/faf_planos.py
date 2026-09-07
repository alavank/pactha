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
    linhas = (await db.execute(text("""
        SELECT id_plano_acao, codigo_plano_acao, situacao,
               data_inicio_vigencia, data_fim_vigencia, diagnostico, objetivos,
               valor_total, valor_repasse_emenda, valor_repasse_especifico,
               valor_repasse_voluntario, valor_recursos_proprios,
               valor_rendimentos, valor_custeio, valor_investimento,
               valor_saldo_disponivel, orgao_repassador,
               sigla_orgao_repassador, fundo_repassador, nome_ente_recebedor,
               cnpj_ente_recebedor, tipo_unidade_recebedora, relatorios_gestao,
               atualizado_em
          FROM faf_planos_acao
         WHERE municipio_id = :m
         ORDER BY data_fim_vigencia DESC NULLS LAST, valor_total DESC NULLS LAST
    """), {"m": municipio_id})).mappings().all()

    if not linhas:
        return {"tem_dados": False, "motivo": MOTIVO_SEM_COLETA}

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
        "atualizado_em": max((p["atualizado_em"] for p in linhas
                              if p["atualizado_em"]), default=None),
    }


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
    return dados
