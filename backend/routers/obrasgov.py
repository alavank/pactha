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

⚠️ `municipio_id` PODE SER INFERENCIA NOSSA — e o campo `vinculo` diz qual dos
dois casos e cada linha:

    'prefeitura'   algum CNPJ do municipio bate com tomador/executor. E
                   inferencia nossa, como sempre foi.
    'territorio'   o `/geometria?cod_ibge=` do Governo aponta a obra neste
                   municipio. Aqui o municipio veio da FONTE, e
                   `cod_ibge_geometria` guarda a prova. A obra costuma ser de
                   outro ente (em Santa Maria: UFSM, DNIT, IF Farroupilha).
    'abrangencia'  projeto guarda-chuva, com geometria em centenas de
                   municipios — nao e uma obra nesta cidade.

Ver o cabecalho de `ingestion/obrasgov.py`.

A classificacao **acao / papel / andamento / encerradas** e feita AQUI, e nao no
cliente — mesmo motivo do `routers/sismob.py`: tela, TV, celular e PDF precisam
concordar sobre o que e urgente. Ver `_classificar`, e em especial por que a
DATA EFETIVA nao serve de sinal nesta fonte.
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
EM_EXECUCAO = "Em execução"


def _f(v) -> Optional[float]:
    return float(v) if v is not None else None


def _d(v) -> Optional[str]:
    return v.isoformat() if v is not None else None


# ⚠️ O QUE ENTRA NA CONTA DO MUNICIPIO, isolado para poder ser testado.
#
# Medido em 07/09/2026 no freitas: 56 projetos 'abrangencia' somam R$ 15,89
# BILHOES contra R$ 606,8 mi de TODAS as 421 obras da prefeitura — 96% do valor
# da tela. E o MESMO projeto repetido: "Manutencao rodoviaria na malha federal
# do DNIT em MG" (R$ 383,3 mi, 790 municipios) cai em 41 das 42 cidades da
# carteira, e cada uma somava os R$ 383 mi inteiros.
#
# ⭐ Eles NAO somem: continuam na resposta, marcados, e a tela os mostra em bloco
# proprio — o programa do DNIT de fato passa por ali. O que nao podem e entrar na
# conta de "quanto o municipio tem em obras federais".
#
# ⚠️ 'territorio' CONTA. Ali a obra e uma obra so, naquele lugar, e o Governo e
# quem diz (`/geometria?cod_ibge=`). O dono ser a UFSM ou o DNIT nao a torna
# menos real para quem mora na cidade — a tela diz de quem e pelo selo.
def conta_no_total(vinculo: Optional[str]) -> bool:
    """A obra entra nos totais e nos cortes do municipio?"""
    return (vinculo or "prefeitura") != "abrangencia"


