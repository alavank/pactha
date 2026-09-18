"""Radar de captação — os programas federais com prazo ABERTO para propor.

A plataforma acompanha o que o município já tem. Esta é a única tela que olha
para frente: a porta que ainda está aberta e até quando.

⚠️ O RECORTE É POR UF DO MUNICÍPIO, e não por bairrismo. Dos 17 programas
abertos em 02/09/2026, 9 são regionais — "INFRA-ESTRUTURA BÁSICA SR(RS)" só
aceita município gaúcho. Mostrá-lo a um prefeito mineiro seria oferecer uma
porta que não abre, que é o defeito que a tela de Programas do RS já documenta.
Medido: MG vê 9 programas, RS vê 10.

⚠️ E A DATA É CONFERIDA AQUI TAMBÉM, não só na coleta. A tabela é fotografia do
dia em que o coletor rodou; entre uma rodada e outra um prazo vence. Confiar na
coleta deixaria a tela anunciando prazo morto — e prazo morto numa tela de
captação faz o município montar processo para nada.

⭐ GATE PRÓPRIO desde 05/09/2026: `transferegov_radar.ver` + tela
`transferegov_radar`. O Radar é item de PRIMEIRO NÍVEL do menu, fora de qualquer
grupo (foi tirado de dentro de FEDERAIS em 04/09 justamente porque é a única
tela que olha para FRENTE), e agora a permissão diz a mesma coisa que o menu.

⚠️ SEM RECORTE DE UF, e continua sendo a razão de não usar `convenios.ver`: a
primeira versão usou aquela chave por analogia com a Consulta Popular, e estava
errada — `convenios` é declarada com `ufs` no catálogo, então a caixinha só
apareceria para cliente daqueles estados. O radar é FEDERAL e vale para os 27.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/programas-captacao", tags=["programas-captacao"])

# O que a PREFEITURA propõe direto. O consórcio é coletado (está no array
# `naturezas`) mas é outra pessoa jurídica: listá-lo junto, sem distinção,
# ofereceria ao prefeito um programa que ele não assina.
NATUREZA_PREFEITURA = "Administração Pública Municipal"


# ⚠️ A CTE E O FILTRO SAO COMPARTILHADOS entre a listagem e a CONTAGEM do
# menu, de proposito. Este arquivo ja avisa, no meio do SQL, que repetir a
# mesma expressao em dois lugares e como eles passam a divergir — e um
# contador na barra lateral que discorde da tela seria a pior versao disso:
# o gestor clicaria em "7 oportunidades" e encontraria seis.
_CTE_ABERTOS = """
        WITH hoje AS (SELECT (NOW() AT TIME ZONE 'America/Sao_Paulo')::date AS d),
        base AS (
          SELECT p.*,
                 -- ⚠️ AS DUAS PORTAS, calculadas UMA VEZ e usadas no filtro, na
                 -- ordenação e na resposta. Repetir a expressão nos três lugares
                 -- é como eles passam a divergir: some um `dt_ini` de um deles e
                 -- a tela promete uma janela que o filtro já não garante.
                 (p.dt_fim_receb  >= h.d AND (p.dt_ini_receb  IS NULL OR p.dt_ini_receb  <= h.d)) AS porta_receb,
                 (p.dt_fim_emenda >= h.d AND (p.dt_ini_emenda IS NULL OR p.dt_ini_emenda <= h.d)) AS porta_emenda,
                 -- ⚠️ A TERCEIRA PORTA SÓ ABRE PARA O NOMEADO (17/09/2026). O
                 -- programa de beneficiário específico já diz quem propõe; fora
                 -- da lista, mostrá-lo seria oferecer uma porta que não abre.
                 -- `COALESCE` porque CNPJ ausente ou lista nula dão NULL, e NULL
                 -- não pode vazar para a resposta como "talvez".
                 COALESCE(p.dt_fim_benef >= h.d AND (p.dt_ini_benef IS NULL OR p.dt_ini_benef <= h.d)
                          AND :cnpj = ANY(p.proponentes_cnpj), false) AS porta_benef,
                 -- O município está na lista do programa, seja qual for a porta.
                 -- Na de emenda isso quer dizer, na prática, emenda já indicada
                 -- (medido: 888 de 943 listados já propuseram), e a porta NÃO
                 -- fecha para quem está fora, porque a lista cresce na janela.
                 COALESCE(:cnpj = ANY(p.proponentes_cnpj), false) AS nomeado,
                 h.d AS hoje_br
            FROM programas_captacao p CROSS JOIN hoje h
        )
