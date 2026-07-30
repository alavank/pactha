"""Configuracao comum dos geradores de TEXTO CURTO da IA (faixa de narrativa do
BI, ticker de insights e painel).

Existe por causa de uma armadilha concreta: o modelo e trocavel por env
(`PACTHA_AI_MODEL_TEXTO`), mas nem todo modelo aceita os mesmos parametros.
`claude-haiku-4-5` responde 400 "This model does not support the effort
parameter" — entao trocar para Haiku (que custa 1/3 do Sonnet 5) para economizar
derrubaria a faixa do dashboard inteira.

Aqui os parametros de raciocinio so sao enviados quando o modelo os suporta.
"""
from __future__ import annotations
import os

# Modelos que aceitam `output_config.effort` e `thinking`. Nos textos curtos
# desligamos o raciocinio de proposito: o modelo apenas REDIGE uma frase — os
# numeros ja chegam calculados do backend — e no Sonnet 5 omitir `thinking`
# ligaria o modo adaptativo por padrao, gastando token a toa.
_SUPORTAM_RACIOCINIO = ("claude-sonnet-5", "claude-opus-5", "claude-opus-4-8",
                        "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6",
                        "claude-fable-5")


def modelo_texto() -> str:
    return os.getenv("PACTHA_AI_MODEL_TEXTO", "claude-sonnet-5")


def params_raciocinio(modelo: str | None = None) -> dict:
    """kwargs extras de `messages.create` para o modelo em uso ({} se ele nao
    suportar). Use com `**params_raciocinio()`."""
    m = modelo or modelo_texto()
    if any(m.startswith(x) for x in _SUPORTAM_RACIOCINIO):
        return {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}}
    return {}
