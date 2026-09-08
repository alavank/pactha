"""SISMOB — obras de saude do Ministerio da Saude (financiamento fundo a fundo).

Coleta em `ingestion/sismob_obras.py` (API publica, sem login). Aqui e so leitura.

A resposta separa **acao / em_dia / encerradas** NO SERVIDOR, e nao devolve uma
lista unica para o cliente filtrar. Dois motivos: o gestor nao deveria ter de ler
7 linhas para achar as 2 que importam, e tela, TV, celular e PDF precisam
concordar sobre o que e urgente — se cada um classificasse por conta, um dia
divergiriam.

A classificacao vem de `services/sismob_regras.py`, que e SEM I/O justamente
para o cron de push usar a mesma (o worker nao tem /app/routers).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from services.registro_rotas import exige
from services.sismob_catalogo import url_portal
from services.sismob_regras import classificar

router = APIRouter(prefix="/api/sismob", tags=["sismob"])

MOTIVO_SEM_COLETA = (
    "As obras do SISMOB deste município ainda não foram coletadas. A coleta é "
    "automática e usa o código IBGE — não depende de senha."
)

_CAMPOS = """
    proposta_id, numero_proposta, nu_cnpj, entidade,
    programa, tipo_obra, tipo_recurso, ano_referencia,
    co_situacao_obra, situacao, etapa, fase_projeto, dt_mudanca_situacao, justificativa,
    bairro, logradouro, co_cnes, nu_cnes, estabelecimento,
    vl_proposta, vl_total_contrato, vl_percentual_executado,
    dt_primeira_parcela, repasse_total, parcelas_pagas, regime_parcelas,
    nu_portaria, dt_portaria, dt_ordem_servico, dt_inicio_obra,
    dt_provavel_conclusao_final, dt_conclusao_final,
    dt_inicio_funcionamento, dt_inauguracao,
    possui_etapa_funcionamento,
    fotos_grupos, fotos_total, fotos_ultima_em,
    ultima_atividade_em, dt_atualizacao_fonte, updated_at