"""

_FILTRO_ABERTOS = """         WHERE ausente_desde IS NULL
           -- ⚠️ O "HOJE" E O DE BRASILIA, e nao o do servidor. `CURRENT_DATE`
           -- sai do fuso da sessao do Postgres, que nos containers e UTC: entre
           -- 21h e meia-noite de Brasilia o dia ja virou la, e um prazo que
           -- fecha HOJE sumiria do radar na noite anterior — justamente nas
           -- horas em que alguem correndo atras do prazo iria olhar. O mesmo
           -- criterio do `hoje_br()` no coletor; os dois tem de concordar,
           -- senao a tabela guarda um recorte e a tela mostra outro.
           -- ⚠️ DUAS PORTAS: basta UMA aberta. `porta_receb`/`porta_emenda` são
           -- calculadas acima com o mesmo critério e voltam para a tela — quem
           -- decide por onde se entra é a data, não a coleta, porque a coleta
           -- roda uma vez por dia e um rótulo gravado envelheceria.
           AND (porta_receb OR porta_emenda OR porta_benef)
           -- ⚠️ A JANELA TEM DOIS LADOS, e isso vale para as duas portas.
           -- "Aberto" é estar DENTRO do período, e não apenas antes do fim: um
           -- programa que só abre em novembro entraria na conta de "abertos
           -- hoje" e o gestor montaria proposta para um sistema que ainda não a
           -- aceita. O `dt_ini` de cada porta está dentro do respectivo cálculo.
           AND :nat = ANY(naturezas)
           -- ⚠️ SEM `OR cardinality(ufs) = 0` DE PROPÓSITO. A tentação é tratar
           -- array vazio como "vale para todos"; medido no arquivo real, NENHUM
           -- programa municipal vem sem UF (os nacionais listam as 27). Então
           -- esse ramo só seria alcançado por defeito de coleta — e, alcançado,
           -- mostraria o programa a TODO município do país. Numa tela que manda
           -- o gestor abrir processo, o padrão seguro é não mostrar o que não
           -- se sabe a quem se destina.
           AND :uf = ANY(ufs)
         -- ⚠️ ORDENA PELO PRAZO QUE ESTA VALENDO, e nao sempre por
         -- `dt_fim_receb`. Para um programa que so tem a emenda aberta, aquele
         -- campo e uma data PASSADA (ou nula): ordenar por ele jogaria o
         -- programa para o topo como se fosse o mais urgente, ou para o fim com
         -- os nulos. `LEAST` ignora NULL no Postgres, entao o CASE deixa de fora
         -- a porta fechada e sobra a data que o gestor precisa cumprir.
"""

_SELECT_LISTA = """        SELECT id_programa, nome, orgao, modalidade, dt_ini_receb, dt_fim_receb,
               dt_fim_emenda, acao_orcamentaria, subtipo, cod_programa,
               (dt_fim_receb  - hoje_br) AS dias,
               (dt_fim_emenda - hoje_br) AS dias_emenda,
               cardinality(ufs) AS qt_ufs,
               -- ⚠️ COLUNAS NOVAS VAO NO FIM. As linhas sao lidas por indice
               -- posicional (`r[0]`..`r[12]`) logo abaixo; inserir no meio
               -- desloca tudo em silencio e a tela passa a mostrar um campo no
               -- lugar de outro.
               porta_receb, porta_emenda,
               porta_benef, dt_fim_benef, (dt_fim_benef - hoje_br) AS dias_benef, nomeado
          FROM base
