"""TCE-PR — o que o município do Paraná declarou ao Tribunal, pelo PIT/SIM-AM.

Lê as tabelas que `ingestion/tce_pr.py` grava. Uma rota, uma tela (`tce_pr`).

⚠️ SÓ RESPONDE PARA MUNICÍPIO DO PR. O Tribunal é do Estado; para outra UF a
resposta é `tem_dados: false` com o motivo, e o menu já esconde a tela lá.

⚠️ O DADO TEM ATRASO DE MESES, e isso é o prazo do SIM-AM, não falha nossa: a
entidade entrega mês a mês e o TCE publica depois. O payload leva `ultimo_envio`
(o último mês entregue) para a tela dizer "dados até junho/2026".
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/pr", tags=["tce-pr"])

_FORA_DO_PR = ("O TCE-PR fiscaliza os municípios do Paraná; este município é de "
               "outro estado.")

# Marcas no plano padrão / descrição da fonte, comparadas em minúsculas e sem
# acento (`unaccent` não é garantido nos bancos, então normaliza aqui).
_MARCAS_CONVENIO = ("voluntaria", "convenio", "emenda")
_MARCAS_LEGAIS = ("transfer", "fundo a fundo", "bloco de", "fnde", "pnae", "pnate",
                  "fundeb", "suas", "salario educacao", "complementacao da uniao",
                  "assistencia financeira da uniao", "agentes comunitarios")


def _sem_acento(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn").lower()


def categoria_da_fonte(plano: str | None, fonte: str | None) -> str:
    """`convenio` | `legal` | `propria` — de onde veio o dinheiro desta fonte.

    - `convenio`: transferência VOLUNTÁRIA, convênio ou emenda. É o que o PACTHA
      acompanha, e a tela abre por aqui.
    - `legal`: fundo a fundo e transferências automáticas (SUS em blocos,
      FNDE, FUNDEB, SUAS) — dinheiro de fora, mas sem instrumento a vigiar.
    - `propria`: recurso livre, impostos vinculados, taxas, operação de crédito.

    ⚠️ Emenda de saúde fundo a fundo ("Bloco de Custeio ... Emendas Individuais")
    cai em `convenio` de propósito: é emenda, e o gestor pergunta por ela junto
    das outras. O texto vem do PLANO PADRÃO do TCE e da fonte que o município
    criou; o município escreve a fonte como quer, e por isso as marcas são
    largas."""
    t = _sem_acento(f"{plano or ''} | {fonte or ''}")
    if any(m in t for m in _MARCAS_CONVENIO):
        return "convenio"
    if any(m in t for m in _MARCAS_LEGAIS):
        return "legal"
    return "propria"


async def _uf(db: AsyncSession, municipio_id: int) -> str:
    uf = (await db.execute(text(
        "SELECT upper(coalesce(uf, '')) FROM municipios WHERE id = :m"),
        {"m": municipio_id})).scalar()
    if uf is None:
        raise HTTPException(404, "Município não encontrado")
    return uf


def _f(v):
    return float(v) if v is not None else None


def _d(v):
    return v.isoformat() if v else None


@router.get("/tce", dependencies=[exige("tce_pr.ver")])
async def tce(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Convênios, obras, licitações, contratos e despesa por fonte — TCE-PR."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "tce_pr")
    if await _uf(db, municipio_id) != "PR":
        return {"tem_dados": False, "motivo": _FORA_DO_PR}
    m = {"m": municipio_id}

    arquivos = (await db.execute(text("""
        SELECT ano, referencia, ultimo_envio, atualizado_em
          FROM tce_pr_arquivos WHERE municipio_id = :m ORDER BY ano DESC
    """), m)).fetchall()
    if not arquivos:
        # ⚠️ "Ainda não coletado" NÃO é "o município não tem nada no TCE".
        return {"tem_dados": True, "coletado": False}

    entidades = (await db.execute(text("""
        SELECT id_pessoa, max(nm_entidade), sum(n) FROM (
            SELECT id_pessoa, nm_entidade, count(*) AS n FROM tce_pr_contratos
             WHERE municipio_id = :m GROUP BY 1, 2
            UNION ALL
            SELECT id_pessoa, nm_entidade, count(*) FROM tce_pr_licitacoes
             WHERE municipio_id = :m GROUP BY 1, 2
            UNION ALL
            SELECT id_pessoa, nm_entidade, count(*) FROM tce_pr_despesa_fonte
             WHERE municipio_id = :m GROUP BY 1, 2
        ) t WHERE id_pessoa IS NOT NULL GROUP BY id_pessoa ORDER BY sum(n) DESC
    """), m)).fetchall()

    return {
        "tem_dados": True,
        "coletado": True,
        "atualizado_em": _d(max(r[3] for r in arquivos)),
        # O ano mais recente com arquivo: a referência de geração e o último mês
        # que a entidade entregou ao SIM-AM (armadilha 9 do coletor).
        "referencia": arquivos[0][1],
        "ultimo_envio": arquivos[0][2],
        "anos_coletados": [r[0] for r in arquivos],
        "entidades": [{"id": r[0], "nome": r[1]} for r in entidades],
        "despesa": await _despesa(db, municipio_id),
        "convenios": await _convenios(db, municipio_id),
        "obras": await _obras(db, municipio_id),
        "licitacoes_por_ano": await _licitacoes_por_ano(db, municipio_id),
        "contratos_vigentes": await _contratos_vigentes(db, municipio_id),
    }


async def _despesa(db: AsyncSession, municipio_id: int) -> list[dict]:
    """Empenhado/liquidado/pago por fonte, nos exercícios agregados pelo coletor."""
    linhas = (await db.execute(text("""
        SELECT ano, id_pessoa, cd_fonte, ds_fonte, ds_plano_padrao, qt_empenhos,
               vl_empenhado, vl_liquidado, vl_pago
          FROM tce_pr_despesa_fonte WHERE municipio_id = :m
         ORDER BY ano DESC, vl_empenhado DESC NULLS LAST
    """), {"m": municipio_id})).fetchall()
    return [{
        "ano": r[0], "entidade": r[1], "codigo": r[2], "fonte": r[3], "plano": r[4],
        "empenhos": r[5], "empenhado": _f(r[6]), "liquidado": _f(r[7]),
        "pago": _f(r[8]), "categoria": categoria_da_fonte(r[4], r[3]),
    } for r in linhas]


async def _convenios(db: AsyncSession, municipio_id: int) -> list[dict]:
    linhas = (await db.execute(text("""
        SELECT id_convenio, ano, id_pessoa, nr_convenio, dt_celebracao, situacao,
               esfera, vl_convenio, vl_recurso_proprio, dt_inicio_vigencia,
               dt_fim_vigencia, ds_objeto, ds_fonte_receita
          FROM tce_pr_convenios WHERE municipio_id = :m
         ORDER BY ano DESC, dt_celebracao DESC NULLS LAST
    """), {"m": municipio_id})).fetchall()
    return [{
        "id": r[0], "ano": r[1], "entidade": r[2], "numero": r[3],
        "celebracao": _d(r[4]), "situacao": r[5], "esfera": r[6],
        "valor": _f(r[7]), "contrapartida": _f(r[8]),
        "vigencia_inicio": _d(r[9]), "vigencia_fim": _d(r[10]),
        "objeto": r[11], "fonte": r[12],
    } for r in linhas]


async def _obras(db: AsyncSession, municipio_id: int) -> dict:
    total = (await db.execute(text(
        "SELECT count(*), sum(vl_intervencao) FROM tce_pr_obras WHERE municipio_id = :m"),
        {"m": municipio_id})).first()
    # As 60 mais recentes: a tela mostra a lista, e obra de 2014 concluída não é
    # o que o gestor procura. O total vem à parte para a contagem não mentir.
    linhas = (await db.execute(text("""
        SELECT id_intervencao, ano, id_pessoa, nm_intervencao, vl_intervencao,
               dt_inicio, prazo_dias, situacao, regime, dt_ultima_medicao, bens
          FROM tce_pr_obras WHERE municipio_id = :m
         ORDER BY ano DESC, vl_intervencao DESC NULLS LAST LIMIT 60
    """), {"m": municipio_id})).fetchall()
    return {
        "total": int(total[0] or 0),
        "valor_total": _f(total[1]),
        "obras": [{
            "id": r[0], "ano": r[1], "entidade": r[2], "nome": r[3],
            "valor": _f(r[4]), "inicio": _d(r[5]), "prazo_dias": r[6],
            "situacao": r[7], "regime": r[8], "ultima_medicao": _d(r[9]),
            "locais": r[10] or [],
        } for r in linhas],
    }


async def _licitacoes_por_ano(db: AsyncSession, municipio_id: int) -> list[dict]:
    linhas = (await db.execute(text("""
        SELECT ano, id_pessoa, count(*), sum(vl_licitacao)
          FROM tce_pr_licitacoes
         WHERE municipio_id = :m
           AND ano IN (SELECT DISTINCT ano FROM tce_pr_licitacoes
                        WHERE municipio_id = :m ORDER BY ano DESC LIMIT 6)
         GROUP BY ano, id_pessoa ORDER BY ano DESC, id_pessoa
    """), {"m": municipio_id})).fetchall()
    return [{"ano": r[0], "entidade": r[1], "total": r[2],
             "valor_estimado": _f(r[3])} for r in linhas]


async def _contratos_vigentes(db: AsyncSession, municipio_id: int) -> list[dict]:
    """Contratos de pé hoje, com prazo e valor DEPOIS dos aditivos.

    ⚠️ O fim vale o MAIOR entre o do contrato e o dos aditivos de prazo, e o valor
    é o `vl_atualizado` do aditivo de valor mais recente — sem isso, contrato
    prorrogado aparece vencido e o aditivado aparece pelo valor de origem.
    Contrato com aditivo de rescisão sai da lista."""
    linhas = (await db.execute(text("""
        WITH ad AS (
            SELECT id_contrato,
                   max(dt_fim) FILTER (WHERE arquivo = 'prazo') AS fim_aditivo,
                   bool_or(arquivo = 'rescisao') AS rescindido,
                   (array_agg(vl_atualizado ORDER BY dt_aditivo DESC NULLS LAST,
                                                     ano_aditivo DESC)
                     FILTER (WHERE arquivo = 'valor' AND vl_atualizado IS NOT NULL)
                   )[1] AS valor_atual,
                   count(*) AS qt
              FROM tce_pr_contratos_aditivos WHERE municipio_id = :m
             GROUP BY id_contrato
        )
        SELECT c.id_contrato, c.nr_contrato, c.ano, c.id_pessoa, c.ds_objeto,
               c.nm_contratado, c.vl_contrato, ad.valor_atual,
               greatest(c.dt_fim, ad.fim_aditivo) AS fim, coalesce(ad.qt, 0)
          FROM tce_pr_contratos c LEFT JOIN ad USING (id_contrato)
         WHERE c.municipio_id = :m
           AND NOT coalesce(ad.rescindido, FALSE)
           AND greatest(c.dt_fim, ad.fim_aditivo) >= CURRENT_DATE
         ORDER BY fim LIMIT 60
    """), {"m": municipio_id})).fetchall()
    return [{
        "id": r[0], "numero": f"{r[1]}/{r[2]}", "entidade": r[3], "objeto": r[4],
        "contratado": r[5], "valor": _f(r[6]), "valor_atual": _f(r[7]),
        "vigencia_ate": _d(r[8]), "aditivos": r[9],
    } for r in linhas]
