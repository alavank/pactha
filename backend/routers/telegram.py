"""Router Telegram — webhook + comandos + vinculação de usuários.

Endpoints:
  POST  /api/telegram/webhook          (publico, validado por secret token)
  GET   /api/telegram/status           (logado)  status do bot/webhook
  POST  /api/telegram/setup-webhook    (admin)   configura webhook automatico
  POST  /api/telegram/link-code        (logado)  gera codigo de vinculacao 6 chars
  GET   /api/telegram/my-link          (logado)  ve vinculacao atual
  DELETE /api/telegram/my-link         (logado)  desvincula

Fluxo de vinculacao:
  1. User PACTA loga, vai em /dashboard/telegram, clica "Gerar codigo"
  2. Backend gera codigo aleatorio (10 min validade), retorna
  3. User abre o bot no Telegram, manda /start CODIGO
  4. Bot valida codigo -> grava telegram_users (chat_id <-> user_id)
  5. A partir dali, qualquer mensagem do user no bot vai pra IA PACTA
"""
from __future__ import annotations
import os
import secrets
import string
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from database import get_db
from services.auth import get_current_user
from services import telegram as tg
from models import User

log = logging.getLogger("telegram-router")

router = APIRouter(prefix="/api/telegram", tags=["telegram"])

# Secret token enviado no header X-Telegram-Bot-Api-Secret-Token (Telegram envia
# de volta o que configuramos em setWebhook). Validacao previne webhook spoofing.
_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _gen_code() -> str:
    """Gera codigo aleatorio 8 chars uppercase, sem ambiguos (0/O/1/I)."""
    alpha = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # 31 chars sem ambiguidades
    return "".join(secrets.choice(alpha) for _ in range(8))


async def _ensure_history(db: AsyncSession, chat_id: int, role: str, content: str, max_msgs: int = 8):
    """Acrescenta mensagem ao historico do user (anel, mantem ultimas N)."""
    msg = {"role": role, "content": content[:2000]}
    # Append + slice via SQL (mais robusto que ler/editar/escrever)
    await db.execute(text("""
        UPDATE telegram_users
        SET historico = (
            COALESCE(historico, '[]'::jsonb) || CAST(:msg AS JSONB)
        ),
        last_used_at = NOW()
        WHERE chat_id = :cid
    """), {"msg": json.dumps(msg), "cid": chat_id})
    # Trunca pra ultimas max_msgs
    await db.execute(text(f"""
        UPDATE telegram_users
        SET historico = (
            SELECT COALESCE(jsonb_agg(value), '[]'::jsonb)
            FROM (
                SELECT value, row_number() OVER () AS rn,
                       count(*) OVER () AS total
                FROM jsonb_array_elements(historico) WITH ORDINALITY t(value, rn)
            ) s
            WHERE rn > GREATEST(0, total - {max_msgs})
        )
        WHERE chat_id = :cid
    """), {"cid": chat_id})
    await db.commit()


# ----------------------------------------------------------------------------
# Comandos do bot
# ----------------------------------------------------------------------------

