"""Gestão de Parcerias — a emenda de saúde do município, por parlamentar.

Le a tabela `parcerias_propostas`, alimentada por `ingestion/parcerias.py` a
partir de `api-publica.transferegov.gestao.gov.br/parcerias`. O modulo processa
as transferencias de 2024 em diante — 144 dos 176 programas publicados sao
Fundo a Fundo da Saude —, e ate 07/09/2026 era o unico instrumento federal que a
plataforma nao enxergava.

⭐ A LEITURA QUE ESTA TELA EXISTE PARA DAR e a de PARLAMENTAR: quanto cada um
destinou ao municipio, em quantas propostas, e em que pe cada uma esta. Medido
no tenant trust: Comissao da Saude com 84 propostas e R$ 67,7 milhoes; Bancada
de Goias com R$ 69 mi. Nenhum desses numeros existia no produto.

⚠️ NAO CONFUNDIR COM A TELA DE VOLUNTARIAS. Aquela mostra os convenios
discricionarios do SICONV, que continuam vindo dos dumps CSV. Esta e outro
modulo, com outro ciclo (proposta -> parceria) e outro tipo de instrumento. As
duas coexistem de proposito.
"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Municipio
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/parcerias", tags=["parcerias"])

# A fonte publica o instrumento; o link deixa qualquer numero desta tela
# conferivel por quem duvidar dele.
URL_FONTE = ("https://api-publica.transferegov.gestao.gov.br/parcerias/"
             "proposta?id_proposta=")

MOTIVO_SEM_COLETA = (
    "A coleta da Gestão de Parcerias ainda não rodou para este município. "
    "Ela é diária e cobre as transferências de 2024 em diante."
)


# ⚠️ O QUE CONTA COMO "DO MUNICIPIO", e por que a pergunta precisou ser feita.
#
# `cd_ibge_recebedor` filtra pelo municipio do RECEBEDOR — e recebedor nao e so a
# prefeitura. Medido em 07/09/2026: Goiania tem 172 propostas, das quais 15 sao do
# FUNDO ESTADUAL DE SAUDE (que atende Goias inteiro) e outras tantas de associacao
# privada, cooperativa e sociedade empresaria. No tenant trust isso e 20 propostas
# estaduais (R$ 31,1 mi) e 54 privadas (R$ 55,6 mi) dentro de 706 — 13,6% do valor.
#
# ⚠️ E O ESTRAGO MAIOR ERA NO RANKING. A tela responde "quem trouxe recurso para a
# cidade", e somar o Fundo ESTADUAL de Saude ao nome de um parlamentar afirma algo
# que a fonte nao afirma: aquele dinheiro e do estado, aplicado no estado inteiro.
#
# A fonte diz a esfera em `nm_natureza_juridica`, com vocabulario fechado (amostra
# de 1.000 propostas nacionais, 07/09/2026):
#
#     719  Fundo Publico da Administracao Direta Municipal      <- municipal
#      20  Municipio                                            <- municipal
#     152  Associacao Privada          46 Sociedade Empresaria Limitada
#      18  Cooperativa                 16 Fundacao Privada
#      18  Fundo Publico da Adm. Direta Estadual ou do DF        <- outra esfera
#       5  Consorcio Publico            4 Empresario (Individual)
#
# ⭐ NADA E DESCARTADO, ao contrario do que `faf_planos` faz. La o plano do estado
# nao tem vinculo municipal nenhum (o IBGE e a SEDE do ente). Aqui tem: a Santa
# Casa que recebeu emenda federal ESTA na cidade, e o gestor quer saber. O que nao
# pode e entrar na conta como se fosse dinheiro da prefeitura. Entao fica, marcado,
# e fora dos totais.
#
# A regra mora em `services/natureza.py` desde 15/09/2026: as Voluntarias
# (dumps de Discricionarias) tem o mesmo problema, com outro vocabulario, e uma
# regra por fonte divergiria.
from services.natureza import e_municipal as _municipal  # noqa: E402


def _f(v) -> Optional[float]:
    """`None` continua `None`. ⚠️ Proposta sem valor declarado não é proposta de
    R$ 0,00 — zero na tela seria uma afirmação que a fonte não faz."""
    return float(v) if v is not None else None


def _d(v) -> Optional[str]:
    return v.isoformat() if v is not None else None


async def fetch_parcerias(db: AsyncSession, municipio_id: int) -> dict:
    """Nucleo da consulta, SEM gate de auth — mesmo desenho de
    `fetch_obras_federais`, para o Painel de Indicadores poder reusar depois sem
    duplicar a agregacao."""
    # `detalhe->'_resumo'` e o que o coletor calculou da arvore da proposta
    # (ingestion/parcerias.execucao_da_arvore): pago pela OB, saldo, nao
    # classificado. SO o resumo — a arvore inteira (~8 KB por proposta) fica para
    # o detalhe, que busca uma proposta por vez.
    linhas = (await db.execute(text("""
        SELECT id_proposta, objeto, situacao, valor_total, ano_proposta,
               data_proposta, nome_ente_recebedor, cnpj_ente_recebedor,
               natureza_juridica, id_parceria, codigo_parceria,
               situacao_parceria, data_assinatura, numero_emenda, parlamentar,
               tipo_emenda, valor_emenda, resultado_esperado, atualizado_em,
               detalhe->'_resumo' AS resumo, detalhe IS NOT NULL AS detalhe_coletado,
               nu_externo
          FROM parcerias_propostas
         WHERE municipio_id = :m
         ORDER BY ano_proposta DESC NULLS LAST, valor_total DESC NULLS LAST
    """), {"m": municipio_id})).mappings().all()

    if not linhas:
        return {"tem_dados": False, "motivo": MOTIVO_SEM_COLETA}
    # ⭐ A EXECUCAO, somada so na administracao municipal (a mesma regra dos
    # totais). "Medidas" conta quantas propostas ja tem a arvore colhida: sem
    # isso, R$ 0 pago numa carteira que o coletor ainda nao percorreu seria lido
    # como "nada foi pago".
    ex_pago = ex_saldo = ex_nao_class = 0.0
    ex_medidas = ex_com_saldo = ex_pendentes = 0

    itens = []
    # ⚠️ AGREGADOS EM PYTHON, e não em SQL com GROUP BY: a tela precisa da lista
    # E dos dois resumos na mesma resposta, e uma segunda consulta ao banco para
    # somar o que já está em memória seria trabalho pago duas vezes.
    por_parlamentar: dict[str, dict] = {}
    por_situacao: dict[str, int] = {}
    total = total_emenda = 0.0
    fora_qtd = 0
    fora_valor = 0.0
    # ⚠️ QUANTAS, e não quanto: ver o comentário de `com_emenda` na resposta.
    com_emenda = 0
    for p in linhas:
        valor = _f(p["valor_total"])
        vl_emenda = _f(p["valor_emenda"])
        resumo = p["resumo"] if isinstance(p["resumo"], dict) else None
        # ⚠️ SÓ A ADMINISTRAÇÃO MUNICIPAL ENTRA NA CONTA. Ver `_municipal`: o
        # Fundo ESTADUAL de Saúde e a associação privada aparecem na lista, mas
        # somá-los diria que a prefeitura recebeu o que ela não recebeu.
        municipal = _municipal(p["natureza_juridica"])
        if municipal:
            total += valor or 0
            total_emenda += vl_emenda or 0
        else:
            fora_qtd += 1
            fora_valor += valor or 0
        itens.append({
            "municipal": municipal,
            "id_proposta": p["id_proposta"],
            "objeto": p["objeto"],
            "situacao": p["situacao"],
            "valor": valor,
            "ano": p["ano_proposta"],
            "data_proposta": _d(p["data_proposta"]),
            "ente_recebedor": p["nome_ente_recebedor"],
            "cnpj_recebedor": p["cnpj_ente_recebedor"],
            "natureza_juridica": p["natureza_juridica"],
            # Nulo enquanto a proposta não virou instrumento — estado legítimo e
            # frequente, e a tela mostra "não celebrada" em vez de esconder.
            "id_parceria": p["id_parceria"],
            "codigo_parceria": p["codigo_parceria"],
            "situacao_parceria": p["situacao_parceria"],
            "data_assinatura": _d(p["data_assinatura"]),
            "numero_emenda": p["numero_emenda"],
            "parlamentar": p["parlamentar"],
            "tipo_emenda": p["tipo_emenda"],
            "valor_emenda": vl_emenda,
            "resultado_esperado": p["resultado_esperado"],
            "url_fonte": URL_FONTE + str(p["id_proposta"]),
            # Numero da proposta no sistema de ORIGEM (para a saude, o FNS).
            "nu_externo": p["nu_externo"],
            # ⭐ DA ARVORE DA PROPOSTA (15/09/2026). `resumo` nulo com
            # `detalhe_coletado` falso = o coletor ainda nao passou; nulo com
            # `detalhe_coletado` verdadeiro = proposta sem parceria celebrada
            # (nao ha execucao). Nunca "zero".
            "detalhe_coletado": bool(p["detalhe_coletado"]),
            "resumo": resumo,
        })
        if municipal and p["detalhe_coletado"]:
            ex_medidas += 1
            if resumo:
                ex_pago += float(resumo.get("pago") or 0)
                if resumo.get("saldo_total") is not None:
                    ex_com_saldo += 1
                    ex_saldo += float(resumo.get("saldo_total") or 0)
                nc = float(resumo.get("nao_classificado") or 0)
                ex_nao_class += nc
                if nc > 0:
                    ex_pendentes += 1
        if p["parlamentar"] and municipal:
            e = por_parlamentar.setdefault(
                p["parlamentar"], {"parlamentar": p["parlamentar"],
                                   "propostas": 0, "valor": 0.0,
                                   "tipo": p["tipo_emenda"]})
            e["propostas"] += 1
            e["valor"] += vl_emenda or 0
        if municipal and p["numero_emenda"]:
            com_emenda += 1
        sit = p["situacao"] or "Sem situação"
        por_situacao[sit] = por_situacao.get(sit, 0) + 1

    return {
        "tem_dados": True,
        "itens": itens,
        # ⚠️ `total` conta a ADMINISTRAÇÃO MUNICIPAL, e `itens` traz TODAS as
        # linhas — a diferença é `fora_do_municipio`, logo abaixo. Contar tudo
        # aqui poria o Fundo Estadual de Saúde no cartão «Propostas» da
        # prefeitura; esconder as linhas faria a lista não bater com o portal.
        "total": len(itens) - fora_qtd,
        "total_listado": len(itens),
        "valor_total": round(total, 2),
        "valor_emenda": round(total_emenda, 2),
        # ⚠️ QUANTAS PROPOSTAS TÊM EMENDA, e é isto que a tela mostra no lugar de
        # repetir `valor_emenda` num cartão.
        #
        # Nesta fonte o valor da proposta É o valor da emenda em quase toda
        # linha — medido em 07/09/2026: 538 de 547 no freitas, 691 de 706 no
        # trust, 14 de 14 em Monte Sião. Dois cartões lado a lado com o MESMO
        # número não informam nada e fazem quem lê desconfiar de erro (o dono
        # desconfiou, olhando Nova Palma, onde os dois davam R$ 2.184.085,00).
        #
        # ⭐ A contagem informa onde o valor repetido não informava: em Nova
        # Palma é "11 de 11" — toda proposta com parlamentar nomeado —, e no
        # freitas é "510 de 547", que aponta as 37 sem emenda identificada.
        "com_emenda": com_emenda,
        # ⭐ O RANKING É O PRODUTO DESTA TELA. Ordenado por valor, que é a
        # pergunta que o gestor faz — "quem trouxe mais para a cidade".
        "por_parlamentar": sorted(por_parlamentar.values(),
                                  key=lambda e: -e["valor"]),
        "por_situacao": sorted(
            [{"situacao": k, "qtd": v} for k, v in por_situacao.items()],
            key=lambda e: -e["qtd"]),
        # ⭐ O QUE FICOU FORA DA CONTA, dito em vez de escondido: a tela mostra
        # a linha e avisa por que ela não soma. Silêncio aqui viraria "faltam
        # propostas" para quem conferir contra o portal.
        "fora_do_municipio": {"qtd": fora_qtd, "valor": round(fora_valor, 2)},
        "atualizado_em": max((p["atualizado_em"] for p in linhas
                              if p["atualizado_em"]), default=None),
        # ⭐ O QUE ACONTECEU COM O DINHEIRO (15/09/2026), so da administracao
        # municipal. `medidas` de `total` diz quanto da carteira ja tem a arvore.
        "execucao": {
            "medidas": ex_medidas,
            "pago": round(ex_pago, 2),
            "saldo": round(ex_saldo, 2),
            "com_saldo": ex_com_saldo,
            "nao_classificado": round(ex_nao_class, 2),
            # Propostas com ingresso ainda nao classificado — pendencia do municipio.
            "com_nao_classificado": ex_pendentes,
        },
    }


async def fetch_emendas_indicadas(db: AsyncSession, municipio_id: int,
                                  emendas_com_proposta: set[str]) -> list[dict]:
    """Emendas que o parlamentar ja indicou ao municipio (`/beneficiario_emenda_
    parlamentar`), EXISTA PROPOSTA OU NAO.

    ⭐ A PERGUNTA NOVA: "tem dinheiro indicado para nos que ainda nao virou
    proposta?". `tem_proposta` casa o numero da emenda (mesmo formato nas duas
    rotas, "2026.2023.0002") com o das propostas coletadas.

    [] se a tabela ainda nao existe (a API sobe antes da migration): a tela segue
    inteira, so sem o bloco."""
    try:
        linhas = (await db.execute(text("""
            SELECT numero_emenda, ano_emenda, parlamentar, tipo_emenda,
                   valor_gnd3, valor_gnd4, valor_total, nome_beneficiario,
                   cnpj_beneficiario, natureza_juridica, indicacoes, id_programa
              FROM parcerias_emendas_indicadas
             WHERE municipio_id = :m
             ORDER BY ano_emenda DESC NULLS LAST, valor_total DESC NULLS LAST
        """), {"m": municipio_id})).mappings().all()
    except Exception:
        await db.rollback()
        return []
    return [{
        "numero_emenda": r["numero_emenda"],
        "ano": r["ano_emenda"],
        "parlamentar": r["parlamentar"],
        "tipo": r["tipo_emenda"],
        "valor_gnd3": _f(r["valor_gnd3"]),
        "valor_gnd4": _f(r["valor_gnd4"]),
        "valor_total": _f(r["valor_total"]),
        "beneficiario": r["nome_beneficiario"],
        "cnpj_beneficiario": r["cnpj_beneficiario"],
        "natureza_juridica": r["natureza_juridica"],
        "municipal": _municipal(r["natureza_juridica"]),
        "id_programa": r["id_programa"],
        "indicacoes": r["indicacoes"] if isinstance(r["indicacoes"], list) else [],
        "tem_proposta": bool(r["numero_emenda"]) and r["numero_emenda"] in emendas_com_proposta,
    } for r in linhas]


@router.get("", dependencies=[exige("parcerias.ver")])
async def listar(
    municipio_id: int = Query(..., description="ID do municipio PACTHA"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Propostas do módulo de Gestão de Parcerias, com o ranking por parlamentar."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "parcerias")
    mun = (await db.execute(
        select(Municipio).where(Municipio.id == municipio_id))).scalar_one_or_none()
    if not mun:
        raise HTTPException(404, "Município não encontrado")
    dados = await fetch_parcerias(db, municipio_id)
    dados["municipio"] = {"id": mun.id, "nome": mun.nome, "uf": mun.uf}
    com_proposta = {i["numero_emenda"] for i in dados.get("itens") or [] if i.get("numero_emenda")}
    dados["emendas_indicadas"] = await fetch_emendas_indicadas(db, municipio_id, com_proposta)
    return dados


@router.get("/proposta/{id_proposta}", dependencies=[exige("parcerias.ver")])
async def detalhe_proposta(
    id_proposta: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Uma proposta INTEIRA, do banco: o registro da fonte (`raw_data`, com a
    parceria e a emenda) e a arvore da proposta (`detalhe`) — plano de trabalho,
    parecer, indicadores, conta, extrato, OPP, empenhos e DH -> OP/OB.

    Nenhuma requisicao de saida: tudo foi colhido pelo coletor noturno. `detalhe`
    NULO significa "ainda nao colhido", nunca "a proposta nao tem nada".

    ⚠️ O MUNICIPIO VEM DA LINHA. `id_proposta` e id federal; o que impede quem so
    ve Araujos de abrir proposta de Nova Serrana e a checagem sobre o
    `municipio_id` gravado. Mesmo desenho do detalhe da Transferencia Especial.
    """
    ensure_tela(current, "parcerias")
    row = (await db.execute(text(
        "SELECT municipio_id, raw_data, detalhe, detalhe_atualizado_em, atualizado_em "
        "  FROM parcerias_propostas WHERE id_proposta = :p "
        " ORDER BY atualizado_em DESC NULLS LAST LIMIT 1"
    ), {"p": id_proposta})).first()
    if not row:
        raise HTTPException(404, "Proposta não encontrada nesta base")
    ensure_municipio_access(current, row[0])
    fonte_em = None
    try:
        fonte_em = (await db.execute(text(
            "SELECT data_fonte FROM fonte_atualizacao WHERE fonte = 'transferegov_parcerias'"
        ))).scalar_one_or_none()
    except Exception:
        await db.rollback()
    return {
        "proposta": row[1] if isinstance(row[1], dict) else None,
        "detalhe": row[2] if isinstance(row[2], dict) else None,
        "detalhe_atualizado_em": _d(row[3]),
        "atualizado_em": _d(row[4]),
        "fonte_atualizada_em": _d(fonte_em),
        "url_fonte": URL_FONTE + str(id_proposta),
    }
