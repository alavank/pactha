"""AGENDAMENTOS — a agenda de compromissos da equipe.

Todo o resto da plataforma mostra dado que vem de fora. Este é o único módulo em
que a equipe ESCREVE: o compromisso marcado, a que horas, quem pediu, em que pé
está e o que foi sendo anotado a respeito.

⭐ TRÊS VISUALIZAÇÕES, UMA CONSULTA SÓ. Calendário, kanban e lista leem as mesmas
linhas com os mesmos filtros — o que muda é o desenho na tela, não o recorte. Por
isso não existe endpoint "de calendário" nem "de kanban": eles pediriam três
consultas para manter em sincronia, e a primeira a divergir mostraria um
compromisso que as outras duas escondem.

⚠️ O RELATÓRIO USA A MESMA FUNÇÃO DE FILTRO DA LISTA, e é o motivo de ele morar
aqui e não em `routers/export_pdf.py` com as outras seis. O dono pediu "o
relatório respeita o filtro ativo": se ele montasse a própria consulta, um ajuste
no filtro da tela deixaria o arquivo desalinhado com o que a pessoa está vendo — e
um relatório que não bate com a tela é pior que nenhum, porque ninguém descobre
pela tela qual dos dois está certo.

⚠️ O MUNICÍPIO É IMPLÍCITO NA PREFEITURA, E OBRIGATÓRIO NA ASSESSORIA — e a regra
que separa os dois é a CONTAGEM de municípios ativos do tenant, nunca um tipo
configurado. É a mesma regra que a tela de Usuários já usa
(`municipioUnico = municipios.length === 1`), e ela acerta nos dois casos sem
exigir configuração nova. Num tenant de um município só, o formulário não manda
`municipio_id` e `_municipio_implicito` resolve; com vários, mandar é obrigatório.

⚠️ ANOTAÇÃO É APPEND-ONLY, e a trava é a AUSÊNCIA de rota: não há PUT nem DELETE
de anotação neste arquivo, e isso é decisão de produto (o histórico de um
compromisso é o que impede duas pessoas contarem a mesma história de dois jeitos).
O banco não tem trigger para isso — quem garante é este arquivo.

⚠️ ANEXO TEM PERMISSÃO PRÓPRIA (`agendamentos.anexo_baixar`), pela mesma razão do
módulo de Gestão: a lista mostra QUE existe um anexo, esta caixinha entrega o
ARQUIVO — que pode ser ofício, contrato ou documento pessoal. Ver que existe não
é ver o conteúdo. O formulário NOVO não anexa nada (o redesenho de 05/09/2026
trocou anexo+relato por histórico de anotações), mas o que já foi anexado
continua sendo servido: apagar o acesso a um documento que já está lá seria
perder dado do cliente por mudança de tela.

⚠️ E O `dados_b64` NUNCA SAI NA LISTAGEM. Uma agenda de mês com trinta cartões,
cada um com um PDF em base64, viraria um payload de dezenas de megabytes para
desenhar uma grade de calendário. A lista manda só o metadado; o arquivo sai
pela rota de download, uma requisição por vez, e com a permissão própria.
"""
from __future__ import annotations

import base64
import re
from datetime import date, time, timedelta
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services import authz
from services.audit import registrar
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/agendamentos", tags=["agendamentos"])

# ---------------------------------------------------------------------------
# A PALETA DE ACENTO DOS COMPROMISSOS
# ---------------------------------------------------------------------------
# ⭐ UMA LISTA SÓ, E ELA MORA AQUI. A tela pede `GET /paleta` em vez de trazer
# as cores no código — mesma razão pela qual as colunas do kanban também vêm do
# backend: duas listas divergem no primeiro ajuste, e a divergência aparece como
# um compromisso salvo numa cor que a tela não sabe desenhar.
#
# ⚠️ O HEX É DADO, O CONTRASTE É RECEITA. A tela não guarda variante clara nem
# escura de cada cor: o chip monta fundo e texto com `color-mix` sobre os tokens
# do tema (`.ag-chip`, em globals.css), então a MESMA cor lê bem no claro e no
# escuro sem uma segunda tabela para manter em sincronia.
#
# Nove tons na mesma família das cores de gráfico do PACTHA (`--bi-c1..c5`) e do
# acento do sistema (`--bi-accent`), espaçados no círculo cromático para que dois
# compromissos vizinhos no calendário nunca se confundam.
PALETA: tuple[tuple[str, str], ...] = (
    ("#12b886", "Menta"),
    ("#2fb0c4", "Turquesa"),
    ("#4fa3ee", "Azul"),
    ("#a58cf0", "Violeta"),
    ("#e07ab0", "Rosa"),
    ("#f9846a", "Coral"),
    ("#f5b93f", "Âmbar"),
    ("#8bb734", "Limão"),
    ("#7b8794", "Grafite"),
)
CORES = tuple(hexa for hexa, _ in PALETA)
COR_PADRAO = CORES[0]

# As três colunas que todo tenant tem. A `chave` é o que o código usa para
# apontar uma delas; o `nome` é da tela e não se renomeia (ver `atualizar_coluna`).
# ⚠️ Tem de bater com o seed de `add_agendamentos_compromisso.sql`.
COLUNAS_FIXAS = ("solicitada", "em_andamento", "concluida")
COLUNA_ENTRADA = "solicitada"
# A cor de partida do cabecalho de uma coluna — o cinza da paleta. Tem de bater
# com o DEFAULT de `add_agendamentos_coluna_cor.sql`.
COR_COLUNA_PADRAO = "#7b8794"
# Teto absoluto do quadro e teto de customizadas — os dois são do documento de
# redesenho, e valem TAMBÉM aqui e não só no botão da tela: um POST repetido por
# duas abas abertas passaria do limite se quem contasse fosse o navegador.
MAX_COLUNAS = 5
MAX_COLUNAS_CUSTOMIZADAS = 2

# ⚠️ BUSCA SEM ACENTO SEM `unaccent`. A extensão não está instalada em nenhum dos
# cinco bancos (ver `limpa_prestacao_contas_nao_informado.sql`), então o mesmo
# mapa de tradução é aplicado dos DOIS lados: `translate()` na coluna, aqui em
# Python no termo digitado. Sendo o mesmo mapa, o casamento é exato por
# construção — o que um `unaccent` de um lado só nunca garantiria.
_DE = "áàâãäéèêëíìîïóòôõöúùûüçñ"
_PARA = "aaaaaeeeeiiiiooooouuuucn"
_TRADUZ = str.maketrans(_DE, _PARA)