async def _cmd_start(db: AsyncSession, chat_id: int, args: str, telegram_user: str):
    """Comando /start [CODIGO_DE_VINCULACAO]."""
    args = args.strip()
    if not args:
        # Sem codigo - verifica se ja esta vinculado
        r = await db.execute(text("""
            SELECT u.name, u.email, m.nome AS mun_nome
            FROM telegram_users tu
            JOIN users u ON u.id = tu.user_id
            LEFT JOIN municipios m ON m.id = tu.municipio_id
            WHERE tu.chat_id = :cid
        """), {"cid": chat_id})
        row = r.first()
        if row:
            await tg.send_message(
                chat_id,
                f"👋 Olá *{row[0]}*!\n\n"
                f"Você já está vinculado à conta `{row[1]}`"
                + (f" — município *{row[2]}*" if row[2] else "") + ".\n\n"
                "Envie qualquer pergunta sobre seus convênios, propostas ou parlamentares "
                "e eu consulto o banco PACTA pra você.\n\n"
                "Comandos:\n"
                "/help — ajuda\n"
                "/municipio — trocar município padrão\n"
                "/desvincular — desconectar esta conta"
            )
        else:
            await tg.send_message(
                chat_id,
                "👋 *Bem-vindo ao bot PACTA!*\n\n"
                "Para usar este bot, você precisa vincular sua conta PACTA:\n\n"
                "1. Acesse a plataforma PACTA → menu *Telegram*\n"
                "2. Clique em *Gerar código de vinculação*\n"
                "3. Envie aqui:\n"
                "`/start SEU_CODIGO`\n\n"
                "Exemplo: `/start ABC23456`"
            )
        return

    # Tenta vincular pelo codigo
    code = args.upper().strip()
    r = await db.execute(text("""
        SELECT user_id, expires_at, used_at FROM telegram_link_codes WHERE codigo = :c
    """), {"c": code})
    row = r.first()
    now = datetime.now(timezone.utc)
    if not row:
        await tg.send_message(chat_id, "❌ Código inválido. Verifique e tente novamente.")
        return
    if row[2]:
        await tg.send_message(chat_id, "❌ Código já foi usado. Gere um novo na plataforma PACTA.")
        return
    if row[1] < now:
        await tg.send_message(chat_id, "❌ Código expirado. Gere um novo (validade 10 min).")
        return
    user_id = row[0]

    # Vincula (UPSERT)
    await db.execute(text("""
        INSERT INTO telegram_users (chat_id, user_id, telegram_user)
        VALUES (:cid, :uid, :tu)
        ON CONFLICT (chat_id) DO UPDATE SET
            user_id = EXCLUDED.user_id,
            telegram_user = EXCLUDED.telegram_user,
            last_used_at = NOW()
    """), {"cid": chat_id, "uid": user_id, "tu": telegram_user})
    await db.execute(text("UPDATE telegram_link_codes SET used_at = NOW() WHERE codigo = :c"),
                     {"c": code})
    await db.commit()

    # Resposta
    r = await db.execute(text("SELECT name, email FROM users WHERE id = :u"), {"u": user_id})
    user_row = r.first()
    nome = user_row[0] if user_row else "?"
    email = user_row[1] if user_row else "?"
    await tg.send_message(
        chat_id,
        f"✅ *Vinculado com sucesso!*\n\n"
        f"Conta: *{nome}* (`{email}`)\n\n"
        "Agora você pode mandar perguntas em português sobre os convênios, propostas e "
        "parlamentares. Exemplos:\n\n"
        "• _Quais convênios vencem nos próximos 60 dias?_\n"
        "• _Liste tudo do deputado Eduardo Azevedo_\n"
        "• _Resumo do município hoje_\n\n"
        "Use /municipio para definir um município padrão."
    )


async def _cmd_help(chat_id: int):
    await tg.send_message(
        chat_id,
        "🤖 *Bot PACTA — Ajuda*\n\n"
        "Mande qualquer pergunta em português sobre convênios, propostas, parlamentares ou "
        "liberações dos 6 municípios atendidos.\n\n"
        "*Comandos:*\n"
        "/start — vincular conta\n"
        "/municipio — escolher município padrão\n"
        "/limpar — apagar histórico de contexto\n"
        "/desvincular — desconectar conta\n"
        "/help — esta mensagem\n\n"
        "*Exemplos de perguntas:*\n"
        "• Convênios vencendo em 60 dias\n"
        "• Liste tudo do deputado Eduardo Azevedo\n"
        "• Quanto recebi em PNATE em 2026?\n"
        "• Resumo de Piracema hoje\n"
    )


async def _cmd_municipio(db: AsyncSession, chat_id: int, args: str):
    """Define ou lista municipio padrao."""
    args = args.strip()
    if not args:
        mr = await db.execute(text("""
            SELECT m.id, m.nome, m.uf FROM municipios m WHERE m.active = true ORDER BY m.nome
        """))
        muns = mr.fetchall()
        cur = await db.execute(text("""
            SELECT (SELECT nome FROM municipios WHERE id = tu.municipio_id)
            FROM telegram_users tu WHERE tu.chat_id = :cid
        """), {"cid": chat_id})
        cur_row = cur.first()
        atual = cur_row[0] if cur_row else None
        lista = "\n".join(f"• `/municipio {m[1]}` — {m[1]}/{m[2]}" for m in muns)
        await tg.send_message(
            chat_id,
            f"📍 *Município padrão*\n\n"
            f"Atual: *{atual or 'nenhum'}*\n\n"
            f"Para mudar, envie:\n{lista}"
        )
        return
    # Define
    r = await db.execute(text("""
        SELECT id, nome FROM municipios WHERE LOWER(nome) = LOWER(:n) AND active = true
    """), {"n": args})
    row = r.first()
    if not row:
        await tg.send_message(chat_id, f"❌ Município não encontrado: *{args}*. Use /municipio sem argumento para ver a lista.")
        return
    await db.execute(text("UPDATE telegram_users SET municipio_id = :m WHERE chat_id = :cid"),
                     {"m": row[0], "cid": chat_id})
    await db.commit()
    await tg.send_message(chat_id, f"✅ Município padrão definido: *{row[1]}*")


