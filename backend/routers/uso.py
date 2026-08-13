"""TELEMETRIA DE USO — o que as pessoas fazem no sistema.

⚠️ NAO E A TRILHA DE AUDITORIA, e nao deve virar. A trilha (`audit_log`) e
append-only com cadeia de hash, guarda ATO CONSEQUENTE e tem ~181 eventos em 30
dias; ela existe para provar. Isto aqui guarda NAVEGACAO, gera centenas de
eventos por sessao e existe para entender o uso. Misturar apagaria o sinal da
trilha com barulho — e seria impossivel de qualquer forma: o gatilho de
`add_auditoria_imutavel.sql` recusa UPDATE e DELETE, e a coluna de tempo ativo
precisa ser somada a cada batimento.

Duas regras que valem para o arquivo inteiro:
  · telemetria NUNCA atrasa nem derruba a acao do usuario — 204 sempre;
  · o relogio e do SERVIDOR. O cliente diz "estou ativo", nunca "passaram 47
    minutos". Nao ha desktop de prefeitura com relogio confiavel.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import get_current_user
from services.audit import _sessao as _sessao_do_token, registrar
from services.registro_rotas import exige

router = APIRouter(prefix="/api/uso", tags=["uso"])
logger = logging.getLogger("uso")

# Vocabulario FECHADO. Com nove verbos e ~23 telas, "o que acessam mais" cabe
# numa frase; sem o fechamento, em seis meses o agregado tem 200 categorias que
# ninguem sabe ler. Valor desconhecido vira "outro" — NUNCA erro (recusar
# quebraria o lote inteiro por causa de uma linha).
_ACOES = {"ver", "detalhe", "filtrar", "buscar", "exportar",
          "gerar", "perguntar", "acionar", "sair"}

# Teto de eventos por requisicao. O excedente e cortado e CONTADO — a tela
# mostra `descartados`, porque telemetria que descarta calada ensina o dono a
# confiar num total incompleto.
_TETO_LOTE = 100
# Teto do salto de tempo por batimento. Sem ele, notebook fechado na sexta
# despejaria 60 horas de "ativo" na segunda.
_TETO_SALTO_S = 150
# Uma sessao e considerada VIVA se deu sinal nos ultimos 90s (o flush e a cada
# 45s, entao isto tolera uma perda).
_JANELA_ONLINE_S = 90
# Depois de parar de dar sinal, a sessao ainda aparece por mais um tempo — para
# o chip poder ficar vermelho e se despedir, em vez de sumir sem explicacao.
_JANELA_SAINDO_S = 150
# Depois de um LOGOUT EXPLICITO o cartao fica so o tempo de se despedir em
# vermelho. E fato consumado, nao suspeita — segurar mais contradiz o que a
# pessoa acabou de fazer.
_JANELA_DESPEDIDA_S = 20


class _Evento(BaseModel):
    # `extra="ignore"`: chave desconhecida e IGNORADA, nunca 422. O CI tem filtro
    # de paths e o frontend novo sempre vai correr contra API velha por um tempo.
    model_config = {"extra": "ignore"}
    ha_ms: int = 0
    tela: str = ""
    rota: Optional[str] = None
    acao: str = "outro"
    alvo: Optional[str] = None
    ms: Optional[int] = None
    municipio_id: Optional[int] = None
    detalhe: Optional[dict[str, Any]] = None


class _Sessao(BaseModel):
    model_config = {"extra": "ignore"}
    ativo: bool = True
    tela: Optional[str] = None
    encerrar: Optional[str] = None   # 'logout' | 'aba_fechada'


class _Lote(BaseModel):
    model_config = {"extra": "ignore"}
    # ⚠️ O CLIENTE NAO MANDA `sid`. Ele sai do TOKEN, pelo mesmo caminho que a
    # trilha ja usa (`services/audit.py::_sessao`) — sessao que o navegador
    # escolhe nao serve de agrupamento confiavel, e mandar o identificador de
    # sessao no corpo abriria a porta para uma aba escrever na sessao de outra.
    # O campo fica declarado so para nao quebrar cliente antigo; e ignorado.
    sid: str = ""
    sessao: _Sessao = Field(default_factory=_Sessao)
    eventos: list[_Evento] = Field(default_factory=list)


def _corta(v: Optional[str], n: int) -> Optional[str]:
    if v is None:
        return None
    v = str(v).strip()
    return v[:n] if v else None


@router.post("/lote", status_code=204)
async def receber_lote(
    corpo: _Lote,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Recebe o lote de eventos E o batimento da sessao, numa requisicao so.

    A resposta devolve quem esta online — por isso o contador do topo custa
    ZERO requisicao nova. Um poll dedicado de 1 Hz para 30 usuarios seriam 2,6
    milhoes de requisicoes por dia, e o servidor nao tem nada novo a dizer entre
    um batimento e outro.

    ⚠️ Devolve 204 SEMPRE, inclusive em falha. Metrica nao pode derrubar o
    trabalho de ninguem.
    """
    try:
        sid, _ = _sessao_do_token(request)
        if not sid:
            # Sem sessao identificavel (token sem claim, expirado): nao ha o que
            # agrupar. Silencio, nao erro.
            return Response(status_code=204)

        # A ARITMETICA DO TEMPO E DO SERVIDOR, e e ela que torna os tres numeros
        # (total / ativo / ocioso) coerentes por construcao.
        #
        # `AND user_id = :uid` faz o sid ser chave de AGRUPAMENTO, jamais de
        # autorizacao: sid de outra pessoa simplesmente nao atualiza nada.
        #
        # E DUAS ABAS NAO CONTAM DOBRADO por construcao — a segunda encontra
        # `ultimo_sinal` ja avancado e soma ~0. Vale para N abas, N navegadores
        # e retentativa de rede.
        await db.execute(text("""
            INSERT INTO uso_sessao (sid, user_id, user_email, usuario_nome, tela_atual, ip, user_agent)
            VALUES (:sid, :uid, :email, :nome, :tela, :ip, :ua)
            ON CONFLICT (sid) DO NOTHING
        """), {
            "sid": sid, "uid": current.id, "email": current.email,
            "nome": getattr(current, "nome", None) or getattr(current, "name", None),
            "tela": _corta(corpo.sessao.tela, 40),
            "ip": _corta(request.client.host if request.client else None, 64),
            "ua": _corta(request.headers.get("user-agent"), 400),
        })

        n_eventos = min(len(corpo.eventos), _TETO_LOTE)
        descartados = max(0, len(corpo.eventos) - _TETO_LOTE)

        await db.execute(text("""
            UPDATE uso_sessao SET
              seg_ativos  = seg_ativos  + CASE WHEN :ativo
                              THEN LEAST(EXTRACT(EPOCH FROM (NOW() - ultimo_sinal)), :teto)::int ELSE 0 END,
              seg_ociosos = seg_ociosos + CASE WHEN :ativo THEN 0
                              ELSE LEAST(EXTRACT(EPOCH FROM (NOW() - ultimo_sinal)), :teto)::int END,
              ultimo_sinal = NOW(),
              tela_atual   = COALESCE(CAST(:tela AS varchar), tela_atual),
              eventos      = eventos + :n,
              descartados  = descartados + :desc,
              -- ⚠️ CAST OBRIGATORIO. Sem ele o Postgres nao consegue inferir o
              -- tipo de `:encerrar` em `CASE WHEN ... IS NULL` e devolve
              -- AmbiguousParameterError — o UPDATE inteiro falhava, o `except`
              -- engolia (como foi projetado) e o resultado era ZERO sessao
              -- gravada com o endpoint respondendo 204 alegremente. O silencio
              -- que protege o usuario tambem esconde o defeito: por isso o
              -- logger.exception ao lado nao e enfeite.
              -- ⚠️ BATIMENTO SEM `encerrar` RESSUSCITA A SESSAO.
              -- `pagehide` dispara ao RECARREGAR a pagina, nao so ao fechar —
              -- entao um F5 marcava a sessao como encerrada, e como o token
              -- continua o mesmo o batimento seguinte atualizava uma sessao
              -- morta: o cartao ficava VERMELHO para sempre, inclusive o da
              -- propria pessoa que estava ali olhando.
              -- Quem manda sinal esta vivo. A despedida da aba e uma PISTA de
              -- saida, nunca uma sentenca.
              fim          = CASE WHEN CAST(:encerrar AS varchar) IS NULL THEN NULL ELSE NOW() END,
              motivo_fim   = CASE WHEN CAST(:encerrar AS varchar) IS NULL THEN NULL
                                  ELSE CAST(:encerrar AS varchar) END
            WHERE sid = :sid AND user_id = :uid
        """), {
            "sid": sid, "uid": current.id, "ativo": bool(corpo.sessao.ativo),
            "teto": _TETO_SALTO_S, "tela": _corta(corpo.sessao.tela, 40),
            "n": n_eventos, "desc": descartados,
            "encerrar": _corta(corpo.sessao.encerrar, 16),
        })

        if n_eventos:
            # UM insert com unnest: um plano, uma ida ao banco, uma escrita de
            # WAL para as N linhas — em vez de N viagens.
            agora = datetime.now(timezone.utc)
            cols: dict[str, list] = {k: [] for k in
                                     ("t", "tela", "rota", "acao", "alvo", "ms", "mun", "det")}
            for e in corpo.eventos[:_TETO_LOTE]:
                # `ocorrido_em` ancorado no servidor, com corte em [agora-5min, agora]:
                # preserva a ordem dentro da sessao sem confiar no relogio do cliente.
                atraso = max(0, min(int(e.ha_ms or 0), 300_000))
                cols["t"].append(agora - timedelta(milliseconds=atraso))
                cols["tela"].append(_corta(e.tela, 40) or "?")
                cols["rota"].append(_corta(e.rota, 80))
                cols["acao"].append(e.acao if e.acao in _ACOES else "outro")
                cols["alvo"].append(_corta(e.alvo, 120))
                cols["ms"].append(int(e.ms) if e.ms is not None else None)
                cols["mun"].append(e.municipio_id)
                # Teto de 512 B no detalhe. Whitelist por tipo (Pydantic ignora
                # chave desconhecida) e NAO a lista negra por substring que a
                # trilha usa — aquela transformaria "secretaria" em [oculto]
                # (contem "secret"), e "qual secretaria usa mais" viraria
                # [oculto] como resposta mais frequente num sistema de prefeitura.
                det = e.detalhe if isinstance(e.detalhe, dict) else None
                if det is not None and len(str(det)) > 512:
                    det = {"truncado": True}
                cols["det"].append(det)

            import json as _json
            await db.execute(text("""
                INSERT INTO uso_evento
                  (sid, user_id, municipio_id, ocorrido_em, tela, rota, acao, alvo, ms, detalhe)
                SELECT :sid, :uid, m, t, tela, rota, acao, alvo, ms, d::jsonb
                FROM unnest(
                  CAST(:t AS timestamptz[]), CAST(:tela AS varchar[]),
                  CAST(:rota AS varchar[]), CAST(:acao AS varchar[]),
                  CAST(:alvo AS varchar[]), CAST(:ms AS int[]),
                  CAST(:mun AS int[]), CAST(:det AS text[])
                ) AS x(t, tela, rota, acao, alvo, ms, m, d)
            """), {
                "sid": sid, "uid": current.id,
                "t": cols["t"], "tela": cols["tela"], "rota": cols["rota"],
                "acao": cols["acao"], "alvo": cols["alvo"], "ms": cols["ms"],
                "mun": cols["mun"],
                "det": [None if d is None else _json.dumps(d, ensure_ascii=False)
                        for d in cols["det"]],
            })

        # ⭐ SESSAO QUE FECHA VIRA UM ATO NA TRILHA — com o tempo dentro.
        # E a ponte entre os dois sistemas: a telemetria sabe quanto tempo a
        # pessoa ficou e quanto foi ocioso; a trilha e quem guarda "fulano saiu"
        # como evento consequente e imutavel. Sem isto, o "saiu do sistema" da
        # Auditoria continuaria sendo uma linha seca, sem duracao.
        # UMA linha por sessao, e nao uma por batimento — o guard e o `encerrar`.
        if corpo.sessao.encerrar:
            r = await db.execute(text("""
                SELECT seg_ativos, seg_ociosos, eventos,
                       EXTRACT(EPOCH FROM (COALESCE(fim, ultimo_sinal) - inicio))::int
                FROM uso_sessao WHERE sid = :sid AND user_id = :uid
            """), {"sid": sid, "uid": current.id})
            d = r.first()
            if d:
                await registrar(
                    db, action="sessao.encerrada", user=current, request=request,
                    target_type="sessao", target_id=sid,
                    details={
                        "motivo": corpo.sessao.encerrar,
                        "duracao_seg": d[3], "ativo_seg": d[0],
                        "ocioso_seg": d[1], "atos": d[2],
                    },
                )
        await db.commit()
    except Exception:
        # Engolir e DELIBERADO: a alternativa e a metrica derrubar a acao.
        # `exception` e nao `warning` para o stack aparecer no log do container.
        logger.exception("uso/lote: ignorado")
        try:
            await db.rollback()
        except Exception:
            pass

    return Response(status_code=204)


