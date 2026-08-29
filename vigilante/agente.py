"""Lo común a las dos etapas que llaman al modelo.

El loop de mensajes del Agent SDK y la extracción del bloque ```json final son
idénticos en `agente_dia` y `agente_expedientes`: solo cambian el prompt y las
opciones. Vive aquí para que haya una sola copia.
"""

from __future__ import annotations

import json
import re
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)


def extraer_json(texto: str) -> dict[str, Any]:
    """Saca el último bloque ```json de la respuesta del agente."""
    bloques = re.findall(r"```json\s*(\{.*?\})\s*```", texto or "", re.DOTALL)
    if not bloques:
        raise ValueError("El agente no devolvió un bloque ```json al final de su respuesta")
    return json.loads(bloques[-1])


async def ejecutar_agente(
    prompt: str, opciones: ClaudeAgentOptions, verboso: bool = True
) -> tuple[str, ResultMessage]:
    """Corre una consulta y devuelve (texto final, resultado) o levanta si falló."""
    texto_final = ""
    resultado: ResultMessage | None = None

    async for mensaje in query(prompt=prompt, options=opciones):
        if isinstance(mensaje, AssistantMessage):
            for bloque in mensaje.content:
                if isinstance(bloque, ToolUseBlock) and verboso:
                    print(f"   · {bloque.name}({json.dumps(bloque.input, ensure_ascii=False)[:70]})")
                elif isinstance(bloque, TextBlock):
                    texto_final = bloque.text
        elif isinstance(mensaje, ResultMessage):
            resultado = mensaje
            if mensaje.subtype == "success" and mensaje.result:
                texto_final = mensaje.result

    if resultado is None:
        raise RuntimeError("El agente terminó sin devolver un resultado")
    if resultado.subtype != "success":
        raise RuntimeError(f"El agente falló: {resultado.subtype}")

    return texto_final, resultado
