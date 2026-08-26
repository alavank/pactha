"""Mudancas de status detectadas nas atualizacoes diarias (trigger log_status_change).

Alimenta o aviso no dashboard: "o que mudou de status desde a ultima vez".
Fonte: tabela status_changes (preenchida por trigger AFTER UPDATE em
transferegov_propostas e convenios_estadual).
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from services.auth import get_current_user, ensure_municipio_access
from services import authz
from services.registro_rotas import declarado
from models.user import User

router = APIRouter(prefix="/api/status-changes", tags=["status-changes"])

# ⚠️ A tabela `status_changes` e alimentada por trigger em DUAS tabelas —
# `convenios_estadual` e `transferegov_propostas` — e o endpoint devolve as duas
# misturadas. A exigencia honesta e "uma das duas": `exige()` cobraria as duas
# juntas e tiraria o aviso do dashboard de quem so acompanha uma das fontes.
# Mesmo desenho de `routers/municipios.py::municipio_summary`.
_FONTES_PERMISSOES = ("convenios.ver", "transferegov.ver")


def _clean(s):
    if not isinstance(s, str):
        return s
    return s.replace("�", "").replace("  ", " ").strip()


# As `fonte` que o trigger grava, e o motivo de existirem por escrito aqui.
#
# ⚠️ A DO TRANSFEREGOV E `voluntaria`, NAO `transferegov`. Quem escreve e o
# `log_status_change` (migrations/add_status_changes.sql): a tabela de origem e
# `transferegov_propostas`, mas o rotulo gravado e `voluntaria`. Filtrar por
# 'transferegov' devolveria ZERO linhas — sem erro, sem log, com um painel vazio
# que se le como "nada mudou". E o mesmo nome tem outro significado em
# `scraper_municipio_coleta.fonte`, onde 'transferegov' EXISTE: duas colunas
# chamadas `fonte`, com vocabularios diferentes, a poucas linhas uma da outra.
FONTE_VOLUNTARIAS = "voluntaria"
FONTE_SIGCON = "sigcon"
FONTE_FNS = "fns"


async def listar_core(
    db: AsyncSession,
    municipio_ids: list[int],
    days: int = 30,
    limit: int = 100,
    fontes: tuple[str, ...] | None = None,
) -> dict:
    """Nucleo SET-AWARE das mudancas de status, SEM gate de auth. Varre um
    CONJUNTO de municipios (`= ANY(:mids)`); para [X] === por-municipio. Reusado
    pelo endpoint /api/status-changes e pelo Painel de Indicadores (BI).

    `fontes` recorta por origem (ver as constantes acima). `None` = todas, que e
    o comportamento historico e o que os dois chamadores antigos continuam
    recebendo sem mudar uma linha."""
    if not municipio_ids:
        return {"items": [], "total": 0}
    _filtro = "AND fonte = ANY(:fontes)" if fontes else ""
    rows = (await db.execute(text(f"""
        SELECT id, fonte, tabela, ref, orgao, objeto,
               status_anterior, status_novo, changed_at
        FROM status_changes
        WHERE municipio_id = ANY(:mids)
          AND changed_at >= NOW() - make_interval(days => :days)
          AND length(trim(coalesce(objeto, ''))) > 3
          AND coalesce(ref, '') !~* 'n[aã]o h'
          {_filtro}
        ORDER BY changed_at DESC
        LIMIT :lim
    """), {"mids": list(municipio_ids), "days": days, "lim": limit,
           **({"fontes": list(fontes)} if fontes else {})})).fetchall()
    items = [{
        "id": r[0],
        "fonte": r[1],
        "ref": r[3],
        "orgao": _clean(r[4]),
        "objeto": _clean(r[5]),
        "status_anterior": _clean(r[6]),
        "status_novo": _clean(r[7]),
        "changed_at": r[8].isoformat() if r[8] else None,
    } for r in rows]
    return {"items": items, "total": len(items)}


def _mesma_situacao(a, b) -> bool:
    """Duas grafias do MESMO estado? Compara sem caixa, sem espaço duplicado e
    sem o `�` que o portal solta no lugar de acento corrompido.

    Existe porque "mudou de status" tem de significar mudou de ESTADO. Uma
    diferença só de caixa (`Complementado` x `complementado`) é ruído de fonte,
    não notícia — e o trigger, que compara com `IS DISTINCT FROM`, não tem como
    saber disso."""
    def _n(s):
        return " ".join(str(s or "").replace("�", "").split()).casefold()
    return _n(a) == _n(b)


def consolidar_por_ref(items: list[dict], limite: int = 40) -> list[dict]:
    """A mudança LÍQUIDA por instrumento na janela, e não cada escrita.

    ⭐ POR QUE ISTO EXISTE (medido em produção, 25/08/2026). A mesma proposta
    aparecia quatro vezes no painel, indo e voltando entre dois rótulos — porque
    `transferegov_propostas.situacao` tem DOIS escritores (o scraper e o CSV
    diário do open data) e cada um desfazia o do outro. O trigger registra toda
    escrita; o painel tem de responder outra pergunta.

    "O que mudou nos últimos 15 dias" é: onde o instrumento ESTAVA quando a
    janela começou e onde ele ESTÁ agora. Então:
      - do grupo, o estado inicial é o `status_anterior` da mudança MAIS ANTIGA
        e o final é o `status_novo` da MAIS NOVA;
      - se os dois forem o mesmo estado, o instrumento VOLTOU para onde estava:
        não houve mudança líquida, e ele sai da lista;
      - `passos` guarda quantas escritas houve, para a tela poder dizer que
        aquilo oscilou em vez de fingir que foi um pulo só.

    ⚠️ `items` TEM de vir ordenado do mais novo para o mais antigo (é como o
    `listar_core` devolve). E o LIMITE se aplica DEPOIS de consolidar — cortar
    antes truncaria um grupo pela metade e inventaria uma mudança líquida que
    não existe."""
    grupos: dict[tuple, dict] = {}
    for it in items:                       # do mais NOVO para o mais ANTIGO
        chave = (it.get("fonte"), it.get("ref"))
        g = grupos.get(chave)
        if g is None:
            # 1ª visita = a mudança mais NOVA deste instrumento: ela dá o estado
            # final, a data e os campos de exibição.
            grupos[chave] = {**it, "passos": 1}
        else:
            # As seguintes são mais antigas: só recuam o estado INICIAL.
            g["status_anterior"] = it.get("status_anterior")
            g["passos"] += 1
    saida = [g for g in grupos.values()
             if not _mesma_situacao(g.get("status_anterior"), g.get("status_novo"))]
    saida.sort(key=lambda g: g.get("changed_at") or "", reverse=True)
    return saida[:limite]


@router.get("", dependencies=[declarado(*_FONTES_PERMISSOES)])
async def listar(
    municipio_id: int = Query(...),
    days: int = Query(30, description="janela em dias"),
    limit: int = Query(100),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Lista as mudancas de status recentes de um municipio (mais novas primeiro)."""
    ensure_municipio_access(current, municipio_id)
    if not any(authz.pode(current, chave) for chave in _FONTES_PERMISSOES):
        authz.negar(current, tipo="permissao",
                    exigido=" ou ".join(_FONTES_PERMISSOES),
                    possui=authz.permissoes_de(current),
                    mensagem="Voce nao tem permissao para esta acao")
    return await listar_core(db, [municipio_id], days, limit)
