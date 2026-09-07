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
_MUNICIPAIS = ("fundo publico da administracao direta municipal", "municipio")


def _municipal(natureza: Optional[str]) -> bool:
    """A proposta e da ADMINISTRACAO MUNICIPAL?

    ⚠️ AUSENCIA CONTA COMO MUNICIPAL. Se a fonte parar de mandar a natureza, a
    alternativa seria zerar os cartoes da tela em silencio — pior que uma
    proposta a mais na conta. E `fora_do_municipio` na resposta deixa a mudanca
    visivel em vez de escondida.
    """
    if not natureza:
        return True
    t = (natureza.lower()
         .replace("ç", "c").replace("ã", "a").replace("õ", "o")
         .replace("é", "e").replace("ú", "u").replace("í", "i")
         .replace("á", "a").replace("ó", "o").replace("ê", "e").strip())
    return any(t.startswith(m) for m in _MUNICIPAIS)


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
    linhas = (await db.execute(text("""
        SELECT id_proposta, objeto, situacao, valor_total, ano_proposta,
               data_proposta, nome_ente_recebedor, cnpj_ente_recebedor,
               natureza_juridica, id_parceria, codigo_parceria,
               situacao_parceria, data_assinatura, numero_emenda, parlamentar,
               tipo_emenda, valor_emenda, resultado_esperado, atualizado_em
          FROM parcerias_propostas
         WHERE municipio_id = :m
         ORDER BY ano_proposta DESC NULLS LAST, valor_total DESC NULLS LAST
    """), {"m": municipio_id})).mappings().all()

    if not linhas:
        return {"tem_dados": False, "motivo": MOTIVO_SEM_COLETA}

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
        })
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
    }


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
    return dados
