"""Emendas parlamentares FEDERAIS — a carteira do município e a execução dela.

Coleta em `ingestion/portal_transparencia.py` (dump aberto do TransfereGov +
API da CGU). Aqui é só leitura.

⭐ O QUE ESTA TELA MOSTRA QUE NENHUMA OUTRA MOSTRAVA. A emenda federal aparecia
de raspão em dois lugares — como Transferência Especial em «Especiais» e como
selo `TE` na lista de Convênios — e sempre pelo mesmo caminho: a emenda que
virou PROPOSTA. Medido em 06/09/2026: **45% das emendas de Nova Palma e 43% das
de Monte Sião têm `ID_PROPOSTA` vazio**. Quase metade da carteira era invisível.

⚠️⚠️ OS DOIS VALORES RESPONDEM PERGUNTAS DIFERENTES, e somá-los é o erro caro
desta tela:

    valor_indicado (dump) ..... quanto DESTA emenda foi para ESTE beneficiário.
                                Responde "quanto o município recebeu".
    empenhado/pago (CGU) ...... quanto da emenda INTEIRA a União movimentou.
                                É NACIONAL: uma emenda de bancada de R$ 30 mi que
                                passou por Nova Palma com R$ 250 mil traz R$ 30 mi.

Por isso o payload **nunca** soma os dois, e os totais de execução vêm rotulados
com o denominador ("sobre as N emendas já consultadas"). A tabela do agregado
nem tem `municipio_id` — a guarda é o schema (ver `add_emendas_federais.sql`).

⚠️ TRÊS ESTADOS DE EXECUÇÃO, NUNCA DOIS. `execucao_consultada = false` é
ausência NOSSA; `encontrada = false` é a CGU não conhecer o código; `pago = 0` é
a CGU AFIRMANDO zero. Confundir os dois primeiros com o terceiro é a única forma
de esta tela mentir com números certos — por isso os valores saem `None`, e a
tela imprime «—».

⚠️ E `municipio_id` AQUI É INFERÊNCIA NOSSA, feita por CNPJ do beneficiário: a
API da CGU não tem filtro territorial em `/emendas`. Ver o cabeçalho do coletor.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.coleta import (FRASE_EMENDAS_FEDERAIS, classificar_emendas_federais,
                             frescor_coleta)
from services.nome_parlamentar import e_parlamentar_real, e_pessoa
from services.registro_rotas import exige

router = APIRouter(prefix="/api/emendas-federais", tags=["emendas-federais"])

# ⚠️ RÓTULO DE EXIBIÇÃO — o CÓDIGO é a verdade. Os nomes saem do próprio dump do
# Governo (`siconv_programa.zip`, coluna `DESC_ORGAO_SUP_PROGRAMA`, medido em
# 06/09/2026 sobre 1,1 milhão de linhas, uma variante por código): não foram
# escritos de memória, porque dois deles desmentiram o palpite — 58000 é PESCA e
# não Turismo, e 81000 é DIREITOS HUMANOS e não Encargos. Código desconhecido
# aparece como o próprio código, nunca como "Outros".
ORGAOS_SIAFI = {
    "20000": "Presidência da República",
    "22000": "Agricultura e Pecuária",
    "24000": "Ciência, Tecnologia e Inovação",
    "25000": "Economia",
    "26000": "Educação",
    "30000": "Justiça e Segurança Pública",
    "36000": "Saúde",
    "39000": "Infraestrutura",
    "44000": "Meio Ambiente",
    "49000": "Desenvolvimento Agrário e Agricultura Familiar",
    "51000": "Esporte",
    "52000": "Defesa",
    "53000": "Integração e Desenvolvimento Regional",
    "54000": "Turismo",
    "55000": "Desenvolvimento e Assistência Social",
    "56000": "Cidades",
    "58000": "Pesca e Aquicultura",
    "81000": "Direitos Humanos e Cidadania",
}

# O que a fonte escreve no `TIPO_PARLAMENTAR`, e o que o gestor lê.
ROTULO_TIPO = {
    "INDIVIDUAL": "Individual",
    "BANCADA": "Bancada",
    "COMISSAO": "Comissão",
    "RELATOR GERAL": "Relator-geral",
}


def _f(v) -> Optional[float]:
    return float(v) if v is not None else None


def orgao_nome(codigo: Optional[str]) -> Optional[str]:
    if not codigo:
        return None
    return ORGAOS_SIAFI.get(codigo, codigo)


def classificar(e: dict) -> dict:
    """Por que esta emenda merece atenção — ou por que não merece.

    ⚠️⚠️ «PAGO» INCLUI O RESTO A PAGAR, e isso não é detalhe contábil. Emenda
    empenhada em dezembro é paga, quase sempre, como *resto a pagar* no ano
    seguinte. Olhar só `valor_pago` faria a tela chamar de PARADA uma emenda que
    já foi paga — e o gestor cobraria o parlamentar por algo que aconteceu.

    ⚠️ E «não consultada» NÃO entra em «precisa de cobrança». Se entrasse, um
    município recém-ligado abriria com metade da carteira "urgente", que é o
    mesmo que nenhuma — o defeito medido e documentado em `routers/obrasgov.py`.
    """
    if not e["execucao_consultada"]:
        return {"grupo": "nao_consultada", "alertas": [],
                "motivo": "A execução desta emenda ainda não foi consultada no "
                          "Portal da Transparência."}
    if e["encontrada"] is False:
        return {"grupo": "nao_encontrada", "alertas": [],
                "motivo": "O Portal da Transparência não tem registro para este "
                          "código de emenda."}
    emp = e["valor_empenhado"] or 0
    pago_total = (e["valor_pago"] or 0) + (e["valor_resto_pago"] or 0)
    alertas = []
    if (e["valor_resto_inscrito"] or 0) > 0:
        alertas.append("resto_a_pagar")
    if (e["valor_resto_cancelado"] or 0) > 0:
        alertas.append("resto_cancelado")
    if emp <= 0:
        return {"grupo": "sem_empenho", "alertas": alertas,
                "motivo": "Indicada e ainda sem empenho."}
    if pago_total <= 0:
        if e["impositiva"]:
            alertas.append("impositiva_parada")
        return {"grupo": "parado", "alertas": alertas,
                "motivo": ("Empenhada e sem nenhum pagamento até agora."
                           + (" É emenda impositiva." if e["impositiva"] else ""))}
    if pago_total < emp:
        return {"grupo": "andamento", "alertas": alertas,
                "motivo": "Empenhada e paga em parte."}
    return {"grupo": "paga", "alertas": alertas, "motivo": None}


_SQL_ITENS = """
SELECT c.codigo_emenda, c.nr_emenda, c.ano, c.parlamentar, c.tipo_parlamentar,
       c.impositiva, c.orgao_siafi, c.beneficiario_cnpj, c.beneficiario_nome,
       c.e_prefeitura, c.codigo_confirmado,
       sum(coalesce(c.valor_repasse_emenda, 0)) AS valor_indicado,
       array_remove(array_agg(DISTINCT nullif(c.id_proposta, '')), NULL) AS propostas,
       max(g.valor_empenhado)  AS valor_empenhado,
       max(g.valor_liquidado)  AS valor_liquidado,
       max(g.valor_pago)       AS valor_pago,
       max(g.valor_resto_inscrito)  AS valor_resto_inscrito,
       max(g.valor_resto_cancelado) AS valor_resto_cancelado,
       max(g.valor_resto_pago)      AS valor_resto_pago,
       max(g.funcao) AS funcao, max(g.subfuncao) AS subfuncao,
       max(g.localidade_gasto) AS localidade_gasto,
       q.consultado_em, q.achou_agregado, coalesce(q.n_documentos, 0) AS n_docs
  FROM emendas_federais_carteira c
  -- ⚠️⚠️ LATERAL, E NÃO UM `LEFT JOIN` DIRETO — a diferença é o dinheiro do
  -- município. `emendas_federais_cgu` é 1:N por desenho: a chave única é
  -- (codigo_emenda, localidade_gasto, funcao, subfuncao), e a fonte usa isso.
  -- MEDIDO em produção, 06/09/2026: o código 202341160001 voltou com DUAS
  -- linhas — «VERA CRUZ - RS · Saúde · R$ 50.548,00» e «MÚLTIPLO · Encargos
  -- especiais · R$ 5.000.000,00».
  --
  -- Com o join direto, `sum(c.valor_repasse_emenda)` fica no MESMO GROUP BY do
  -- fan-out: k linhas na CGU multiplicam por k o valor que veio do DUMP. E só o
  -- dinheiro infla — `max()` e `array_agg(DISTINCT ...)` atravessam o fan-out
  -- intactos —, então nada na tela denuncia. Pior: a inflação é proporcional a
  -- quanto a CGU detalha a emenda, ou seja, MAIOR nas mais executadas.
  --
  -- Hoje nenhum código da carteira tem duas linhas (medido: zero nos dois
  -- municípios), então o defeito está LATENTE. A redução prévia é correta nos
  -- dois mundos: com k=1 não muda número nenhum; com k>1 é a diferença entre o
  -- total certo e um total maior e plausível.
  LEFT JOIN LATERAL (
      SELECT g2.valor_empenhado, g2.valor_liquidado, g2.valor_pago,
             g2.valor_resto_inscrito, g2.valor_resto_cancelado,
             g2.valor_resto_pago, g2.funcao, g2.subfuncao, g2.localidade_gasto
        FROM emendas_federais_cgu g2
       WHERE g2.codigo_emenda = c.codigo_emenda
       -- A linha de MAIOR empenho é a que representa a emenda na tela. Somar as
       -- fatias seria pior: elas se sobrepõem («MÚLTIPLO» é agregado das
       -- demais), e somar agregado com detalhe dobraria o número.
       ORDER BY g2.valor_empenhado DESC NULLS LAST
       LIMIT 1
  ) g ON TRUE
  LEFT JOIN emendas_federais_consulta q ON q.codigo_emenda = c.codigo_emenda
 WHERE c.municipio_id = :m
 GROUP BY c.codigo_emenda, c.nr_emenda, c.ano, c.parlamentar, c.tipo_parlamentar,
          c.impositiva, c.orgao_siafi, c.beneficiario_cnpj, c.beneficiario_nome,
          c.e_prefeitura, c.codigo_confirmado, q.consultado_em, q.achou_agregado,
          q.n_documentos
 ORDER BY c.ano DESC NULLS LAST, valor_indicado DESC NULLS LAST