def _classificar(o: dict, hoje: date) -> dict:
    """Por que esta obra merece atenção — ou por que não merece.

    ⚠️⚠️ **A DATA EFETIVA NÃO É SINAL DE NADA NESTA FONTE, e a primeira versão
    desta função errou por supor que era.** Medido em 04/09/2026 contra a
    produção dos cinco tenants: `data_inicial_efetiva` e `data_final_efetiva`
    estão vazias em **100% das 1.011 obras coletadas**, e na própria API são 4
    de 200 — com **65 obras "Concluída" sem data de conclusão**. Ou seja: o
    Governo fecha a obra mudando a SITUAÇÃO, não preenchendo a data.

    A consequência da regra antiga era uma lista de urgências inútil: Nova Palma
    abria com **27 de 30** obras "exigindo atenção", Arapuá com 3 de 3. Uma
    lista em que quase tudo é urgente não é lida — e o gestor perde justamente
    a obra que travou de verdade.

    Então **quem classifica é a `situacao`**, e a data prevista só gradua:

      Paralisada · Inacabada ....... ação — a fonte já declara o problema
      Em execução + prazo vencido .. ação — começou e passou do prazo
      Cadastrada + previsto vencido  «não saiu do papel» — projeto encalhado,
                                     que é outra conversa e outra cobrança
      Concluída · Cancelada ........ encerradas
      o resto ...................... andamento

    ⚠️ «Não saiu do papel» é grupo PRÓPRIO e não um subtipo de ação, porque a
    ação de campo é diferente: obra parada se cobra do executor, projeto
    encalhado se cobra do próprio município e do órgão repassador. Em Nova Palma
    são as 21 obras da Defesa Civil — R$ 24,7 milhões cadastrados que ainda não
    viraram canteiro. Some-las às urgências esconderia as duas coisas."""
    situacao = (o.get("situacao") or "").strip()
    fim_prev = o.get("data_final_prevista")
    ini_prev = o.get("data_inicial_prevista")

    if situacao in ENCERRADAS:
        return {"grupo": "encerradas", "alerta": None, "motivo": None}
    if situacao in PARADAS:
        return {"grupo": "acao", "alerta": situacao.lower(),
                "motivo": f"A fonte marca esta obra como {situacao.lower()}."}

    if situacao == EM_EXECUCAO:
        if fim_prev and fim_prev < hoje:
            dias = (hoje - fim_prev).days
            return {"grupo": "acao", "alerta": "prazo_vencido",
                    "motivo": (f"Continua EM EXECUÇÃO e o prazo previsto de "
                               f"conclusão venceu há {dias} dia(s), em "
                               f"{fim_prev.strftime('%d/%m/%Y')}.")}
        return {"grupo": "andamento", "alerta": None, "motivo": None}

    # Não está em execução nem encerrada: é projeto cadastrado. Vencer o prazo
    # aqui não é obra atrasada — é obra que não começou.
    vencida = next((d for d in (ini_prev, fim_prev) if d and d < hoje), None)
    if vencida:
        dias = (hoje - vencida).days
        qual = "início" if vencida is ini_prev else "conclusão"
        return {"grupo": "papel", "alerta": "nao_saiu_do_papel",
                "motivo": (f"Continua como «{situacao or 'sem situação'}» e a "
                           f"data prevista de {qual} passou há {dias} dia(s), em "
                           f"{vencida.strftime('%d/%m/%Y')}.")}
    return {"grupo": "andamento", "alerta": None, "motivo": None}