def _sem_acento(s: str) -> str:
    return s.lower().translate(_TRADUZ)


def _sql_sem_acento(expr: str) -> str:
    """O mesmo `_sem_acento`, em SQL, para a coluna."""
    return f"translate(lower({expr}), '{_DE}', '{_PARA}')"


class CompromissoCreate(BaseModel):
    """⚠️ `municipio_id` É OPCIONAL AQUI E OBRIGATÓRIO NA ASSESSORIA. O pydantic
    não sabe quantos municípios o tenant tem; quem decide é `_resolver_municipio`,
    que preenche sozinho quando há um só e recusa com 422 quando há vários."""
    municipio_id: Optional[int] = None
    demanda: str = Field(..., min_length=1, max_length=200)
    data: date
    hora_inicio: time
    tem_periodo: bool = False
    hora_fim: Optional[time] = None
    data_solicitacao: Optional[date] = None
    solicitante: str = Field(..., min_length=1, max_length=120)
    contato_whatsapp: Optional[str] = None
    cor: str = COR_PADRAO
    coluna_id: Optional[int] = None
    # Na criação o formulário oferece UM campo livre de anotação, que vira a
    # primeira do histórico. Depois disso, anotação só entra pela rota própria.
    anotacao: Optional[str] = None


class CompromissoUpdate(BaseModel):
    """Todos anuláveis: o PUT manda só o que mudou.

    ⚠️ `hora_fim` e `contato_whatsapp` PRECISAM PODER VOLTAR A VAZIO, e é por
    isso que a edição parcial deste modelo é decidida por `model_fields_set` e
    não por `is not None`. Desmarcar "Definir período" é uma edição legítima que
    apaga a hora de término; com o teste ingênuo ela seria descartada em
    silêncio, e o bloco continuaria esticado no calendário."""
    municipio_id: Optional[int] = None
    demanda: Optional[str] = Field(None, min_length=1, max_length=200)
    data: Optional[date] = None
    hora_inicio: Optional[time] = None
    tem_periodo: Optional[bool] = None
    hora_fim: Optional[time] = None
    data_solicitacao: Optional[date] = None
    solicitante: Optional[str] = Field(None, min_length=1, max_length=120)
    contato_whatsapp: Optional[str] = None
    cor: Optional[str] = None
    coluna_id: Optional[int] = None


class ColunaUpdate(BaseModel):
    """⚠️ ROTA PRÓPRIA PARA O KANBAN, e não o PUT inteiro.

    Arrastar um cartão de coluna muda UMA coisa. Mandar o objeto completo faria
    um cartão arrastado a partir de uma tela carregada há dez minutos
    sobrescrever com dado velho a demanda que outra pessoa acabou de editar. Um
    PATCH de um campo não tem como fazer isso."""
    coluna_id: int


class ColunaNova(BaseModel):
    """Nome e cor do cabeçalho da coluna.

    ⚠️ A COR VEM DA MESMA `PALETA` DO COMPROMISSO, e não de uma segunda lista de
    tons claros. O cabeçalho é desenhado com `color-mix` sobre a superfície do
    tema (`.ag-solto`, em globals.css), então a mesma cor sai pastel no claro e
    discreta no escuro — guardar o pastel já calculado exigiria uma paleta
    paralela só para o tema escuro."""
    nome: str = Field(..., min_length=1, max_length=40)
    cor: Optional[str] = None


class AnotacaoNova(BaseModel):
    texto: str = Field(..., min_length=1)


# ---------------------------------------------------------------- validação --

def _so_digitos(v: Optional[str]) -> Optional[str]:
    """`(51) 99999-9999` -> `51999999999`. Vazio vira None.

    ⚠️ A MÁSCARA É DA TELA, O BANCO GUARDA DÍGITO. Gravar a pontuação faria
    "51999999999" e "(51) 99999-9999" serem dois números diferentes para
    qualquer busca ou comparação futura — e os dois saem do mesmo formulário,
    porque colar de outro lugar não passa pela máscara."""
    if v is None:
        return None
    d = re.sub(r"\D", "", v)
    if not d:
        return None
    if len(d) not in (10, 11):
        raise HTTPException(
            422, "O contato de WhatsApp precisa ter DDD e 8 ou 9 dígitos — "
                 f"recebi {len(d)}.")
    return d


def _valida_horario(hora_inicio, tem_periodo, hora_fim) -> None:
    """As duas regras que a tela também aplica, repetidas aqui de propósito.

    Validação que só existe no navegador é sugestão: um `curl` a ignora, e o
    resultado é um bloco que termina antes de começar — que o calendário desenha
    com altura negativa, ou seja, não desenha."""
    if not tem_periodo:
        return
    if hora_fim is None:
        raise HTTPException(422, "Com período marcado, o horário de término é "
                                 "obrigatório.")
    if hora_inicio is not None and hora_fim <= hora_inicio:
        raise HTTPException(422, "O término precisa ser depois do início.")


def _valida_cor(cor: Optional[str]) -> Optional[str]:
    if cor is None:
        return None
    c = cor.strip().lower()
    if c not in CORES:
        raise HTTPException(
            422, f"Cor {cor!r} não é da paleta de compromissos. Use uma de "
                 f"{list(CORES)}.")
    return c


# ------------------------------------------------------------- o município --

async def _municipio_implicito(db: AsyncSession) -> Optional[int]:
    """O município do tenant, quando ele tem UM só.

    ⭐ É O QUE FAZ "O MUNICÍPIO É IMPLÍCITO NA PREFEITURA" SER VERDADE NO BANCO.
    A tela de uma prefeitura não tem campo de município em lugar nenhum — mas a
    coluna é NOT NULL e é ela que sustenta o recorte de carteira, o JOIN do nome
    e o carimbo da trilha. Em vez de afrouxar a coluna (que esconderia a linha de
    todo usuário de carteira restrita, porque `= ANY(:mids)` nunca casa com
    NULL), o backend responde a pergunta que a tela não faz.

    Devolve None quando há zero ou mais de um: aí o formulário TEM de escolher.
    """
    rows = (await db.execute(text(
        "SELECT id FROM municipios WHERE active = TRUE LIMIT 2"))).fetchall()
    return rows[0][0] if len(rows) == 1 else None


