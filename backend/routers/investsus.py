"""InvestSUS — os repasses federais de saúde que caem no Fundo Municipal.

⭐ DESDE 02/09/2026 ESTA TELA TEM DINHEIRO DE VERDADE. Nasceu como conteúdo
curado porque o InvestSUS exige login e o acesso estava barrado no MFA. O valor
consolidado por bloco, porém, é PÚBLICO e sai do ConsultaFNS sem login nenhum —
`ingestion/fns_faf.py` coleta e esta rota serve.

⚠️ COMO ESSE CAMINHO FOI ACHADO, porque a lição vale para as outras 16 fontes:
uma investigação anterior SONDOU endereços por adivinhação, tomou `{}` e HTTP 400
como prova de ausência e concluiu — por escrito — que "não há caminho público
para o fundo a fundo". Estava errado. O caminho apareceu ao ABRIR A TELA do
ConsultaFNS e ler as chamadas que ela mesma faz. **Quando a API não responde,
abra a tela antes de declarar que não existe caminho.**

⚠️ O AVISO MUDOU DE ASSUNTO, NÃO SUMIU. Antes dizia "esta tela não coleta". Hoje
o que ela não tem é o DETALHE parcela a parcela — esse continua atrás do login do
InvestSUS. Conteúdo estático sem ressalva se passa por monitoramento, e numa tela
de dinheiro de saúde isso é pior que tela vazia; um consolidado apresentado como
se fosse o extrato completo teria o mesmo defeito.

⚠️ Gate `investsus.ver` + tela `investsus`. A permissão herda de `consultas` na
migration, então quem já via o FNS vê esta tela sem concessão nova — decisão
registrada em `add_permissoes_por_acao.sql`.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.investsus_conteudo import (
    AVISO, AVISO_SEM_COLETA, BLOCOS, BLOQUEIO_MFA, CONFERIR, LINKS, RESUMO,
    SUBTITULO, TITULO,
)
from services.registro_rotas import exige

router = APIRouter(prefix="/api/investsus", tags=["investsus"])


async def _faf(db: AsyncSession, municipio_id: int, ano: int | None) -> dict | None:
    """O fundo a fundo consolidado por bloco e grupo. None = nunca coletado.

    ⚠️ None E LISTA VAZIA SÃO COISAS DIFERENTES e a tela usa a diferença: None
    vira "ainda não coletamos" e `[]` viraria "coletamos e o município não
    recebeu". Devolver `{}` nos dois casos faria a tela acusar o município de não
    receber nada quando o problema é nosso.

    ⚠️ A SOMA É FEITA SOBRE `grupo_codigo <> 0`, com fallback. `grupo_codigo = 0`
    é a linha de TOTAL do bloco, gravada quando o portal não detalhou grupos —
    somar tudo junto contaria o mesmo dinheiro duas vezes em qualquer bloco que
    tenha as duas formas.
    """
    anos = [r[0] for r in (await db.execute(text(
        "SELECT DISTINCT ano FROM fns_repasse_faf WHERE municipio_id = :m "
        "ORDER BY ano DESC"), {"m": municipio_id})).all()]
    if not anos:
        return None
    alvo = ano if ano in anos else anos[0]

    linhas = (await db.execute(text("""
        SELECT bloco_codigo, bloco_nome, grupo_codigo, grupo_nome,
               vl_total, vl_desconto, vl_liquido, updated_at
          FROM fns_repasse_faf
         WHERE municipio_id = :m AND ano = :a
         ORDER BY bloco_codigo, grupo_codigo
    """), {"m": municipio_id, "a": alvo})).all()

    blocos: dict[int, dict] = {}
    atualizado = None
    for bcod, bnome, gcod, gnome, tot, desc, liq, upd in linhas:
        b = blocos.setdefault(bcod, {"codigo": bcod, "nome": bnome, "grupos": [],
                                     "total": 0.0, "desconto": 0.0, "liquido": 0.0,
                                     "_detalhado": False})
        f = lambda v: float(v) if v is not None else 0.0  # noqa: E731
        # ⚠️ O CARIMBO É DA LINHA, QUALQUER LINHA — e por isso sobe ANTES do
        # desvio abaixo. Ele ficava só no ramo dos grupos reais, então um
        # município cujos blocos vieram todos sem detalhamento exibia dinheiro
        # de verdade sem nenhuma data de coleta ao lado: a tela mostrava o valor
        # e não sabia dizer de quando ele era.
        if upd and (atualizado is None or upd > atualizado):
            atualizado = upd
        if gcod == 0:
            # Total do bloco sem detalhamento: só entra se nenhum grupo real veio.
            b["_total_solto"] = (f(tot), f(desc), f(liq))
            continue
        b["_detalhado"] = True
        b["grupos"].append({"codigo": gcod, "nome": gnome, "total": f(tot),
                            "desconto": f(desc), "liquido": f(liq)})
        b["total"] += f(tot)
        b["desconto"] += f(desc)
        b["liquido"] += f(liq)

    for b in blocos.values():
        if not b.pop("_detalhado") and "_total_solto" in b:
            b["total"], b["desconto"], b["liquido"] = b["_total_solto"]
        b.pop("_total_solto", None)

    lista = sorted(blocos.values(), key=lambda x: -x["total"])
    for b in lista:
        b["grupos"].sort(key=lambda g: -g["total"])

    # ⭐ A SÉRIE DOS ÚLTIMOS QUATRO ANOS — o desconto de um ano sozinho não diz
    # nada; a sequência diz tudo. Medido em Bueno Brandão/MG: 2,2% do repasse
    # retido em 2023, 1,6% em 2024, **10,0% em 2025 e 23,6% em 2026**. É a mesma
    # informação que o gestor levaria meses para juntar abrindo o portal ano a
    # ano — e o salto entre 2024 e 2025 é o que faz alguém perguntar por quê.
    #
    # ⚠️ MESMA REGRA DE `grupo_codigo <> 0` DA CONSULTA ACIMA: a linha de total
    # do bloco convive com as linhas de grupo, e somar as duas contaria o mesmo
    # dinheiro duas vezes. Aqui o filtro é feito com um NOT EXISTS por (ano,
    # bloco), que é a tradução em SQL do `_detalhado` do laço.
    serie = [{
        "ano": r[0],
        "total": float(r[1] or 0), "desconto": float(r[2] or 0), "liquido": float(r[3] or 0),
        # O ano corrente ainda está recebendo competências: o total dele NÃO é
        # comparável com o de um ano fechado, e a tela precisa dizer isso.
        "em_curso": r[0] == date.today().year,
    } for r in (await db.execute(text("""
        SELECT ano, SUM(vl_total), SUM(vl_desconto), SUM(vl_liquido)
          FROM fns_repasse_faf f
         WHERE municipio_id = :m
           AND (grupo_codigo <> 0 OR NOT EXISTS (
                 SELECT 1 FROM fns_repasse_faf g
                  WHERE g.municipio_id = f.municipio_id AND g.ano = f.ano
                    AND g.bloco_codigo = f.bloco_codigo AND g.grupo_codigo <> 0))
         GROUP BY ano ORDER BY ano DESC LIMIT 4
    """), {"m": municipio_id})).all()]
    serie.reverse()   # do mais antigo para o mais novo: a barra lê da esquerda

    return {
        "ano": alvo,
        "anos": anos,
        "blocos": lista,
        "total": sum(b["total"] for b in lista),
        "desconto": sum(b["desconto"] for b in lista),
        "liquido": sum(b["liquido"] for b in lista),
        "serie": serie,
        "atualizado_em": atualizado.isoformat() if atualizado else None,
    }


@router.get("", dependencies=[exige("investsus.ver")])
async def investsus(
    municipio_id: int = Query(...),
    ano: int | None = Query(None, description="Ano do fundo a fundo; padrão = o mais recente coletado"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Fundo a fundo consolidado + conteúdo curado + situação da credencial."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "investsus")

    row = (await db.execute(text(
        "SELECT nome, cnpj FROM municipios WHERE id = :m"), {"m": municipio_id})).first()
    if row is None:
        raise HTTPException(404, "Município não encontrado")

    # ⭐ O ÚNICO DADO VIVO DA TELA. A credencial pode estar guardada com escopo
    # DESTE município ou com escopo da instância (municipio_id NULL) — o Cofre
    # aceita os dois, e os coletores também. Contar só as do município daria
    # "não cadastrada" num tenant de um município só, onde a credencial legítima
    # está no escopo geral. É o arranjo real do Monte Sião.
    cred = (await db.execute(text("""
        SELECT count(*) FILTER (WHERE municipio_id = :m),
               count(*) FILTER (WHERE municipio_id IS NULL)
          FROM cofre_senhas
         WHERE automation_key = 'investsus'
            OR sistema ILIKE 'InvestSUS%'
    """), {"m": municipio_id})).first()
    do_municipio, da_instancia = (cred[0] or 0), (cred[1] or 0)

    faf = await _faf(db, municipio_id, ano)

    return {
        "tem_dados": True,
        # ⚠️ O AVISO DEPENDE DO QUE HÁ PARA MOSTRAR. O texto padrão abre com
        # "Os valores abaixo" — mandá-lo num tenant sem coleta apontaria para um
        # dinheiro que a tela não está exibindo.
        "aviso": AVISO if faf else AVISO_SEM_COLETA,
        "titulo": TITULO,
        "subtitulo": SUBTITULO,
        "resumo": RESUMO,
        "blocos": BLOCOS,
        "conferir": CONFERIR,
        "links": LINKS,
        # ⭐ O DINHEIRO. None enquanto o coletor não rodou neste tenant.
        "faf": faf,
        # Agora É automática — mas só do consolidado por bloco. A tela é obrigada
        # a manter essa distinção visível; ver o cabeçalho do módulo.
        "coleta_automatica": faf is not None,
        # Medido em 17/08: a credencial funciona, o SCPA é que exige MFA ainda
        # não cadastrado. É pendência do município, e a tela precisa dizer qual.
        # Continua aqui porque é o que destrava o DETALHE parcela a parcela.
        "bloqueio": BLOQUEIO_MFA,
        "municipio": {
            "nome": row[0],
            "cnpj": row[1],
            "credencial_cadastrada": bool(do_municipio or da_instancia),
            "credencial_escopo": ("municipio" if do_municipio
                                  else "instancia" if da_instancia else None),
        },
    }
