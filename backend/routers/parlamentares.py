"""Tela Parlamentares — lista agregada cross-fonte com detalhe expansivel.

Agrega nomes de parlamentar (deputados/senadores) de 3 fontes:
  - convenios_estadual.raw_data->>'responsaveis' (SIGCON-MG, "EDUARDO AZEVEDO")
  - transferegov_propostas.parlamentar (SICONV federal)
  - emendas_estaduais.nome_responsavel

Normaliza o nome (uppercase + remove acentos) p/ chave de agrupamento,
mas exibe o melhor nome (maior frequencia + sem U+FFFD).

Endpoints:
  GET  /api/parlamentares                    lista agregada
  GET  /api/parlamentares/{nome_norm}        lancamentos detalhados desse parlamentar
"""
from __future__ import annotations
import unicodedata
from services.nome_parlamentar import (
    e_parlamentar_real, e_pessoa, emendas_saude_por_autor, propostas_saude_por_autor)
from typing import Optional
from collections import defaultdict
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from services.registro_rotas import exige
from services.bi import anos_list
from models.user import User

router = APIRouter(prefix="/api/parlamentares", tags=["parlamentares"])


class _SkipPlanoAcao(Exception):
    """Sentinela p/ pular o fetch AO VIVO do RP9 quando incluir_plano_acao=False.
    Capturado pelo `except Exception` que ja envolve o bloco (degradacao silenciosa)."""


def _norm(s: str) -> str:
    """Normaliza p/ chave de agrupamento: uppercase + sem acentos + 1 espaco."""
    if not s:
        return ""
    s = s.replace("�", "").strip()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = " ".join(s.upper().split())
    return s


def _money(v) -> float:
    try: return float(v or 0)
    except (TypeError, ValueError): return 0.0


def _fns_label(mun_nome: str) -> str:
    """Rotulo do 'parlamentar' para lancamentos FNS: o Fundo Municipal de Saude
    do municipio. O autor da emenda de saude nao vem na base coletada, entao o
    FMS/municipio entra como proponente (mesma logica do PAC)."""
    return f"FUNDO MUNICIPAL DE SAÚDE — {mun_nome}"


