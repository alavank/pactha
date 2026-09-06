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
  LEFT JOIN emendas_federais_cgu g ON g.codigo_emenda = c.codigo_emenda
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
    import os

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
    tot = {"emendas": 0, "indicado": 0.0, "indicado_prefeitura": 0.0,
           "indicado_outros": 0.0, "empenhado": 0.0, "liquidado": 0.0,
           "pago": 0.0, "resto_inscrito": 0.0, "resto_pago": 0.0,
           "resto_cancelado": 0.0, "parado_n": 0, "parado_valor": 0.0,
           "nao_consultadas_n": 0, "impositivas_n": 0}
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
            "execucao_consultada": x[23] is not None,
            "encontrada": x[24],
            "documentos_n": int(x[25] or 0),
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
            for k, campo in (("empenhado", "valor_empenhado"),
                             ("liquidado", "valor_liquidado"),
                             ("pago", "valor_pago"),
                             ("resto_inscrito", "valor_resto_inscrito"),
                             ("resto_pago", "valor_resto_pago"),
                             ("resto_cancelado", "valor_resto_cancelado")):
                tot[k] += e[campo] or 0
        else:
            tot["nao_consultadas_n"] += 1
        if e["grupo"] == "parado":
            tot["parado_n"] += 1
            tot["parado_valor"] += e["valor_empenhado"] or 0
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
            "emendas": 0, "indicado": 0.0, "empenhado": 0.0, "pago": 0.0,
            "parado_n": 0, "anos": set()})
        a["emendas"] += 1
        a["indicado"] += e["valor_indicado"]
        a["empenhado"] += e["valor_empenhado"] or 0
        a["pago"] += (e["valor_pago"] or 0) + (e["valor_resto_pago"] or 0)
        if e["grupo"] == "parado":
            a["parado_n"] += 1
        if e["ano"]:
            a["anos"].add(int(e["ano"]))

    por_autor = sorted(
        ({**a, "anos": sorted(a["anos"], reverse=True)} for a in autores.values()),
        key=lambda a: a["indicado"], reverse=True)
    tot["parlamentares"] = sum(1 for a in por_autor if not a["colegiado"])

    chave_ok = bool((os.getenv("PORTAL_TRANSPARENCIA_API_KEY") or "").strip())
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
            "SELECT consultado_em FROM emendas_federais_consulta "
            "WHERE codigo_emenda = :c"), {"c": codigo_emenda})
        crow = cons.first()
    except Exception:
        await db.rollback()
        return {"consultado_em": None, "documentos": [],
                "motivo": "A execução desta emenda ainda não foi consultada no "
                          "Portal da Transparência."}
    consultado_em = crow[0].isoformat() if (crow and crow[0]) else None
    docs = [{"data": d[0].isoformat() if d[0] else None, "fase": d[1],
             "codigo_documento": d[2], "documento_resumido": d[3],
             "especie_tipo": d[4]} for d in linhas]
    motivo = ""
    if not docs:
        motivo = ("A CGU não publica documento de execução para esta emenda."
                  if consultado_em else
                  "A execução desta emenda ainda não foi consultada no Portal "
                  "da Transparência.")
    return {"consultado_em": consultado_em, "documentos": docs, "motivo": motivo}
