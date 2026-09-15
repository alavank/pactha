"""TransfereGov - Plano de Acao (Transferencia Especial Federal) e Voluntarias.

DUAS ORIGENS, e nenhuma delas e mais a API interna da SPA (14/09/2026):

  `/buscar` e `/plano-acao/{id}` (detalhe) -> tabela `transferegov_te`,
                   alimentada por `ingestion/transferegov_te.py` a partir da API
                   PUBLICA OFICIAL (`api-publica.transferegov.gestao.gov.br/
                   especiais`) — a listagem nas colunas, a arvore do plano em
                   `detalhe`, os pagamentos em `pagamentos`.
  `/por-cnpj`   -> a mesma API oficial, AO VIVO, filtrando por CNPJ na fonte.

⚠️ A SPA SAIU DAQUI POR INTEIRO. Primeiro a listagem (06/09: ela nao filtrava
por municipio nem por CNPJ no servidor), depois o detalhe (14/09: TRES
requisicoes de saida por CLIQUE, contra a API cuja quota por IP ja deixou a VPS
bloqueada por >6h). O que o detalhe mostrava da SPA — plano, resumo do relatorio
de gestao e extrato — a oficial publica, e o coletor ja guarda.
"""
import os
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from database import get_db
from models import Municipio
from models.user import User
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
import httpx
import unicodedata
from services import authz
from services.natureza import SQL_SO_PREFEITURA
from services.voluntarias_dump import (
    notas_empenho_preferidas, ops_obs_preferido, processo_execucao_preferido, sem_cpf,
    sinais_do_resumo)
from services.registro_rotas import declarado, exige

router = APIRouter(prefix="/api/transferegov", tags=["transferegov"])

# API PUBLICA OFICIAL das Transferencias Especiais (Comunicado no 23/2026 do
# MGI). ⚠️ `api-publica`, e nao `api` — o host sem o prefixo e o que bloqueia.
# Mesmo endereco que o coletor usa (ingestion/transferegov_te._API_PUB); aqui
# serve so a consulta por CNPJ, que nao passa por tabela.
_API_PUB = os.getenv("TE_API_PUBLICA",
                     "https://api-publica.transferegov.gestao.gov.br/especiais")

import logging as _logging
logger = _logging.getLogger("transferegov")


def _dias_restantes(dt_str: Optional[str]) -> Optional[int]:
    """Calcula dias entre hoje e a data de fim de vigencia (dd/mm/yyyy)."""
    if not dt_str:
        return None
    from datetime import date, datetime as _dt
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            d = _dt.strptime(dt_str.strip()[:10], fmt).date()
            return (d - date.today()).days
        except (ValueError, AttributeError):
            continue
    return None


async def _especiais_por_cnpj(cnpj: str) -> list[dict]:
    """Planos de acao de UM CNPJ, pela API publica oficial. Nunca levanta.

    ⭐ SUBSTITUIU UMA VARREDURA NACIONAL POR DUAS REQUISICOES. Ate 06/09/2026
    esta consulta baixava a listagem do Brasil inteiro (~58 mil planos, paginas
    de 5 MB) da API interna da SPA e filtrava o CNPJ em memoria, com orcamento
    de 15s e cache de 1h. Como a fonte rate-limita, o orcamento estourava quase
    sempre: a tela respondia com uma FATIA da base nacional e dava por
    encerrado — se o CNPJ procurado nao tivesse caido nas primeiras paginas, o
    resultado era "nenhum plano", indistinguivel de nao ter plano nenhum.

    A API oficial filtra no servidor: CNPJ -> `id_beneficiario` -> planos
    daquele beneficiario. Duas requisicoes, resposta completa, sem cache e sem
    orcamento para estourar.

    Devolve [] tanto para "CNPJ sem plano" quanto para "fonte fora do ar" — o
    mesmo contrato de antes, para a tela nao estourar 500.
    """
    so_digitos = "".join(c for c in (cnpj or "") if c.isdigit())
    if len(so_digitos) != 14:
        return []
    try:
        async with httpx.AsyncClient(timeout=45) as cli:
            r = await cli.get(f"{_API_PUB}/beneficiarios-especiais",
                              params={"cnpj_beneficiario": so_digitos,
                                      "pagina": 1, "tamanho_da_pagina": 200})
            if r.status_code != 200:
                logger.warning(f"especiais/beneficiarios {so_digitos}: HTTP {r.status_code}")
                return []
            bens = (r.json() or {}).get("data") or []
            if not bens:
                return []
            ben = bens[0]
            planos: list[dict] = []
            pagina, total_paginas = 1, 1
            while pagina <= total_paginas:
                rp = await cli.get(f"{_API_PUB}/planos-acao-especiais",
                                   params={"id_beneficiario": ben.get("id_beneficiario"),
                                           "pagina": pagina, "tamanho_da_pagina": 200})
                if rp.status_code != 200:
                    logger.warning(f"especiais/planos {so_digitos}: HTTP {rp.status_code}")
                    break
                d = rp.json() or {}
                planos.extend(d.get("data") or [])
                total_paginas = int(d.get("total_pages") or 1)
                pagina += 1
            # O beneficiario viaja junto: nome, CNPJ e UF nao vem no plano.
            return [{**p, "_beneficiario": ben} for p in planos]
    except Exception as ex:
        logger.warning(f"especiais por CNPJ {so_digitos}: {str(ex)[:120]} — TE indisponivel")
        return []


def _num_dv(num, dv) -> str | None:
    """'12345' + '6' -> '12345-6' (agência/conta com dígito verificador). Só o
    número quando não há DV; None quando não há número. Usado pra montar os dados
    bancários da emenda Pix (TE), que a API `planos-acao-especiais` já traz."""
    num = str(num or "").strip()
    dv = str(dv or "").strip()
    if not num:
        return None
    return f"{num}-{dv}" if dv else num


