"""
PACTA IA - endpoint conversacional.

POST /api/ia/chat { messages: [...], municipio_id?: int }
  -> stream / json com resposta + traces de tools usadas.
"""
import os
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from database import get_db
from services.auth import get_current_user
from services.ai_agent import TOOLS, execute_tool, SYSTEM_PROMPT

logger = logging.getLogger("pacta-ia")

router = APIRouter(prefix="/api/ia", tags=["ia"])


class ChatMsg(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMsg]
    municipio_id: Optional[int] = Field(None, description="ID do municipio em foco")
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 2048


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Conversa com PACTA IA. Itera ate o modelo nao chamar mais tools."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY nao configurada")

    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        raise HTTPException(500, "anthropic SDK nao instalado")

    client = AsyncAnthropic(api_key=api_key)

    # Injetar contexto do municipio no system
    system = [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
    ]
    if payload.municipio_id:
        system.append({"type": "text",
                        "text": f"\nContexto: municipio_id atual = {payload.municipio_id}"})

    msgs = [{"role": m.role, "content": m.content} for m in payload.messages]
    traces = []

    # Loop de tool_use (max 10 iteracoes para evitar runaway)
    for hop in range(10):
        try:
            resp = await client.messages.create(
                model=payload.model,
                max_tokens=payload.max_tokens,
                system=system,
                tools=TOOLS,
                messages=msgs,
            )
        except Exception as e:
            raise HTTPException(502, f"Falha Claude API: {str(e)[:200]}")

        # Acumular content blocks
        text_blocks = [b.text for b in resp.content if hasattr(b, "text") and b.type == "text"]
        tool_uses = [b for b in resp.content if b.type == "tool_use"]

        if not tool_uses:
            # Resposta final
            return {
                "answer": "\n".join(text_blocks).strip(),
                "stop_reason": resp.stop_reason,
                "traces": traces,
                "usage": {
                    "input_tokens": resp.usage.input_tokens,
                    "output_tokens": resp.usage.output_tokens,
                    "cache_creation": getattr(resp.usage, "cache_creation_input_tokens", 0),
                    "cache_read": getattr(resp.usage, "cache_read_input_tokens", 0),
                },
            }

        # Executar tools
        msgs.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for tu in tool_uses:
            try:
                result = await execute_tool(tu.name, tu.input, db)
            except Exception as e:
                result = {"erro": str(e)[:200]}
            traces.append({"tool": tu.name, "input": tu.input, "result_keys": list(result.keys()) if isinstance(result, dict) else None})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, ensure_ascii=False, default=str)[:30000],
            })
        msgs.append({"role": "user", "content": tool_results})

    raise HTTPException(500, "PACTA IA excedeu 10 hops de tool_use")


@router.get("/tools")
async def list_tools(_=Depends(get_current_user)):
    """Lista os tools disponiveis para o modelo (debug/transparencia)."""
    return {"tools": [{"name": t["name"], "description": t["description"]} for t in TOOLS]}