"""


def _f(v) -> Optional[float]:
    return float(v) if v is not None else None


def _d(v) -> Optional[str]:
    return v.isoformat() if v is not None else None


async def fetch_sismob_obras(db: AsyncSession, municipio_id: int) -> dict:
    """Nucleo da consulta SISMOB, SEM gate de auth — reusado pelo endpoint (apos
    ensure_tela) e pelo Painel de Indicadores (gated so por municipio), igual a
    fetch_cauc_situacao / fetch_cagec_situacao."""
    linhas = (await db.execute(text(f"""
        SELECT {_CAMPOS} FROM sismob_obras
        WHERE municipio_id = :m AND ausente_desde IS NULL
        ORDER BY ultima_atividade_em NULLS FIRST
    """), {"m": municipio_id})).mappings().all()

    if not linhas:
        return {"tem_dados": False, "motivo": MOTIVO_SEM_COLETA}

    emp_rows = (await db.execute(text("""
        SELECT e.proposta_id, e.cnpj, e.numero_contrato, e.razao_social,
               e.valor_final_licitado
        FROM sismob_obra_empresas e
        JOIN sismob_obras o ON o.proposta_id = e.proposta_id
        WHERE o.municipio_id = :m AND o.ausente_desde IS NULL
        ORDER BY e.valor_final_licitado DESC NULLS LAST
    """), {"m": municipio_id})).mappings().all()
    por_obra: dict[int, list[dict]] = {}
    for e in emp_rows:
        por_obra.setdefault(e["proposta_id"], []).append({
            "cnpj": e["cnpj"], "numero_contrato": e["numero_contrato"] or None,
            "razao_social": e["razao_social"],
            "valor_final_licitado": _f(e["valor_final_licitado"]),
        })

    mun = (await db.execute(text("SELECT nome, uf FROM municipios WHERE id = :m"),
                            {"m": municipio_id})).first()
    hoje = date.today()

    acao, em_dia, encerradas = [], [], []
    tot = {"obras": 0, "vivas": 0, "concluidas": 0, "canceladas": 0,
           "valor_proposta": 0.0, "repasse_total": 0.0, "repasse_parado": 0.0,
           "contratado": 0.0, "saldo_licitacao": 0.0, "contrapartida_municipal": 0.0}
    por_situacao: dict[str, dict] = {}
    por_programa: dict[str, dict] = {}
    empresas_ac: dict[str, dict] = {}

    for r in linhas:
        o = dict(r)
        empresas = por_obra.get(o["proposta_id"], [])
        o["empresas"] = empresas
        diag = classificar(o, hoje)

        co = o["co_situacao_obra"]
        proposta = _f(o["vl_proposta"]) or 0.0
        repasse = _f(o["repasse_total"]) or 0.0
        contrato = sum(e["valor_final_licitado"] or 0.0 for e in empresas)

        tot["obras"] += 1
        tot["valor_proposta"] += proposta
        tot["repasse_total"] += repasse
        tot["contratado"] += contrato
        if co in (7, 8):
            tot["canceladas"] += 1
        elif co in (3, 4):
            tot["concluidas"] += 1
        else:
            tot["vivas"] += 1
        # "Parado" conta so o dinheiro que JA ESTA na conta de obra que nao anda
        # — e o numero que faz o gestor agir.
        if any(g["regra"] == "sem_atualizacao" for g in diag["regras"]):
            tot["repasse_parado"] += repasse
        # Saldo e contrapartida so quando positivos: um contrato menor que o
        # repasse deixa saldo a reprogramar; maior significa dinheiro do
        # municipio entrando. Somar os dois com sinal esconderia ambos.
        if repasse and contrato:
            if repasse > contrato:
                tot["saldo_licitacao"] += repasse - contrato
            else:
                tot["contrapartida_municipal"] += contrato - repasse

        for acc, chave in ((por_situacao, o["situacao"]), (por_programa, o["programa"])):
            k = chave or "Não informado"
            e = acc.setdefault(k, {"label": k, "qtd": 0, "valor": 0.0})
            e["qtd"] += 1
            e["valor"] += proposta
        for e in empresas:
            k = e["cnpj"]
            a = empresas_ac.setdefault(k, {"cnpj": k, "razao_social": e["razao_social"],
                                           "obras": 0, "valor": 0.0})
            a["obras"] += 1
            a["valor"] += e["valor_final_licitado"] or 0.0

        item = {
            "proposta_id": o["proposta_id"], "numero_proposta": o["numero_proposta"],
            "estabelecimento": o["estabelecimento"], "bairro": o["bairro"],
            "programa": o["programa"], "tipo_obra": o["tipo_obra"],
            "tipo_recurso": o["tipo_recurso"], "ano_referencia": o["ano_referencia"],
            "situacao": o["situacao"], "co_situacao_obra": co, "etapa": o["etapa"],
            "percentual": _f(o["vl_percentual_executado"]),
            "severidade": diag["severidade"], "regras": diag["regras"],
            "dinheiro": {
                "proposta": proposta, "repassado": repasse,
                "parcelas_pagas": o["parcelas_pagas"], "regime": o["regime_parcelas"],
                "contrato": contrato or None,
                "saldo": round(repasse - contrato, 2) if (repasse and contrato) else None,
            },
            "empresas": empresas,
            "fotos": {"grupos": o["fotos_grupos"], "total": o["fotos_total"],
                      "ultima_em": _d(o["fotos_ultima_em"].date() if o["fotos_ultima_em"] else None)},
            "datas": {k: _d(o[k]) for k in (
                "dt_portaria", "dt_ordem_servico", "dt_inicio_obra",
                "dt_primeira_parcela", "dt_provavel_conclusao_final",
                "dt_conclusao_final", "dt_inicio_funcionamento", "dt_mudanca_situacao")},
            "ultima_atividade_em": _d(o["ultima_atividade_em"]),
            "url_portal": url_portal(o["proposta_id"]),
        }
        if diag["regras"]:
            acao.append(item)
        elif diag["severidade"] == "encerrada" or co in (3, 4, 7, 8):
            encerradas.append(item)
        else:
            em_dia.append(item)

    ordem = {"critico": 0, "atencao": 1}
    acao.sort(key=lambda i: (ordem.get(i["severidade"], 9),
                             -max((g.get("dias") or 0) for g in i["regras"])))

    # O CONVENENTE DAS OBRAS E O FUNDO MUNICIPAL DE SAUDE, nao a prefeitura —
    # e ele tem cadastro PROPRIO no CAGEC. Cruzar aqui e o que transforma duas
    # meias-verdades numa frase acionavel: sozinho, o CAGEC "nao acha o fundo"
    # (o que soa como falha de coleta) e o SISMOB mostra "so mais uma obra".
    # Juntos provam que o fundo EXISTE, esta ATIVO, movimenta recurso federal —
    # e esta FORA do cadastro estadual, o que pela LDO o impede de receber do
    # FES/Feas.
    ent = next((dict(r) for r in linhas if r["nu_cnpj"]), None)
    entidade = None
    if ent:
        cad = (await db.execute(text("""
            SELECT situacao, regular FROM cagec_situacao
            WHERE municipio_id = :m
              AND regexp_replace(cnpj, '\\D', '', 'g') = :c
        """), {"m": municipio_id, "c": ent["nu_cnpj"]})).first()
        # O cadastro e o DO ESTADO do municipio (CAGEC em MG, CHE no RS). Onde
        # nao coletamos o cadastro daquele estado, "nao tem cadastro" seria
        # afirmar o que ninguem conferiu — ai o motivo fica em branco.
        from services.cadastro_estadual import cadastro_da_uf
        cad_uf = cadastro_da_uf(mun[1] if mun else None)
        motivo = None
        if not cad and cad_uf:
            motivo = (f"Esta entidade executa recurso federal mas não tem cadastro "
                      f"no {cad_uf['sigla']}. Sem ele não assina convênio estadual de "
                      f"saúde — e a prefeitura estar regular não resolve, porque no "
                      f"{cad_uf['sigla']} cada entidade tem cadastro próprio.")
        entidade = {
            "nome": ent["entidade"], "cnpj": ent["nu_cnpj"],
            "cagec": {
                "cadastrado": bool(cad),
                "situacao": cad[0] if cad else None,
                "regular": cad[1] if cad else None,
                "motivo": motivo,
            },
        }
    return {
        "tem_dados": True,
        "municipio_id": municipio_id,
        "municipio": mun[0] if mun else None, "uf": mun[1] if mun else None,
        "entidade": entidade,
        "totais": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in tot.items()},
        "acao": acao, "em_dia": em_dia, "encerradas": encerradas,
        "por_situacao": sorted(por_situacao.values(), key=lambda e: -e["valor"]),
        "por_programa": sorted(por_programa.values(), key=lambda e: -e["valor"]),
        "empresas_concentracao": sorted(empresas_ac.values(), key=lambda e: -e["valor"]),
        "coletado_em": _d(max((r["updated_at"] for r in linhas if r["updated_at"]),
                              default=None)),
    }


@router.get("", dependencies=[exige("sismob.ver")])
async def obras(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Obras do SISMOB do municipio, ja classificadas por urgencia."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "sismob")
    return await fetch_sismob_obras(db, municipio_id)


@router.get("/obra/{proposta_id}", dependencies=[exige("sismob.ver")])
async def obra(
    proposta_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Uma obra com o payload cru da fonte.

    Fica sob /obra/ e nao na raiz para nao colidir com um futuro filtro por
    query string, e o path e inteiro, o que evita ambiguidade de rota."""
    row = (await db.execute(text("""
        SELECT municipio_id, raw_data FROM sismob_obras WHERE proposta_id = :p
    """), {"p": proposta_id})).first()
    if not row:
        raise HTTPException(404, "Obra não encontrada")
    ensure_municipio_access(current, row[0])
    ensure_tela(current, "sismob")
    dados = await fetch_sismob_obras(db, row[0])
    for grupo in ("acao", "em_dia", "encerradas"):
        for i in dados.get(grupo, []):
            if i["proposta_id"] == proposta_id:
                # A galeria sai daqui e não da listagem: são 12 fotos por obra,
                # e mandá-las em toda listagem inflaria o payload da tela (e do
                # Modo Tela) por um dado que só o modal usa.
                return {**i, "galeria": galeria_do_raw(row[1]), "raw_data": row[1]}
    raise HTTPException(404, "Obra não encontrada")