@router.get("/buscar", dependencies=[exige("transferegov_especiais.ver")])
async def buscar(
    municipio_id: int = Query(..., description="ID do municipio PACTHA"),
    # Aceita VARIAS situacoes (?situacao=CIENTE&situacao=IMPEDIDO).
    situacao: Optional[list[str]] = Query(None, description="CIENTE, EM_ANALISE, IMPEDIDO, etc (aceita varias)"),
    programa: Optional[str] = Query(None, description="codigo do programa (ex: 09032022)"),
    parlamentar: Optional[str] = Query(None, description="texto livre - busca em codigoEmendaFormatado"),
    emenda: Optional[str] = Query(None, description="codigo da emenda formatado"),
    objeto: Optional[str] = Query(None, description="busca em politicasPublicas"),
    refresh: bool = Query(False, description=(
        "SEM EFEITO desde 06/09/2026: a leitura e direta da tabela e nao ha "
        "mais cache em memoria para invalidar. Continua declarado porque a "
        "tela envia no botao Atualizar (page.tsx:251)."),),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Lista planos de acao do municipio + filtros opcionais.

    ⭐ LE AS COLUNAS DA TABELA, e nao mais o `raw_data` cru.

    Ate 06/09/2026 este endpoint lia `raw_data` e destrinchava as chaves
    camelCase da API interna da SPA (`planoAcaoSituacao`, `valorTotal`, ...).
    Isso amarrava a TELA ao formato de UMA fonte: quando o coletor passou a ler
    a API publica oficial — cujas chaves sao outras (`situacao_plano_acao`,
    `valor_custeio_plano_acao`) — todo `it.get(...)` aqui devolveria None sem
    levantar excecao nenhuma, e a tela ficaria com as colunas vazias em
    silencio.

    As colunas de `transferegov_te` ja guardam o retrato normalizado (e sao o
    que o RM sempre leu). O `raw_data` continua servindo o punhado de campos
    que nao viraram coluna, agora com as chaves da fonte nova.

    ⚠️ O FILTRO POR NOME DO MUNICIPIO SAIU DAQUI. Ele existia como segunda rede
    porque o coletor antigo casava plano->municipio por SUBSTRING DE NOME e
    podia gravar linha de outro municipio. O coletor novo entra pelo CNPJ
    (`municipios.cnpj` -> `id_beneficiario` -> planos daquele beneficiario), e o
    `WHERE municipio_id = :m` ja e exato. Mantido, o filtro passaria a ESCONDER
    plano correto: basta o beneficiario nao repetir o nome do municipio.
    """
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "transferegov_especiais")
    mun = (await db.execute(select(Municipio).where(Municipio.id == municipio_id))).scalar_one_or_none()
    if not mun:
        raise HTTPException(404, "Município não encontrado")

    # Filtros em SQL: sao colunas indexaveis, e filtrar em memoria so fazia
    # sentido quando a origem era um JSON opaco.
    where = ["municipio_id = :m"]
    params: dict = {"m": municipio_id}
    if situacao:
        where.append("upper(coalesce(situacao, '')) = ANY(:sits)")
        params["sits"] = [str(s).upper().strip() for s in situacao]
    if programa:
        where.append("coalesce(programa_codigo, '') ILIKE :prog")
        params["prog"] = f"%{programa}%"
    if parlamentar:
        where.append("(coalesce(parlamentar, '') ILIKE :parl OR coalesce(emenda, '') ILIKE :parl)")
        params["parl"] = f"%{parlamentar}%"
    if emenda:
        where.append("coalesce(emenda, '') ILIKE :em")
        params["em"] = f"%{emenda}%"
    if objeto:
        where.append("coalesce(objeto, '') ILIKE :obj")
        params["obj"] = f"%{objeto}%"

    # Os MARCADORES da listagem saem da arvore do plano (`detalhe`) em SQL, e
    # nao trazendo a arvore inteira: ela tem ~8 KB por plano, e a listagem so
    # precisa de cinco valores dela. `detalhe` NULO (coletor ainda nao passou)
    # da NULL em todos — a tela mostra "—", nunca "sem saldo".
    rows = (await db.execute(text(
        "SELECT plano_acao_id, codigo, programa_codigo, situacao, situacao_trabalho, "
        "       beneficiario_nome, beneficiario_cnpj, uf, emenda, valor_custeio, "
        "       valor_investimento, valor_total, objeto, raw_data, "
        "       detalhe->'conta'->'saldo'->>'saldo_final_gestao_financeira', "
        "       detalhe->'conta'->'saldo'->>'data_saldo_conta', "
        "       (SELECT sum((d->>'vl_total_devolucao')::numeric) "
        "          FROM jsonb_array_elements(coalesce(detalhe->'devolucoes', '[]'::jsonb)) d), "
        "       detalhe->'planos_trabalho'->0->>'data_fim_execucao_plano_trabalho', "
        "       (SELECT string_agg(DISTINCT o->>'nome_orgao_analise_pendente_pt', '; ') "
        "          FROM jsonb_array_elements(coalesce(detalhe->'planos_trabalho', '[]'::jsonb)) pt, "
        "               jsonb_array_elements(coalesce(pt->'orgaos_pendentes', '[]'::jsonb)) o), "
        "       detalhe IS NOT NULL "
        f"  FROM transferegov_te WHERE {' AND '.join(where)} "
        " ORDER BY plano_acao_id DESC"
    ), params)).all()

    items = []
    for r in rows:
        raw = r[13] if isinstance(r[13], dict) else {}
        devolvido = r[16]
        items.append({
            "id": r[0],
            "codigo": r[1],
            "programa_codigo": r[2],
            "programa_id": raw.get("id_programa"),
            "situacao_plano_acao": r[3],
            "situacao_plano_trabalho": r[4],
            "beneficiario_nome": r[5],
            "beneficiario_cnpj": r[6],
            "uf": r[7],
            "politicas_publicas": raw.get("codigo_descricao_areas_politicas_publicas_plano_acao"),
            "emenda_codigo": r[8],
            "valor_custeio": float(r[9] or 0),
            "valor_investimento": float(r[10] or 0),
            "valor_total": float(r[11] or 0),
            "objeto_descricao": r[12],
            "motivo_impedimento": raw.get("motivo_impedimento_plano_acao"),
            # Dados bancários da emenda Pix — a API `planos-acao-especiais` já traz
            # (banco/agência/conta do plano de ação) e o coletor guarda no raw_data;
            # aqui só é exposto. Vazio quando o plano ainda não tem domicílio bancário.
            "banco": raw.get("nome_banco_plano_acao") or (raw.get("codigo_banco_plano_acao") or None),
            "agencia": _num_dv(raw.get("numero_agencia_plano_acao"), raw.get("dv_agencia_plano_acao")),
            "conta": _num_dv(raw.get("numero_conta_plano_acao"), raw.get("dv_conta_plano_acao")),
            "situacao_dado_bancario": raw.get("descricao_situacao_dado_bancario_plano_acao") or None,
            # ⚠️ SEMPRE NULOS, e ja eram: 0 de 800 planos da fonte antiga tinham
            # `dataAtualizacao*` preenchida (medido em 06/09/2026). Ficam no
            # contrato porque some-los seria mexer no formato de saida sem
            # necessidade; a data que a fonte nova de fato tem
            # (`dt_hora_situacao_plano_trabalho`) e outra coisa e seria mentira
            # servi-la com este nome.
            "dt_atualizacao_plano_acao": None,
            "dt_atualizacao_plano_trabalho": None,
            # ⭐ DA ARVORE DO PLANO (API oficial, 14/09/2026). Todos None quando
            # `detalhe_coletado` e False — "nao medido", nunca "zero".
            "detalhe_coletado": bool(r[19]),
            "saldo_conta": float(r[14]) if r[14] is not None else None,
            "saldo_conta_em": r[15],
            # Soma de TODAS as devolucoes do plano. Devolucao e o sinal de que
            # algo deu errado (saldo nao usado, glosa) e ate aqui era invisivel.
            "valor_devolvido": float(devolvido) if devolvido else None,
            "fim_execucao": r[17],
            # Orgaos com analise pendente no plano de trabalho ("quem esta
            # segurando"). A base nacional dessa rota tinha 0 linhas em
            # 14/09/2026 — o campo existe para o dia em que tiver.
            "analise_pendente": r[18] or None,
        })

    return {
        "items": items,
        "total": len(items),
        "municipio": {"id": mun.id, "nome": mun.nome, "uf": mun.uf},
        # ⚠️ SEMPRE 0, e no contrato de proposito. A tela imprime "Cache: Xmin"
        # quando isto e > 0 (page.tsx:375); agora a leitura e direta da tabela,
        # sem cache em memoria, entao 0 e a verdade. Tirar o campo faria o
        # `setCacheAge(r.data.cache_age_seconds)` guardar `undefined`.
        "cache_age_seconds": 0,
    }


def _digits(s) -> str:
    return "".join(c for c in (s or "") if c.isdigit())


def _padrao_like(termo: str) -> str:
    """Termo digitado -> padrao ILIKE que sobrevive ao acento PERDIDO da fonte.

    ⚠️ O portal TransfereGov serve U+FFFD no lugar da letra acentuada e o coletor
    APAGA esse caractere (ingestion/transferegov_voluntarias.py, `_clean`, por
    onde `proponente` passa). O banco guarda, entao, "MUNICPIO DE SO GONALO"
    onde o portal queria "MUNICÍPIO DE SÃO GONÇALO" — e `proponente ILIKE
    '%São%'` nunca casa. Nem `'%Sao%'`: a letra nao foi desacentuada, foi
    DELETADA.

    Nao e teoria. Este mesmo arquivo ja convive com isso em _VOLUNTARIA_LIKE
    ("%enviado para an%lise%") e o upsert do coletor se recusa a sobrescrever
    `objeto` quando o texto novo contem chr(65533). A busca era o unico lugar
    que ignorava a regra.

    A saida e a MESMA do _VOLUNTARIA_LIKE, generalizada: cada caractere
    nao-ASCII do termo vira `%`, que casa a letra presente ("São"), a letra sem
    acento ("Sao") e a letra ausente ("So").

    Escapa ANTES os curingas do LIKE (`\\`, `%`, `_`): sem isso um `_` digitado
    casa qualquer caractere e um `%` sozinho devolve a base inteira. O caractere
    de escape do LIKE no Postgres JA e a barra invertida por padrao — nao ha
    clausula ESCAPE de proposito, para nao depender de standard_conforming_strings.

    Devolve "" para termo vazio: quem chama TEM de pular o filtro nesse caso, e
    nunca mandar "%%" (que traria tudo e pareceria "o filtro nao funciona")."""
    t = (termo or "").strip()
    if not t:
        return ""
    saida = []
    for ch in t:
        if ch in ("\\", "%", "_"):
            saida.append("\\" + ch)
        elif ord(ch) > 127 or len(unicodedata.normalize("NFD", ch)) > 1:
            saida.append("%")
        else:
            saida.append(ch)
    return "%" + "".join(saida) + "%"


@router.get("/por-cnpj", dependencies=[exige("transferegov_cnpj.ver")])
async def por_cnpj(
    cnpj: str = Query(..., description="CNPJ do proponente (com ou sem mascara)"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Consulta TransfereGov por CNPJ (nao entra em relatorio). So o CNPJ, sem UF.
    - Especiais/Plano de Acao: API publica NACIONAL (cache 1h), filtra pelo CNPJ;
    - Voluntarias: do que ja foi coletado no banco (identificacao = CNPJ).
    Nao e escopado por municipio (e o proposito). Voluntarias respeita o escopo
    de municipios do usuario nao-admin.
    """
    ensure_tela(current, "transferegov_cnpj")
    alvo = _digits(cnpj)
    if len(alvo) != 14:
        raise HTTPException(400, "Informe um CNPJ válido (14 dígitos)")

    # 1) Especiais / Plano de Acao — API publica oficial, filtrada por CNPJ na
    #    PROPRIA FONTE (antes: varredura nacional + filtro em memoria).
    especiais = []
    for it in await _especiais_por_cnpj(alvo):
        ben = it.get("_beneficiario") or {}
        codigo = it.get("codigo_plano_acao") or ""
        especiais.append({
            "id": it.get("id_plano_acao"),
            "codigo": codigo or None,
            # Mesma derivacao do coletor (ingestion/transferegov_te.
            # plano_novo_para_linha): `codigo_programa` da fonte perde o zero a
            # esquerda, o codigo do plano nao.
            "programa_codigo": (codigo.rsplit("-", 1)[0] if "-" in codigo else None),
            "situacao": it.get("situacao_plano_acao"),
            "beneficiario_nome": ben.get("nome_beneficiario"),
            "beneficiario_cnpj": ben.get("cnpj_beneficiario"),
            "uf": ben.get("uf_beneficiario"),
            "politicas_publicas": it.get("codigo_descricao_areas_politicas_publicas_plano_acao"),
            "emenda_codigo": it.get("codigo_emenda_parlamentar_formatado_plano_acao"),
            "valor_total": round(float(it.get("valor_custeio_plano_acao") or 0)
                                 + float(it.get("valor_investimento_plano_acao") or 0), 2),
            "objeto_descricao": (it.get("detalhamento_objeto") or it.get("nome_objeto")),
        })
    # Sem try/except aqui: `_especiais_por_cnpj` ja engole a falha da fonte e
    # devolve [], que e o mesmo contrato do `except httpx.HTTPError: pass` que
    # existia neste lugar — com a vantagem de o motivo sair no log de la.

    # 2) Voluntarias/Convenios: base SICONV federal (Brasil inteiro, dados
    #    abertos), por CNPJ. Dado publico -> nao escopado por municipio.
    #    ⚠️ ATRAS DA FLAG SICONV_MODULE (decisao do dono, 10/08/2026): o padrao
    #    do PACTHA e SEM a base SICONV — ela so existe onde o cliente pediu
    #    (hoje: freitas, unica com o coletor agendado). Nos demais tenants a
    #    tabela foi TRUNCADA: consultar e devolver [] deixaria a tela mostrar
    #    "0 convenios encontrados" como se fosse resultado de busca — e modulo
    #    ausente NAO e resultado vazio, e a diferenca entre "procurei e nao
    #    achei" e "nem procuro". A flag viaja no payload (`siconv_module`) e o
    #    frontend esconde a secao inteira; ligar = env SICONV_MODULE=1 SO na
    #    API do tenant — sem build-arg por cliente, sem CI.
    _siconv = os.getenv("SICONV_MODULE") == "1"
    voluntarias = []
    if _siconv:
        rows = (await db.execute(text("""
            SELECT nr_proposta, situacao, proponente, municipio, uf, ano, objeto,
                   vl_global, vl_repasse, nr_convenio, situacao_convenio,
                   vl_desembolsado, dt_assinatura, dt_fim_vigencia
            FROM siconv_federal
            WHERE cnpj = :c
            ORDER BY ano DESC NULLS LAST, id_proposta DESC
            LIMIT 800
        """), {"c": alvo})).fetchall()
        voluntarias = [{
            "numero_proposta": r[0], "situacao": r[1], "proponente": r[2],
            "municipio": r[3], "uf": r[4], "ano": r[5], "objeto": r[6],
            "valor_global": float(r[7]) if r[7] else None,
            "valor_repasse": float(r[8]) if r[8] else None,
            "nr_convenio": r[9], "situacao_convenio": r[10],
            "valor_desembolsado": float(r[11]) if r[11] else None,
            "dt_assinatura": r[12].isoformat() if r[12] else None,
            "dt_fim_vigencia": r[13].isoformat() if r[13] else None,
        } for r in rows]

    return {
        "cnpj": alvo,
        "siconv_module": _siconv,
        "especiais": especiais, "voluntarias": voluntarias,
        "total_especiais": len(especiais), "total_voluntarias": len(voluntarias),
    }


# Status que identifica uma proposta VOLUNTARIA (FREITAS). Alem do classico
# "Proposta/Plano de Trabalho enviado para Analise", a Freitas considera tambem
# voluntarias todas as propostas/planos no PIPELINE de analise/aprovacao/
# complementacao (antes da celebracao): "Aprovados", "em Analise", "em
# Complementacao", "complementado enviada para Analise", "Proposta Aprovada e
# Plano de Trabalho ...", etc. NAO inclui: Prestacao de Contas, Rejeitadas,
# "Em execucao" (convenio ja celebrado). O acento corrompido (U+FFFD) e tratado
# com curinga (an%lise).
_VOLUNTARIA_LIKE = "%enviado para an%lise%"  # mantido p/ compat
_VOLUNTARIA_SQL = (
    "(situacao ILIKE '%plano de trabalho%' "
    "AND (situacao ILIKE '%an%lise%' OR situacao ILIKE '%aprovad%' OR situacao ILIKE '%complementa%') "
    "AND situacao NOT ILIKE '%presta%' AND situacao NOT ILIKE '%rejeitad%')"
)
# REJEITADAS: qualquer status contendo "rejeitad" (Rejeitados / Rejeitados por
# Impedimento tecnico). Tratamos como categoria propria; nao entram na Geral.
_REJEITADA_LIKE = "%rejeitad%"
# ENCERRADAS: instrumento finalizado. Inclui Anulado, Rescindido e Prestacao
# de Contas finalizada (Concluida/Aprovada/Aprovada com Ressalvas).
# Usamos SQL composto pra excluir do Geral.
_ENCERRADA_SQL = (
    "(situacao ILIKE '%anulad%' OR situacao ILIKE '%rescind%' OR "
    "(situacao ILIKE '%presta%' AND (situacao ILIKE '%conclu%' OR situacao ILIKE '%aprovad%')))"
)
# ⭐ VIVA = o CICLO DE VIDA ATIVO: tudo que NAO foi rejeitado nem encerrado.
# E o recorte da tela «Voluntarias» desde 08/2026 (pedido do dono).
#
# O QUE MUDOU E POR QUE. Antes «Voluntarias» era so o PIPELINE DE ANALISE
# (_VOLUNTARIA_SQL) e parava exatamente onde a proposta vira instrumento: no dia
# em que o convenio era celebrado ele SUMIA da tela e reaparecia noutra, chamada
# «Geral». Quem acompanha uma proposta do inicio ao fim tinha de trocar de aba no
# meio do caminho — e, pior, o filtro de situacao da tela e montado a partir das
# LINHAS CARREGADAS (frontend/src/components/TransfereGovPropostas.tsx), entao a
# opcao "Em execucao" nunca podia aparecer ali: as linhas nao chegavam.
#
# ⚠️ NAO INCLUI rejeitadas nem encerradas, de proposito. As duas sao DESFECHO,
# nao trabalho em curso, e cada uma tem aba propria — traze-las para ca faria
# «Voluntarias» duplicar duas telas inteiras e contradizer o proprio nome.
#
# ⚠️ `situacao IS NULL` ENTRA. Linha sem situacao coletada nao e desfecho — e
# ausencia de informacao, e sumir com ela seria afirmar um encerramento que
# ninguem viu. E o mesmo criterio do ramo `geral`, logo abaixo.
_VIVA_SQL = (
    "(situacao IS NULL OR (situacao NOT ILIKE '%rejeitad%' "
    f"AND NOT {_ENCERRADA_SQL}))"
)
# EM QUAL DAS QUATRO TELAS de propostas um instrumento aparece, como expressao SQL.
# Existe para o vinculo do /pac poder LINKAR para a tela certa usando AS MESMAS
# regras que o /voluntarias usa para montar cada categoria — se divergissem, o
# link do PAC levaria a uma tela onde o convenio nao esta, que e pior que nao
# linkar. A ordem repete a do handler `voluntarias`: voluntarias -> rejeitadas ->
# encerradas -> o que sobra. `situacao` NULA cai no ELSE ('geral'), igual ao
# ramo `situacao IS NULL` de la.
# ⚠️ `situacao` sem qualificador: so pode ser usado em consulta onde
# transferegov_propostas e a unica tabela com essa coluna.
_CATEGORIA_SQL = (
    "CASE "
    f"WHEN {_VOLUNTARIA_SQL} THEN 'voluntarias' "
    "WHEN situacao ILIKE '%rejeitad%' THEN 'rejeitadas' "
    f"WHEN {_ENCERRADA_SQL} THEN 'encerradas' "
    "ELSE 'geral' END"
)


# ⭐⭐ AS QUATRO TELAS QUE DIVIDEM ESTA ROTA — e por que a categoria subiu para o
# CAMINHO em 05/09/2026.
#
# «Em execução», «Voluntárias», «Rejeitadas» e «Encerradas» sao QUATRO folhas do
# menu lateral, mas um componente so no frontend
# (`components/TransfereGovPropostas.tsx`) com uma prop `categoria`. Ate aqui a
# categoria vinha em QUERY, e as quatro telas dividiam a chave `transferegov.ver`
# — entao conceder uma concedia as quatro, e o pedido do dono e o oposto: «em
# Federais posso liberar Em execução e não PAC».
#
# ⚠️ GATEAR POR QUERY NAO SERIA TRAVA. O parametro e escolha do cliente: quem
# tivesse so «Rejeitadas» pediria `?categoria=geral` e leria a outra tela. Com a
# categoria no CAMINHO, o gate le o segmento que a rota casou — e ai vale o mesmo
# que quatro rotas separadas, sem quatro copias da mesma query de 200 linhas.
_TELA_POR_CATEGORIA: dict[str, str] = {
    "geral": "transferegov_geral",
    "voluntarias": "transferegov_voluntarias",
    "rejeitadas": "transferegov_rejeitadas",
    "encerradas": "transferegov_encerradas",
}

# As quatro chaves, para o `declarado(...)` da rota. A decisao de QUAL cobrar
# mora no corpo, porque ela depende do caminho.
_CATEGORIA_PERMISSOES: tuple = tuple(
    f"{t}.ver" for t in _TELA_POR_CATEGORIA.values())


def _guarda_categoria(current: User, categoria: str) -> str:
    """Cobra a permissao e a tela DA CATEGORIA PEDIDA. Devolve a chave da tela.

    ⚠️ Categoria desconhecida e 404, e nao "sem filtro": um default que
    devolvesse tudo seria exatamente o furo que este desenho fecha — bastaria
    inventar um nome para escapar do gate."""
    tela = _TELA_POR_CATEGORIA.get((categoria or "").strip().lower())
    if not tela:
        raise HTTPException(404, "Categoria desconhecida")
    authz.exigir(current, f"{tela}.ver")
    ensure_tela(current, tela)
    return tela


@router.get("/lista/{categoria}",
            dependencies=[declarado(*_CATEGORIA_PERMISSOES)])
async def voluntarias(
    categoria: str,
    municipio_id: int = Query(...),
    situacao: Optional[str] = Query(None),
    orgao: Optional[str] = Query(None),
    # BUSCA SEPARADA POR CAMPO. A caixa unica ("nº / proponente / CNPJ") era um OR
    # de tres colunas: nao dava para dizer QUAL numero se procurava, o numero do
    # CONVENIO nem era consultado, e qualquer digito no termo arrastava CNPJs
    # parecidos junto. Cada campo abaixo filtra a SUA coluna.
    instrumento: Optional[str] = Query(None, description="nº do convênio/instrumento (codigo_instrumento ou numero_processo)"),
    proposta: Optional[str] = Query(None, description="nº da proposta (ex.: 048291/2025)"),
    proponente: Optional[str] = Query(None, description="nome do proponente"),
    cnpj: Optional[str] = Query(None, description="CNPJ do proponente, com ou sem máscara"),
    # LEGADO: a caixa unica saiu da tela, mas URLs salvas ainda mandam `search`.
    # Continua valendo — e agora tambem olha o codigo_instrumento, que era o
    # numero que faltava.
    search: Optional[str] = Query(None, description="LEGADO: busca em nº proposta/instrumento/proponente/CNPJ"),
    parlamentar: Optional[str] = Query(None, description="filtra pelo parlamentar (ILIKE)"),
    # Aceitam VARIOS valores (?vigencia=vence30&vigencia=prestacao). Um valor
    # unico chega como lista de um, entao os links antigos dos KPIs do dashboard
    # continuam valendo sem mudanca.
    situacao_contratacao: Optional[list[str]] = Query(None, description="Normal | Clausula Suspensiva | Liminar Judicial (aceita varios)"),
    vigencia: Optional[list[str]] = Query(None, description="vence30 | vence60 | vence90 | vence120 | prestacao (aceita varios)"),
    vig_fim_de: Optional[str] = Query(None, description="fim de vigencia >= AAAA-MM-DD"),
    vig_fim_ate: Optional[str] = Query(None, description="fim de vigencia <= AAAA-MM-DD"),
    # QUEM RECEBE (15/09/2026). O filtro por IBGE traz o que esta sediado na
    # cidade: em Goiania 75% do valor e do Estado de Goias. Sem o parametro a
    # lista traz TUDO, marcado por `municipal`; a tela oferece o filtro.
    recebedor: Optional[str] = Query(None, description="prefeitura | outros"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Lista propostas SICONV de um municipio, filtradas por categoria.

    Dados coletados pelo scraper Playwright (acesso livre guest) em
    transferegov_propostas. Categorias:
      - voluntarias: o CICLO DE VIDA ATIVO — pipeline de analise E instrumentos
              em execucao. Exclui apenas rejeitadas e encerradas. (Era so o
              pipeline de analise ate 08/2026; ver `_VIVA_SQL`.)
      - rejeitadas: status com "Rejeitad"
      - encerradas: Anulado / Rescindido / Prestacao de Contas Concluida/Aprovada
      - geral: a tela «Em execucao» — o que sobra depois de tirar o pipeline de
              analise, as rejeitadas e as encerradas.

    ⚠️ `voluntarias` e `geral` agora SE SOBREPOEM, e isso e intencional: sao
    perguntas diferentes sobre o mesmo dado ("o que esta em andamento?" e "o que
    ja foi celebrado?"). Nenhuma proposta some de aba nenhuma por causa disso.

    ⚠️ A CATEGORIA E OBRIGATORIA e vem do CAMINHO — ver `_TELA_POR_CATEGORIA`.
    Ela deixou de ser um filtro opcional para ser a identidade da tela.
    """
    ensure_municipio_access(current, municipio_id)
    _guarda_categoria(current, categoria)
    where = ["municipio_id = :mun"]
    params: dict = {"mun": municipio_id}
    if categoria == "voluntarias":
        # ⚠️ `_VIVA_SQL`, NAO `_VOLUNTARIA_SQL`. O segundo continua existindo e
        # continua sendo usado — pelo `_CATEGORIA_SQL` (que decide para qual aba
        # o link do PAC aponta) e pelo ramo `geral` logo abaixo, que precisa
        # EXCLUIR o pipeline de analise para nao mostrar proposta nao celebrada
        # numa tela chamada «Em execucao». Trocar os dois por `_VIVA_SQL` faria
        # as duas telas devolverem a mesma coisa.
        where.append(_VIVA_SQL)
    elif categoria == "rejeitadas":
        where.append("situacao ILIKE :rejpat"); params["rejpat"] = _REJEITADA_LIKE
    elif categoria == "encerradas":
        where.append(_ENCERRADA_SQL)
    elif categoria == "geral":
        # Geral = o que sobra: nem voluntaria (pipeline de analise), nem rejeitada,
        # nem encerrada/prestacao. Sobra basicamente "Em execucao" + legados.
        where.append(f"(situacao IS NULL OR (NOT {_VOLUNTARIA_SQL} AND situacao NOT ILIKE :rejpat AND NOT {_ENCERRADA_SQL}))")
        params["rejpat"] = _REJEITADA_LIKE
    if situacao:
        where.append("situacao ILIKE :sit"); params["sit"] = f"%{situacao}%"
    if orgao:
        where.append("orgao ILIKE :org"); params["org"] = f"%{orgao}%"
    if recebedor == "prefeitura":
        where.append(SQL_SO_PREFEITURA)
    elif recebedor == "outros":
        where.append("municipal IS FALSE")
    if parlamentar:
        where.append("parlamentar ILIKE :parl"); params["parl"] = f"%{parlamentar}%"
    if situacao_contratacao:
        # OR entre as escolhidas: "Normal" OU "Liminar Judicial" etc.
        _conds = []
        for _i, _sc in enumerate(situacao_contratacao):
            _conds.append(f"situacao_contratacao ILIKE :sc{_i}")
            params[f"sc{_i}"] = f"%{_sc}%"
        where.append("(" + " OR ".join(_conds) + ")")
    # --- BUSCA POR CAMPO (cada um filtra a SUA coluna, e sao combinados com AND) ---
    if _padrao_like(instrumento or ""):
        # O numero do CONVENIO ("981397"). E o que a tela imprime na meta de cada
        # item ("· instr 981397") e o que titula o modal — e era a UNICA coluna que
        # a busca nao olhava. `numero_processo` entra junto porque e o outro numero
        # do mesmo instrumento, impresso no detalhe: um quinto campo so para ele
        # seria formulario a mais para a mesma pergunta.
        where.append("(codigo_instrumento ILIKE :inst OR numero_processo ILIKE :inst)")
        params["inst"] = _padrao_like(instrumento)
    if _padrao_like(proposta or ""):
        where.append("numero_proposta ILIKE :prop")
        params["prop"] = _padrao_like(proposta)
    if _padrao_like(proponente or ""):
        where.append("proponente ILIKE :propon")
        params["propon"] = _padrao_like(proponente)
    if cnpj:
        # SO OS DIGITOS, dos dois lados: o portal grava com mascara
        # ("18.243.220/0001-01") e o gestor cola dos dois jeitos. Termo sem digito
        # nenhum nao filtra — CNPJ e numero, e casar letra contra CNPJ so daria ruido.
        _c = _digits(cnpj)
        if _c:
            where.append(r"regexp_replace(coalesce(identificacao,''), '\D', '', 'g') LIKE :cnpj")
            params["cnpj"] = f"%{_c}%"
    if search:
        # LEGADO (a tela nao manda mais; links salvos ainda mandam). Duas
        # correcoes: ganhou codigo_instrumento e passou a usar o padrao tolerante
        # ao acento apagado.
        conds = ["numero_proposta ILIKE :s", "codigo_instrumento ILIKE :s",
                 "proponente ILIKE :s", "identificacao ILIKE :s"]
        params["s"] = _padrao_like(search) or f"%{search}%"
        _sd = _digits(search)
        # >= 8 digitos: so entao o termo parece pedaco de CNPJ. Antes QUALQUER
        # numero entrava aqui — buscar "2025" devolvia toda proposta cujo CNPJ
        # contivesse 2025, misturado com os acertos de verdade.
        if len(_sd) >= 8:
            conds.append(r"regexp_replace(coalesce(identificacao,''), '\D', '', 'g') LIKE :sd")
            params["sd"] = f"%{_sd}%"
        where.append("(" + " OR ".join(conds) + ")")
    sql = f"""
        SELECT numero_proposta, situacao, orgao, proponente, possui_parecer,
               identificacao, codigo_instrumento, modalidade, situacao_siafi,
               numero_processo, objeto, programa, dt_inicio_vigencia,
               dt_fim_vigencia, dt_proposta, dt_assinatura, updated_at,
               situacao_contratacao, clausula_suspensiva_dt_prevista,
               clausula_suspensiva_motivo, parlamentar,
               situacao_contratacao_detalhe,
               -- A contagem de licitacoes: a do DUMP quando ha arvore com a
               -- lista (PR 4, 15/09/2026 — a raspagem da tela virou reserva), senao
               -- a raspada. MESMA posicao (row[22]) da coluna que substitui.
               CASE WHEN jsonb_typeof(arvore->'processo_execucao') = 'array'
                    THEN COALESCE((arvore->'_resumo'->>'n_licitacoes')::int,
                                  jsonb_array_length(arvore->'processo_execucao'))
                    ELSE processo_execucao_qtd END,
               -- NO FIM de proposito: o dicionario abaixo le por INDICE.
               natureza_juridica, municipal,
               -- 15/09/2026: SO o resumo da arvore dos dumps (row[25]), e nao
               -- a arvore: ela chega a 1 MB numa proposta, e a lista traz
               -- centenas. Os selos saem de `sinais_do_resumo`.
               arvore->'_resumo'
        FROM transferegov_propostas
        WHERE {' AND '.join(where)}
        ORDER BY numero_proposta DESC
    """
    r = await db.execute(text(sql), params)
    items = [{
        "numero_proposta": row[0], "situacao": row[1], "orgao": row[2],
        "proponente": row[3], "possui_parecer": row[4], "identificacao": row[5],
        "codigo_instrumento": row[6], "modalidade": row[7], "situacao_siafi": row[8],
        "numero_processo": row[9], "objeto": row[10], "programa": row[11],
        "dt_inicio_vigencia": row[12], "dt_fim_vigencia": row[13],
        "dt_proposta": row[14], "dt_assinatura": row[15],
        "dias_restantes": _dias_restantes(row[13]),
        "atualizado_em": row[16].isoformat() if row[16] else None,
        "situacao_contratacao": row[17],
        "clausula_suspensiva_dt_prevista": row[18].isoformat() if row[18] else None,
        "clausula_suspensiva_motivo": row[19],
        "parlamentar": row[20],
        "situacao_contratacao_detalhe": row[21],
        "processo_execucao_qtd": row[22],
        "natureza_juridica": row[23],
        # ⚠️ NULO conta como prefeitura (a fonte nao disse): o selo "nao e da
        # prefeitura" so aparece quando a fonte AFIRMA outra natureza.
        "municipal": row[24] is not False,
        # Selos do dump (vigencia prorrogada, dias sem desembolso, prazo da
        # prestacao de contas, % fisico). None = arvore ainda nao colhida ou
        # proposta sem convenio. Contados HOJE: ver `sinais_do_resumo`.
        "sinais": sinais_do_resumo(row[25]),
    } for row in r.fetchall()]

    # Filtro de vigencia (presets: dias para vencer) — vindo dos KPIs ou do filtro
    if vigencia:
        _LIMITES = {"vence30": 30, "vence60": 60, "vence90": 90, "vence120": 120}
        # So os presets CONHECIDOS entram. Se nada reconhecido sobrar, nao
        # filtramos — mesma leniencia de antes, que deixava passar valor estranho
        # em vez de devolver lista vazia sem explicacao.
        _sel = [v for v in vigencia if v in _LIMITES or v == "prestacao"]
        if _sel:
            def _match_vig(d):
                if d is None:
                    return False
                for _v in _sel:
                    if _v == "prestacao":
                        if d < -90:
                            return True
                    elif 0 <= d <= _LIMITES[_v]:
                        return True
                return False
            items = [i for i in items if _match_vig(i["dias_restantes"])]

    # Filtro por intervalo de DATA de fim de vigencia (de / ate, ISO AAAA-MM-DD)
    if vig_fim_de or vig_fim_ate:
        from datetime import datetime as _dt2
        def _parse_fim(s):
            if not s:
                return None
            for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    return _dt2.strptime(str(s).strip()[:10], fmt).date()
                except (ValueError, TypeError):
                    continue
            return None
        de = _parse_fim(vig_fim_de)
        ate = _parse_fim(vig_fim_ate)
        def _match_range(it):
            d = _parse_fim(it.get("dt_fim_vigencia"))
            if d is None:
                return False
            if de and d < de:
                return False
            if ate and d > ate:
                return False
            return True
        items = [i for i in items if _match_range(i)]

    # Mesma ordenacao do SIGCON: vigentes por urgencia ASC, vencidos depois
    # (|dias| ASC), sem data por ultimo.
    def _sort_key(x):
        d = x["dias_restantes"]
        if d is None:
            return (2, 0)
        if d >= 0:
            return (0, d)
        return (1, -d)
    items.sort(key=_sort_key)

    last = None
    if items:
        last = max((i["atualizado_em"] for i in items if i["atualizado_em"]), default=None)
    return {"items": items, "total": len(items), "atualizado_em": last,
            # Quantas da lista NAO sao da prefeitura (estado sediado na cidade,
            # entidade da sociedade civil, consorcio) — a tela diz isso em vez
            # de esconder. Ver `services/natureza.py`.
            "fora_da_prefeitura": sum(1 for i in items if not i["municipal"])}


@router.get("/voluntarias/{numero_proposta:path}",
            dependencies=[declarado(*_CATEGORIA_PERMISSOES)])
async def voluntarias_detalhe(
    numero_proposta: str,
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Detalhe completo de uma proposta (todos os campos capturados do portal).

    ⚠️ ACEITA QUALQUER UMA DAS QUATRO CATEGORIAS, e nao uma tela especifica: a
    MESMA proposta aparece em «Em execução» ou em «Encerradas» conforme a
    situacao dela, que muda sozinha com o tempo. Exigir a tela exata faria o
    detalhe parar de abrir no dia em que o TransfereGov mudasse o status —
    para o usuario, a linha da lista deixaria de clicar sem explicacao.
    Quem nao tem nenhuma das quatro nao passa daqui."""
    ensure_municipio_access(current, municipio_id)
    if not any(authz.pode(current, chave) for chave in _CATEGORIA_PERMISSOES):
        # Cobra a primeira para a negativa sair com chave, trilha e mensagem
        # normais em vez de um 403 escrito a mao.
        authz.exigir(current, _CATEGORIA_PERMISSOES[0])
    r = await db.execute(text("""
        SELECT numero_proposta, situacao, orgao, proponente, identificacao,
               codigo_instrumento, modalidade, situacao_siafi, numero_processo,
               objeto, programa, dt_inicio_vigencia, dt_fim_vigencia,
               dt_proposta, dt_assinatura, detalhe,
               situacao_contratacao, clausula_suspensiva_dt_prevista,
               clausula_suspensiva_motivo, parlamentar,
               valor_global, valor_repasse, valor_contrapartida,
               situacao_contratacao_detalhe, processo_execucao_qtd,
               historico_comunicacoes, documentos_quadro_resumo, historico_atualizado_em,
               ops_obs, obras, processo_execucao, valor_emenda,
               -- Situacao do Projeto Basico/Termo de Referencia. ULTIMA coluna de
               -- proposito: o dict abaixo le por INDICE, e inserir no meio
               -- deslocaria todos os row[N] seguintes em silencio.
               projeto_basico,
               -- NEs da aba Execucao Concedente. ULTIMA coluna, mesma razao do
               -- projeto_basico: o dict abaixo le por INDICE.
               notas_empenho,
               -- ⚠️ A SITUACAO DO TR QUE VEM DO CSV PUBLICO, e nao da tela logada.
               --
               -- `projeto_basico` (row[32]) e o JSONB do scraper autenticado e vem
               -- NULO na pratica: ele exige o SP `execucao` da sessao gov.br
               -- quente, e a auditoria mediu esse SP frio ("SP execucao frio" 519x,
               -- sessao morta 298 de 720 horas em 30 dias). Enquanto isso,
               -- `situacao_projeto_basico` chega no `siconv_proposta.zip` desde
               -- 31/08 (transferegov_opendata.py:426), esta preenchida em 2.799 de
               -- 3.200 propostas do freitas, e NENHUMA tela a lia.
               --
               -- Medido em 03/09/2026: o convenio 981397/2025 de Araujos, que o
               -- dono relatou "sem termo de referencia", tem aqui "Em Analise" —
               -- exatamente a informacao que faltava na tela.
               --
               -- ULTIMA coluna, pela mesma razao das duas acima: o dict le por
               -- INDICE e inserir no meio desloca tudo em silencio.
               situacao_projeto_basico,
               -- 15/09/2026, depois dela pelo mesmo motivo: quem recebe.
               natureza_juridica, municipal,
               -- 15/09/2026: a ARVORE dos dumps de Discricionarias (row[37..40]),
               -- no fim pela mesma razao de todas as de cima.
               arvore, arvore_atualizado_em, ops_obs_aberto, notas_empenho_aberto
        FROM transferegov_propostas
        WHERE municipio_id = :mun AND numero_proposta = :num
    """), {"mun": municipio_id, "num": numero_proposta})
    row = r.first()
    if not row:
        raise HTTPException(404, "Proposta não encontrada")
    # ⭐ O desembolso vem do DUMP quando ha (ver `ops_obs_preferido`), completado
    # com NS/OP/situacao da raspagem onde o numero da OB bate. A aba OPs/OBs e o
    # RM passam a dizer a mesma coisa.
    _ops, _ops_fonte = ops_obs_preferido(row[39], row[28])
    # PR 4 (15/09/2026): as NEs e as licitacoes tambem saem do dump primeiro — a
    # raspagem das duas telas (sessao gov.br) virou reserva. As MESMAS funcoes do
    # RM, para o modal e o relatorio dizerem a mesma coisa.
    _arv = row[37] if isinstance(row[37], dict) else {}
    _nes, _nes_fonte = notas_empenho_preferidas(row[40], row[33])
    _pe, _pe_qtd, _pe_fonte = processo_execucao_preferido(
        _arv.get("processo_execucao"), (_arv.get("_resumo") or {}).get("n_licitacoes"),
        row[30], row[24])
    return {
        "numero_proposta": row[0], "situacao": row[1], "orgao": row[2],
        "proponente": row[3], "identificacao": row[4], "codigo_instrumento": row[5],
        "modalidade": row[6], "situacao_siafi": row[7], "numero_processo": row[8],
        "objeto": row[9], "programa": row[10], "dt_inicio_vigencia": row[11],
        "dt_fim_vigencia": row[12], "dt_proposta": row[13], "dt_assinatura": row[14],
        "detalhe": row[15] or {},
        "situacao_contratacao": row[16],
        "clausula_suspensiva_dt_prevista": row[17].isoformat() if row[17] else None,
        "clausula_suspensiva_motivo": row[18],
        "parlamentar": row[19],
        "valor_global": float(row[20]) if row[20] is not None else None,
        "valor_repasse": float(row[21]) if row[21] is not None else None,
        "valor_contrapartida": float(row[22]) if row[22] is not None else None,
        "situacao_contratacao_detalhe": row[23],
        # Do dump quando ha (ver `processo_execucao_preferido`), senao a raspada.
        "processo_execucao_qtd": _pe_qtd,
        "processo_execucao_fonte": _pe_fonte,
        "historico_comunicacoes": row[25] or [],
        "documentos_quadro_resumo": row[26] or [],
        "historico_atualizado_em": row[27].isoformat() if row[27] else None,
        "ops_obs": _ops,
        # "dump" | "portal" | None — a tela diz de onde veio.
        "ops_obs_fonte": _ops_fonte,
        "obras": row[29] or None,
        # lista de licitacoes COM situacao (Concluído / Em execução ...)
        "processo_execucao": _pe or [],
        # valores da emenda: valor_emenda vem do CSV; voluntario e proponente
        # sao DERIVADOS (voluntario = repasse - emenda; proponente = contrapartida).
        "valor_emenda": float(row[31]) if row[31] is not None else None,
        "valor_voluntario": (float(row[21]) - float(row[31]))
            if (row[21] is not None and row[31] is not None) else None,
        "valor_proponente": float(row[22]) if row[22] is not None else None,
        # {situacao, documentos:[...]} — o documento que sustenta a clausula
        # suspensiva e em que pe ele esta no portal. None quando a sessao do SP
        # `execucao` estava fria na coleta (nunca {} — ver ingestion/transferegov_http).
        "projeto_basico": row[32] or None,
        # [{numero, minuta, valor, valor_siafi, situacao, dt_emissao, minuta_apenas}]
        # `minuta_apenas` marca a linha que NAO e dinheiro (minuta de R$ 1,00).
        # PR 4: a do DUMP manda e a raspada antiga completa
        # (`notas_empenho_preferidas`); "dump" | "dump+portal" | "portal".
        "notas_empenho": _nes or [],
        "notas_empenho_fonte": _nes_fonte,
        # "Em Análise", "Aprovado", "Em Complementação"... — do CSV publico, e o
        # unico caminho que funciona com a sessao gov.br fria. A tela usa este
        # campo quando `projeto_basico` (a versao rica, logada) nao veio.
        "situacao_projeto_basico": row[34] or None,
        # Quem recebe (15/09/2026): o estado ou a entidade sediada na cidade nao
        # e a prefeitura — ver `services/natureza.py`. NULO conta como prefeitura.
        "natureza_juridica": row[35],
        "municipal": row[36] is not False,
        # A ARVORE do dump (15/09/2026): convenio, emendas, aditivos,
        # prorrogacoes, plano de trabalho, obras, prestacao de contas e o
        # `_resumo`. Linhas CRUAS da fonte, pelos nomes das colunas do CSV — a
        # tela rotula. As listas GRANDES (pagamentos, licitacoes, liquidacoes)
        # nao estao aqui: vem paginadas de `/voluntarias-arvore/{tipo}`.
        # Sem CPF de pessoa fisica (`sem_cpf`). None = ainda nao colhida.
        "arvore": sem_cpf(row[37]) if row[37] else None,
        "arvore_atualizado_em": row[38].isoformat() if row[38] else None,
    }


# As listas GRANDES da arvore dos dumps (15/09/2026): tabela, coluna de data
# (texto dd/mm/aaaa da fonte), colunas devolvidas e onde a busca procura.
_FILHOS = {
    "pagamentos": ("tg_pagamentos", "data_pagamento",
                   "nr_mov_fin, data_pagamento, fornecedor_doc, fornecedor_nome, tipo, "
                   "valor, dados->>'NR_DL', dados->>'DESC_DL', favorecidos",
                   ("fornecedor_nome", "fornecedor_doc")),
    "licitacoes": ("tg_licitacoes", "data_publicacao",
                   "id_licitacao, data_publicacao, numero, modalidade, status, valor, "
                   "dados, contratos, itens",
                   ("numero", "modalidade", "status")),
    "liquidacoes": ("tg_documentos_liquidacao", "data_emissao",
                    "id_dl, data_emissao, numero, descricao, razao_social, valor, status, itens",
                    ("numero", "razao_social", "descricao")),
}


def _filho(tipo: str, row) -> dict:
    if tipo == "pagamentos":
        return {"nr_mov_fin": row[0], "data": row[1], "fornecedor_doc": row[2],
                "fornecedor_nome": row[3], "tipo": row[4],
                "valor": float(row[5]) if row[5] is not None else None,
                "nr_dl": row[6], "desc_dl": row[7], "favorecidos": row[8] or []}
    if tipo == "licitacoes":
        return {"id": row[0], "data": row[1], "numero": row[2], "modalidade": row[3],
                "status": row[4], "valor": float(row[5]) if row[5] is not None else None,
                "dados": row[6] or {}, "contratos": row[7] or [], "itens": row[8] or []}
    return {"id": row[0], "data": row[1], "numero": row[2], "descricao": row[3],
            "razao_social": row[4], "valor": float(row[5]) if row[5] is not None else None,
            "status": row[6], "itens": row[7] or []}


@router.get("/voluntarias-arvore/{tipo}",
            dependencies=[declarado(*_CATEGORIA_PERMISSOES)])
async def voluntarias_arvore_lista(
    tipo: str,
    numero_proposta: str = Query(...),
    municipio_id: int = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    busca: Optional[str] = Query(None, description="fornecedor, número, modalidade..."),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Pagamentos, licitações ou documentos de liquidação de UMA proposta,
    PAGINADOS (15/09/2026 — os dumps de Discricionárias).

    Paginado porque o tamanho é real: medido até 12.868 pagamentos num único
    convênio. O mesmo gate do detalhe (qualquer uma das quatro telas), e o
    município da LINHA — nada de id solto.

    ⚠️ PROPOSTA QUE NÃO É DA PREFEITURA vem com `so_resumo` e sem itens — a
    decisão do dono (opção B) foi guardar só as contas delas. A tela explica em
    vez de mostrar uma lista vazia como se não houvesse pagamento."""
    if tipo not in _FILHOS:
        raise HTTPException(404, "Tipo desconhecido")
    ensure_municipio_access(current, municipio_id)
    if not any(authz.pode(current, chave) for chave in _CATEGORIA_PERMISSOES):
        authz.exigir(current, _CATEGORIA_PERMISSOES[0])
    r = await db.execute(text(
        "SELECT id_proposta_siconv, municipal, arvore->'_resumo' FROM transferegov_propostas "
        "WHERE municipio_id = :mun AND numero_proposta = :num"),
        {"mun": municipio_id, "num": numero_proposta})
    prop = r.first()
    if not prop:
        raise HTTPException(404, "Proposta não encontrada")
    resumo = prop[2] or {}
    base = {"tipo": tipo, "offset": offset, "limit": limit,
            "so_resumo": bool(resumo.get("so_resumo")) or prop[1] is False,
            "resumo": {k: resumo.get(k) for k in ("n_pagamentos", "pago_fornecedores",
                                                  "n_fornecedores", "n_licitacoes",
                                                  "n_liquidacoes")}}
    if not prop[0] or base["so_resumo"]:
        return {**base, "items": [], "total": 0, "soma": None}
    tabela, col_data, cols, onde_busca = _FILHOS[tipo]
    where = ["municipio_id = :mun", "id_proposta = :idp"]
    params: dict = {"mun": municipio_id, "idp": str(prop[0])}
    if busca and busca.strip():
        where.append("(" + " OR ".join(f"{c} ILIKE :b" for c in onde_busca) + ")")
        params["b"] = f"%{busca.strip()}%"
    w = " AND ".join(where)
    tot = (await db.execute(text(f"SELECT count(*), sum(valor) FROM {tabela} WHERE {w}"),
                            params)).first()
    # A data e TEXTO da fonte (dd/mm/aaaa). Ordenar como texto poria 31/01
    # depois de 01/12; o CASE converte so o que tem o formato, sem erro.
    ordem = (f"CASE WHEN {col_data} ~ '^[0-9]{{2}}/[0-9]{{2}}/[0-9]{{4}}' "
             f"THEN to_date(left({col_data}, 10), 'DD/MM/YYYY') END DESC NULLS LAST")
    rows = (await db.execute(text(
        f"SELECT {cols} FROM {tabela} WHERE {w} ORDER BY {ordem}, id DESC "
        f"OFFSET :off LIMIT :lim"), {**params, "off": offset, "lim": limit})).fetchall()
    return {**base, "items": [_filho(tipo, x) for x in rows], "total": int(tot[0] or 0),
            "soma": float(tot[1]) if tot[1] is not None else None}


@router.get("/canceladas", dependencies=[exige("transferegov_rejeitadas.ver")])
async def canceladas(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """As propostas CANCELADAS (`siconv_proposta_cancelada.zip`, 15/09/2026).

    Vêm num arquivo PRÓPRIO, que o PACTHA nunca leu, e a regra de categoria das
    telas não conhece o status "Cancelados" — por isso tabela e rota próprias,
    mostradas na tela de Rejeitadas. Com a marca de quem não é a prefeitura,
    como toda lista de voluntárias."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "transferegov_rejeitadas")
    r = await db.execute(text("""
        SELECT numero_proposta, proponente, natureza_juridica, municipal, objeto, orgao,
               valor_global, dados->>'DIA_PROPOSTA', dados->>'SIT_PROPOSTA',
               dados->>'MODALIDADE'
          FROM tg_propostas_canceladas
         WHERE municipio_id = :mun
         ORDER BY numero_proposta DESC
    """), {"mun": municipio_id})
    items = [{
        "numero_proposta": x[0], "proponente": x[1], "natureza_juridica": x[2],
        "municipal": x[3] is not False, "objeto": x[4], "orgao": x[5],
        "valor_global": float(x[6]) if x[6] is not None else None,
        "dt_proposta": x[7], "situacao": x[8], "modalidade": x[9],
    } for x in r.fetchall()]
    return {"items": items, "total": len(items),
            "fora_da_prefeitura": sum(1 for i in items if not i["municipal"])}


@router.get("/plano-acao/{plano_acao_id}",
            dependencies=[exige("transferegov_especiais.ver")])
async def detalhe(plano_acao_id: int,
                  db: AsyncSession = Depends(get_db),
                  current: User = Depends(get_current_user)):
    """Detalhe completo de um Plano de Acao, INTEIRO DO BANCO: o plano (API
    oficial), a arvore do plano e os pagamentos — nenhuma requisicao de saida.

    ⭐ ATE 14/09/2026 CADA CLIQUE DISPARAVA TRES REQUISICOES a API interna da
    SPA (plano, resumo do relatorio de gestao, extrato), com timeout de 30s
    cada, contra a fonte cuja quota por IP ja deixou a VPS bloqueada por >6h
    (INFRA.md §5). Tudo isso a API oficial publica, e o coletor ja guarda:
      `plano`     -> `raw_data`, o registro de `planos-acao-especiais` (chaves
                     snake_case da fonte) + `_beneficiario`
      `detalhe`   -> a arvore do plano (`ingestion/transferegov_te.
                     arvore_do_plano`): plano de trabalho, executores, empenhos,
                     conta e extrato, relatorios de gestao (com QUEM RECEBEU),
                     devolucoes, historico, programa
      `pagamentos`-> DH -> OP/OB, o MESMO JSON que o RM congela
    A tela passa a mostrar exatamente o dado que o RM le.

    ⚠️ `detalhe` e `pagamentos` NULOS significam "o coletor ainda nao passou
    por este plano", nunca "o plano nao tem nada" — a tela diz a diferenca.
    """
    # ⚠️ A TELA E `transferegov_especiais`. Ate 14/09/2026 este gate cobrava
    # `transferegov`, que deixou de ser TELA em 05/09 (virou so a acao
    # «Atualizar dados», ver services/telas_catalog.py) — ou seja, negava o
    # modal a todo usuario que recebeu a tela nova, que e exatamente quem abre
    # esta tela. So o super-admin passava.
    authz.exigir_tela(current, "transferegov_especiais")
    row = (await db.execute(text(
        "SELECT municipio_id, raw_data, detalhe, pagamentos, detalhe_atualizado_em "
        "  FROM transferegov_te WHERE plano_acao_id = :p"
    ), {"p": plano_acao_id})).first()
    if not row:
        raise HTTPException(404, "Plano de ação não encontrado nesta base")
    # ⭐ AGORA HA MUNICIPIO para conferir. Com o detalhe vindo da SPA, o
    # `plano_acao_id` era so um id federal e o endpoint abria plano de QUALQUER
    # municipio do Brasil a quem tivesse a tela. Vindo da tabela, a linha tem
    # dono: quem so ve Araujos nao abre plano de Nova Serrana pelo id.
    if row[0] is not None:
        ensure_municipio_access(current, row[0])
    fonte_em = None
    try:
        fonte_em = (await db.execute(text(
            "SELECT data_fonte FROM fonte_atualizacao WHERE fonte = 'transferegov_especiais'"
        ))).scalar_one_or_none()
    except Exception:
        await db.rollback()      # tabela ainda nao migrada: o detalhe segue sem a data
    return {
        "plano": row[1] if isinstance(row[1], dict) else None,
        "detalhe": row[2] if isinstance(row[2], dict) else None,
        "pagamentos": row[3] if isinstance(row[3], dict) else None,
        "detalhe_atualizado_em": row[4].isoformat() if row[4] else None,
        "fonte_atualizada_em": fonte_em.isoformat() if fonte_em else None,
    }


# ============================================================================
# ADMIN: status da sessao gov.br + dispara scraper manualmente apos re-captura
# ============================================================================

# `sessoes.ver`, e nao `transferegov.ver`: pelo mesmo motivo que a tela exigida
# no corpo e `sessoes` e nao `transferegov` — o que sai daqui e o estado da
# credencial gov.br guardada no Cofre, nao dado de transferencia. A rota mora
# neste router so por vizinhanca de assunto.
@router.get("/admin/sessao-status", dependencies=[exige("sessoes.ver")])
async def sessao_status(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Retorna idade/validade REAL da sessao gov.br no Cofre.

    Decodifica o JWT 'user-id' das cookies (sessao parcerias.transferegov tem
    expiracao curta ~20min, refrescada com atividade). Retorna minutos
    restantes REAIS, nao so idade da captura."""
    # Antes bastava estar LOGADO — e isto le uma linha do COFRE: devolve a
    # `observacao` da credencial, o municipio dela e os claims do gov.br
    # (vinculo, nivel, expiracao). E o mesmo tipo de vazamento que fez
    # `/api/session-capture/*` ficar de fora da lista do quiosque em
    # services/auth.py.
    #
    # A tela e `sessoes`, e NAO `transferegov` (a do irmao /admin/run-scraper),
    # de proposito: quem le isto e a tela /dashboard/sessoes, que e operacional
    # da Alavank (gestao de credencial gov.br, §12) e por isso nem entra no
    # catalogo oferecido ao cliente (services/telas_catalog.py). Quem chega
    # nessa pagina ja tem `sessoes` — o guard de rota do front usa a mesma
    # chave —, entao a exigencia e invisivel para o uso legitimo e barra
    # exatamente quem chamaria a URL direto.
    #
    # Sem exigencia de municipio: a sessao SSO do gov.br serve varios
    # municipios (a propria busca aqui e "a mais recente, de qualquer um") e
    # amarra-la a um recorte mudaria a logica de negocio, nao acrescentaria gate.
    authz.exigir_tela(user, "sessoes")
    from datetime import datetime, timezone
    from services import crypto
    import base64
    import json as _json
    r = await db.execute(text("""
        -- ⚠️ `municipio_id IS NULL`: mesmo recorte dos outros tres leitores da
        -- sessao (govbr_renew, govbr_keepalive, control.session_status). Linha
        -- COM municipio e credencial de prefeitura, nao sessao do operador — e
        -- uma delas pode conter blob de sessao por causa de capturas antigas,
        -- que mandavam `municipio_id` e gravavam por cima da senha.
        SELECT id, municipio_id, updated_at, observacao, senha_hash
        FROM cofre_senhas
        WHERE automation_key='govbr' AND length(senha_hash) > 1000
          AND municipio_id IS NULL
        ORDER BY updated_at DESC LIMIT 1
    """))
    row = r.first()
    if not row:
        return {"has_session": False, "message": "Nenhuma sessao gov.br capturada"}
    age_h = (datetime.now(timezone.utc) - row[2]).total_seconds() / 3600
    base: dict = {
        "has_session": True,
        "id": row[0],
        "municipio_id": row[1],
        "updated_at": row[2].isoformat(),
        "age_hours": round(age_h, 2),
        "observacao": row[3],
    }
    # Decodifica o JWT 'user-id' (sem validar assinatura) pra ver exp real
    try:
        dec = crypto.decrypt(row[4]) or ""
        data = _json.loads(dec)
        cookies = data.get("cookies", [])
        uid_cookie = next((c for c in cookies if c.get("name") == "user-id"), None)
        if uid_cookie:
            token = uid_cookie.get("value", "")
            parts = token.split(".")
            if len(parts) >= 2:
                payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = _json.loads(base64.urlsafe_b64decode(payload_b64))
                exp_ts = payload.get("exp")
                if exp_ts:
                    now_ts = datetime.now(timezone.utc).timestamp()
                    mins = (exp_ts - now_ts) / 60
                    base["user_id_exp_minutes"] = round(mins, 1)
                    base["expired"] = mins <= 0
                    base["expira_em"] = datetime.fromtimestamp(
                        exp_ts, tz=timezone.utc).isoformat()
                    base["vinculo"] = payload.get("vinculo")
                    base["nivel"] = payload.get("nivel")
                    return base
    except Exception as e:
        base["decode_error"] = str(e)[:100]
    # Fallback: usa idade da captura (sessao tipica ~20 min)
    base["expired"] = age_h > 0.33
    return base


@router.post("/admin/run-scraper",
             dependencies=[exige("transferegov.atualizar")])
async def run_scraper_manual(
    municipio_id: Optional[int] = Query(None, description="se None, roda todos"),
    user=Depends(get_current_user),
):
    """Dispara o scraper voluntarias manualmente (background). Util apos
    re-capturar a sessao gov.br via bookmarklet."""
    ensure_municipio_access(user, municipio_id)
    # ⚠️ A TELA E `sessoes`, e nao uma do grupo FEDERAIS. O botao que chama isto
    # mora em Configuracoes › Sessões (gov.br) — a coleta so anda com uma sessao
    # autenticada recem-capturada, e e la que se re-captura. Ate 05/09/2026 aqui
    # se exigia a tela `transferegov`, que deixou de existir quando o grupo foi
    # dividido em oito telas; cobrar uma das oito seria escolher ao acaso qual
    # delas "abre o botao" que nao esta em nenhuma.
    ensure_tela(user, "sessoes")
    import asyncio as _aio
    from ingestion.transferegov_voluntarias import run, run_one

    async def _bg():
        try:
            if municipio_id:
                await run_one(municipio_id)
            else:
                await run()
        except Exception as e:
            import logging
            logging.getLogger("scraper-manual").exception(f"erro: {e}")

    _aio.create_task(_bg())
    return {"ok": True, "scope": "single" if municipio_id else "all",
            "message": "Scraper iniciado em background. Acompanhe via logs."}


@router.get("/pac", dependencies=[exige("transferegov_pac.ver")])
async def listar_pac(
    municipio_id: int = Query(..., description="ID do municipio PACTHA"),
    parlamentar: Optional[str] = Query(None, description="filtra pela emenda parlamentar (parcial)"),
    situacao: Optional[str] = Query(None, description="filtra a situacao (parcial)"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Selecao PAC / Novo PAC do municipio (coletado do TransfereGov Acesso Livre,
    tabela transferegov_pac). Retorna a listagem por municipio."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "transferegov_pac")
    where = ["municipio_id = :m"]
    params: dict = {"m": municipio_id}
    if parlamentar:
        where.append("emenda_parlamentar ILIKE :p"); params["p"] = f"%{parlamentar}%"
    if situacao:
        where.append("situacao ILIKE :s"); params["s"] = f"%{situacao}%"
    sql = f"""
        SELECT numero_proposta, programa, programa_codigo, proponente, cnpj, situacao,
               valor_repasse, valor_contrapartida, valor_total, emenda_parlamentar,
               qualificacao, objeto, justificativa, updated_at
        FROM transferegov_pac WHERE {' AND '.join(where)}
        ORDER BY numero_proposta DESC
    """
    rows = (await db.execute(text(sql), params)).fetchall()

    # === ELO INVERSO: PAC -> VOLUNTARIA/CONVENIO ============================
    # O RM ja resolve o sentido "de qual selecao do PAC esta voluntaria nasceu"
    # (services/rm_builder._pac_da_voluntaria, usado para nao imprimir o mesmo
    # recurso duas vezes). A TELA do PAC precisa do caminho contrario: dado um
    # item da selecao, QUAL instrumento nasceu dele.
    #
    # ⚠️ SEGUNDA CONSULTA, e nao coluna nova no SELECT acima: o dict logo abaixo le
    # por INDICE (r[0]..r[13]) e uma coluna no meio deslocaria tudo em silencio.
    #
    # ⚠️ A leitura do JSONB acontece no BANCO, e nao em Python: trazer a coluna
    # `detalhe` inteira de todas as propostas do municipio so para ler UMA chave
    # poria alguns MB no fio a cada abertura da tela, e o host e burstable de
    # 2 vCPU. Com o LATERAL sai UMA linha por proposta que TEM vinculo.
    #
    # ⚠️ O pre-filtro `p.detalhe::text ILIKE '%novo pac%'` NAO e redundante com o
    # `lower(kv.key) LIKE` de dentro: sem ele o LATERAL expande TODAS as chaves de
    # TODAS as propostas do municipio (dezenas por proposta) para so entao
    # descartar. Ele derruba o conjunto para as ~35 propostas que tem o campo,
    # ANTES da expansao. E o que torna isto viavel num host de 2 vCPU.
    #
    # ⚠️ `lower(kv.key) LIKE '%novo pac%'` e o equivalente SQL da busca tolerante de
    # `_pac_da_voluntaria` (que normaliza NFD e procura "novo pac"): o trecho
    # procurado nao tem acento nenhum, so o resto do rotulo tem. Se um dia o rotulo
    # do portal mudar, os DOIS lados precisam mudar juntos.
    vinc_sql = rf"""
        SELECT regexp_replace(kv.value, '\D', '', 'g') AS pac_digitos,
               p.numero_proposta, p.codigo_instrumento, p.situacao,
               p.dt_inicio_vigencia, p.dt_fim_vigencia, p.valor_repasse,
               {_CATEGORIA_SQL} AS categoria
        FROM transferegov_propostas p
        CROSS JOIN LATERAL jsonb_each_text(
            CASE WHEN jsonb_typeof(p.detalhe) = 'object' THEN p.detalhe ELSE '{{}}'::jsonb END
        ) AS kv
        WHERE p.municipio_id = :m
          AND p.detalhe::text ILIKE '%novo pac%'
          AND left(kv.key, 1) <> '_'
          AND lower(kv.key) LIKE '%novo pac%'
          AND regexp_replace(kv.value, '\D', '', 'g') <> ''
    """
    por_pac: dict[str, list[dict]] = {}
    try:
        for v in (await db.execute(text(vinc_sql), {"m": municipio_id})).fetchall():
            por_pac.setdefault(v[0], []).append({
                "numero_proposta": v[1],
                "codigo_instrumento": v[2],
                "situacao": v[3],
                "dt_inicio_vigencia": v[4],
                "dt_fim_vigencia": v[5],
                "valor_repasse": float(v[6]) if v[6] is not None else None,
                "dias_restantes": _dias_restantes(v[5]),
                # Em qual das quatro telas de propostas o instrumento esta —
                # calculado com AS MESMAS constantes do /voluntarias (_CATEGORIA_SQL).
                "categoria": v[7],
            })
    except Exception as ex:
        # Best-effort, igual ao bloco do PAC no rm_builder: tenant onde as
        # voluntarias nunca foram raspadas nao pode PERDER a listagem do PAC por
        # causa do vinculo. Sem vinculo a tela mostra o que sempre mostrou.
        logger.warning(f"PAC: vinculo com voluntarias indisponivel p/ {municipio_id}: {str(ex)[:120]}")

    def _f(v):
        return float(v) if v is not None else None
    items = [{
        "numero_proposta": r[0], "programa": r[1], "programa_codigo": r[2],
        "proponente": r[3], "cnpj": r[4], "situacao": r[5],
        "valor_repasse": _f(r[6]), "valor_contrapartida": _f(r[7]), "valor_total": _f(r[8]),
        "emenda_parlamentar": r[9], "qualificacao": r[10],
        "objeto": r[11], "justificativa": r[12],
        # LISTA, e nao um so: nada no portal impede duas propostas apontarem para a
        # mesma selecao, e escolher uma calada esconderia a outra. Vazia = nao ha
        # instrumento CONHECIDO — nao e o mesmo que "nao ha instrumento" (tenant
        # com as voluntarias nunca raspadas cai no mesmo vazio).
        "vinculos": por_pac.get(_digits(r[0]), []),
    } for r in rows]
    atualizado = max((r[13] for r in rows if r[13]), default=None)
    return {"items": items, "total": len(items),
            "atualizado": atualizado.isoformat() if atualizado else None}