@router.get("/presenca", dependencies=[exige("uso.ver")])
async def presenca(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Quem esta online agora, e desde quando.

    "Online" e derivado na LEITURA (`ultimo_sinal` recente), sem varredor e sem
    UPDATE de fechamento: corrige retroativamente e nao depende de agendador,
    que esta infra nao tem dentro do processo.

    ⚠️ Exclui QUIOSQUE. O token de TV dura 365 dias e a televisao do saguao
    consultaria o dia inteiro — sem o filtro ela fica permanentemente no topo de
    "quem esta online", "ha 47 dias", afundando as pessoas de verdade.

    O contador de segundos roda no CLIENTE, sobre o `desde` daqui; por isso a
    resposta devolve `agora`, para o navegador corrigir o proprio relogio.
    """
    r = await db.execute(text("""
        SELECT s.sid, s.user_email, s.usuario_nome, s.inicio, s.tela_atual,
               s.seg_ativos, u.role, s.ultimo_sinal, s.fim,
               EXTRACT(EPOCH FROM (NOW() - s.ultimo_sinal))::int AS ha_seg
        FROM uso_sessao s JOIN users u ON u.id = s.user_id
        WHERE COALESCE(u.role, '') <> 'viewer'
          -- QUEM SAIU DE VERDADE some rapido; quem sumiu em silencio demora.
          -- Sao coisas diferentes: o logout explicito e um FATO (a pessoa
          -- clicou em sair), e deixa-la 2,5 minutos no painel depois disso
          -- contradiz o que ela acabou de fazer. Ja a sessao que para de dar
          -- sinal pode ser rede ruim, tunel, notebook fechando a tampa — ali a
          -- espera maior evita fazer alguem sumir e voltar piscando.
          AND CASE WHEN s.fim IS NOT NULL
                   THEN s.fim > NOW() - make_interval(secs => :saiu)
                   ELSE s.ultimo_sinal > NOW() - make_interval(secs => :janela) END
        ORDER BY s.inicio
    """), {"janela": _JANELA_SAINDO_S, "saiu": _JANELA_DESPEDIDA_S})
    linhas = r.fetchall()
    return {
        "agora": datetime.now(timezone.utc).isoformat(),
        # O ESTADO vem do servidor, nao do relogio do navegador:
        #   presente  — deu sinal agora e esta ativo
        #   ocioso    — esta la, mas sem clique/tecla/rolagem
        #   saindo    — parou de dar sinal; some da lista em poucos segundos
        # A janela de "saindo" existe para o chip poder despedir-se em vermelho
        # antes de sumir, em vez de desaparecer sem explicacao.
        "online": [{
            "nome": x[2] or (x[1] or "").split("@")[0],
            "email": x[1],
            "desde": x[3].isoformat() if x[3] else None,
            "tela": x[4],
            "seg_ativos": x[5],
            "estado": ("saindo" if (x[8] is not None or (x[9] or 0) > _JANELA_ONLINE_S)
                       else "presente"),
            "ha_seg": x[9],
            # A COR VEM DO SERVIDOR, derivada do id da sessao. Assim ela e
            # ESTAVEL enquanto a pessoa estiver logada — nao muda a cada
            # atualizacao da tela de quem esta olhando — e NOVA quando ela sai e
            # entra de novo. Nao e por usuario: cor amarrada a pessoa viraria
            # codigo que a equipe decora.
            "cor": int(x[0][:8], 16) % 6,
            "sou_eu": x[1] == current.email,
        } for x in linhas],
    }


@router.get("/sessoes", dependencies=[exige("uso.ver")])
async def listar_sessoes(
    dias: int = 7,
    limite: int = 100,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """As sessoes de trabalho, com o que cada uma fez.

    ⚠️ SITUACAO DERIVADA NA LEITURA, sem varredor e sem UPDATE de fechamento.
    Sessao que morre sem aviso — aba fechada, notebook sem bateria, rede caindo
    — fica com `fim` nulo para sempre; comparar `ultimo_sinal` com agora resolve
    isso retroativamente e nao depende de agendador, que esta infra nao tem
    dentro do processo. `fim` so e escrito por evento REAL (logout, despedida da
    aba), e a despedida e otimizacao de precisao, jamais fonte de verdade.
    """
    r = await db.execute(text("""
        SELECT s.sid, s.user_email, s.usuario_nome, s.inicio,
               s.ultimo_sinal, s.fim, s.motivo_fim,
               s.seg_ativos, s.seg_ociosos, s.eventos, s.descartados,
               s.tela_atual, s.ip, s.user_agent,
               EXTRACT(EPOCH FROM (COALESCE(s.fim, s.ultimo_sinal) - s.inicio))::int AS seg_total,
               CASE WHEN s.fim IS NOT NULL THEN COALESCE(s.motivo_fim, 'encerrada')
                    WHEN s.ultimo_sinal > NOW() - INTERVAL '90 seconds' THEN 'ativa'
                    ELSE 'expirou' END AS situacao
        FROM uso_sessao s
        WHERE s.inicio > NOW() - make_interval(days => :dias)
        ORDER BY s.inicio DESC
        LIMIT :lim
    """), {"dias": max(1, min(dias, 90)), "lim": max(1, min(limite, 500))})
    return {"sessoes": [dict(x._mapping) for x in r.fetchall()]}


@router.get("/eventos", dependencies=[exige("uso.ver")])
async def listar_eventos(
    sid: Optional[str] = None,
    dias: int = 7,
    limite: int = 300,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Os atos, em ordem de acontecimento. Com `sid`, so os daquela sessao."""
    cond = "e.ocorrido_em > NOW() - make_interval(days => :dias)"
    par: dict[str, Any] = {"dias": max(1, min(dias, 90)),
                           "lim": max(1, min(limite, 1000))}
    if sid:
        cond += " AND e.sid = :sid"
        par["sid"] = sid[:32]
    r = await db.execute(text(f"""
        SELECT e.ocorrido_em, e.tela, e.rota, e.acao, e.alvo, e.ms,
               e.municipio_id, m.nome AS municipio, e.detalhe,
               s.user_email, s.usuario_nome, e.sid
        FROM uso_evento e
        LEFT JOIN uso_sessao s ON s.sid = e.sid
        LEFT JOIN municipios m ON m.id = e.municipio_id
        WHERE {cond}
        -- `id DESC` desempata: varios atos do MESMO lote chegam com carimbos
        -- a milissegundos de distancia, e sem o desempate a lista embaralhava
        -- dentro do minuto — parecia desordenada porque estava.
        ORDER BY e.ocorrido_em DESC, e.id DESC
        LIMIT :lim
    """), par)
    return {"eventos": [dict(x._mapping) for x in r.fetchall()]}
