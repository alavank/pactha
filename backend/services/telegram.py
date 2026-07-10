"""Cliente Telegram Bot API (HTTPs simples, sem SDK pesado).
Envia mensagens, edita, mostra typing... etc.

Token: env var TELEGRAM_BOT_TOKEN (criar bot em @BotFather no Telegram).
"""
from __future__ import annotations
import os
import logging
from typing import Any
import httpx

log = logging.getLogger("telegram")


def _token() -> str:
    tok = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not tok:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN nao configurado. Crie um bot em @BotFather "
            "e configure a env var no servidor (Coolify)."
        )
    return tok


def _base_url() -> str:
    return f"https://api.telegram.org/bot{_token()}"


async def send_message(
    chat_id: int | str,
    text: str,
    parse_mode: str = "Markdown",
    reply_to: int | None = None,
) -> dict[str, Any]:
    """Envia mensagem. Markdown e default — limita 4096 chars; quebra automaticamente."""
    if len(text) > 4000:
        # Telegram limita 4096 — quebra em lotes preservando linhas
        parts = []
        cur = ""
        for line in text.split("\n"):
            if len(cur) + len(line) + 1 > 3800:
                parts.append(cur)
                cur = line
            else:
                cur = (cur + "\n" + line) if cur else line
        if cur:
            parts.append(cur)
        last_result = {}
        for p in parts:
            last_result = await _send_one(chat_id, p, parse_mode, reply_to if not last_result else None)
        return last_result
    return await _send_one(chat_id, text, parse_mode, reply_to)


async def _send_one(chat_id, text, parse_mode, reply_to) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    async with httpx.AsyncClient(timeout=30) as cli:
        r = await cli.post(f"{_base_url()}/sendMessage", json=payload)
        if r.status_code != 200:
            # Telegram falha de markdown — refaz como plain
            if parse_mode and "can't parse entities" in r.text.lower():
                payload.pop("parse_mode", None)
                r = await cli.post(f"{_base_url()}/sendMessage", json=payload)
        r.raise_for_status()
        return r.json()


async def send_typing(chat_id: int | str) -> None:
    """Mostra '... esta digitando' por 5 segundos (Telegram limita)."""
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            await cli.post(f"{_base_url()}/sendChatAction",
                           json={"chat_id": chat_id, "action": "typing"})
    except Exception:
        pass  # nao critico


async def set_webhook(url: str, secret_token: str | None = None) -> dict[str, Any]:
    """Configura webhook do bot."""
    payload: dict[str, Any] = {"url": url, "drop_pending_updates": True,
                                "allowed_updates": ["message", "callback_query"]}
    if secret_token:
        payload["secret_token"] = secret_token
    async with httpx.AsyncClient(timeout=15) as cli:
        r = await cli.post(f"{_base_url()}/setWebhook", json=payload)
        r.raise_for_status()
        return r.json()


async def delete_webhook() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as cli:
        r = await cli.post(f"{_base_url()}/deleteWebhook")
        r.raise_for_status()
        return r.json()


async def get_webhook_info() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as cli:
        r = await cli.get(f"{_base_url()}/getWebhookInfo")
        r.raise_for_status()
        return r.json()


async def get_me() -> dict[str, Any]:
    """Retorna info do bot (username etc)."""
    async with httpx.AsyncClient(timeout=15) as cli:
        r = await cli.get(f"{_base_url()}/getMe")
        r.raise_for_status()
        return r.json()


def telegram_configured() -> bool:
    """Returns True se TELEGRAM_BOT_TOKEN esta setado (sem raise)."""
    return bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip())