def galeria_do_raw(raw: dict | None) -> list[dict]:
    """Os grupos de fotografia da obra, normalizados a partir do payload da fonte.

    ⚠️ O GRUPO E A DATA VALEM MESMO SEM A IMAGEM, e hoje isso não é teoria: o
    serviço de imagem do Ministério devolve 500 (medido em 07/09/2026 em três
    obras de dois municípios). Ainda assim, saber que as últimas fotos são de
    «Terreno» e «Placa da obra», e que a mais recente é de 08/08/2025, diz que a
    obra parou antes de começar — que é a leitura que o gestor precisa fazer.
    Por isso a galeria é montada do metadado, e a imagem entra por cima quando
    a origem responde.
    """
    grupos = []
    for g in (raw or {}).get("gruposFotografias") or []:
        fotos = [{"id": f.get("id"),
                  "em": (f.get("dtAtualizacao") or "")[:10] or None}
                 for f in (g.get("fotos") or []) if f.get("id")]
        if fotos:
            grupos.append({
                "grupo": g.get("noGrupo") or "Sem grupo",
                "total": len(fotos),
                "ultima_em": max((f["em"] for f in fotos if f["em"]), default=None),
                "fotos": fotos,
            })
    # Mais recente primeiro: é o que responde "em que fase ele parou de registrar".
    grupos.sort(key=lambda g: (g["ultima_em"] or ""), reverse=True)
    return grupos