_CAMPOS = """
    id_unico, nome, descricao, funcao_social, meta_global,
    natureza, especie, situacao, uf, cep, endereco,
    data_inicial_prevista, data_final_prevista,
    data_inicial_efetiva, data_final_efetiva, data_cadastro,
    populacao_beneficiada, empregos_gerados, valor_investimento_previsto,
    origens_recurso, eixos, tipos, tomadores, executores, repassadores,
    sistema_origem, atualizado_em,
    vinculo, cod_ibge_geometria, abrangencia_municipios,
    percentual_execucao, data_execucao, valor_empenhado, valor_liquidado,
    valor_pago, valor_restos_pagar, empenhos, contratos, paralisacao
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
    acao, papel, andamento, encerradas = [], [], [], []
    tot = {"obras": 0, "valor": 0.0, "valor_acao": 0.0, "valor_papel": 0.0,
           "empregos": 0, "populacao": 0}
    # ⚠️ O GUARDA-CHUVA CONTADO À PARTE, e não somado. Medido em 07/09/2026 no
    # freitas: 56 projetos 'abrangencia' somam R$ 15,89 BILHÕES contra R$ 606,8
    # mi de todas as 421 obras da prefeitura — 96% do valor da tela. É o mesmo
    # projeto repetido: "Manutenção rodoviária na malha federal do DNIT em MG"
    # (R$ 383,3 mi, 790 municípios) cai em 41 dos 42 municípios da carteira, e
    # cada um somava os R$ 383 mi inteiros como se fossem obra da cidade.
    #
    # ⭐ NÃO SÃO ESCONDIDOS: continuam na lista, marcados, porque o programa do
    # DNIT de fato passa por ali e o gestor pode querer vê-lo. O que não podem é
    # entrar na conta de "quanto o município tem em obras federais".
    guarda_chuva = {"obras": 0, "valor": 0.0}
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
            # ⭐ DE QUEM E A OBRA. 'prefeitura' = algum CNPJ do municipio bate;
            # 'territorio' = so a geometria aponta, e o dono e outro ente (em
            # Santa Maria sao UFSM, DNIT, IF Farroupilha); 'abrangencia' =
            # projeto guarda-chuva que nao e uma obra nesta cidade. Sem esta
            # marca, a tela repetiria por outro caminho o erro que o coletor
            # documenta: obra da UFSM posando de obra da prefeitura.
            "vinculo": o["vinculo"] or "prefeitura",
            "cod_ibge_geometria": o["cod_ibge_geometria"],
            "abrangencia_municipios": o["abrangencia_municipios"],
            # ⚠️ `None` e nao 0 em todos os quatro, pela mesma razao do `valor`:
            # projeto sem empenho coletado nao foi empenhado em zero — nao se
            # mediu. Zero e uma afirmacao que so a fonte pode fazer.
            "percentual_execucao": _f(o["percentual_execucao"]),
            "data_execucao": _d(o["data_execucao"]),
            "valor_empenhado": _f(o["valor_empenhado"]),
            "valor_liquidado": _f(o["valor_liquidado"]),
            "valor_pago": _f(o["valor_pago"]),
            "valor_restos_pagar": _f(o["valor_restos_pagar"]),
            "empenhos": o["empenhos"] or [],
            "contratos": o["contratos"] or [],
            # A justificativa de por que a obra parou, e se ha tratativas.
            "paralisacao": o["paralisacao"] or [],
            "ano": ano,
            # O link que deixa qualquer numero desta tela conferivel na fonte.
            "url_fonte": ("https://api-publica.obrasgov.gestao.gov.br/obras/"
                          "projeto-investimento?id_projeto_investimento="
                          + str(o["id_unico"] or "")),
            **diag,
        }
        {"acao": acao, "papel": papel, "andamento": andamento,
         "encerradas": encerradas}[diag["grupo"]].append(item)

        if not conta_no_total(item["vinculo"]):
            guarda_chuva["obras"] += 1
            guarda_chuva["valor"] += valor
        else:
            tot["obras"] += 1
            tot["valor"] += valor
            if diag["grupo"] == "acao":
                tot["valor_acao"] += valor
            elif diag["grupo"] == "papel":
                tot["valor_papel"] += valor
            tot["empregos"] += o["empregos_gerados"] or 0
            tot["populacao"] += o["populacao_beneficiada"] or 0

        def soma(mapa: dict, chave: str) -> None:
            # ⚠️ Os cortes por situação/eixo/sistema/origem seguem o mesmo
            # critério dos totais: um gráfico em que 96% do valor é um programa
            # rodoviário do DNIT não descreve o município.
            if not conta_no_total(item["vinculo"]):
                return
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
        "acao": acao, "papel": papel, "andamento": andamento,
        "encerradas": encerradas,
        "por_situacao": sorted(por_situacao.values(), key=lambda e: -e["valor"]),
        "por_eixo": sorted(por_eixo.values(), key=lambda e: -e["valor"]),
        "por_sistema": sorted(por_sistema.values(), key=lambda e: -e["valor"]),
        "por_origem": sorted(por_origem.values(), key=lambda e: -e["valor"]),
        # ⚠️ DESC: o filtro de ano da tela abre no ANO CORRENTE, e para isso ele
        # precisa da lista de anos que existem. Ver `lib/anoPadrao.ts`.
        "anos": sorted(anos, reverse=True),
        # ⭐ O QUE FICOU FORA DA CONTA, dito em vez de escondido. A tela mostra
        # a linha (com o selo) e explica por que ela não soma — silêncio aqui
        # faria a contagem não bater para quem conferisse contra o portal.
        "guarda_chuva": {"obras": guarda_chuva["obras"],
                         "valor": round(guarda_chuva["valor"], 2)},
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
