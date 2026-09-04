"""Obras.gov.br / CIPI — as obras federais do municipio, de todas as areas.

Coleta em `ingestion/obrasgov.py` (API publica, sem login). Aqui e so leitura.

⚠️ O QUE ESTA TELA MOSTRA QUE NENHUMA OUTRA MOSTRAVA. O SISMOB cobre saude e o
SIMEC cobre educacao; o resto — mobilidade, saneamento, habitacao, seguranca e a
**reconstrucao da Defesa Civil** — nao aparecia em lugar nenhum. Em Nova Palma
sao 21 das 30 obras.

⚠️ E ELA REPETE, DE PROPOSITO, OBRA QUE OUTRA TELA JA MOSTRA. O CIPI reune obras
que o SISMOB tambem publica: das 360 obras de Freitas, 45 vem marcadas
`sistema_origem = SISMOB`. Isso e decisao do dono ("mesmo que as obras do SISMOB
estejam tambem no obrasgov geral, nao tem problema") — esta e a visao GERAL, e
esconder metade dela para evitar repeticao daria um numero que nao bate com o
Obras.gov.br. O campo `sistema_origem` vai junto em cada obra para a tela poder
dizer de onde veio, em vez de fingir que a repeticao nao existe.

⚠️ `municipio_id` E INFERENCIA NOSSA, nao campo da fonte: a API nao tem filtro
territorial e o vinculo e feito por CNPJ de tomador/executor. Ver o cabecalho de
`ingestion/obrasgov.py`.

A classificacao **acao / andamento / encerradas** e feita AQUI, e nao no cliente
— mesmo motivo do `routers/sismob.py`: tela, TV, celular e PDF precisam
concordar sobre o que e urgente.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/obrasgov", tags=["obrasgov"])

MOTIVO_SEM_COLETA = (
    "As obras federais deste município ainda não foram coletadas. A coleta é "
    "automática, roda de madrugada e reconhece o município pelo CNPJ — não "
    "depende de senha."
)

# ⚠️ SITUACAO E TEXTO DA FONTE, e a fonte usa exatamente estes seis (medidos
# sobre 32.300 obras de RS/MG/GO/ES/TO). Nao normalizar para um enum nosso: se o
# Governo criar um setimo, ele tem de aparecer na tela como veio, e nao virar
# "Outros" em silencio.
ENCERRADAS = ("Concluída", "Cancelada")
PARADAS = ("Paralisada", "Inacabada")


def _f(v) -> Optional[float]:
    return float(v) if v is not None else None


def _d(v) -> Optional[str]:
    return v.isoformat() if v is not None else None


def _classificar(o: dict, hoje: date) -> dict:
    """Por que esta obra merece atenção — ou por que não merece.

    ⚠️ ATRASO SE MEDE COM `data_final_prevista` CONTRA `data_final_efetiva`
    NULA. Nulo na efetiva é "ainda não aconteceu", e é justamente esse par que
    denuncia obra parada; comparar com a data de cadastro ou preencher a efetiva
    com a prevista apagaria o único sinal que a fonte dá."""
    situacao = (o.get("situacao") or "").strip()
    fim_prev = o.get("data_final_prevista")
    fim_efe = o.get("data_final_efetiva")
    ini_prev = o.get("data_inicial_prevista")
    ini_efe = o.get("data_inicial_efetiva")

    if situacao in PARADAS:
        return {"grupo": "acao", "alerta": situacao.lower(),
                "motivo": f"A fonte marca esta obra como {situacao.lower()}."}
    if situacao in ENCERRADAS:
        return {"grupo": "encerradas", "alerta": None, "motivo": None}

    if fim_prev and not fim_efe and fim_prev < hoje:
        dias = (hoje - fim_prev).days
        return {"grupo": "acao", "alerta": "prazo_vencido",
                "motivo": (f"O prazo previsto de conclusão venceu há {dias} dia(s) "
                           f"({fim_prev.strftime('%d/%m/%Y')}) e a fonte não "
                           "registrou conclusão.")}
    if ini_prev and not ini_efe and ini_prev < hoje:
        dias = (hoje - ini_prev).days
        return {"grupo": "acao", "alerta": "nao_comecou",
                "motivo": (f"O início estava previsto para "
                           f"{ini_prev.strftime('%d/%m/%Y')} (há {dias} dia(s)) e "
                           "a fonte não registrou início.")}
    return {"grupo": "andamento", "alerta": None, "motivo": None}


_CAMPOS = """
    id_unico, nome, descricao, funcao_social, meta_global,
    natureza, especie, situacao, uf, cep, endereco,
    data_inicial_prevista, data_final_prevista,
    data_inicial_efetiva, data_final_efetiva, data_cadastro,
    populacao_beneficiada, empregos_gerados, valor_investimento_previsto,
    origens_recurso, eixos, tipos, tomadores, executores, repassadores,
    sistema_origem, atualizado_em