@router.get("/obra/{proposta_id}/foto/{foto_id}", dependencies=[exige("sismob.ver")])
async def foto(
    proposta_id: int,
    foto_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """A imagem da obra, servida POR AQUI — o usuário não sai do PACTHA.

    ⚠️ O `proposta_id` NO CAMINHO NÃO É ENFEITE: é o que impede este endpoint de
    virar um proxy aberto para qualquer URL do Ministério. O id da foto só é
    aceito se estiver no payload DAQUELA obra, e a obra passa pelo gate de
    município e de tela como qualquer outra leitura. Sem isso, bastaria uma
    conta de quiosque com um UUID qualquer para usar o servidor de repasse.

    ⚠️ FALHA DA ORIGEM SAI COMO 502, e com a frase — nunca como imagem quebrada:
    a tela precisa distinguir «o Ministério está fora» de «esta obra não tem
    foto», que é exatamente o que confundiria quem olha uma obra parada.
    """
    row = (await db.execute(text(
        "SELECT municipio_id, raw_data FROM sismob_obras WHERE proposta_id = :p"
    ), {"p": proposta_id})).first()
    if not row:
        raise HTTPException(404, "Obra não encontrada")
    ensure_municipio_access(current, row[0])
    ensure_tela(current, "sismob")

    ids = {f["id"] for g in galeria_do_raw(row[1]) for f in g["fotos"]}
    if foto_id not in ids:
        raise HTTPException(404, "Foto não pertence a esta obra")

    import httpx
    from fastapi import Response
    from services.sismob_catalogo import URL_FOTO
    try:
        async with httpx.AsyncClient(timeout=25, verify=False) as c:
            r = await c.get(URL_FOTO.format(id=foto_id),
                            headers={"User-Agent": "PACTHA/1.0",
                                     "Referer": "https://sismobcidadao.saude.gov.br/",
                                     "Accept": "image/*"})
    except Exception as e:
        raise HTTPException(502, f"O SISMOB não respondeu: {type(e).__name__}") from e
    # Assinatura de imagem, e não o content-type: a origem devolve
    # `application/octet-stream` para PNG e JSON de erro com 200 em alguns casos.
    if r.status_code == 200 and r.content[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0",
                                                  b"\xff\xd8\xff\xe1", b"\xff\xd8\xff\xdb"):
        tipo = "image/png" if r.content[:4] == b"\x89PNG" else "image/jpeg"
        # Cache no navegador: a foto de uma obra não muda, e sem isto cada
        # abertura do modal repete a ida ao Ministério.
        return Response(content=r.content, media_type=tipo,
                        headers={"Cache-Control": "private, max-age=86400"})
    raise HTTPException(502, "O SISMOB não entregou a imagem (erro na origem).")


@router.post("/refresh", dependencies=[exige("sismob.atualizar")])
async def refresh(current: User = Depends(get_current_user)):
    """Dispara a coleta na hora. Mesmo precedente de /api/cauc/refresh: o
    coletor e sincrono, entao vai para uma thread para nao travar o event loop."""
    ensure_tela(current, "sismob")
    from ingestion.sismob_obras import ingest
    import os
    os.environ["SISMOB_FORCE"] = "1"      # pedido explicito ignora o auto-throttle
    try:
        n = await anyio.to_thread.run_sync(ingest)
    finally:
        os.environ.pop("SISMOB_FORCE", None)
    return {"ok": True, "obras": n}
