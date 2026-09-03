"""SICONFI / TESOURO NACIONAL — a terceira coluna da tela de regularidade.

Fica ao lado do CAUC (federal) e do cadastro estadual (CAGEC-MG / CHE-RS) pelo
mesmo motivo que eles ficam juntos: para o gestor o assunto e um so — "estou em
condicao de receber?". Por isso a chave e `cauc.ver` e a tela e `cauc`, sem
caixinha propria: conceder um terco da tela de regularidade nao e uma escolha
que o administrador queira fazer.

O QUE ISTO ACRESCENTA AO CAUC, que ja cobre as mesmas obrigacoes:

  * O CAUC diz REGULAR ou IRREGULAR nas obrigacoes 3.1.2 (RGF ao Siconfi),
    3.2.2 (RREO ao Siconfi) e 3.3 (contas anuais). Ele nao diz **o que** nem
    **quando**. O extrato de entregas diz: entregavel, periodo, data e forma.
  * A **CAPAG** nao existe no CAUC. E a nota de A+ a D que define se o
    municipio pode contrair operacao de credito com garantia da Uniao — porta
    de captacao que o gestor pode nem saber que tem (ou que perdeu).

⚠️ `tem_dados: false` NAO E "esta tudo bem". E "ainda nao coletamos" — o mesmo
cuidado que `cadastros_negativos.em: null` tem no `/api/cagec`. A tela precisa
distinguir ausencia de coleta de ausencia de pendencia, senao pinta de verde um
municipio sobre o qual nao sabe nada.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/siconfi", tags=["siconfi"])

# O que cada nota da CAPAG significa na pratica. Sai daqui e nao da tela porque
# a frase e a consequencia FINANCEIRA da nota (Portaria MF 501/2021), nao um
# rotulo estetico — e porque o RM e a IA precisam da mesma frase.
CAPAG_SIGNIFICADO = {
    "A": "apta a contratar operação de crédito com garantia da União",
    "A+": "apta a contratar operação de crédito com garantia da União",
    "B": "apta a contratar operação de crédito com garantia da União",
    "B+": "apta a contratar operação de crédito com garantia da União",
    "C": "NÃO apta a contratar operação de crédito com garantia da União",
    "D": "NÃO apta a contratar operação de crédito com garantia da União",
}

# Os tres indicadores, na ordem em que o Tesouro os numera.
INDICADORES = (
    ("endividamento", "Endividamento", "dívida consolidada sobre a receita corrente líquida"),
    ("poupanca", "Poupança corrente", "despesa corrente sobre a receita corrente ajustada"),
    ("liquidez", "Liquidez", "obrigações financeiras sobre a disponibilidade de caixa"),
)


async def fetch_siconfi(db: AsyncSession, municipio_id: int) -> dict:
    """Nucleo da consulta, SEM gate — reusavel pelo Painel de Indicadores como
    `fetch_cauc_situacao` e `fetch_cagec_situacao` ja sao."""
    capag = (await db.execute(text("""
        SELECT exercicio, posicao, nota,
               ind_endividamento, nota_endividamento,
               ind_poupanca, nota_poupanca,
               ind_liquidez, nota_liquidez, icf, observacao, atualizado_em
          FROM siconfi_capag WHERE municipio_id = :m
         ORDER BY exercicio DESC, posicao DESC NULLS LAST
         LIMIT 1
    """), {"m": municipio_id})).first()

    entregas = (await db.execute(text("""
        SELECT exercicio, entregavel, periodo, periodicidade,
               status_relatorio, data_status, forma_envio, atualizado_em
          FROM siconfi_entregas WHERE municipio_id = :m
         ORDER BY exercicio DESC, entregavel, periodo
    """), {"m": municipio_id})).fetchall()

    if not capag and not entregas:
        return {
            "tem_dados": False,
            # ⚠️ Frase de NAO COLETADO, nunca de "nada consta".
            "motivo": ("As contas deste município no Tesouro Nacional ainda não "
                       "foram consultadas. A coleta é diária e automática; se "
                       "esta mensagem persistir, a fonte pode estar indisponível."),
        }

    # Uma linha por exercicio, com os entregaveis agrupados — e como a tela
    # mostra e como o gestor pensa ("o que falta de 2026?").
    por_ano: dict[int, list[dict]] = {}
    for e in entregas:
        por_ano.setdefault(e[0], []).append({
            "entregavel": e[1],
            "periodo": e[2],
            "periodicidade": e[3],
            # ⚠️ 'HO' (homologado) so aparece em RREO/RGF/DCA. A MSC vem sem
            # status e ESTA entregue: quem prova a entrega e a data.
            "status": e[4],
            "entregue_em": e[5].isoformat() if e[5] else None,
            "forma_envio": e[6],
        })

    exercicios = [{
        "exercicio": ano,
        "entregas": itens,
        "total": len(itens),
        # Quantos entregaveis DISTINTOS o ente movimentou naquele ano. E o
        # numero que responde "ele esta prestando contas?" sem exigir que a
        # tela conheca o calendario de cada obrigacao.
        "entregaveis": sorted({i["entregavel"] for i in itens}),
    } for ano, itens in sorted(por_ano.items(), reverse=True)]

    out = {
        "tem_dados": True,
        "exercicios": exercicios,
        "ultima_entrega": max(
            (i["entregue_em"] for a in exercicios for i in a["entregas"]
             if i["entregue_em"]), default=None),
        "capag": None,
    }
    if capag:
        nota = (capag[2] or "").strip()
        out["capag"] = {
            "exercicio": capag[0],
            "posicao": capag[1].isoformat() if isinstance(capag[1], date) else None,
            "nota": nota or None,
            # ⚠️ Sem entrada no mapa o significado e `None`, e a tela mostra so a
            # nota. Inventar a consequencia de uma nota que o Tesouro criou
            # depois desta versao seria pior que omiti-la.
            "significado": CAPAG_SIGNIFICADO.get(nota.upper()),
            "indicadores": [
                {"chave": "endividamento", "titulo": "Endividamento",
                 "descricao": "dívida consolidada sobre a receita corrente líquida",
                 "valor": float(capag[3]) if capag[3] is not None else None,
                 "nota": capag[4]},
                {"chave": "poupanca", "titulo": "Poupança corrente",
                 "descricao": "despesa corrente sobre a receita corrente ajustada",
                 "valor": float(capag[5]) if capag[5] is not None else None,
                 "nota": capag[6]},
                {"chave": "liquidez", "titulo": "Liquidez",
                 "descricao": "obrigações financeiras sobre a disponibilidade de caixa",
                 "valor": float(capag[7]) if capag[7] is not None else None,
                 "nota": capag[8]},
            ],
            "icf": capag[9],
            "observacao": capag[10],
            "atualizado_em": capag[11].isoformat() if capag[11] else None,
        }
    return out


@router.get("", dependencies=[exige("cauc.ver")])
async def situacao(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Contas entregues ao Tesouro Nacional e nota CAPAG do município.

    Mesma tela do CAUC (`cauc`) e mesma chave: as três colunas da regularidade
    (federal, estadual e Tesouro) respondem a uma pergunta só."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "cauc")
    return await fetch_siconfi(db, municipio_id)