async def _resolver_municipio(db: AsyncSession, pedido: Optional[int]) -> int:
    if pedido:
        return pedido
    unico = await _municipio_implicito(db)
    if unico is None:
        raise HTTPException(422, "Escolha o município do compromisso.")
    return unico


# ⚠️ A ORDEM DAS COLUNAS AQUI É LIDA POR ÍNDICE em `_row_to_dict`. Coluna nova
# entra no FIM — é a regra da casa, e o defeito que ela evita (todo campo depois
# do inserido passa a ler o vizinho) não levanta erro: só troca os valores de
# lugar na tela.
_SELECT = """
    -- ⚠️ `users.name`, E NAO `users.nome`. As duas tabelas usam vocabulario
    -- diferente e isso ja custou um erro em producao: `municipios` tem `nome`
    -- (portugues) e `users` tem `name` (ingles). O `pglast` valida a GRAMATICA
    -- do SQL e nao o ESQUEMA, entao `ur.nome` passou por toda a suite e so
    -- apareceu como ProgrammingError na tela do cliente. Ver
    -- `test_agendamentos.py::test_o_select_so_usa_coluna_que_existe_no_modelo`.
    SELECT a.id, a.municipio_id, m.nome, m.uf,
           a.demanda, a.data, a.hora_inicio, a.tem_periodo, a.hora_fim,
           a.data_solicitacao, a.solicitante, a.contato_whatsapp, a.cor,
           a.coluna_id, k.nome, a.anexos,
           a.criado_por, uc.name, a.created_at, a.updated_at,
           (SELECT COUNT(*) FROM agendamentos_anotacoes n
             WHERE n.compromisso_id = a.id)
      FROM agendamentos a
      JOIN municipios m ON m.id = a.municipio_id
      JOIN agendamentos_colunas k ON k.id = a.coluna_id
      LEFT JOIN users uc ON uc.id = a.criado_por
"""


def _hhmm(v) -> Optional[str]:
    """`time` -> `HH:MM`. Sem segundos: o formulário é de hora e minuto, e
    "14:30:00" na tela é ruído que ninguém digitou."""
    return v.strftime("%H:%M") if v is not None else None


def _row_to_dict(row, *, with_anexos: bool = False) -> dict:
    """⚠️ O PADRAO E `False` — o lado SEGURO. Quem esquecer o argumento omite o
    `dados_b64` em vez de vaza-lo, e vazar aqui anula a permissao
    `agendamentos.anexo_baixar`: quem tem so `ver` ja teria recebido o arquivo.
    Hoje NENHUMA chamada pede `True`; o parametro existe para que um dia pedir
    seja uma decisao escrita, e nao um descuido."""
    anexos = row[15] or []
    if not with_anexos:
        anexos = [{k: v for k, v in a.items() if k != "dados_b64"} for a in anexos]
    return {
        "id": row[0],
        "municipio_id": row[1],
        "municipio": row[2],
        "uf": row[3],
        "demanda": row[4],
        "data": row[5].isoformat() if row[5] else None,
        "hora_inicio": _hhmm(row[6]),
        "tem_periodo": bool(row[7]),
        "hora_fim": _hhmm(row[8]),
        "data_solicitacao": row[9].isoformat() if row[9] else None,
        "solicitante": row[10] or "",
        "contato_whatsapp": row[11],
        "cor": row[12] or COR_PADRAO,
        "coluna_id": row[13],
        "coluna": row[14],
        "anexos": anexos,
        "criado_por": row[16],
        "criado_por_nome": row[17],
        "created_at": row[18].isoformat() if row[18] else None,
        "updated_at": row[19].isoformat() if row[19] else None,
        "anotacoes_qtd": int(row[20] or 0),
    }


def _filtros(municipio_id, de, ate, coluna_id, busca,
             municipios_permitidos=None, municipio_ids=None) -> tuple[str, dict]:
    """O WHERE compartilhado pela lista E pelo relatório.

    ⚠️ FUNÇÃO ÚNICA DE PROPÓSITO. É o que garante que o relatório traga
    exatamente as linhas que a tela mostra. Duas montagens de filtro divergem no
    primeiro ajuste, e a divergência aparece como "o relatório veio com um
    compromisso a mais" — sem nada para culpar.

    ⚠️ `municipios_permitidos` É O RECORTE DO PEDIDO "TODOS", e ele existe
    porque a primeira versão deste módulo mentia sobre ele. O comentário da tela
    dizia que, sem `municipio_id`, "o backend devolve o que o alcance da pessoa
    permite" — e não devolvia: não havia recorte nenhum aqui, e o que impedia o
    tenant inteiro de sair era o 403 de `ensure_municipio_access(user, None)`.
    Ou seja, a opção «todos os municípios» respondia 403 para TODO usuário que
    não fosse o super-admin da Alavank, que é o único com carteira `None`.

    Agora o pedido "todos" significa **todos OS MEUS**, com o mesmo desenho do
    `routers/convenios.py` (que já resolvia isto): carteira restrita vira um
    `= ANY`, carteira `None` (super-admin) não filtra, e carteira VAZIA devolve
    lista vazia — nunca o tenant inteiro.

    ⚠️ `municipio_ids` É O FILTRO DA TOOLBAR e ele se SOMA ao recorte da
    carteira, nunca o substitui: é escolha do usuário sobre o que ele já pode
    ver. Marcar cidades no filtro nunca pode alcançar uma que a carteira não
    tenha.
    """
    where, params = [], {}
    if municipio_id:
        where.append("a.municipio_id = :m"); params["m"] = municipio_id
    elif municipios_permitidos is not None:
        # ⚠️ `= ANY(:mids)` e não `IN :mids`: o SQLAlchemy só expande `IN` com
        # `expanding=True`, e sem isso a lista chega como um parâmetro só.
        where.append("a.municipio_id = ANY(:mids)")
        params["mids"] = list(municipios_permitidos)
    if municipio_ids:
        where.append("a.municipio_id = ANY(:mfiltro)")
        params["mfiltro"] = list(municipio_ids)
    if de:
        where.append("a.data >= :de"); params["de"] = de
    if ate:
        where.append("a.data <= :ate"); params["ate"] = ate
    if coluna_id:
        where.append("a.coluna_id = :k"); params["k"] = coluna_id
    if busca:
        # ⚠️ TRÊS CAMPOS, E SÓ ELES (decisão do dono): nome do município,
        # demanda e solicitante. Varrer também o contato faria uma busca por
        # "99" devolver metade da agenda; varrer as anotações faria a linha
        # aparecer por um texto que a tela nem mostra na lista.
        alvos = " OR ".join(
            f"{_sql_sem_acento(c)} LIKE :q"
            for c in ("m.nome", "a.demanda", "a.solicitante"))
        where.append(f"({alvos})")
        params["q"] = f"%{_sem_acento(busca)}%"
    return (" WHERE " + " AND ".join(where) if where else ""), params