async def _cmd_limpar(db: AsyncSession, chat_id: int):
    await db.execute(text("UPDATE telegram_users SET historico = '[]'::jsonb WHERE chat_id = :cid"),
                     {"cid": chat_id})
    await db.commit()
    await tg.send_message(chat_id, "🧹 Histórico limpo. Próxima pergunta começa do zero.")


async def _cmd_desvincular(db: AsyncSession, chat_id: int):
    await db.execute(text("DELETE FROM telegram_users WHERE chat_id = :cid"), {"cid": chat_id})
    await db.commit()
    await tg.send_message(chat_id, "✅ Conta desvinculada. Use /start CODIGO pra vincular novamente.")


# ----------------------------------------------------------------------------
# Handler central de mensagem
# ----------------------------------------------------------------------------

async def _handle_message(db: AsyncSession, message: dict):
    """Processa mensagem recebida do Telegram."""
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    if not chat_id:
        return
    from_user = message.get("from", {})
    tg_user = (
        from_user.get("username") and f"@{from_user['username']}"
        or " ".join(filter(None, [from_user.get("first_name"), from_user.get("last_name")]))
        or "?"
    )
    text_msg = (message.get("text") or "").strip()
    if not text_msg:
        return

    # Comandos /xxx args
    if text_msg.startswith("/"):
        cmd_full = text_msg.split(maxsplit=1)
        cmd = cmd_full[0].lower().split("@")[0]  # remove @botname se houver
        args = cmd_full[1] if len(cmd_full) > 1 else ""
        if cmd == "/start":
            await _cmd_start(db, chat_id, args, tg_user)
            return
        if cmd == "/help":
            await _cmd_help(chat_id)
            return

        # Comandos que exigem vinculacao
        r = await db.execute(text("SELECT user_id FROM telegram_users WHERE chat_id = :c"), {"c": chat_id})
        if not r.first():
            await tg.send_message(chat_id, "⚠️ Você não está vinculado. Use /start CODIGO.")
            return

        if cmd == "/municipio":
            await _cmd_municipio(db, chat_id, args); return
        if cmd == "/limpar":
            await _cmd_limpar(db, chat_id); return
        if cmd == "/desvincular":
            await _cmd_desvincular(db, chat_id); return
        await tg.send_message(chat_id, f"❌ Comando desconhecido: {cmd}. Use /help.")
        return

    # Mensagem livre = pergunta pra IA
    r = await db.execute(text("""
        SELECT tu.user_id, tu.municipio_id, tu.historico, u.name
        FROM telegram_users tu JOIN users u ON u.id = tu.user_id
        WHERE tu.chat_id = :cid
    """), {"cid": chat_id})
    row = r.first()
    if not row:
        await tg.send_message(
            chat_id,
            "⚠️ Você precisa vincular sua conta primeiro.\n\n"
            "Acesse o PACTA → menu *Telegram* → *Gerar código*\n"
            "Depois envie aqui: `/start SEU_CODIGO`"
        )
        return
    user_id, mun_id, historico, user_name = row
    historico = historico if isinstance(historico, list) else []

    await tg.send_typing(chat_id)
    try:
        from routers.ai import _run_ai_chat
        result = await _run_ai_chat(db, text_msg, historico, mun_id, user_name)
        reply = result["reply"]
        # Salva no historico (user + assistant)
        await _ensure_history(db, chat_id, "user", text_msg)
        await _ensure_history(db, chat_id, "assistant", reply)
        await tg.send_message(chat_id, reply, parse_mode="Markdown")
    except Exception as e:
        log.exception("erro IA chat telegram")
        await tg.send_message(chat_id, f"⚠️ Erro ao consultar a IA: `{str(e)[:200]}`")


# ----------------------------------------------------------------------------
# WEBHOOK (publico — Telegram chama)
# ----------------------------------------------------------------------------

