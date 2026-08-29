"""Herramientas MCP in-process que el agente puede disparar.

El servidor MCP es pasivo: solo expone funciones con su esquema. El que decide
llamarlas es el agente. Son deliberadamente pocas y de solo lectura.

Nota de diseño: `titulos_del_dia` existe para que el agente pueda auditar lo que
el prefiltro determinista descartó. Sin ella, un error del prefiltro es
invisible y definitivo.
"""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from . import dof_api

LIMITE_TEXTO = 40_000  # caracteres; las notas largas se truncan para no reventar contexto

NOMBRE_SERVIDOR = "dof"
TOOL_TEXTO_NOTA = f"mcp__{NOMBRE_SERVIDOR}__texto_nota"
TOOL_TITULOS_DEL_DIA = f"mcp__{NOMBRE_SERVIDOR}__titulos_del_dia"


def _texto(payload: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": payload}]}


def _error(mensaje: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": f"ERROR: {mensaje}"}], "is_error": True}


@tool(
    "texto_nota",
    "Devuelve el texto oficial completo de una publicación del DOF a partir de su codNota. "
    "Úsala solo para las notas que de verdad parecen relevantes: el texto es largo.",
    {"cod_nota": int},
)
async def texto_nota(args: dict[str, Any]) -> dict[str, Any]:
    cod_nota = args["cod_nota"]
    try:
        cuerpo = dof_api.texto_nota(int(cod_nota))
    except LookupError as exc:
        return _error(str(exc))
    except Exception as exc:  # red caída, 500 del DOF, etc.
        return _error(f"No pude leer la nota {cod_nota}: {exc}")

    if len(cuerpo) > LIMITE_TEXTO:
        cuerpo = cuerpo[:LIMITE_TEXTO] + "\n\n[...texto truncado...]"
    return _texto(f"codNota {cod_nota} — {dof_api.URL_PUBLICA.format(cod_nota=cod_nota)}\n\n{cuerpo}")


@tool(
    "titulos_del_dia",
    "Lista TODOS los títulos publicados en el DOF en una fecha (formato DD-MM-YYYY), "
    "incluidos los que el prefiltro descartó. Úsala si sospechas que el prefiltro "
    "dejó fuera algo relevante para el giro.",
    {"fecha": str},
)
async def titulos_del_dia(args: dict[str, Any]) -> dict[str, Any]:
    fecha = args["fecha"]
    try:
        diario = dof_api.notas_del_dia(fecha)
    except Exception as exc:
        return _error(f"No pude leer el sumario del {fecha}: {exc}")

    filas = [
        {
            "cod_nota": n.cod_nota,
            "edicion": n.edicion,
            "dependencia": n.dependencia,
            "titulo": n.titulo,
        }
        for n in diario.notas
    ]
    return _texto(json.dumps({"fecha": fecha, "total": len(filas), "notas": filas}, ensure_ascii=False, indent=1))


def servidor_dof():
    """Servidor MCP in-process con las herramientas del DOF."""
    return create_sdk_mcp_server(
        name=NOMBRE_SERVIDOR,
        version="0.1.0",
        tools=[texto_nota, titulos_del_dia],
    )