def _carteira(current, municipio_id):
    """O recorte de município de um pedido de LEITURA em lote.

    Devolve `(permitidos, vazia)`:
      - `municipio_id` presente  -> (None, False): o filtro é ele, e quem valida
        o acesso é `ensure_municipio_access`, chamado pelo endpoint.
      - ausente, carteira restrita -> (a carteira, False): "todos os MEUS".
      - ausente, super-admin       -> (None, False): sem filtro, é o alcance dele.
      - ausente, carteira VAZIA    -> (None, True): não há o que listar. Devolver
        sem filtro aqui seria entregar o tenant inteiro a quem não alcança
        município nenhum.
    """
    if municipio_id:
        return None, False
    permitidos = getattr(current, "allowed_municipio_ids", None)
    if permitidos is None:
        return None, False
    if not permitidos:
        return None, True
    return list(permitidos), False


async def _exigir_acesso(db: AsyncSession, aid: int, user) -> None:
    """Os dois recortes de todo endpoint que fala de UM compromisso.

    Num lugar só porque são cinco (ler, editar, mover, apagar, baixar anexo) e
    porque o nome da tabela vira literal de SQL lá dentro: uma cópia divergente é
    uma porta que continua aberta sem ninguém notar. Mesmo desenho do `gestao`."""
    authz.exigir_tela(user, "agendamentos")
    await authz.ensure_dono(db, "agendamentos", "id", aid, user)


async def _contexto(db: AsyncSession, aid: int) -> dict:
    """Município e demanda da linha, para a trilha dizer SOBRE QUAL."""
    row = (await db.execute(text(
        "SELECT municipio_id, demanda, data FROM agendamentos WHERE id = :id"
    ), {"id": aid})).first()
    if not row:
        return {}
    return {"municipio_id": row[0], "demanda": row[1],
            "data": row[2].isoformat() if row[2] else None}


async def _anotacoes(db: AsyncSession, aid: int) -> list[dict]:
    """O histórico, do mais antigo para o mais recente.

    ⚠️ ORDEM CRESCENTE, e ela é do desenho da tela: o campo de escrever fica
    embaixo, então a anotação nova aparece logo acima dele — que é onde o olho
    já está. Invertida, cada anotação nova empurraria o histórico para longe do
    campo que acabou de ser usado."""
    rows = (await db.execute(text("""
        SELECT n.id, n.autor_id, u.name, n.texto, n.created_at
          FROM agendamentos_anotacoes n
          LEFT JOIN users u ON u.id = n.autor_id
         WHERE n.compromisso_id = :id
         ORDER BY n.created_at ASC, n.id ASC
    """), {"id": aid})).fetchall()
    return [{"id": r[0], "autor_id": r[1], "autor": r[2],
             "texto": r[3], "criado_em": r[4].isoformat() if r[4] else None}
            for r in rows]


async def _colunas(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(text(
        "SELECT id, nome, ordem, fixa, chave, cor FROM agendamentos_colunas "
        "ORDER BY ordem ASC, id ASC"))).fetchall()
    return [{"id": r[0], "nome": r[1], "ordem": r[2], "fixa": bool(r[3]),
             "chave": r[4], "cor": r[5] or COR_COLUNA_PADRAO} for r in rows]


async def _coluna_de_entrada(db: AsyncSession) -> int:
    """O id de «Solicitada» neste banco. SERIAL não promete o mesmo número nos
    cinco tenants — por isso a busca é pela `chave`, nunca por `id = 1`."""
    rid = (await db.execute(text(
        "SELECT id FROM agendamentos_colunas WHERE chave = :c"),
        {"c": COLUNA_ENTRADA})).scalar()
    if rid is None:
        raise HTTPException(500, "A coluna «Solicitada» não existe neste banco.")
    return rid


async def _coluna_valida(db: AsyncSession, coluna_id: Optional[int]) -> int:
    if not coluna_id:
        return await _coluna_de_entrada(db)
    existe = (await db.execute(text(
        "SELECT 1 FROM agendamentos_colunas WHERE id = :i"),
        {"i": coluna_id})).scalar()
    if not existe:
        raise HTTPException(422, "Essa coluna do quadro não existe.")
    return coluna_id


# ---------------------------------------------------------------- leitura ---

@router.get("/paleta", dependencies=[exige("agendamentos.ver")])
async def paleta(current: User = Depends(get_current_user)):
    """As cores que o formulário oferece.

    Vem do backend para a tela não ter uma segunda lista: duas listas divergem, e
    a divergência aparece como um compromisso salvo numa cor que os swatches não
    marcam — o usuário abre a edição e nenhuma cor está selecionada."""
    ensure_tela(current, "agendamentos")
    return {"cores": [{"hex": h, "nome": n} for h, n in PALETA],
            "padrao": COR_PADRAO}