"""


async def fetch_obras_federais(db: AsyncSession, municipio_id: int) -> dict:
    """Nucleo da consulta, SEM gate de auth — mesmo desenho de
    `fetch_sismob_obras`, para o Painel de Indicadores poder reusar depois sem
    duplicar a classificacao."""
    linhas = (await db.execute(text(f"""
        SELECT {_CAMPOS} FROM obrasgov_projetos
        WHERE municipio_id = :m
        ORDER BY valor_investimento_previsto DESC NULLS LAST
    """), {"m": municipio_id})).mappings().all()

    if not linhas:
        return {"tem_dados": False, "motivo": MOTIVO_SEM_COLETA}

    hoje = date.today()
    acao, andamento, encerradas = [], [], []
    tot = {"obras": 0, "valor": 0.0, "valor_acao": 0.0,
           "empregos": 0, "populacao": 0}
    por_situacao: dict[str, dict] = {}
    por_eixo: dict[str, dict] = {}
    por_sistema: dict[str, dict] = {}
    por_origem: dict[str, dict] = {}
    anos: set[int] = set()

    for r in linhas:
        o = dict(r)
        valor = _f(o["valor_investimento_previsto"]) or 0.0
        diag = _classificar(o, hoje)

        # ⚠️ O ANO VAI NO ITEM, e não é calculado de novo na tela. O filtro de
        # ano e a lista `anos` que o alimenta TÊM de sair do mesmo critério —
        # senão o filtro oferece um ano que não seleciona nada, e a tela abre
        # vazia sem nenhum erro para investigar.
        ref = o["data_inicial_prevista"] or o["data_cadastro"]
        ano = ref.year if ref else None

        item = {
            "id_unico": o["id_unico"],
            "nome": o["nome"], "descricao": o["descricao"],
            "funcao_social": o["funcao_social"], "meta_global": o["meta_global"],
            "natureza": o["natureza"], "especie": o["especie"],
            "situacao": o["situacao"], "endereco": o["endereco"], "cep": o["cep"],
            "data_inicial_prevista": _d(o["data_inicial_prevista"]),
            "data_final_prevista": _d(o["data_final_prevista"]),
            "data_inicial_efetiva": _d(o["data_inicial_efetiva"]),
            "data_final_efetiva": _d(o["data_final_efetiva"]),
            "data_cadastro": _d(o["data_cadastro"]),
            "populacao_beneficiada": o["populacao_beneficiada"],
            "empregos_gerados": o["empregos_gerados"],
            # ⚠️ `None` e nao 0: obra sem valor declarado nao e obra de graca.
            # Zero na tela seria uma afirmacao que a fonte nao faz.
            "valor": _f(o["valor_investimento_previsto"]),
            "origens_recurso": list(o["origens_recurso"] or []),
            "eixos": list(o["eixos"] or []),
            "tipos": list(o["tipos"] or []),
            "tomadores": list(o["tomadores"] or []),
            "executores": list(o["executores"] or []),
            "repassadores": list(o["repassadores"] or []),
            "sistema_origem": o["sistema_origem"],
            "ano": ano,
            # O link que deixa qualquer numero desta tela conferivel na fonte.
            "url_fonte": ("https://api-publica.obrasgov.gestao.gov.br/obras/"
                          "projeto-investimento?id_projeto_investimento="
                          + str(o["id_unico"] or "")),
            **diag,
        }
        {"acao": acao, "andamento": andamento,
         "encerradas": encerradas}[diag["grupo"]].append(item)

        tot["obras"] += 1
        tot["valor"] += valor
        if diag["grupo"] == "acao":
            tot["valor_acao"] += valor
        tot["empregos"] += o["empregos_gerados"] or 0
        tot["populacao"] += o["populacao_beneficiada"] or 0

        def soma(mapa: dict, chave: str) -> None:
            e = mapa.setdefault(chave, {"nome": chave, "obras": 0, "valor": 0.0})
            e["obras"] += 1
            e["valor"] += valor

        soma(por_situacao, o["situacao"] or "Sem situação")
        soma(por_sistema, o["sistema_origem"] or "Não informado")
        for eixo in (o["eixos"] or ["Sem eixo"]):
            soma(por_eixo, eixo)
        for origem in (o["origens_recurso"] or ["Não informada"]):
            soma(por_origem, origem)
        if ano:
            anos.add(ano)

    return {
        "tem_dados": True,
        "totais": tot,
        "acao": acao, "andamento": andamento, "encerradas": encerradas,
        "por_situacao": sorted(por_situacao.values(), key=lambda e: -e["valor"]),
        "por_eixo": sorted(por_eixo.values(), key=lambda e: -e["valor"]),
        "por_sistema": sorted(por_sistema.values(), key=lambda e: -e["valor"]),
        "por_origem": sorted(por_origem.values(), key=lambda e: -e["valor"]),
        # ⚠️ DESC: o filtro de ano da tela abre no ANO CORRENTE, e para isso ele
        # precisa da lista de anos que existem. Ver `lib/anoPadrao.ts`.
        "anos": sorted(anos, reverse=True),
        "coletado_em": _d(max((r["atualizado_em"] for r in linhas
                               if r["atualizado_em"]), default=None)),
    }


@router.get("", dependencies=[exige("obrasgov.ver")])
async def obras_federais(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Obras federais do município, já classificadas por urgência."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "obrasgov")
    return await fetch_obras_federais(db, municipio_id)