@router.post("/webhook")
async def webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    """Endpoint chamado pelo Telegram quando o bot recebe mensagem."""
    if _WEBHOOK_SECRET and x_telegram_bot_api_secret_token != _WEBHOOK_SECRET:
        log.warning("webhook com secret invalido")
        raise HTTPException(403, "Secret invalido")
    payload = await request.json()
    log.info(f"telegram update: {json.dumps(payload, ensure_ascii=False)[:300]}")
    try:
        if "message" in payload:
            await _handle_message(db, payload["message"])
        elif "edited_message" in payload:
            await _handle_message(db, payload["edited_message"])
    except Exception as e:
        log.exception(f"erro processando update: {e}")
    return {"ok": True}


# ----------------------------------------------------------------------------
# ADMIN / USUARIO
# ----------------------------------------------------------------------------

@router.get("/status")
async def status(_=Depends(get_current_user)):
    """Status do bot + webhook config."""
    if not tg.telegram_configured():
        return {"configured": False, "message": "TELEGRAM_BOT_TOKEN não configurado no Railway."}
    try:
        me = await tg.get_me()
        wh = await tg.get_webhook_info()
        return {
            "configured": True,
            "bot": me.get("result", {}),
            "webhook": wh.get("result", {}),
        }
    except Exception as e:
        return {"configured": True, "error": str(e)[:200]}


class WebhookSetup(BaseModel):
    base_url: str  # ex: https://pacta-api.up.railway.app


@router.post("/setup-webhook")
async def setup_webhook(body: WebhookSetup, user: User = Depends(get_current_user)):
    """Configura o webhook do bot pra apontar pra este backend.
    Apenas admins. Tambem grava um secret aleatorio se nao existir."""
    if user.role != "admin":
        raise HTTPException(403, "Apenas admins")
    if not tg.telegram_configured():
        raise HTTPException(400, "TELEGRAM_BOT_TOKEN nao configurado")
    base = body.base_url.rstrip("/")
    url = f"{base}/api/telegram/webhook"
    secret = _WEBHOOK_SECRET or secrets.token_urlsafe(16)
    try:
        result = await tg.set_webhook(url, secret_token=secret)
        return {
            "ok": True,
            "webhook_url": url,
            "telegram_response": result,
            "note": "Se TELEGRAM_WEBHOOK_SECRET nao estiver setado no env, configure agora "
                    f"com este valor: {secret}",
        }
    except Exception as e:
        raise HTTPException(500, f"Falha ao configurar webhook: {e}")


@router.post("/link-code")
async def gerar_link_code(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Gera codigo de vinculacao 8 chars (validade 10 min) p/ user atual."""
    code = _gen_code()
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    await db.execute(text("""
        INSERT INTO telegram_link_codes (codigo, user_id, expires_at)
        VALUES (:c, :u, :e)
    """), {"c": code, "u": user.id, "e": expires})
    # Limpa codigos antigos do user (mantem so este)
    await db.execute(text("""
        DELETE FROM telegram_link_codes
        WHERE user_id = :u AND codigo != :c
    """), {"u": user.id, "c": code})
    await db.commit()
    bot_username = None
    if tg.telegram_configured():
        try:
            me = await tg.get_me()
            bot_username = me.get("result", {}).get("username")
        except Exception:
            pass
    return {
        "codigo": code,
        "expira_em": expires.isoformat(),
        "instrucoes": (
            f"1. Abra @{bot_username} no Telegram\n"
            "2. Envie: /start " + code if bot_username
            else "Abra o bot PACTA no Telegram e envie: /start " + code
        ),
        "bot_username": bot_username,
        "bot_link": f"https://t.me/{bot_username}?start={code}" if bot_username else None,
    }


@router.get("/my-link")
async def my_link(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mostra vinculacao Telegram atual do user."""
    r = await db.execute(text("""
        SELECT chat_id, telegram_user, municipio_id,
               (SELECT nome FROM municipios WHERE id = tu.municipio_id) AS mun_nome,
               created_at, last_used_at
        FROM telegram_users tu
        WHERE tu.user_id = :u
        ORDER BY last_used_at DESC
    """), {"u": user.id})
    items = [{
        "chat_id": str(row[0]),
        "telegram_user": row[1],
        "municipio_id": row[2],
        "municipio_nome": row[3],
        "vinculado_em": row[4].isoformat() if row[4] else None,
        "ultima_atividade": row[5].isoformat() if row[5] else None,
    } for row in r.fetchall()]
    return {"items": items, "total": len(items)}


@router.delete("/my-link/{chat_id}")
async def desvincular_chat(
    chat_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(text("DELETE FROM telegram_users WHERE chat_id = :c AND user_id = :u"),
                     {"c": int(chat_id), "u": user.id})
    await db.commit()
    return {"ok": True}