@router.get("", dependencies=[exige("parlamentares.ver")])
async def listar(
    municipio_id: Optional[int] = Query(None, description="Filtra um municipio (None=todos)"),
    q: Optional[str] = Query(None, description="Busca parcial no nome"),
    ano: Optional[int] = Query(None, description="Filtra por ano (None=todos)"),
    anos: Optional[list[int]] = Query(None, description="Varios anos (mandato); soma-se a `ano`"),
    tipo: str = Query("parlamentar", description="parlamentar (padrao) | outro | todos"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Lista agregada de parlamentares, com totais cross-fonte.

    Retorna:
      [{
        nome_normalizado: "EDUARDO AZEVEDO",
        nome_display: "EDUARDO AZEVEDO",       # melhor representacao
        total_lancamentos: 12,
        valor_total: 1234567.89,
        municipios: ["Araujos", "Bom Despacho"],
        por_fonte: {sigcon: 8, voluntaria: 2, emenda: 2},
        tipo: "parlamentar",                    # ou "outro" (fundo, municipio)
      }, ...]

    `tipo` filtra o que volta e vem "parlamentar" por PADRAO: a tela e de
    parlamentares, e o proponente institucional (Fundo Municipal de Saude,
    Municipio de X) liderava o ranking em valor sem ser gente. O payload traz
    `contagem` com os dois lados, para o seletor da tela oferecer "outros"
    sem precisar de uma segunda chamada.
    """
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "parlamentares")
    return await aggregate_parlamentares(
        db, municipio_id=municipio_id, q=q,
        ano=anos_list((anos or []) + ([ano] if ano else [])),
        tipo=tipo,
    )


async def aggregate_parlamentares(
    db: AsyncSession,
    municipio_id: Optional[int] = None,
    q: Optional[str] = None,
    ano=None,
    incluir_plano_acao: bool = True,
    municipio_ids: Optional[list[int]] = None,
    tipo: str = "todos",
) -> dict:
    """Nucleo da agregacao cross-fonte de parlamentares, SEM gate de auth.

    Reusado pelo endpoint /api/parlamentares (apos ensure_tela) e pelo Painel
    Executivo do prefeito (gated so por municipio). incluir_plano_acao=False pula
    o fetch AO VIVO do RP9 federal (mais rapido, p/ telas snappy).

    `municipio_ids` (lista) = escopo CONSOLIDADO da assessoria: agrega sobre esse
    CONJUNTO (`= ANY(:muns)`). Ignorado quando `municipio_id` (unico) e informado;
    ausentes ambos = todos (comportamento original preservado).

    `tipo`: "parlamentar" (so pessoas) | "outro" (so entidades) | "todos".
    ⚠️ O default e "todos" DE PROPOSITO: seis chamadores (bi.py, painel.py,
    /comparar) ja dependiam do conjunto inteiro. Quem quer o recorte de pessoas
    pede — e os endpoints de TELA pedem "parlamentar". Trocar o default aqui
    mudaria, em silencio, o valor exibido no Painel do prefeito."""
    by_norm: dict[str, dict] = defaultdict(lambda: {
        "nome_normalizado": "",
        "nome_display": "",
        "nome_variants": set(),
        "total_lancamentos": 0,
        "valor_total": 0.0,
        "municipios": set(),
        # ⚠️ `emenda_federal` entra AQUI, e nao so no bloco que a preenche: o
        # bloco roda dentro de `try/except Exception: pass`, entao sem a chave
        # no dicionario o KeyError do primeiro `+= 1` seria ENGOLIDO e a fonte
        # inteira sumiria em silencio, com a tela funcionando.
        "por_fonte": {"sigcon": 0, "voluntaria": 0, "emenda": 0, "plano_acao": 0,
                      "pac": 0, "fns": 0, "emenda_federal": 0},
        # Marcado pelas fontes que entram com PROPONENTE no lugar do autor (PAC
        # sem emenda, FNS). Nao e adivinhacao de texto: a propria origem sabe
        # que ali nao vem nome de pessoa. Vira `tipo` no final e some do payload.
        "_inst": False,
    })

    where_extra = ""
    params: dict = {}
    if municipio_id:
        where_extra = " AND municipio_id = :mun"
        params["mun"] = municipio_id
    elif municipio_ids:
        where_extra = " AND municipio_id = ANY(:muns)"
        params["muns"] = list(municipio_ids)

    # Filtro de ano — a fonte do ano difere por tabela:
    #   convenios_estadual/emendas_estaduais -> coluna `ano`
    #   transferegov_propostas -> derivado do sufixo do numero_proposta ("xxx/AAAA")
    #   emendas_federais_carteira -> coluna `ano` (o ano do PROGRAMA da emenda)
    anos = anos_list(ano)
    ano_sig = ano_vol = ano_em = ""
    if anos:
        ano_sig = " AND ano = ANY(:anos)"
        ano_em = " AND ano = ANY(:anos)"
        ano_vol = " AND split_part(numero_proposta, '/', 2) = ANY(:anos_txt)"
        params["anos"] = anos
        params["anos_txt"] = [str(a) for a in anos]

    # 1) convenios_estadual: SIGCON (responsaveis) E FNS (noAutor/noParlamentar)
    # Federal FNS pode ter campos noAutor, noParlamentar, dsAutor — variações
    # diferentes entre cadastros antigos e emendas individuais.
    sql_sigcon = f"""
        SELECT
            COALESCE(
                raw_data->>'responsaveis',
                raw_data->>'noAutor',
                raw_data->>'noParlamentar',
                raw_data->>'dsAutor',
                raw_data->>'parlamentar',
                ''
            ) AS nome,
            municipio_id,
            (SELECT nome FROM municipios WHERE id=convenios_estadual.municipio_id) AS mun_nome,
            COALESCE(valor_total, valor_concedente, 0) AS valor,
            COALESCE(fonte, '') AS fonte_db
        FROM convenios_estadual
        WHERE (
            raw_data->>'responsaveis' IS NOT NULL
            OR raw_data->>'noAutor' IS NOT NULL
            OR raw_data->>'noParlamentar' IS NOT NULL
            OR raw_data->>'dsAutor' IS NOT NULL
            OR raw_data->>'parlamentar' IS NOT NULL
        )
        {where_extra}{ano_sig}
    """
    for row in (await db.execute(text(sql_sigcon), params)).fetchall():
        for nm in str(row[0] or "").split(","):
            nm = nm.strip()
            # "Não há" NAO e parlamentar. O SIGCON escreve esse texto em
            # `responsaveis` quando nao ha responsavel, e ele estava LIDERANDO o
            # ranking do freitas com R$ 14.936.735,03 em 12 lancamentos e 7
            # municipios — treze vezes o segundo colocado. Ver
            # services/nome_parlamentar.py: a regra mora la porque tres telas
            # leem esta mesma coluna.
            if not e_parlamentar_real(nm):
                continue
            key = _norm(nm)
            if not key:
                continue
            entry = by_norm[key]
            entry["nome_variants"].add(nm)
            entry["total_lancamentos"] += 1
            entry["valor_total"] += _money(row[3])
            if row[2]:
                entry["municipios"].add(row[2])
            # classifica por fonte: FNS é federal, SIGCON-MG é estadual
            fonte_db = (row[4] or "").upper()
            if "FNS" in fonte_db or "MS" in fonte_db:
                entry["por_fonte"]["voluntaria"] += 1  # contagem federal usa esse bucket
            else:
                entry["por_fonte"]["sigcon"] += 1

    # 2) TransfereGov Voluntarias (parlamentar)
    sql_vol = f"""
        SELECT
            parlamentar AS nome,
            municipio_id,
            (SELECT nome FROM municipios WHERE id=transferegov_propostas.municipio_id) AS mun_nome,
            COALESCE(valor_global, valor_repasse, 0) AS valor
        FROM transferegov_propostas
        WHERE parlamentar IS NOT NULL
        AND LENGTH(TRIM(parlamentar)) >= 3
        -- ⚠️ So a PREFEITURA entra no ranking (15/09/2026): a emenda que foi para
        -- o Estado de Goias nao e recurso trazido para a prefeitura de Goiania.
        -- Ver `services/natureza.py`.
        AND municipal IS NOT FALSE
        {where_extra}{ano_vol}
    """
    for row in (await db.execute(text(sql_vol), params)).fetchall():
        for nm in str(row[0] or "").split(","):
            nm = nm.strip()
            if not nm or len(nm) < 3:
                continue
            key = _norm(nm)
            if not key:
                continue
            entry = by_norm[key]
            entry["nome_variants"].add(nm)
            entry["total_lancamentos"] += 1
            entry["valor_total"] += _money(row[3])
            if row[2]:
                entry["municipios"].add(row[2])
            entry["por_fonte"]["voluntaria"] += 1

    # 3) Emendas Estaduais (nome_responsavel)
    sql_em = f"""
        SELECT
            nome_responsavel AS nome,
            municipio_id,
            (SELECT nome FROM municipios WHERE id=emendas_estaduais.municipio_id) AS mun_nome,
            COALESCE(valor_indicacao, 0) AS valor
        FROM emendas_estaduais
        WHERE nome_responsavel IS NOT NULL
        AND LENGTH(TRIM(nome_responsavel)) >= 3
        {where_extra}{ano_em}
    """
    for row in (await db.execute(text(sql_em), params)).fetchall():
        for nm in str(row[0] or "").split(","):
            nm = nm.strip()
            if not nm or len(nm) < 3:
                continue
            key = _norm(nm)
            if not key:
                continue
            entry = by_norm[key]
            entry["nome_variants"].add(nm)
            entry["total_lancamentos"] += 1
            entry["valor_total"] += _money(row[3])
            if row[2]:
                entry["municipios"].add(row[2])
            entry["por_fonte"]["emenda"] += 1

    # 4) Transferencia Especial / Plano de Acao (RP9, "emenda Pix") — DA TABELA.
    #    E por onde chega a maioria das emendas de deputado FEDERAL.
    #
    #    ⚠️ ISTO ERA UM FETCH AO VIVO da API federal e custava 5-7s POR ABERTURA
    #    da tela. Medido em 02/09/2026: 1,8s por pagina da API, ES = 2 paginas,
    #    e o orcamento (`TE_FETCH_BUDGET_S`, default 15s) chegava a cortar MG no
    #    meio. O cache de 1h nao salvava porque vive na MEMORIA DO PROCESSO e o
    #    uvicorn roda `--workers 2`: cada worker aquece o seu, o usuario alterna
    #    entre eles, e todo deploy zera os dois.
    #
    #    O dado ja esta no banco: `transferegov_te`, que o coletor preenche
    #    extraindo o autor do MESMO campo (`codigoEmendaFormatado`, parte apos o
    #    '-') com a mesma regra. Conferido contra o ao vivo em Conceicao da
    #    Barra/ES: mesmos parlamentares, mesmo total (R$ 7.329.500).
    #
    #    Ganho: a tela deixa de depender de API externa instavel, passa a ler o
    #    mesmo dado que a aba do dashboard (services/bi_abas.py) — as duas nao
    #    podem mais divergir por fonte — e o custo vira o de uma query local.
    #
    #    ⚠️ FILTRO POR CNPJ: `transferegov_te` esta contaminada porque o coletor
    #    casa o beneficiario por SUBSTRING do nome, entao "MUNICIPIO DE PARAISO
    #    DO TOCANTINS" cai no municipio mineiro "Tocantins" e "CONCEICAO DA
    #    BARRA DE MINAS" caia aqui. O fetch ao vivo escapava disso so porque
    #    pedia a listagem POR UF. Sem este filtro, trocar a fonte introduziria
    #    lancamento de outro municipio. O `OR` preserva a linha quando falta
    #    CNPJ de um dos lados (municipio sem CNPJ perderia toda a sua TE).
    #
    #    `incluir_plano_acao` deixa de significar "pula o fetch caro" — ficou
    #    como interruptor da fonte, e os chamadores que passavam False (Painel,
    #    /comparar) seguem funcionando.
    ano_te = " AND substr(te.programa_codigo, 5, 4) = ANY(:anos_txt)" if anos else ""
    sql_te = f"""
        SELECT te.parlamentar,
               (SELECT nome FROM municipios WHERE id = te.municipio_id) AS mun_nome,
               COALESCE(te.valor_total, 0) AS valor
        FROM transferegov_te te
        LEFT JOIN municipios m ON m.id = te.municipio_id
        WHERE te.parlamentar IS NOT NULL
          AND (
                te.beneficiario_cnpj IS NULL OR m.cnpj IS NULL
                OR regexp_replace(te.beneficiario_cnpj, '[^0-9]', '', 'g')
                   = regexp_replace(m.cnpj, '[^0-9]', '', 'g')
              )
          {where_extra.replace("municipio_id", "te.municipio_id")}{ano_te}
    """
    try:
        if not incluir_plano_acao:
            raise _SkipPlanoAcao()
        for row in (await db.execute(text(sql_te), params)).fetchall():
            autor = (row[0] or "").strip()
            if not autor or len(autor) < 3:
                continue  # sem emenda nominal (institucional) -> fora do ranking
            key = _norm(autor)
            if not key:
                continue
            entry = by_norm[key]
            entry["nome_variants"].add(autor)
            entry["total_lancamentos"] += 1
            entry["valor_total"] += _money(row[2])
            if row[1]:
                entry["municipios"].add(row[1])
            entry["por_fonte"]["plano_acao"] += 1
    except _SkipPlanoAcao:
        pass
    except Exception:
        pass

    # 5) Selecao PAC / Novo PAC — o PROPONENTE entra como "parlamentar" (ou a
    #    emenda parlamentar quando houver). Fonte: transferegov_pac.
    ano_pac = " AND split_part(numero_proposta, '/', 2) = ANY(:anos_txt)" if anos else ""
    sql_pac = f"""
        SELECT COALESCE(NULLIF(TRIM(emenda_parlamentar), ''), proponente) AS nome,
               municipio_id,
               (SELECT nome FROM municipios WHERE id=transferegov_pac.municipio_id) AS mun_nome,
               COALESCE(valor_total, 0) AS valor,
               (NULLIF(TRIM(emenda_parlamentar), '') IS NULL) AS veio_do_proponente
        FROM transferegov_pac
        WHERE COALESCE(NULLIF(TRIM(emenda_parlamentar), ''), proponente) IS NOT NULL
        {where_extra}{ano_pac}
    """
    try:
        for row in (await db.execute(text(sql_pac), params)).fetchall():
            nm = (row[0] or "").strip()
            if not nm or len(nm) < 3:
                continue
            key = _norm(nm)
            if not key:
                continue
            entry = by_norm[key]
            entry["nome_variants"].add(nm)
            entry["total_lancamentos"] += 1
            entry["valor_total"] += _money(row[3])
            if row[2]:
                entry["municipios"].add(row[2])
            entry["por_fonte"]["pac"] += 1
            # Sem emenda parlamentar, o nome acima E o proponente (o municipio,
            # o consorcio) — entidade, nao pessoa.
            if row[4]:
                entry["_inst"] = True
    except Exception:
        pass

    # 6) FNS — a EMENDA DE SAUDE, ATRIBUIDA AO PARLAMENTAR AUTOR.
    #
    # ⚠️ ESTE BLOCO FOI REESCRITO EM 04/09/2026. A versao anterior partia de "o
    # autor da emenda de saude NAO vem na base coletada (0 parlamentar em todas
    # as propostas)" e, por isso, jogava o valor inteiro do convenio no
    # "FUNDO MUNICIPAL DE SAUDE — X" (via `_fns_label`). A premissa era FALSA:
    # o autor VEM, so que ANINHADO em `raw_data.linhaPropostas[].parlamentares[]`
    # — nunca no nivel raiz. Medido: a emenda "Incremento pap" R$400k do Igor
    # Timo (Nova Serrana) estava no banco e no RM, e sumia desta tela e do Painel.
    #
    # O RM ja le esse aninhamento (services/rm_builder.py, laco do FNS:
    # `ind.get("parlamentares")` -> noApelidoPolitico/noParlamentar/nome). Aqui a
    # MESMA precedencia e o MESMO valor (o da PROPOSTA individual, `vlProposta`),
    # para a tela, o Painel (que reusa esta funcao) e o RM nunca divergirem.
    #
    # ⚠️ O FALLBACK PARA O FUNDO MUNICIPAL CONTINUA — mas so quando a proposta
    # REALMENTE nao tem autor: assim nenhum valor se perde, e o que tem autor
    # deixa de ser escondido atras do fundo. Sem dupla contagem: cada proposta
    # conta OU para os seus parlamentares OU para o fundo, nunca os dois.
    #
    # ⚠️ `jsonb_typeof = 'array'` no WHERE: sem ele, linha FNS antiga sem
    # `linhaPropostas` traria NULL e o laco Python quebraria; com ele, some da
    # varredura (nao tem proposta individual a atribuir).
    sql_fns = f"""
        SELECT municipio_id,
               (SELECT nome FROM municipios WHERE id=convenios_estadual.municipio_id) AS mun_nome,
               raw_data->'linhaPropostas' AS props
        FROM convenios_estadual
        WHERE fonte ILIKE '%FNS%'
          AND jsonb_typeof(raw_data->'linhaPropostas') = 'array'
        {where_extra}{ano_sig}
    """
    try:
        for row in (await db.execute(text(sql_fns), params)).fetchall():
            mun_nome = row[1]
            # `emendas_saude_por_autor` desce no aninhamento e devolve
            # (autor|None, valor) por proposta — a MESMA extracao que o RM usa.
            for autor, val in emendas_saude_por_autor(row[2]):
                # autor None = proposta sem parlamentar -> Fundo Municipal, para
                # o valor nao se perder (o comportamento antigo, agora so aqui).
                nm = autor if autor else (_fns_label(mun_nome) if mun_nome else None)
                if not nm:
                    continue
                key = _norm(nm)
                if not key:
                    continue
                entry = by_norm[key]
                entry["nome_variants"].add(nm)
                entry["total_lancamentos"] += 1
                entry["valor_total"] += val
                if mun_nome:
                    entry["municipios"].add(mun_nome)
                entry["por_fonte"]["fns"] += 1
                if not autor:
                    entry["_inst"] = True
    except Exception:
        pass

    # 7) EMENDAS FEDERAIS (dump SICONV por CNPJ + CGU) — a CARTEIRA por autor.
    #
    # ⭐ O QUE ELA ACRESCENTA. Ate aqui a emenda federal so chegava a esta tela
    # quando virava INSTRUMENTO: TE (bloco 4), proposta voluntaria (bloco 2),
    # PAC (bloco 5) ou proposta do FNS (bloco 6). A emenda INDICADA e ainda nao
    # instrumentalizada nao existia aqui — e ela e 45% da carteira nos dois
    # municipios medidos. O ranking subestimava sistematicamente quem indicou e
    # nao viu o dinheiro sair, que e justamente o parlamentar que o gestor
    # precisa procurar.
    #
    # ⚠️⚠️ O RISCO AQUI E DUPLA CONTAGEM, e ele e maior que em qualquer das seis
    # fontes acima — porque esta le a MESMA base que ja alimenta duas delas:
    #   · `transferegov_propostas.parlamentar` e preenchido por
    #     `ingestion/siconv_emenda_backfill.py`, que le ESTE dump e casa por
    #     `id_proposta_siconv`;
    #   · `transferegov_te.emenda` guarda o codigo no formato '<codigo>-<Nome>'.
    # Somar sem descontar inflaria `valor_total` — e esta funcao alimenta TAMBEM
    # o Painel Executivo do prefeito (`routers/painel.py`) e o BI
    # (`services/bi_abas.py`). Numero inflado no painel do prefeito e pior que
    # fonte faltando: o inflado ninguem confere.
    #
    # Entao o SQL desconta pelas DUAS chaves que existem de verdade. Onde nao ha
    # chave (PAC, FNS) NAO se tenta casar por nome: casamento por nome de autor
    # apagaria emenda legitima, e perder dado bom para evitar dado repetido e o
    # pior dos dois erros.
    #
    # ⚠️ E AQUI NAO HA FILTRO ANTI-CONTAMINACAO POR CNPJ (ao contrario do bloco
    # 4): esta tabela ja NASCE casada por CNPJ na coleta, entao e limpa por
    # construcao. A linha FICA mesmo quando o beneficiario nao e a prefeitura —
    # emenda ao Hospital N. S. da Piedade E emenda daquele parlamentar para
    # aquele municipio, e esconde-la faria o ranking mentir por omissao.
    ano_ef = " AND ef.ano = ANY(:anos)" if anos else ""
    sql_ef = f"""
        SELECT ef.parlamentar,
               (SELECT nome FROM municipios WHERE id = ef.municipio_id),
               COALESCE(ef.valor_repasse_emenda, 0),
               COALESCE(ef.tipo_parlamentar, '')
          FROM emendas_federais_carteira ef
         WHERE ef.parlamentar IS NOT NULL
           AND length(btrim(ef.parlamentar)) >= 3
           AND NOT EXISTS (
                 SELECT 1 FROM transferegov_propostas v
                  WHERE v.parlamentar IS NOT NULL
                    AND v.id_proposta_siconv IS NOT NULL
                    AND v.id_proposta_siconv = ef.id_proposta)
           AND NOT EXISTS (
                 SELECT 1 FROM transferegov_te te
                  WHERE te.parlamentar IS NOT NULL
                    AND ef.codigo_emenda IS NOT NULL
                    AND split_part(te.emenda, '-', 1) = ef.codigo_emenda)
           {where_extra.replace("municipio_id", "ef.municipio_id")}{ano_ef}
    """
    try:
        for row in (await db.execute(text(sql_ef), params)).fetchall():
            nm = (row[0] or "").strip()
            # `e_parlamentar_real` pela mesma razao do bloco 1: a fonte escreve
            # ROTULO no lugar do nome ("RELATOR GERAL" chega assim), e a regra
            # mora em services/nome_parlamentar.py porque tres telas a usam.
            if len(nm) < 3 or not e_parlamentar_real(nm):
                continue
            key = _norm(nm)
            if not key:
                continue
            entry = by_norm[key]
            entry["nome_variants"].add(nm)
            entry["total_lancamentos"] += 1
            entry["valor_total"] += _money(row[2])
            if row[1]:
                entry["municipios"].add(row[1])
            entry["por_fonte"]["emenda_federal"] += 1
            # A ORIGEM sabe que nao e pessoa — mesma precedencia deterministica
            # do PAC (bloco 5) e do FNS (bloco 6), que vem ANTES de `e_pessoa`.
            # Emenda de COMISSAO, BANCADA e RELATOR GERAL e colegiada por
            # definicao: sao 7 dos 35 nomes de autor dos dois municipios medidos.
            if (row[3] or "").strip().upper() in ("COMISSAO", "BANCADA",
                                                  "RELATOR GERAL"):
                entry["_inst"] = True
    except Exception:
        # Degrada em silencio, como as demais: a tabela pode nem existir num
        # tenant onde a migration ainda nao rodou, e uma fonte a menos nao pode
        # derrubar a tela inteira.
        pass

    # Resolve nome_display: prefere a variante mais comum sem U+FFFD
    out = []
    for key, entry in by_norm.items():
        variants = list(entry["nome_variants"])
        # ordena: 1) sem U+FFFD primeiro, 2) mais "completo" (mais espacos)
        variants.sort(key=lambda v: (
            "�" in v,
            -len(v.split()),
            -len(v),
        ))
        entry["nome_normalizado"] = key
        entry["nome_display"] = (variants[0] if variants else key).replace("�", "").strip()
        del entry["nome_variants"]
        entry["municipios"] = sorted(entry["municipios"])
        # `tipo` = "parlamentar" (pessoa) | "outro" (fundo, municipio, consorcio).
        # Duas perguntas, nesta ordem: a ORIGEM ja sabe que nao e pessoa (PAC no
        # proponente, FNS)? Se nao, o NOME denuncia entidade? A origem vem
        # primeiro por ser determinística — nao depende de acertar o texto.
        institucional = entry.pop("_inst", False) or not e_pessoa(entry["nome_display"])
        entry["tipo"] = "outro" if institucional else "parlamentar"
        out.append(entry)

    # Filtro de busca textual
    if q:
        q_norm = _norm(q)
        out = [e for e in out if q_norm in e["nome_normalizado"]]

    # Contagem ANTES do filtro de tipo — o seletor da tela precisa saber quantos
    # existem de cada lado, inclusive do lado que nao esta sendo exibido.
    total_parlamentares = sum(1 for e in out if e["tipo"] == "parlamentar")
    total_outros = len(out) - total_parlamentares

    if tipo in ("parlamentar", "outro"):
        out = [e for e in out if e["tipo"] == tipo]

    # Ordena por total descendente
    out.sort(key=lambda e: (-e["total_lancamentos"], -e["valor_total"]))

    return {
        "items": out,
        "total": len(out),
        "contagem": {"parlamentar": total_parlamentares, "outro": total_outros},
    }


# ---------------------------------------------------------------------------
# Comparacao entre dois periodos
# ---------------------------------------------------------------------------

@router.get("/comparar", dependencies=[exige("parlamentares.ver")])
async def comparar(
    municipio_id: Optional[int] = Query(None),
    a: list[int] = Query(..., description="Anos do periodo A (o mais antigo, referencia)"),
    b: list[int] = Query(..., description="Anos do periodo B (o mais recente, comparado)"),
    q: Optional[str] = Query(None, description="Busca parcial no nome"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Quanto cada parlamentar destinou no periodo A contra o periodo B.

    Os dois periodos sao CONJUNTOS LIVRES de anos — comparar 2024 com 2025, ou
    o mandato inteiro com o anterior, ou dois anos com um. A tela oferece
    atalhos ("Mandato atual x anterior"), mas a regra aqui nao os conhece.

    Reusa `aggregate_parlamentares` DUAS vezes em vez de escrever uma consulta
    propria. E mais lento (duas agregacoes) e vale a pena: a comparacao nunca
    pode discordar da lista que esta na mesma tela, e uma segunda consulta
    "equivalente" e exatamente como as duas divergem com o tempo. Por isso
    tambem `incluir_plano_acao=False` nos dois lados — o fetch AO VIVO do RP9
    federal nao e reproduzivel para um ano passado, entao inclui-lo de um lado
    so criaria uma diferenca que nao existe na realidade.
    """
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "parlamentares")

    anos_a = sorted(set(a))
    anos_b = sorted(set(b))
    if not anos_a or not anos_b:
        raise HTTPException(400, "Informe pelo menos um ano em cada periodo.")
    if set(anos_a) & set(anos_b):
        # Ano nos dois lados infla os dois totais com o mesmo dinheiro e a
        # variacao vira ficcao. Melhor recusar do que devolver numero bonito.
        raise HTTPException(400, "Os dois periodos nao podem compartilhar o mesmo ano.")

    ra = await aggregate_parlamentares(db, municipio_id=municipio_id, q=q,
                                       ano=anos_a, incluir_plano_acao=False)
    rb = await aggregate_parlamentares(db, municipio_id=municipio_id, q=q,
                                       ano=anos_b, incluir_plano_acao=False)

    por_a = {i["nome_normalizado"]: i for i in ra["items"]}
    por_b = {i["nome_normalizado"]: i for i in rb["items"]}

    itens = []
    for chave in set(por_a) | set(por_b):
        ia, ib = por_a.get(chave), por_b.get(chave)
        va = float(ia["valor_total"]) if ia else 0.0
        vb = float(ib["valor_total"]) if ib else 0.0
        delta = vb - va
        # Percentual so existe quando havia base. De 0 para 300 mil nao e
        # "+infinito%": e ENTRADA, e a tela mostra a palavra, nao um numero.
        pct = (delta / va * 100.0) if va > 0 else None
        if va == 0 and vb > 0:
            situacao = "novo"
        elif vb == 0 and va > 0:
            situacao = "saiu"
        elif abs(delta) < 0.005:
            situacao = "igual"
        else:
            situacao = "subiu" if delta > 0 else "caiu"
        itens.append({
            "nome_normalizado": chave,
            "nome_display": (ib or ia)["nome_display"],
            "valor_a": va,
            "valor_b": vb,
            "lancamentos_a": int(ia["total_lancamentos"]) if ia else 0,
            "lancamentos_b": int(ib["total_lancamentos"]) if ib else 0,
            "delta": delta,
            "delta_pct": pct,
            "situacao": situacao,
        })

    # Quem mais mexeu no dinheiro primeiro — em valor absoluto, nao em
    # percentual: +900% de R$ 2 mil nao interessa a ninguem.
    itens.sort(key=lambda i: (-abs(i["delta"]), -max(i["valor_a"], i["valor_b"])))

    ta = sum(i["valor_a"] for i in itens)
    tb = sum(i["valor_b"] for i in itens)
    return {
        "periodo_a": {"anos": anos_a, "rotulo": _rotulo_periodo(anos_a),
                      "total": ta, "parlamentares": len(por_a)},
        "periodo_b": {"anos": anos_b, "rotulo": _rotulo_periodo(anos_b),
                      "total": tb, "parlamentares": len(por_b)},
        # A tela mostra isto junto do total: comparar 2 anos com 4 nao e errado,
        # mas quem le precisa saber que os periodos tem tamanhos diferentes.
        "mesma_duracao": len(anos_a) == len(anos_b),
        "delta": tb - ta,
        "delta_pct": ((tb - ta) / ta * 100.0) if ta > 0 else None,
        "items": itens,
        "total": len(itens),
    }


def _rotulo_periodo(anos: list[int]) -> str:
    """"2021–2024" para anos contiguos, "2021, 2023" para soltos."""
    if len(anos) == 1:
        return str(anos[0])
    contiguo = all(x == anos[i - 1] + 1 for i, x in enumerate(anos) if i)
    return f"{anos[0]}–{anos[-1]}" if contiguo else ", ".join(map(str, anos))


@router.get("/{nome_normalizado:path}",
            dependencies=[exige("parlamentares.ver")])
async def detalhe(
    nome_normalizado: str,
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None, description="Filtra por ano (None=todos)"),
    anos: Optional[list[int]] = Query(None, description="Varios anos (mandato); soma-se a `ano`"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Retorna todos os lancamentos (convenios/propostas/emendas) desse parlamentar."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "parlamentares")
    # Aceita tanto chave normalizada quanto nome livre
    nome_param = nome_normalizado.replace("+", " ")
    # Busca por ILIKE em cada fonte com o nome original (case-insensitive)
    where_extra = ""
    params: dict = {"n": f"%{nome_param}%"}
    if municipio_id:
        where_extra_sigcon = " AND c.municipio_id = :mun"
        where_extra_vol = " AND v.municipio_id = :mun"
        where_extra_em = " AND e.municipio_id = :mun"
        params["mun"] = municipio_id
    else:
        where_extra_sigcon = where_extra_vol = where_extra_em = ""
    # Filtro de ano (fonte do ano difere por tabela — ver endpoint listar)
    _anos = anos_list((anos or []) + ([ano] if ano else []))
    if _anos:
        where_extra_sigcon += " AND c.ano = ANY(:anos)"
        where_extra_vol += " AND split_part(v.numero_proposta, '/', 2) = ANY(:anos_txt)"
        where_extra_em += " AND e.ano = ANY(:anos)"
        params["anos"] = _anos
        params["anos_txt"] = [str(a) for a in _anos]

    # SIGCON
    sql1 = f"""
        SELECT c.id, c.municipio_id, m.nome AS mun_nome,
               c.nr_sigcon, c.objeto, c.situacao,
               c.valor_total, c.valor_concedente,
               c.raw_data->>'responsaveis' AS responsaveis,
               c.dt_vigencia_inicial, c.dt_vigencia_atual, c.dt_vigencia_final,
               c.ano, c.orgao_concedente
        FROM convenios_estadual c LEFT JOIN municipios m ON m.id = c.municipio_id
        WHERE c.raw_data->>'responsaveis' ILIKE :n
        {where_extra_sigcon}
        ORDER BY c.ano DESC NULLS LAST, c.dt_publicacao DESC NULLS LAST
    """
    sigcon = [{
        "id": r[0], "municipio_id": r[1], "municipio_nome": r[2],
        "numero": r[3], "objeto": r[4], "situacao": r[5],
        "valor_total": _money(r[6]), "valor_repasse": _money(r[7]),
        "responsaveis": r[8],
        "dt_vigencia_inicial": str(r[9]) if r[9] else None,
        "dt_vigencia_atual": str(r[10]) if r[10] else None,
        "dt_vigencia_final": str(r[11]) if r[11] else None,
        "ano": r[12], "orgao": r[13],
        "fonte": "sigcon",
    } for r in (await db.execute(text(sql1), params)).fetchall()]

    # Voluntarias
    sql2 = f"""
        SELECT v.id, v.municipio_id,
               (SELECT nome FROM municipios WHERE id=v.municipio_id) AS mun_nome,
               v.numero_proposta, v.codigo_instrumento, v.objeto, v.situacao,
               v.valor_global, v.valor_repasse, v.parlamentar,
               v.dt_inicio_vigencia, v.dt_fim_vigencia, v.orgao,
               v.situacao_contratacao, v.situacao_contratacao_detalhe
        FROM transferegov_propostas v
        WHERE v.parlamentar ILIKE :n
          AND v.municipal IS NOT FALSE  -- so a prefeitura (services/natureza.py)
        {where_extra_vol}
        ORDER BY v.numero_proposta DESC
    """
    voluntarias = [{
        "id": r[0], "municipio_id": r[1], "municipio_nome": r[2],
        "numero_proposta": r[3], "codigo_instrumento": r[4],
        "objeto": r[5], "situacao": r[6],
        "valor_global": _money(r[7]), "valor_repasse": _money(r[8]),
        "parlamentar": r[9],
        "dt_inicio_vigencia": r[10], "dt_fim_vigencia": r[11],
        "orgao": r[12],
        "situacao_contratacao": r[13],
        "situacao_contratacao_detalhe": r[14] if isinstance(r[14], dict) else None,
        "fonte": "voluntaria",
    } for r in (await db.execute(text(sql2), params)).fetchall()]

    # Emendas
    sql3 = f"""
        SELECT e.id, e.municipio_id,
               (SELECT nome FROM municipios WHERE id=e.municipio_id) AS mun_nome,
               e.nr_indicacao, e.ano, e.beneficiario, e.tipo_atendimento,
               e.valor_indicacao, e.nome_responsavel, e.status_indicacao,
               e.uo_sigla
        FROM emendas_estaduais e
        WHERE e.nome_responsavel ILIKE :n
        {where_extra_em}
        ORDER BY e.ano DESC NULLS LAST
    """
    emendas = [{
        "id": r[0], "municipio_id": r[1], "municipio_nome": r[2],
        "nr_indicacao": r[3], "ano": r[4],
        "beneficiario": r[5], "tipo_atendimento": r[6],
        "valor_indicacao": _money(r[7]),
        "nome_responsavel": r[8], "status_indicacao": r[9],
        "uo_sigla": r[10],
        "fonte": "emenda",
    } for r in (await db.execute(text(sql3), params)).fetchall()]

    # Plano de Acao / Transferencia Especial (RP9) — AO VIVO (mesma fonte da tela
    # TransfereGov). Autor vem em codigoEmendaFormatado ('<codigo>-<Nome>').
    # DA TABELA `transferegov_te`, pela mesma razao da listagem (fonte 4 do
    # aggregate): o fetch AO VIVO custava 5-7s e o cache de 1h nao ajudava,
    # porque vive na memoria do processo e o uvicorn roda --workers 2.
    #
    # ⚠️ E PRECISA ser a mesma fonte da listagem. Se a lista lesse a tabela e o
    # detalhe a API ao vivo, o cartao mostraria um total e, ao expandir,
    # lancamentos que somam outro — a mesma divergencia que ja existia entre a
    # aba do dashboard e esta tela. Uma fonte so, para nao haver duas verdades.
    #
    # Filtro por CNPJ: a tabela esta contaminada pelo casamento por substring do
    # coletor (ver comentario na fonte 4). Sem ele, o detalhe listaria lancamento
    # de outro municipio.
    plano_acao: list = []
    try:
        ano_te_d = " AND substr(te.programa_codigo, 5, 4) = ANY(:anos_txt_te)" if _anos else ""
        mun_te_d = " AND te.municipio_id = :mun_te" if municipio_id else ""
        sql_pa = f"""
            SELECT te.plano_acao_id, te.municipio_id, m.nome, te.codigo, te.emenda,
                   te.parlamentar, te.objeto, te.situacao,
                   COALESCE(te.valor_total, 0), COALESCE(te.valor_custeio, 0),
                   COALESCE(te.valor_investimento, 0)
            FROM transferegov_te te
            LEFT JOIN municipios m ON m.id = te.municipio_id
            WHERE te.parlamentar IS NOT NULL AND te.municipio_id IS NOT NULL
              AND (
                    te.beneficiario_cnpj IS NULL OR m.cnpj IS NULL
                    OR regexp_replace(te.beneficiario_cnpj, '[^0-9]', '', 'g')
                       = regexp_replace(m.cnpj, '[^0-9]', '', 'g')
                  )
              {mun_te_d}{ano_te_d}
        """
        pa_params: dict = {}
        if municipio_id:
            pa_params["mun_te"] = municipio_id
        if _anos:
            pa_params["anos_txt_te"] = [str(a) for a in _anos]
        alvo = _norm(nome_param)
        for r in (await db.execute(text(sql_pa), pa_params)).fetchall():
            autor = (r[5] or "").strip()
            if not autor or alvo not in _norm(autor):
                continue
            plano_acao.append({
                "id": r[0],
                "municipio_id": r[1], "municipio_nome": r[2],
                "codigo": r[3],
                "emenda": (r[4] or "").partition("-")[0].strip(),
                "parlamentar": autor,
                "objeto": r[6],
                "situacao": r[7],
                "valor_total": _money(r[8]),
                "valor_custeio": _money(r[9]),
                "valor_investimento": _money(r[10]),
                "fonte": "plano_acao",
            })
    except Exception:
        pass
    plano_acao.sort(key=lambda x: x["valor_total"], reverse=True)

    # Selecao PAC / Novo PAC — proponente (ou emenda) como parlamentar
    pac_list: list = []
    try:
        pac_sql = """
            SELECT id, municipio_id,
                   (SELECT nome FROM municipios WHERE id=transferegov_pac.municipio_id) AS mun,
                   numero_proposta, programa, situacao, valor_total,
                   emenda_parlamentar, proponente, objeto
            FROM transferegov_pac
            WHERE COALESCE(NULLIF(TRIM(emenda_parlamentar), ''), proponente) ILIKE :n
        """
        pac_params: dict = {"n": f"%{nome_param}%"}
        if municipio_id:
            pac_sql += " AND municipio_id = :mun"; pac_params["mun"] = municipio_id
        if _anos:
            pac_sql += " AND split_part(numero_proposta, '/', 2) = ANY(:anos_txt)"
            pac_params["anos_txt"] = [str(a) for a in _anos]
        pac_sql += " ORDER BY valor_total DESC NULLS LAST"
        for r in (await db.execute(text(pac_sql), pac_params)).fetchall():
            pac_list.append({
                "id": r[0], "municipio_id": r[1], "municipio_nome": r[2],
                "numero_proposta": r[3], "programa": r[4], "situacao": r[5],
                "valor_total": _money(r[6]), "emenda_parlamentar": r[7],
                "proponente": r[8], "objeto": r[9], "fonte": "pac",
            })
    except Exception:
        pass

    # FNS — a emenda de saude sob o AUTOR aninhado, a MESMA regra do agregado
    # (bloco 6) e do BI (ver services/nome_parlamentar.propostas_saude_por_autor).
    # Antes este bloco casava so o rotulo "FUNDO MUNICIPAL DE SAUDE — <mun>"
    # contra o nome buscado, entao ao expandir um parlamentar REAL (Igor Timo,
    # Nova Serrana, 04/09/2026) o card sumia: o cabecalho ja contava a emenda —
    # o agregado descia no aninhamento —, mas o detalhe nao. Terceira superficie
    # do mesmo bug (#371 corrigiu as duas primeiras).
    #
    # ⚠️ Um card por PROPOSTA (vlProposta), nao pela linha inteira. A linha FNS
    # soma varias propostas; emitir o valor da linha faria o total ao expandir
    # divergir do que o cabecalho atribuiu ao parlamentar — a "duas verdades" que
    # o comentario do RP9 acima existe para impedir. Sem autor real, a proposta
    # cai no Fundo Municipal (mesmo fallback do agregado, p/ o valor nao se
    # perder), e o drill-down do proprio Fundo segue funcionando.
    fns_list: list = []
    try:
        alvo = _norm(nome_param)
        fns_sql = """
            SELECT c.id, c.municipio_id,
                   (SELECT nome FROM municipios WHERE id=c.municipio_id) AS mun,
                   c.objeto, c.orgao_concedente, c.ano,
                   c.dt_vigencia_inicial, c.dt_vigencia_final,
                   c.raw_data->'linhaPropostas'
            FROM convenios_estadual c
            WHERE c.fonte ILIKE '%FNS%'
              AND jsonb_typeof(c.raw_data->'linhaPropostas') = 'array'
        """
        fns_params: dict = {}
        if municipio_id:
            fns_sql += " AND c.municipio_id = :mun"; fns_params["mun"] = municipio_id
        if _anos:
            fns_sql += " AND c.ano = ANY(:anos)"; fns_params["anos"] = _anos
        for r in (await db.execute(text(fns_sql), fns_params)).fetchall():
            mun_nome = r[2] or ""
            label = _fns_label(mun_nome)
            label_key = _norm(label)
            for p in propostas_saude_por_autor(r[8]):
                autor = p["autor"]
                if autor:
                    if alvo and alvo not in _norm(autor):
                        continue
                    proponente = autor
                else:
                    if alvo and alvo not in label_key and label_key not in alvo:
                        continue
                    proponente = label
                fns_list.append({
                    "id": r[0], "municipio_id": r[1], "municipio_nome": r[2],
                    "numero": p["numero"], "objeto": r[3], "situacao": p["situacao"],
                    "valor_total": _money(p["valor"]), "orgao": r[4], "ano": r[5],
                    "dt_vigencia_inicial": str(r[6]) if r[6] else None,
                    "dt_vigencia_final": str(r[7]) if r[7] else None,
                    "proponente": proponente, "fonte": "fns",
                })
        fns_list.sort(key=lambda x: x["valor_total"], reverse=True)
    except Exception:
        pass

    # EMENDAS FEDERAIS — a setima fonte, que o agregado conta desde 06/09/2026 e
    # que este endpoint NAO devolvia ate 07/09.
    #
    # ⭐ POR QUE FALTAVA IMPORTAR. `por_fonte.emenda_federal` e o
    # `total_lancamentos` do cabecalho ja a incluiam, entao o cartao prometia "3
    # emendas federais" e ao abrir nao havia secao nenhuma; `total_geral` daqui
    # tambem nao batia com o `total_lancamentos` de la. Pior: o parlamentar que
    # so tem emenda federal — e sao 45% da carteira nos municipios medidos, a
    # emenda INDICADA que nunca virou instrumento — caia no 404 abaixo e o card
    # abria com erro. O defeito ficou invisivel enquanto a tela mostrava as sete
    # fontes numa grade de "—"; virou obvio quando o resumo passou a ser selo.
    #
    # ⚠️⚠️ OS DOIS `NOT EXISTS` SAO OS MESMOS DO AGREGADO, e nao dao para
    # simplificar: esta tabela le a MESMA base que ja alimenta TransfereGov
    # (`id_proposta_siconv`, preenchido por `siconv_emenda_backfill.py`) e
    # Transferencia Especial (`te.emenda` no formato '<codigo>-<Nome>'). Sem o
    # desconto, a mesma emenda apareceria DUAS VEZES ao expandir e o
    # `valor_total` daqui passaria o do cabecalho — que e onde o gestor confere.
    # Onde nao ha chave (PAC, FNS) nao se tenta casar por nome, pela mesma razao
    # de la: casamento por nome de autor apagaria emenda legitima.
    ef_list: list = []
    try:
        where_ef = ""
        if municipio_id:
            where_ef += " AND ef.municipio_id = :mun"
        if _anos:
            where_ef += " AND ef.ano = ANY(:anos)"
        sql_ef_det = f"""
            SELECT ef.id, ef.municipio_id,
                   (SELECT nome FROM municipios WHERE id = ef.municipio_id) AS mun,
                   ef.codigo_emenda, ef.nr_emenda, ef.ano,
                   ef.beneficiario_nome, ef.e_prefeitura,
                   ef.parlamentar, ef.tipo_parlamentar,
                   COALESCE(ef.valor_repasse_emenda, 0),
                   ef.qualif_proponente
              FROM emendas_federais_carteira ef
             WHERE ef.parlamentar ILIKE :n
               AND NOT EXISTS (
                     SELECT 1 FROM transferegov_propostas v
                      WHERE v.parlamentar IS NOT NULL
                        AND v.id_proposta_siconv IS NOT NULL
                        AND v.id_proposta_siconv = ef.id_proposta)
               AND NOT EXISTS (
                     SELECT 1 FROM transferegov_te te
                      WHERE te.parlamentar IS NOT NULL
                        AND ef.codigo_emenda IS NOT NULL
                        AND split_part(te.emenda, '-', 1) = ef.codigo_emenda)
               {where_ef}
             ORDER BY ef.ano DESC NULLS LAST, ef.valor_repasse_emenda DESC NULLS LAST
        """
        ef_list = [{
            "id": r[0], "municipio_id": r[1], "municipio_nome": r[2],
            "codigo_emenda": r[3], "nr_emenda": r[4] or None, "ano": r[5],
            "beneficiario_nome": r[6], "e_prefeitura": bool(r[7]),
            "parlamentar": r[8], "tipo_parlamentar": r[9],
            # ⚠️ `valor_repasse_emenda` e NAO `valor_repasse_proposta`: e o que o
            # agregado soma, e usar o outro faria o total ao expandir divergir do
            # que o cabecalho atribuiu ao parlamentar.
            "valor_total": _money(r[10]),
            "qualif_proponente": r[11],
            "fonte": "emenda_federal",
        } for r in (await db.execute(text(sql_ef_det), params)).fetchall()]
    except Exception:
        # Degrada em silencio, como as demais: a tabela pode nem existir num
        # tenant onde a migration ainda nao rodou.
        pass

    # ⚠️ `ef_list` ENTRA NESTA GUARDA. Fora dela, o parlamentar que so tem emenda
    # federal continuaria recebendo 404 mesmo agora que a lista dele existe.
    if not (sigcon or voluntarias or emendas or plano_acao or pac_list
            or fns_list or ef_list):
        raise HTTPException(404, f"Nenhum lancamento encontrado para '{nome_param}'")

    return {
        "nome_consulta": nome_param,
        "sigcon": sigcon,
        "voluntarias": voluntarias,
        "emendas": emendas,
        "plano_acao": plano_acao,
        "pac": pac_list,
        "fns": fns_list,
        "emendas_federais": ef_list,
        "total_sigcon": len(sigcon),
        "total_voluntarias": len(voluntarias),
        "total_emendas": len(emendas),
        "total_plano_acao": len(plano_acao),
        "total_pac": len(pac_list),
        "total_fns": len(fns_list),
        "total_emendas_federais": len(ef_list),
        "total_geral": len(sigcon) + len(voluntarias) + len(emendas) + len(plano_acao) + len(pac_list) + len(fns_list) + len(ef_list),
        "valor_total": (
            sum(x["valor_total"] for x in sigcon)
            + sum(x["valor_global"] for x in voluntarias)
            + sum(x["valor_indicacao"] for x in emendas)
            + sum(x["valor_total"] for x in plano_acao)
            + sum(x["valor_total"] for x in pac_list)
            + sum(x["valor_total"] for x in fns_list)
            + sum(x["valor_total"] for x in ef_list)
        ),
    }