"""

_ORDEM_LISTA = """         ORDER BY LEAST(CASE WHEN porta_receb  THEN dt_fim_receb  END,
                        CASE WHEN porta_emenda THEN dt_fim_emenda END,
                        CASE WHEN porta_benef  THEN dt_fim_benef  END), nome
    """


@router.get("", dependencies=[exige("transferegov_radar.ver")])
async def radar(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Programas abertos hoje para este município apresentar proposta."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "transferegov_radar")

    mun = (await db.execute(text(
        "SELECT nome, uf, regexp_replace(coalesce(cnpj, ''), '\\D', '', 'g') "
        "FROM municipios WHERE id = :m"), {"m": municipio_id})).first()
    if mun is None:
        raise HTTPException(404, "Município não encontrado")
    uf = (mun[1] or "").strip().upper()
    # ⚠️ CHAVE É CNPJ, NUNCA NOME. "MUNICIPIO DE SANTA MARIA" casaria com Santa
    # Maria do Herval, que está nomeada em outros programas.
    cnpj = mun[2] or ""

    # ⚠️ SEM UF NÃO DÁ PARA RESPONDER, e o honesto é dizer isso. A alternativa
    # seria rodar a consulta assim mesmo: `'' = ANY(ufs)` nunca casa, a tela
    # receberia lista vazia e leria "não há programa aberto" — acusando o
    # TransfereGov de não ter oportunidade por causa de um cadastro nosso
    # incompleto. O `motivo` manda a pessoa para onde se conserta.
    if not uf:
        return {"municipio": {"nome": mun[0], "uf": ""}, "total": 0, "programas": [],
                "atualizado_em": None,
                "motivo": "Este município está sem UF cadastrada, e o recorte dos "
                          "programas é por estado. Cadastre a UF em Configurações "
                          "→ Municípios para o radar funcionar."}

    # ⚠️ O CARIMBO DA COLETA SAI DA TABELA INTEIRA, e não das linhas filtradas.
    # Derivá-lo do resultado parecia natural e era um defeito: um município cuja
    # UF não tem NENHUM programa aberto recebia lista vazia E carimbo nulo, e a
    # tela — que usa o carimbo nulo para dizer "ainda não coletamos" — acusava
    # uma pendência nossa que não existe. São dois fatos distintos: "quando
    # olhamos" não depende de "o que achamos para você".
    coleta = (await db.execute(text(
        "SELECT max(visto_em) FROM programas_captacao"))).scalar()

    linhas = (await db.execute(
        text(_CTE_ABERTOS + _SELECT_LISTA + _FILTRO_ABERTOS + _ORDEM_LISTA),
        {"uf": uf, "nat": NATUREZA_PREFEITURA, "cnpj": cnpj})).all()

    # ⚠️ `qt_ufs` VAI CRU PARA A TELA, e a classificação é só de três estados.
    # A primeira versão mandava apenas "nacional | regional" com corte em 27, e
    # a tela traduzia `regional` como o selo "só MG" — o que era MENTIRA no
    # programa de Saneamento, aberto a 20 estados. Um programa restrito a UM
    # estado e um aberto a vinte pedem leituras opostas do gestor (o primeiro é
    # disputa curta; o segundo, concorrência nacional disfarçada), então a
    # distinção precisa sobreviver até a tela.
    itens = [{
        "id_programa": r[0], "nome": r[1], "orgao": r[2], "modalidade": r[3],
        "dt_ini_receb": r[4].isoformat() if r[4] else None,
        "dt_fim_receb": r[5].isoformat() if r[5] else None,
        "dt_fim_emenda": r[6].isoformat() if r[6] else None,
        "acao_orcamentaria": r[7], "subtipo": r[8], "cod_programa": r[9],
        "dias": r[10], "dias_emenda": r[11],
        "qt_ufs": r[12] or 0,
        "abrangencia": ("nacional" if (r[12] or 0) >= 27
                        else "exclusivo" if (r[12] or 0) == 1
                        else "regional"),
        # ⚠️ POR QUAL PORTA SE ENTRA — o campo mais importante desta resposta
        # depois do nome. "recebimento" é proposta espontânea: a prefeitura
        # protocola e pronto. "emenda" depende de um deputado ou senador destinar
        # o recurso — o gestor NÃO cumpre esse prazo sozinho. Antes de 02/09/2026
        # o radar só carregava a primeira porta, e por isso a tela nunca precisou
        # distinguir; agora que as duas chegam, misturá-las faria o prefeito
        # achar que basta protocolar, o que é pior que não mostrar o programa.
        #
        # ⚠️ DESDE 17/09/2026 SÃO TRÊS PORTAS, e por isso uma LISTA, e não mais
        # o rótulo "recebimento | emenda | ambas". "beneficiario" só chega aqui
        # quando o CNPJ do município está na lista do programa.
        "portas": [nome for nome, aberta in (("recebimento", r[13]), ("emenda", r[14]),
                                             ("beneficiario", r[15])) if aberta],
        "dt_fim_benef": r[16].isoformat() if r[16] else None,
        "dias_benef": r[17],
        "nomeado": bool(r[18]),
    } for r in linhas]

    return {
        "municipio": {"nome": mun[0], "uf": uf},
        # Sem CNPJ cadastrado a terceira porta nunca abre, e a tela precisa dizer
        # isso: senão "nenhum programa com o município nomeado" se lê como fato.
        "cnpj_cadastrado": bool(cnpj),
        "total": len(itens),
        "programas": itens,
        # ⚠️ SEM CARIMBO, A TELA NÃO PODE PROMETER FRESCOR. `None` significa uma
        # coisa só: a coleta nunca rodou neste tenant. Lista vazia COM carimbo é
        # outra coisa — "olhamos e não há programa para a sua UF" — e a tela
        # precisa poder separar as duas.
        "atualizado_em": coleta.isoformat() if coleta else None,
    }


@router.get("/contagem", dependencies=[exige("transferegov_radar.ver")])
async def contagem(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Só o número de programas abertos — para o contador do menu.

    ⚠️ EXISTE PARA NÃO CARREGAR A LISTA INTEIRA A CADA NAVEGAÇÃO. O menu é
    renderizado em toda tela do sistema; chamar o endpoint completo dali traria
    dezenas de programas com objeto, datas e órgão para exibir um inteiro.

    ⚠️ E USA O MESMO FILTRO da listagem (`_CTE_ABERTOS` + `_FILTRO_ABERTOS`),
    não uma cópia. Um contador que discorde da tela é pior que contador nenhum:
    o gestor clica em "7 oportunidades" e encontra seis, e a partir daí não
    confia em nenhum número do sistema.

    Devolve também os dias até o prazo mais próximo — é o que permite à tela
    decidir se o número merece um sinal de urgência, sem uma segunda chamada.
    """
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "transferegov_radar")

    mun = (await db.execute(text(
        "SELECT upper(coalesce(uf, '')), regexp_replace(coalesce(cnpj, ''), '\\D', '', 'g') "
        "FROM municipios WHERE id = :m"),
        {"m": municipio_id})).first()
    uf, cnpj = (mun[0], mun[1]) if mun else ("", "")
    # Sem UF o recorte não existe (ver o `motivo` da listagem). Zero aqui é a
    # resposta honesta: o menu não tem espaço para explicar, e a tela explica.
    if not uf:
        return {"total": 0, "dias_mais_proximo": None}

    linha = (await db.execute(
        text(_CTE_ABERTOS + """
        SELECT count(*),
               min(LEAST(CASE WHEN porta_receb  THEN dt_fim_receb  END,
                         CASE WHEN porta_emenda THEN dt_fim_emenda END,
                         CASE WHEN porta_benef  THEN dt_fim_benef  END) - hoje_br)
          FROM base
        """ + _FILTRO_ABERTOS),
        {"uf": uf, "nat": NATUREZA_PREFEITURA, "cnpj": cnpj})).first()

    return {"total": int(linha[0] or 0),
            "dias_mais_proximo": int(linha[1]) if linha and linha[1] is not None else None}


