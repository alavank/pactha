"""Helpers de resiliencia compartilhados pelos scrapers PACTHA.

Centraliza:
  - get_sync_db_url(): DATABASE_URL_SYNC limpo de channel_binding
  - neon_connect(): context manager psycopg2 com retry/backoff p/ Neon
  - decode_jwt_payload() / jwt_minutes_remaining(): inspecao de JWT
  - normalize_cookies_for_playwright() / _for_httpx(): Cofre -> cliente
"""
from __future__ import annotations

import os
import ssl
import time
import json
import base64
import socket
import logging
from contextlib import contextmanager

import psycopg2

logger = logging.getLogger("resilience")

# erros transitorios que justificam reconexao ao Neon
_TRANSIENT = (
    psycopg2.OperationalError,
    psycopg2.InterfaceError,
    ssl.SSLError,
    socket.error,
    socket.timeout,
    ConnectionError,
)


def get_sync_db_url() -> str:
    """DATABASE_URL_SYNC sem channel_binding (psycopg2 nao suporta)."""
    return (
        os.getenv("DATABASE_URL_SYNC", "")
        .replace("&channel_binding=require", "")
        .replace("?channel_binding=require", "")
    )


@contextmanager
def neon_connect(url: str | None = None, max_retries: int = 3, base_wait: float = 2.0,
                 connect_timeout: int = 10, statement_timeout_ms: int = 60000):
    """Context manager psycopg2 com retry exponencial.

    Uso:
        with neon_connect() as conn:
            cur = conn.cursor(); cur.execute(...); conn.commit()
    A conexao e fechada automaticamente na saida.
    """
    url = url or get_sync_db_url()
    conn = None
    last_err = None
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(
                url,
                connect_timeout=connect_timeout,
                options=f"-c statement_timeout={statement_timeout_ms}",
            )
            break
        except _TRANSIENT as e:
            last_err = e
            if attempt < max_retries - 1:
                wait = base_wait ** attempt  # 1, 2, 4...
                logger.warning(
                    f"Conexao Neon falhou ({attempt+1}/{max_retries}), retry {wait:.0f}s: "
                    f"{type(e).__name__}: {str(e)[:120]}"
                )
                time.sleep(wait)
            else:
                logger.error(
                    f"Neon nao respondeu apos {max_retries} tentativas: "
                    f"{type(e).__name__}: {str(e)[:200]}"
                )
                raise
    if conn is None:
        raise last_err or RuntimeError("neon_connect: falha desconhecida")
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception as e:
            logger.warning(f"Erro ao fechar conexao Neon: {e}")


def decode_jwt_payload(token: str) -> dict | None:
    """Decodifica o payload (claims) de um JWT sem verificar assinatura."""
    if not token or "." not in token:
        return None
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        pb = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(pb))
    except Exception:
        return None


def jwt_minutes_remaining(token: str) -> float:
    """Minutos ate o 'exp' do JWT. -inf se invalido/sem exp."""
    payload = decode_jwt_payload(token)
    if not payload or "exp" not in payload:
        return float("-inf")
    return (payload["exp"] - time.time()) / 60


_SAMESITE_MAP = {
    "no_restriction": "None", "none": "None",
    "lax": "Lax", "strict": "Strict",
}


def normalize_cookies_for_playwright(cofre_data: dict | None) -> list[dict] | None:
    """Cofre JSON ({'cookies': [...]}) -> formato add_cookies do Playwright."""
    if not cofre_data or not isinstance(cofre_data.get("cookies"), list):
        return None
    out = []
    for c in cofre_data["cookies"]:
        if not c.get("name") or c.get("value") is None:
            continue
        ck = {
            "name": c["name"], "value": c["value"],
            "path": c.get("path") or "/",
            "secure": bool(c.get("secure")),
            "httpOnly": bool(c.get("httpOnly")),
        }
        if c.get("domain"):
            ck["domain"] = c["domain"]
        ss = c.get("sameSite")
        if ss:
            ck["sameSite"] = _SAMESITE_MAP.get(str(ss).lower(), "Lax")
        exp = c.get("expirationDate")
        if exp:
            try:
                ck["expires"] = float(exp)
            except (TypeError, ValueError):
                pass
        out.append(ck)
    return out or None


def normalize_cookies_for_httpx(cofre_data: dict | None) -> dict | None:
    """Cofre JSON -> dict {name: value} para httpx.Client(cookies=...)."""
    if not cofre_data or not isinstance(cofre_data.get("cookies"), list):
        return None
    return {
        c["name"]: c["value"]
        for c in cofre_data["cookies"]
        if c.get("name") and c.get("value") is not None
    } or None