@router.get("/colunas", dependencies=[exige("agendamentos.ver")])
async def listar_colunas(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """As colunas do kanban, na ordem do quadro."""
    ensure_tela(current, "agendamentos")
    return {"colunas": await _colunas(db),
            "max": MAX_COLUNAS, "max_customizadas": MAX_COLUNAS_CUSTOMIZADAS}


@router.get("/contexto", dependencies=[exige("agendamentos.ver")])
async def contexto_do_tenant(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """⭐ SE ESTE TENANT PEDE MUNICÍPIO OU NÃO — a resposta vem do backend.

    A tela poderia deduzir contando a lista que a barra lateral carregou, e era
    assim que a tela de Usuários fazia. Só que aquela lista é a CARTEIRA DA
    PESSOA, não o tenant: numa assessoria de 42 municípios, um usuário com um
    município só veria a agenda em modo prefeitura — sem filtro, sem coluna de
    município, e com o campo do formulário escondido. Aqui a contagem é a do
    tenant, e é a mesma para todo mundo que entra."""
    ensure_tela(current, "agendamentos")
    unico = await _municipio_implicito(db)
    return {
        # `True` = tenant de assessoria/consórcio com carteira: a tela mostra
        # município no formulário, no filtro e em cada cartão.
        "multi_municipio": unico is None,
        "municipio_implicito": unico,
    }


@router.get("", dependencies=[exige("agendamentos.ver")])
async def listar(
    municipio_id: Optional[int] = Query(None),
    municipio_ids: Optional[list[int]] = Query(None,
        description="filtro da toolbar (multi-seleção)"),
    de: Optional[date] = Query(None, description="data inicial (inclusive)"),
    ate: Optional[date] = Query(None, description="data final (inclusive)"),
    coluna_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None, description="busca em município/demanda/solicitante"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """A relação filtrada. Alimenta as TRÊS abas e o card lateral."""
    # ⚠️ `ensure_municipio_access` SÓ COM MUNICÍPIO ESCOLHIDO. Chamada com None
    # ela levanta 403 ("Selecione um municipio permitido") para todo usuário de
    # carteira restrita — o que matava a opção «todos os municípios».
    # Quando não há município, quem faz o recorte é `_carteira`, abaixo.
    if municipio_id:
        ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "agendamentos")
    permitidos, vazia = _carteira(current, municipio_id)
    if vazia:
        return {"items": [], "total": 0}
    onde, params = _filtros(municipio_id, de, ate, coluna_id, q,
                            permitidos, municipio_ids)
    # ⚠️ ORDEM CRESCENTE de data E DE HORA. A lista é uma AGENDA: o que vem
    # primeiro é o que acontece primeiro. As outras telas do repo ordenam por
    # `updated_at DESC` porque mostram histórico — aqui isso poria o mês que vem
    # no topo. A hora entra na ordenação porque o kanban e o card lateral
    # empilham compromissos do MESMO dia.
    sql = _SELECT + onde + " ORDER BY a.data ASC, a.hora_inicio ASC, a.id ASC"
    rows = (await db.execute(text(sql), params)).fetchall()
    return {"items": [_row_to_dict(r) for r in rows], "total": len(rows)}


@router.get("/{aid}", dependencies=[exige("agendamentos.ver")])
async def detalhe(
    aid: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Um compromisso COM o histórico de anotações.

    O histórico não vai na listagem de propósito: uma agenda de mês com trinta
    cartões traria trinta históricos para desenhar uma grade que só mostra o
    CONTADOR de anotações."""
    await _exigir_acesso(db, aid, current)
    row = (await db.execute(text(_SELECT + " WHERE a.id = :id"), {"id": aid})).first()
    if not row:
        raise HTTPException(404, "Compromisso não encontrado")
    item = _row_to_dict(row)
    item["anotacoes"] = await _anotacoes(db, aid)
    return item


# ----------------------------------------------------------------- escrita ---

@router.post("", dependencies=[exige("agendamentos.criar")])
async def criar(
    body: CompromissoCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    authz.exigir_tela(current, "agendamentos")
    municipio_id = await _resolver_municipio(db, body.municipio_id)
    # ⚠️ SÓ `authz.exigir_municipio` — que é a família NOVA de travas, sujeita a
    # `AUTHZ_MODO`. Acrescentar aqui `ensure_municipio_access` (família antiga,
    # que nega nos dois modos) faria esta rota passar a bloquear HOJE, fora da
    # janela de observação que o resto do módulo respeita. Ver a skill `authz`.
    authz.exigir_municipio(current, municipio_id)
    _valida_horario(body.hora_inicio, body.tem_periodo, body.hora_fim)
    cor = _valida_cor(body.cor) or COR_PADRAO
    coluna_id = await _coluna_valida(db, body.coluna_id)
    rid = (await db.execute(text("""
        INSERT INTO agendamentos
            (municipio_id, demanda, data, hora_inicio, tem_periodo, hora_fim,
             data_solicitacao, solicitante, contato_whatsapp, cor, coluna_id,
             criado_por)
        VALUES (:m, :dem, :d, :hi, :tp, :hf, :ds, :sol, :zap, :cor, :k, :u)
        RETURNING id
    """), {
        "m": municipio_id, "dem": body.demanda.strip(), "d": body.data,
        "hi": body.hora_inicio,
        # Sem período, a hora de término não é guardada nem que venha no corpo:
        # é o que impede um bloco esticado de reaparecer se o toggle for
        # desmarcado depois de a hora já ter sido digitada.
        "tp": body.tem_periodo, "hf": body.hora_fim if body.tem_periodo else None,
        "ds": body.data_solicitacao, "sol": body.solicitante.strip(),
        "zap": _so_digitos(body.contato_whatsapp), "cor": cor, "k": coluna_id,
        "u": getattr(current, "id", None),
    })).scalar()
    if body.anotacao and body.anotacao.strip():
        await db.execute(text("""
            INSERT INTO agendamentos_anotacoes (compromisso_id, autor_id, texto)
            VALUES (:c, :u, :t)
        """), {"c": rid, "u": getattr(current, "id", None),
               "t": body.anotacao.strip()})
    await db.commit()
    await registrar(
        db, action="agendamentos.create", user=current, request=request,
        target_type="agendamento", target_id=rid, municipio_id=municipio_id,
        alvo_nome=body.demanda,
        details={"demanda": body.demanda, "data": str(body.data),
                 "hora_inicio": _hhmm(body.hora_inicio),
                 "hora_fim": _hhmm(body.hora_fim) if body.tem_periodo else None,
                 "solicitante": body.solicitante, "coluna_id": coluna_id},
    )
    return {"id": rid, "created": True}


@router.put("/{aid}", dependencies=[exige("agendamentos.editar")])
async def atualizar(
    aid: int,
    body: CompromissoUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    await _exigir_acesso(db, aid, current)
    await authz.exigir_dono_da_linha(db, "agendamentos", aid, current)
    antes = await _contexto(db, aid)
    if not antes:
        raise HTTPException(404, "Compromisso não encontrado")

    # ⚠️ `model_fields_set` E NÃO `is not None`. Desmarcar o período (que apaga
    # `hora_fim`) e limpar o contato são edições legítimas que mandam `null`; o
    # teste ingênuo descartaria as duas em silêncio — a pessoa apagaria o
    # término, salvaria, e o bloco continuaria esticado no calendário.
    enviados = body.model_fields_set
    atual = (await db.execute(text(
        "SELECT hora_inicio, tem_periodo, hora_fim FROM agendamentos "
        "WHERE id = :id"), {"id": aid})).first()
    hora_inicio = body.hora_inicio if "hora_inicio" in enviados else atual[0]
    tem_periodo = body.tem_periodo if "tem_periodo" in enviados else atual[1]
    hora_fim = body.hora_fim if "hora_fim" in enviados else atual[2]
    _valida_horario(hora_inicio, tem_periodo, hora_fim)

    campos, params = [], {"id": aid}

    def _marcar(coluna: str, valor) -> None:
        campos.append(f"{coluna} = :{coluna}")
        params[coluna] = valor

    if "municipio_id" in enviados and body.municipio_id:
        # Mesma família de trava do `criar` — ver o comentário de lá.
        authz.exigir_municipio(current, body.municipio_id)
        _marcar("municipio_id", body.municipio_id)
    if "demanda" in enviados and body.demanda is not None:
        _marcar("demanda", body.demanda.strip())
    if "data" in enviados and body.data is not None:
        _marcar("data", body.data)
    if "solicitante" in enviados and body.solicitante is not None:
        _marcar("solicitante", body.solicitante.strip())
    if "data_solicitacao" in enviados:
        _marcar("data_solicitacao", body.data_solicitacao)
    if "contato_whatsapp" in enviados:
        _marcar("contato_whatsapp", _so_digitos(body.contato_whatsapp))
    if "cor" in enviados and body.cor is not None:
        _marcar("cor", _valida_cor(body.cor))
    if "coluna_id" in enviados and body.coluna_id is not None:
        _marcar("coluna_id", await _coluna_valida(db, body.coluna_id))
    # As três do horário andam JUNTAS: mexer numa sem as outras é como o bloco
    # esticado sobrevive ao toggle desmarcado.
    if enviados & {"hora_inicio", "tem_periodo", "hora_fim"}:
        _marcar("hora_inicio", hora_inicio)
        _marcar("tem_periodo", bool(tem_periodo))
        _marcar("hora_fim", hora_fim if tem_periodo else None)

    if not campos:
        return {"id": aid, "updated": False}
    campos.append("updated_at = NOW()")
    await db.execute(text(
        f"UPDATE agendamentos SET {', '.join(campos)} WHERE id = :id"), params)
    await db.commit()

    mudou = {k: (str(v) if isinstance(v, (date, time)) else v)
             for k, v in params.items() if k != "id"}
    await registrar(
        db, action="agendamentos.update", user=current, request=request,
        target_type="agendamento", target_id=aid,
        municipio_id=antes.get("municipio_id"), alvo_nome=antes.get("demanda"),
        details=mudou,
    )
    return {"id": aid, "updated": True}


@router.patch("/{aid}/coluna", dependencies=[exige("agendamentos.editar")])
async def mover_de_coluna(
    aid: int,
    body: ColunaUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Arrastar o cartão de coluna no kanban. Ver o porquê em `ColunaUpdate`."""
    await _exigir_acesso(db, aid, current)
    await authz.exigir_dono_da_linha(db, "agendamentos", aid, current)
    antes = await _contexto(db, aid)
    if not antes:
        raise HTTPException(404, "Compromisso não encontrado")
    coluna_id = await _coluna_valida(db, body.coluna_id)
    nome = (await db.execute(text(
        "SELECT nome FROM agendamentos_colunas WHERE id = :i"),
        {"i": coluna_id})).scalar()
    await db.execute(text(
        "UPDATE agendamentos SET coluna_id = :k, updated_at = NOW() "
        "WHERE id = :id"), {"k": coluna_id, "id": aid})
    await db.commit()
    await registrar(
        db, action="agendamentos.coluna", user=current, request=request,
        target_type="agendamento", target_id=aid,
        municipio_id=antes.get("municipio_id"), alvo_nome=antes.get("demanda"),
        details={"coluna_id": coluna_id, "coluna": nome},
    )
    return {"id": aid, "coluna_id": coluna_id, "coluna": nome}


@router.delete("/{aid}", dependencies=[exige("agendamentos.excluir")])
async def remover(
    aid: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    await _exigir_acesso(db, aid, current)
    await authz.exigir_dono_da_linha(db, "agendamentos", aid, current)
    antes = await _contexto(db, aid)
    if not antes:
        raise HTTPException(404, "Compromisso não encontrado")
    # As anotações vão junto pelo ON DELETE CASCADE da migration: histórico sem
    # compromisso não tem tela nem dono.
    await db.execute(text("DELETE FROM agendamentos WHERE id = :id"), {"id": aid})
    await db.commit()
    await registrar(
        db, action="agendamentos.delete", user=current, request=request,
        target_type="agendamento", target_id=aid,
        municipio_id=antes.get("municipio_id"), alvo_nome=antes.get("demanda"),
        details=antes,
    )
    return {"id": aid, "deleted": True}


# -------------------------------------------------------------- anotações ---

@router.post("/{aid}/anotacoes", dependencies=[exige("agendamentos.editar")])
async def anotar(
    aid: int,
    body: AnotacaoNova,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Acrescenta uma linha ao histórico. Não existe editar nem apagar.

    ⚠️ AQUI NÃO ENTRA `exigir_dono_da_linha`, E É DE PROPÓSITO. O alcance por
    linha restringe quem pode ALTERAR o registro de outra pessoa; anotar não
    altera o compromisso — cria uma linha NOVA, assinada por quem escreveu. O
    documento de redesenho é explícito: «qualquer usuário adiciona; ninguém edita
    nem apaga». Aplicar o alcance aqui faria o técnico restrito aos próprios
    registros não poder responder no compromisso que a secretaria abriu, que é
    justamente a conversa que o histórico existe para guardar."""
    await _exigir_acesso(db, aid, current)
    antes = await _contexto(db, aid)
    if not antes:
        raise HTTPException(404, "Compromisso não encontrado")
    texto = body.texto.strip()
    if not texto:
        raise HTTPException(422, "A anotação não pode ser vazia.")
    nid = (await db.execute(text("""
        INSERT INTO agendamentos_anotacoes (compromisso_id, autor_id, texto)
        VALUES (:c, :u, :t) RETURNING id
    """), {"c": aid, "u": getattr(current, "id", None), "t": texto})).scalar()
    await db.commit()
    await registrar(
        db, action="agendamentos.anotacao", user=current, request=request,
        target_type="agendamento", target_id=aid,
        municipio_id=antes.get("municipio_id"), alvo_nome=antes.get("demanda"),
        # ⚠️ O TEXTO NÃO VAI NA TRILHA. O `audit_log` não se apaga (decisão do
        # dono) e a anotação é campo livre: pode ter nome, telefone e o teor de
        # uma conversa. A trilha registra QUE alguém anotou, e o conteúdo fica
        # onde ele pode ser lido com a permissão do módulo.
        details={"anotacao_id": nid, "tamanho": len(texto)},
    )
    return {"id": nid, "created": True}


# ------------------------------------------------------- colunas do kanban ---

@router.post("/colunas", dependencies=[exige("agendamentos.editar")])
async def criar_coluna(
    body: ColunaNova,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Uma coluna customizada.

    ⚠️ OS DOIS TETOS SÃO CONFERIDOS AQUI, e não só no botão da tela. Duas abas
    abertas contam separado: cada uma vê quatro colunas, cada uma libera o botão,
    e o quadro acaba com seis. Quem conta de verdade é o banco."""
    ensure_tela(current, "agendamentos")
    nome = body.nome.strip()
    if not nome:
        raise HTTPException(422, "A coluna precisa de um nome.")
    colunas = await _colunas(db)
    if len(colunas) >= MAX_COLUNAS:
        raise HTTPException(
            422, f"O quadro comporta {MAX_COLUNAS} colunas — remova uma "
                 f"customizada antes de criar outra.")
    if sum(1 for c in colunas if not c["fixa"]) >= MAX_COLUNAS_CUSTOMIZADAS:
        raise HTTPException(
            422, f"São no máximo {MAX_COLUNAS_CUSTOMIZADAS} colunas próprias.")
    if any(_sem_acento(c["nome"]) == _sem_acento(nome) for c in colunas):
        raise HTTPException(422, f"Já existe uma coluna chamada «{nome}».")
    cor = _valida_cor(body.cor) or COR_COLUNA_PADRAO
    ordem = max((c["ordem"] for c in colunas), default=0) + 1
    rid = (await db.execute(text(
        "INSERT INTO agendamentos_colunas (nome, ordem, fixa, cor) "
        "VALUES (:n, :o, FALSE, :c) RETURNING id"),
        {"n": nome, "o": ordem, "c": cor})).scalar()
    await db.commit()
    await registrar(
        db, action="agendamentos.coluna.create", user=current, request=request,
        target_type="agendamento_coluna", target_id=rid, alvo_nome=nome,
        details={"nome": nome, "ordem": ordem, "cor": cor},
    )
    return {"id": rid, "nome": nome, "ordem": ordem, "fixa": False,
            "chave": None, "cor": cor}


@router.put("/colunas/{cid}", dependencies=[exige("agendamentos.editar")])
async def atualizar_coluna(
    cid: int,
    body: ColunaNova,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Renomeia e recolore — TODAS as colunas, inclusive as três iniciais.

    ⭐ MUDOU EM 05/09/2026 (rodada 1 de ajustes). A regra anterior recusava
    renomear as fixas; o dono reviu: «Solicitada | Em andamento | Concluída» são
    o PONTO DE PARTIDA, não o vocabulário obrigatório de cinco clientes
    diferentes. O que continua valendo é a remoção — fixa não se apaga.

    ⚠️ E RENOMEAR NÃO TOCA NA `chave`. O código acha a coluna de entrada por
    `chave = 'solicitada'` (SERIAL não promete o mesmo id nos cinco bancos);
    o `nome` é só o rótulo da tela. Sem essa separação, renomear «Solicitada»
    quebraria o destino dos cartões de uma coluna removida e o default de todo
    compromisso novo — em silêncio, porque `_coluna_de_entrada` levantaria 500
    só no primeiro cadastro depois da renomeação."""
    ensure_tela(current, "agendamentos")
    colunas = await _colunas(db)
    alvo = next((c for c in colunas if c["id"] == cid), None)
    if not alvo:
        raise HTTPException(404, "Coluna não encontrada")
    nome = body.nome.strip()
    if not nome:
        raise HTTPException(422, "A coluna precisa de um nome.")
    if any(c["id"] != cid and _sem_acento(c["nome"]) == _sem_acento(nome)
           for c in colunas):
        raise HTTPException(422, f"Já existe uma coluna chamada «{nome}».")
    cor = _valida_cor(body.cor) or alvo["cor"]
    await db.execute(text(
        "UPDATE agendamentos_colunas SET nome = :n, cor = :c, updated_at = NOW() "
        "WHERE id = :i"), {"n": nome, "c": cor, "i": cid})
    await db.commit()
    await registrar(
        db, action="agendamentos.coluna.update", user=current, request=request,
        target_type="agendamento_coluna", target_id=cid, alvo_nome=nome,
        details={"de": alvo["nome"], "para": nome, "cor": cor,
                 "fixa": alvo["fixa"]},
    )
    return {"id": cid, "nome": nome, "cor": cor}


@router.delete("/colunas/{cid}", dependencies=[exige("agendamentos.editar")])
async def remover_coluna(
    cid: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Remove uma coluna customizada. Os cartões dela voltam para «Solicitada».

    ⚠️ OS CARTÕES VOLTAM, NÃO SOMEM. `coluna_id` é NOT NULL e a FK impediria o
    DELETE de qualquer jeito — mas o que importa não é o erro do banco: apagar
    uma coluna é arrumar o quadro, e arrumar o quadro não pode apagar
    compromisso. A tela avisa quantos vão voltar antes de confirmar."""
    ensure_tela(current, "agendamentos")
    colunas = await _colunas(db)
    alvo = next((c for c in colunas if c["id"] == cid), None)
    if not alvo:
        raise HTTPException(404, "Coluna não encontrada")
    if alvo["fixa"]:
        raise HTTPException(
            422, f"«{alvo['nome']}» é uma das três colunas fixas do quadro e "
                 f"não pode ser removida.")
    entrada = await _coluna_de_entrada(db)
    movidos = (await db.execute(text(
        "UPDATE agendamentos SET coluna_id = :e, updated_at = NOW() "
        "WHERE coluna_id = :c"), {"e": entrada, "c": cid})).rowcount
    await db.execute(text("DELETE FROM agendamentos_colunas WHERE id = :i"),
                     {"i": cid})
    await db.commit()
    await registrar(
        db, action="agendamentos.coluna.delete", user=current, request=request,
        target_type="agendamento_coluna", target_id=cid, alvo_nome=alvo["nome"],
        details={"nome": alvo["nome"], "compromissos_devolvidos": movidos},
    )
    return {"id": cid, "deleted": True, "compromissos_devolvidos": movidos}


# ------------------------------------------------------------------ anexo ---

@router.get("/{aid}/anexo/{idx}", dependencies=[exige("agendamentos.anexo_baixar")])
async def baixar_anexo(
    aid: int,
    idx: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """O ARQUIVO em si — ofício, comprovante, foto — decodificado do base64.

    Só existe para o que foi anexado ANTES do redesenho de 05/09/2026: o
    formulário novo não anexa. A rota fica porque o documento já está no banco do
    cliente, e tirar a única porta que o entrega seria perder o dado por mudança
    de tela."""
    await _exigir_acesso(db, aid, current)
    row = (await db.execute(text(
        "SELECT anexos, municipio_id, demanda FROM agendamentos WHERE id = :id"
    ), {"id": aid})).first()
    if not row:
        raise HTTPException(404, "Compromisso não encontrado")
    anexos = row[0] or []
    if idx < 0 or idx >= len(anexos):
        raise HTTPException(404, "Anexo não encontrado")
    a = anexos[idx]
    try:
        dados = base64.b64decode(a["dados_b64"])
    except Exception:
        raise HTTPException(500, "Anexo corrompido")
    # Baixar anexo É exportação: o documento sai da plataforma. Entra sob
    # `export.` pela mesma razão dos PDFs — ver `routers/gestao.py`.
    await registrar(
        db, action="export.agendamento_anexo", user=current, request=request,
        target_type="agendamento", target_id=aid, municipio_id=row[1],
        alvo_nome=a.get("nome"),
        details={"compromisso": row[2], "indice": idx, "arquivo": a.get("nome"),
                 "mime": a.get("mime"), "tamanho_bytes": len(dados)},
    )
    return Response(
        content=dados, media_type=a.get("mime") or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{a.get("nome", "anexo")}"'},
    )


# ------------------------------------------------------------- relatorio ---

# ⚠️ TETO DE LINHAS. Sem ele, um filtro largo monta um PDF de milhares de
# páginas na memória do container — e o host tem 2 vCPU compartilhados por 43
# containers. O teto é alto o bastante para qualquer recorte real e devolve 413
# com instrução, em vez de derrubar o worker.
MAX_EXPORT = 5000

PERIODOS = ("dia", "semana", "mes")


def _janela(periodo: str, referencia: date) -> tuple[date, date]:
    """O intervalo fechado do relatório.

    ⚠️ A SEMANA COMEÇA NA SEGUNDA, como a grade do calendário. `weekday()` já dá
    0 na segunda — o `(d + 6) % 7` que a tela usa é porque o `getDay()` do
    JavaScript começa no domingo. Trocar um pelo outro desalinharia o arquivo da
    tela em um dia, que é o tipo de erro que ninguém confere."""
    if periodo == "dia":
        return referencia, referencia
    if periodo == "semana":
        inicio = referencia - timedelta(days=referencia.weekday())
        return inicio, inicio + timedelta(days=6)
    primeiro = referencia.replace(day=1)
    # Dia 1 do mês seguinte menos um dia = último dia deste, sem tabela de meses.
    seguinte = (primeiro + timedelta(days=32)).replace(day=1)
    return primeiro, seguinte - timedelta(days=1)


@router.get("/relatorio/pdf", dependencies=[exige("agendamentos.exportar")])
async def relatorio_pdf(
    request: Request,
    periodo: str = Query("mes", pattern="^(dia|semana|mes)$"),
    referencia: Optional[date] = Query(None, description="data de referência"),
    municipio_id: Optional[int] = Query(None),
    municipio_ids: Optional[list[int]] = Query(None),
    q: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """A agenda do Dia, da Semana ou do Mês, em PDF.

    ⚠️ MESMO `_filtros` DA LISTA. O dono pediu "o relatório respeita o filtro de
    município ativo"; duas montagens de WHERE divergem no primeiro ajuste, e a
    divergência aparece como "o relatório veio com um compromisso a mais" — sem
    nada para culpar."""
    if municipio_id:
        ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "agendamentos")

    permitidos, vazia = _carteira(current, municipio_id)
    if vazia:
        raise HTTPException(403, "Sua conta não alcança nenhum município.")
    ref = referencia or date.today()
    de, ate = _janela(periodo, ref)
    onde, params = _filtros(municipio_id, de, ate, None, q,
                            permitidos, municipio_ids)
    sql = _SELECT + onde + " ORDER BY a.data ASC, a.hora_inicio ASC, a.id ASC"
    rows = (await db.execute(text(sql), params)).fetchall()
    if len(rows) > MAX_EXPORT:
        raise HTTPException(
            413, f"O filtro alcançou {len(rows)} compromissos e o limite de "
                 f"emissão é {MAX_EXPORT}. Estreite o período.")
    itens = [_row_to_dict(r) for r in rows]

    from services import agendamentos_export as ax
    unico = await _municipio_implicito(db)
    conteudo = ax.gerar_pdf(
        itens, periodo=periodo, de=de, ate=ate,
        usuario=getattr(current, "name", None) or getattr(current, "email", ""),
        # Numa prefeitura o cabeçalho nomeia o município (é a identidade do
        # tenant); numa assessoria, quem nomeia cada linha é a coluna Município.
        entidade=await _nome_do_municipio(db, unico) if unico else None,
    )
    nome = f"agendamentos-{periodo}-{ref:%Y-%m-%d}.pdf"

    await registrar(
        db, action="export.agendamentos", user=current, request=request,
        target_type="export", target_id="agendamentos", alvo_nome=nome,
        municipio_id=municipio_id,
        details={
            # ⚠️ O `formato` vai nos FILTROS, e não solto. É a convenção que o
            # `_registrar_export` do `export_pdf.py` já usa.
            "registros": len(itens), "arquivo": nome,
            "filtros": {k: v for k, v in {
                "formato": "pdf", "periodo": periodo, "referencia": str(ref),
                "municipio_id": municipio_id, "municipio_ids": municipio_ids,
                "de": str(de), "ate": str(ate), "q": q,
            }.items() if v not in (None, "", [])} or None,
        },
    )
    return StreamingResponse(
        BytesIO(conteudo), media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={nome}"})


async def _nome_do_municipio(db: AsyncSession, mid: Optional[int]) -> Optional[str]:
    if not mid:
        return None
    row = (await db.execute(text(
        "SELECT nome, uf FROM municipios WHERE id = :i"), {"i": mid})).first()
    return f"{row[0]} - {row[1]}" if row else None