"""


async def buscar(db: AsyncSession, municipio_id: int) -> dict:
    """O payload inteiro numa consulta só.

    ⚠️ SEM FILTRO DE SERVIDOR, e é decisão com gatilho escrito: 44 e 33 emendas
    (os dois municípios ligados) cabem num payload, e KPI e lista saindo do MESMO
    lugar não podem divergir — que é o defeito que aparece toda vez que o total
    vem de um endpoint e a lista de outro. **Acima de ~2.000 emendas o filtro
    sobe para o servidor, e os KPIs sobem junto ou passam a mentir.**
    """
    r = await db.execute(text(
        "SELECT nome, regexp_replace(coalesce(cnpj,''), '\\D', '', 'g') "
        "FROM municipios WHERE id = :m"), {"m": municipio_id})
    row = r.first()
    mun_nome = row[0] if row else None
    tem_cnpj = bool(row and len(row[1] or "") == 14)

    try:
        linhas = (await db.execute(text(_SQL_ITENS), {"m": municipio_id})).fetchall()
    except Exception:
        # Tabela ausente num tenant onde a migration ainda não rodou. A tela
        # inteira não pode cair por isso — mesmo padrão de `freshness.py`.
        await db.rollback()
        linhas = []

    itens, autores, anos, orgaos, benefs = [], {}, set(), {}, {}
    # ⚠️ NENHUM TOTAL DE EXECUÇÃO EM DINHEIRO — ver o comentário no laço abaixo.
    # `indicado` PODE ser somado: ele vem do dump e é a fatia DESTE município.
    tot = {"emendas": 0, "indicado": 0.0, "indicado_prefeitura": 0.0,
           "indicado_outros": 0.0, "com_empenho_n": 0, "com_pagamento_n": 0,
           "com_resto_n": 0, "parado_n": 0, "nao_consultadas_n": 0,
           "impositivas_n": 0}
    consultadas = 0
    for x in linhas:
        e = {
            "codigo_emenda": x[0], "numero_emenda": x[1], "ano": x[2],
            "autor": x[3], "tipo": x[4], "impositiva": x[5],
            "orgao_siafi": x[6], "orgao": orgao_nome(x[6]),
            "beneficiario_cnpj": x[7], "beneficiario_nome": x[8],
            "beneficiario_prefeitura": bool(x[9]),
            "codigo_confirmado": bool(x[10]),
            "valor_indicado": _f(x[11]) or 0.0,
            "propostas": list(x[12] or []),
            # ⚠️⚠️ OS ÍNDICES SÃO POSICIONAIS E ESTAVAM TODOS DESLOCADOS POR UM.
            # `x[25]` nem existia (o SELECT tem 25 colunas, 0..24), então a tela
            # devolvia **IndexError → 500 em todo município com carteira** — ela
            # nunca tinha sido aberta com dado. E os dois vizinhos liam o campo
            # errado em silêncio: `execucao_consultada` lia `achou_agregado` e
            # `encontrada` lia a contagem de documentos.
            #
            # x[22] = q.consultado_em · x[23] = q.achou_agregado · x[24] = n_docs
            # `test_indices_do_sql_batem_com_o_python` amarra os dois lados.
            "execucao_consultada": x[22] is not None,
            "encontrada": x[23],
            "documentos_n": int(x[24] or 0),
        }
        # ⚠️ Os seis valores de execução ficam None quando a CGU nunca foi
        # perguntada. Zero aqui seria uma AFIRMAÇÃO que ninguém fez.
        for i, k in ((13, "valor_empenhado"), (14, "valor_liquidado"),
                     (15, "valor_pago"), (16, "valor_resto_inscrito"),
                     (17, "valor_resto_cancelado"), (18, "valor_resto_pago")):
            e[k] = _f(x[i]) if e["execucao_consultada"] else None
        e["funcao"], e["subfuncao"], e["localidade_gasto"] = x[19], x[20], x[21]
        e.update(classificar(e))
        e["url_fonte"] = ("https://portaldatransparencia.gov.br/emendas/"
                          f"{e['codigo_emenda']}" if e["codigo_emenda"] else
                          "https://portaldatransparencia.gov.br/emendas")
        itens.append(e)

        tot["emendas"] += 1
        tot["indicado"] += e["valor_indicado"]
        if e["beneficiario_prefeitura"]:
            tot["indicado_prefeitura"] += e["valor_indicado"]
        else:
            tot["indicado_outros"] += e["valor_indicado"]
        if e["impositiva"]:
            tot["impositivas_n"] += 1
        if e["execucao_consultada"]:
            consultadas += 1
            # ⚠️⚠️ AQUI NÃO SE SOMA DINHEIRO, E ESSA É A REGRA MAIS IMPORTANTE
            # DESTE ARQUIVO. O agregado da CGU é da emenda INTEIRA, nacional.
            # Somar `valor_empenhado` das 44 emendas de Nova Palma dava
            # **R$ 4.051.927.813,24** — quatro bilhões num município de 5.676
            # habitantes cuja carteira é de R$ 13,68 milhões. Medido em
            # 06/09/2026, antes de a tela ser aberta com a chave ligada.
            #
            # A CGU não publica "quanto DESTA emenda foi pago A ESTE município".
            # Esse número não existe na fonte — então a tela conta ESTADO
            # (quantas andaram, quantas pararam) e mostra VALOR só na linha de
            # cada emenda, rotulado "da emenda inteira".
            #
            # ⚠️ O schema já impedia o `SUM(...) GROUP BY municipio_id` (a tabela
            # do agregado não tem `municipio_id`). Não bastou: eu somei por
            # emenda, no Python, contornando a própria guarda que escrevi.
            if (e["valor_empenhado"] or 0) > 0:
                tot["com_empenho_n"] += 1
            if (e["valor_pago"] or 0) + (e["valor_resto_pago"] or 0) > 0:
                tot["com_pagamento_n"] += 1
            if (e["valor_resto_inscrito"] or 0) > 0:
                tot["com_resto_n"] += 1
        else:
            tot["nao_consultadas_n"] += 1
        if e["grupo"] == "parado":
            tot["parado_n"] += 1
        if e["ano"]:
            anos.add(int(e["ano"]))
        if e["orgao_siafi"]:
            orgaos[e["orgao_siafi"]] = e["orgao"]
        if e["beneficiario_cnpj"]:
            b = benefs.setdefault(e["beneficiario_cnpj"], {
                "cnpj": e["beneficiario_cnpj"], "nome": e["beneficiario_nome"],
                "prefeitura": e["beneficiario_prefeitura"], "emendas": 0,
                "indicado": 0.0})
            b["emendas"] += 1
            b["indicado"] += e["valor_indicado"]

        # ⚠️ SÓ VIRA "PARLAMENTAR" QUEM É PESSOA. `nome_parlamentar.e_pessoa` é a
        # mesma função que tirou «Não há» (R$ 14,9 mi, 12 convênios) do topo do
        # ranking da Freitas, e ela cobre BANCADA/COMISSAO/RELATOR — que são 7
        # dos 35 nomes de autor destes dois municípios.
        nome = (e["autor"] or "").strip()
        if not nome or not e_parlamentar_real(nome):
            continue
        colegiado = (e["tipo"] or "").upper() in ("BANCADA", "COMISSAO",
                                                  "RELATOR GERAL")
        a = autores.setdefault(nome, {
            "autor": nome, "tipo": e["tipo"], "colegiado": colegiado or not e_pessoa(nome),
            "emendas": 0, "indicado": 0.0, "parado_n": 0, "anos": set()})
        a["emendas"] += 1
        # ⚠️ Só `indicado` soma: é o valor do DUMP, a fatia deste município.
        # Empenhado e pago são nacionais e somá-los por autor daria o mesmo
        # absurdo de bilhões — ver o comentário no laço dos totais.
        a["indicado"] += e["valor_indicado"]
        if e["grupo"] == "parado":
            a["parado_n"] += 1
        if e["ano"]:
            a["anos"].add(int(e["ano"]))

    por_autor = sorted(
        ({**a, "anos": sorted(a["anos"], reverse=True)} for a in autores.values()),
        key=lambda a: a["indicado"], reverse=True)
    tot["parlamentares"] = sum(1 for a in por_autor if not a["colegiado"])

    # ⚠️⚠️ A PROVA DE QUE A FONTE ESTÁ LIGADA É O DADO, E NÃO UMA ENV.
    # A versão anterior lia `PORTAL_TRANSPARENCIA_API_KEY` aqui — e essa env
    # mora no WORKER, que é outro container e outro processo. A API nunca a vê.
    # Resultado medido em 06/09/2026: Nova Palma com 64 de 67 emendas já
    # consultadas na CGU, e a tela dizendo «a chave não está configurada neste
    # ambiente», escondendo toda a execução atrás de «—».
    #
    # Perguntar ao dado responde certo nos dois sentidos: onde a coleta rodou, a
    # execução aparece; onde não rodou, a tela não afirma nada sobre a
    # configuração de um processo que ela não enxerga.
    chave_ok = consultadas > 0
    estado = classificar_emendas_federais(
        chave_configurada=chave_ok, houve_coleta=bool(linhas) or consultadas > 0,
        tem_cnpj=tem_cnpj, n_emendas=tot["emendas"],
        n_execucao_consultada=consultadas)
    aviso = FRASE_EMENDAS_FEDERAIS.get(estado, "")
    if estado == "parcial":
        aviso = aviso.format(consultadas=consultadas, total=tot["emendas"])

    coleta_em, falhas = await frescor_coleta(db, municipio_id,
                                             ("portal_transparencia",))
    return {
        "tem_dados": bool(itens),
        "estado": estado, "aviso": aviso, "fonte_ligada": chave_ok,
        "municipio_nome": mun_nome,
        "coleta_em": coleta_em, "coleta_falhas": falhas,
        "execucao": {"consultadas": consultadas, "total": tot["emendas"]},
        "escopo": {"cnpjs": sorted(benefs.values(),
                                   key=lambda b: (not b["prefeitura"], b["nome"] or ""))},
        "totais": tot,
        "items": itens,
        "por_autor": por_autor,
        "anos": sorted(anos, reverse=True),
        "orgaos": [{"codigo": c, "nome": n} for c, n in sorted(orgaos.items())],
        "tipos": sorted({i["tipo"] for i in itens if i["tipo"]}),
    }


@router.get("", dependencies=[exige("emendas_federais.ver")])
async def listar(
    municipio_id: int = Query(..., description="ID do municipio PACTHA"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "emendas_federais")
    return await buscar(db, municipio_id)


@router.get("/{codigo_emenda}/documentos",
            dependencies=[exige("emendas_federais.ver")])
async def documentos(
    codigo_emenda: str,
    municipio_id: int = Query(..., description="ID do municipio PACTHA"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """A linha do tempo da execução de UMA emenda.

    ⚠️ ROTA SEPARADA porque 44 emendas × N documentos seriam centenas de linhas
    em toda abertura de tela, e a maioria nunca é expandida.

    ⚠️ E `municipio_id` é OBRIGATÓRIO e entra no `WHERE`: o código da emenda é
    NACIONAL, então sem ele esta rota viraria um caminho para ler a execução de
    emenda de qualquer município a partir de qualquer tenant.

    ⚠️ Gaveta vazia tem DUAS causas e duas frases: «a CGU não publica documento
    para esta emenda» (consultado) e «ainda não foi consultada» (não consultado).
    """
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "emendas_federais")
    try:
        r = await db.execute(text("""
            SELECT d.data, d.fase, d.codigo_documento, d.codigo_documento_resumido,
                   d.especie_tipo, q.consultado_em
              FROM emendas_federais_documentos d
              LEFT JOIN emendas_federais_consulta q
                     ON q.codigo_emenda = d.codigo_emenda
             WHERE d.codigo_emenda = :c
               AND EXISTS (SELECT 1 FROM emendas_federais_carteira c
                            WHERE c.codigo_emenda = d.codigo_emenda
                              AND c.municipio_id = :m)
             ORDER BY d.data NULLS LAST, d.fase
        """), {"c": codigo_emenda, "m": municipio_id})
        linhas = r.fetchall()
        cons = await db.execute(text(
            "SELECT q.consultado_em, "
            "       (SELECT max(c.tipo_parlamentar) "
            "          FROM emendas_federais_carteira c "
            "         WHERE c.codigo_emenda = q.codigo_emenda "
            "           AND c.municipio_id = :m) "
            "  FROM emendas_federais_consulta q "
            " WHERE q.codigo_emenda = :c"),
            {"c": codigo_emenda, "m": municipio_id})
        crow = cons.first()
    except Exception:
        await db.rollback()
        return {"consultado_em": None, "documentos": [], "colegiado": False,
                "motivo": "A execução desta emenda ainda não foi consultada no "
                          "Portal da Transparência."}
    consultado_em = crow[0].isoformat() if (crow and crow[0]) else None
    tipo = crow[1] if crow else None
    docs = [{"data": d[0].isoformat() if d[0] else None, "fase": d[1],
             "codigo_documento": d[2], "documento_resumido": d[3],
             "especie_tipo": d[4]} for d in linhas]
    # ⚠️ GAVETA VAZIA TEM TRÊS CAUSAS, e a terceira nasceu de uma medição:
    # emenda de COLEGIADO é nacional e tem 900+ documentos, quase nenhum do
    # município — em Monte Sião, 4 emendas de comissão davam 3.600 documentos
    # contra 15 das 27 individuais. A linha do tempo delas não é coletada de
    # propósito (ver TIPOS_COLEGIADO no coletor), e a tela DIZ isso: gaveta
    # vazia sem explicação seria lida como "não houve execução".
    colegiado = (tipo or "").strip().upper() in ("COMISSAO", "BANCADA",
                                                 "RELATOR GERAL")
    motivo = ""
    if not docs:
        if colegiado:
            motivo = ("Emenda de colegiado (bancada, comissão ou relator-geral): "
                      "a execução dela é nacional e atende centenas de "
                      "municípios, então a linha do tempo documento a documento "
                      "não é coletada. Os valores acima são da emenda inteira.")
        elif consultado_em:
            motivo = "A CGU não publica documento de execução para esta emenda."
        else:
            motivo = ("A execução desta emenda ainda não foi consultada no "
                      "Portal da Transparência.")
    return {"consultado_em": consultado_em, "documentos": docs,
            "motivo": motivo, "colegiado": colegiado}