# ---------------------------------------------------------------- ficha ---

_SELECT_FICHA = """        SELECT id_programa, nome, orgao, modalidade, cod_programa, acao_orcamentaria,
               subtipo, ufs, naturezas, dt_disponibilizacao,
               dt_ini_receb, dt_fim_receb, dt_ini_emenda, dt_fim_emenda,
               dt_ini_benef, dt_fim_benef, porta_receb, porta_emenda, porta_benef,
               nomeado, hoje_br, edicoes_anteriores, ficha_em
          FROM base
"""

# Contagem por fase — a MESMA expressão para a edição aberta e para as
# anteriores, nacional e na UF, para as quatro caixas não divergirem.
_CONTA_FASES = """
        SELECT count(*) AS propostas,
               count(*) FILTER (WHERE fase = 'aprovada')  AS aprovadas,
               count(*) FILTER (WHERE fase = 'rejeitada') AS rejeitadas,
               count(*) FILTER (WHERE fase = 'andamento') AS andamento,
               count(*) FILTER (WHERE uf = :uf) AS propostas_uf,
               count(*) FILTER (WHERE uf = :uf AND fase = 'aprovada')  AS aprovadas_uf,
               count(*) FILTER (WHERE uf = :uf AND fase = 'rejeitada') AS rejeitadas_uf,
               -- ⚠️ "REPASSE MEDIANO DAS APROVADAS", nunca "valor do programa":
               -- é o que cada prefeitura pediu e levou, e a fonte não publica
               -- teto nem dotação (ver `add_programas_captacao.sql`).
               percentile_cont(0.5) WITHIN GROUP (ORDER BY vl_repasse)
                   FILTER (WHERE fase = 'aprovada' AND vl_repasse > 0) AS repasse_mediano,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY vl_contrapartida / NULLIF(vl_global, 0))
                   FILTER (WHERE fase = 'aprovada' AND vl_global > 0
                           AND vl_contrapartida IS NOT NULL) AS contrapartida_mediana
          FROM programas_captacao_propostas
         WHERE id_programa = ANY(:ids)
"""


