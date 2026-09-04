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

⚠️ GATE `transferegov.ver` + tela `transferegov`, e NÃO `convenios.ver`. A
primeira versão usava `convenios.ver` por analogia com a Consulta Popular e os
Programas do RS — e estava errada: aquela chave é declarada com
`ufs=("MG","ES","GO","RS")` no catálogo de permissões, ou seja, a caixinha só
aparece para cliente desses quatro estados. O radar é FEDERAL e vale para os 27;
num tenant de outra UF a tela existiria sem permissão possível de conceder.
`transferegov` não tem recorte de UF, é a mesma família dos irmãos deste grupo
do menu, e a fonte do radar é literalmente um arquivo do TransfereGov.
Não cria concessão nova: quem já vê o TransfereGov vê o radar.
"""
from __future__ import annotations

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
           AND (porta_receb OR porta_emenda)
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
               porta_receb, porta_emenda
          FROM base
"""

_ORDEM_LISTA = """         ORDER BY LEAST(CASE WHEN porta_receb  THEN dt_fim_receb  END,
                        CASE WHEN porta_emenda THEN dt_fim_emenda END), nome
    """


@router.get("", dependencies=[exige("transferegov.ver")])
async def radar(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Programas abertos hoje para este município apresentar proposta."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "transferegov")

    mun = (await db.execute(text(
        "SELECT nome, uf FROM municipios WHERE id = :m"), {"m": municipio_id})).first()
    if mun is None:
        raise HTTPException(404, "Município não encontrado")
    uf = (mun[1] or "").strip().upper()

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
        {"uf": uf, "nat": NATUREZA_PREFEITURA})).all()

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
        "porta": ("ambas" if (r[13] and r[14])
                  else "recebimento" if r[13]
                  else "emenda"),
    } for r in linhas]

    return {
        "municipio": {"nome": mun[0], "uf": uf},
        "total": len(itens),
        "programas": itens,
        # ⚠️ SEM CARIMBO, A TELA NÃO PODE PROMETER FRESCOR. `None` significa uma
        # coisa só: a coleta nunca rodou neste tenant. Lista vazia COM carimbo é
        # outra coisa — "olhamos e não há programa para a sua UF" — e a tela
        # precisa poder separar as duas.
        "atualizado_em": coleta.isoformat() if coleta else None,
    }


@router.get("/contagem", dependencies=[exige("transferegov.ver")])
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
    ensure_tela(current, "transferegov")

    uf = (await db.execute(text(
        "SELECT upper(coalesce(uf, '')) FROM municipios WHERE id = :m"),
        {"m": municipio_id})).scalar()
    # Sem UF o recorte não existe (ver o `motivo` da listagem). Zero aqui é a
    # resposta honesta: o menu não tem espaço para explicar, e a tela explica.
    if not uf:
        return {"total": 0, "dias_mais_proximo": None}

    linha = (await db.execute(
        text(_CTE_ABERTOS + """
        SELECT count(*),
               min(LEAST(CASE WHEN porta_receb  THEN dt_fim_receb  END,
                         CASE WHEN porta_emenda THEN dt_fim_emenda END) - hoje_br)
          FROM base
        """ + _FILTRO_ABERTOS),
        {"uf": uf, "nat": NATUREZA_PREFEITURA})).first()

    return {"total": int(linha[0] or 0),
            "dias_mais_proximo": int(linha[1]) if linha and linha[1] is not None else None}