def _data(v):
    return v.isoformat() if v else None


def _num(v):
    return float(v) if v is not None else None


def _fases(r) -> dict:
    return {"propostas": r["propostas"], "aprovadas": r["aprovadas"],
            "rejeitadas": r["rejeitadas"], "andamento": r["andamento"],
            "uf": {"propostas": r["propostas_uf"], "aprovadas": r["aprovadas_uf"],
                   "rejeitadas": r["rejeitadas_uf"]},
            "repasse_mediano": _num(r["repasse_mediano"]),
            "contrapartida_mediana": _num(r["contrapartida_mediana"])}


# ⚠️ DECLARADA DEPOIS DE `/contagem`, e a ordem importa: o FastAPI casa as rotas
# na ordem em que foram registradas, e `/{id_programa}` antes dela engoliria
# "contagem" como id — o contador do menu passaria a receber 404.
@router.get("/{id_programa}", dependencies=[exige("transferegov_radar.ver")])
async def ficha(
    id_programa: str,
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """A ficha de UM programa aberto, para o município: prazos, situação do
    município, concorrência, edições anteriores, exemplos aprovados e quem indica.

    ⚠️ O PROGRAMA PASSA PELO MESMO FILTRO DA LISTA (`_FILTRO_ABERTOS`). Ficha de
    programa vencido, de outra UF ou que só o consórcio assina seria a porta que
    não abre, agora com mais detalhe — 404 é a resposta honesta.
    """
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "transferegov_radar")

    mun = (await db.execute(text(
        "SELECT nome, upper(coalesce(uf, '')), regexp_replace(coalesce(cnpj, ''), '\\D', '', 'g'), "
        "regexp_replace(coalesce(ibge_code, ''), '\\D', '', 'g') "
        "FROM municipios WHERE id = :m"), {"m": municipio_id})).first()
    if mun is None:
        raise HTTPException(404, "Município não encontrado")
    nome_mun, uf, cnpj, ibge = mun[0], mun[1].strip(), mun[2] or "", mun[3] or ""
    if not uf:
        raise HTTPException(404, "Município sem UF cadastrada")

    p = (await db.execute(
        text(_CTE_ABERTOS + _SELECT_FICHA + _FILTRO_ABERTOS + "           AND id_programa = :id\n"),
        {"uf": uf, "nat": NATUREZA_PREFEITURA, "cnpj": cnpj, "id": id_programa},
    )).mappings().first()
    if p is None:
        raise HTTPException(404, "Programa não está aberto para este município hoje")

    hoje = p["hoje_br"]

    def janela(ini, fim, aberta):
        return {"inicio": _data(ini), "fim": _data(fim), "aberta": bool(aberta),
                "dias": (fim - hoje).days if (fim and aberta) else None}

    programa = {
        "id_programa": p["id_programa"], "nome": p["nome"], "orgao": p["orgao"],
        "modalidade": p["modalidade"], "cod_programa": p["cod_programa"],
        "acao_orcamentaria": p["acao_orcamentaria"], "subtipo": p["subtipo"],
        "ufs": sorted(p["ufs"] or []),
        "consorcio_tambem": "Consórcio Público" in (p["naturezas"] or []),
        "dt_disponibilizacao": _data(p["dt_disponibilizacao"]),
        "dias_publicado": (hoje - p["dt_disponibilizacao"]).days if p["dt_disponibilizacao"] else None,
        "janelas": {
            "recebimento": janela(p["dt_ini_receb"], p["dt_fim_receb"], p["porta_receb"]),
            "emenda": janela(p["dt_ini_emenda"], p["dt_fim_emenda"], p["porta_emenda"]),
            "beneficiario": janela(p["dt_ini_benef"], p["dt_fim_benef"], p["porta_benef"]),
        },
        "nomeado": bool(p["nomeado"]),
    }
    resp = {"municipio": {"nome": nome_mun, "uf": uf, "cnpj_cadastrado": bool(cnpj),
                          "ibge_cadastrado": bool(ibge)},
            "programa": programa,
            # ⚠️ `ficha_em` NULL = ficha ainda não montada para este programa.
            # A tela mostra os blocos abaixo como PENDENTES, nunca como zero:
            # "ninguém propôs" dito sobre uma tabela que não foi lida é mentira.
            "ficha_em": p["ficha_em"].isoformat() if p["ficha_em"] else None}
    if p["ficha_em"] is None:
        return resp

    edicoes = p["edicoes_anteriores"] or []
    if isinstance(edicoes, str):  # driver sem decodificação de JSONB
        edicoes = json.loads(edicoes)
    ids_ant = [e["id"] for e in edicoes if e.get("id")]
    todos = [id_programa] + ids_ant

    # SUA SITUAÇÃO — ⚠️ proposta por IBGE (pega a prefeitura E o fundo municipal,
    # que tem CNPJ próprio), indicação por CNPJ (é a única chave do arquivo).
    # Nunca por nome: "SANTA MARIA" casaria Santa Maria do Herval.
    suas = []
    if ibge:
        suas = (await db.execute(text("""
            SELECT id_programa, ano, dt_proposta, nr_proposta, situacao, fase,
                   vl_repasse, vl_global, objeto, proponente
              FROM programas_captacao_propostas
             WHERE id_programa = ANY(:ids) AND ibge = :ibge
             ORDER BY (id_programa = :id) DESC, dt_proposta DESC NULLS LAST
             LIMIT 30"""), {"ids": todos, "ibge": ibge, "id": id_programa})).mappings().all()
    indicacoes = []
    if cnpj:
        indicacoes = (await db.execute(text("""
            SELECT parlamentar, solicitante, indicacao, nr_emenda, valor
              FROM programas_captacao_apoiadores
             WHERE id_programa = :id AND cnpj = :cnpj
             ORDER BY valor DESC NULLS LAST"""), {"id": id_programa, "cnpj": cnpj})).mappings().all()
    resp["situacao"] = {
        "indicacoes": [{"parlamentar": r["parlamentar"], "solicitante": r["solicitante"],
                        "indicacao": r["indicacao"], "nr_emenda": r["nr_emenda"],
                        "valor": _num(r["valor"])} for r in indicacoes],
        "propostas": [{"edicao_atual": r["id_programa"] == id_programa, "ano": r["ano"],
                       "data": _data(r["dt_proposta"]), "nr_proposta": r["nr_proposta"],
                       "situacao": r["situacao"], "fase": r["fase"],
                       "vl_repasse": _num(r["vl_repasse"]), "vl_global": _num(r["vl_global"]),
                       "objeto": r["objeto"], "proponente": r["proponente"]} for r in suas],
    }

    atual = (await db.execute(text(_CONTA_FASES), {"uf": uf, "ids": [id_programa]})).mappings().first()
    resp["concorrencia"] = _fases(atual)
    anteriores = None
    if ids_ant:
        anteriores = (await db.execute(text(_CONTA_FASES), {"uf": uf, "ids": ids_ant})).mappings().first()
    resp["historico"] = {"edicoes": edicoes,
                         "fases": _fases(anteriores) if anteriores else None}

    # EXEMPLOS: o que OUTRAS prefeituras aprovaram — da UF primeiro, depois do
    # país; edição aberta e anteriores. É o que substitui a descrição que o
    # arquivo não traz: o gestor entende o que o programa paga vendo o que já
    # passou.
    exemplos = (await db.execute(text("""
        SELECT id_programa, ano, uf, proponente, objeto, vl_repasse
          FROM programas_captacao_propostas
         WHERE id_programa = ANY(:ids) AND fase = 'aprovada'
           AND objeto IS NOT NULL AND coalesce(ibge, '') <> :ibge
         ORDER BY (uf = :uf) DESC NULLS LAST, ano DESC NULLS LAST, vl_repasse DESC NULLS LAST
         LIMIT 8"""), {"ids": todos, "uf": uf, "ibge": ibge})).mappings().all()
    resp["exemplos"] = [{"edicao_atual": r["id_programa"] == id_programa, "ano": r["ano"],
                         "uf": r["uf"], "proponente": r["proponente"], "objeto": r["objeto"],
                         "vl_repasse": _num(r["vl_repasse"])} for r in exemplos]

    # QUEM INDICA: parlamentares e comissões com emenda neste programa para
    # prefeituras da UF — o gabinete a procurar na próxima rodada.
    quem = (await db.execute(text("""
        SELECT parlamentar, solicitante, count(DISTINCT cnpj) AS municipios,
               sum(valor) AS valor
          FROM programas_captacao_apoiadores
         WHERE id_programa = :id AND uf = :uf
         GROUP BY parlamentar, solicitante
         ORDER BY sum(valor) DESC NULLS LAST
         LIMIT 12"""), {"id": id_programa, "uf": uf})).mappings().all()
    total = (await db.execute(text("""
        SELECT count(*) AS indicacoes, count(DISTINCT cnpj) AS municipios,
               count(DISTINCT cnpj) FILTER (WHERE uf = :uf) AS municipios_uf
          FROM programas_captacao_apoiadores WHERE id_programa = :id"""),
        {"id": id_programa, "uf": uf})).mappings().first()
    resp["apoiadores"] = {
        "indicacoes": total["indicacoes"], "municipios": total["municipios"],
        "municipios_uf": total["municipios_uf"],
        "na_uf": [{"parlamentar": r["parlamentar"], "solicitante": r["solicitante"],
                   "municipios": r["municipios"], "valor": _num(r["valor"])} for r in quem],
    }
    return resp
