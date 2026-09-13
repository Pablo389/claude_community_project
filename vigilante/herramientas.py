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
from .config import normalizar

LIMITE_TEXTO = 40_000  # caracteres; las notas largas se truncan para no reventar contexto

NOMBRE_SERVIDOR = "dof"
TOOL_TEXTO_NOTA = f"mcp__{NOMBRE_SERVIDOR}__texto_nota"
TOOL_TITULOS_DEL_DIA = f"mcp__{NOMBRE_SERVIDOR}__titulos_del_dia"

NOMBRE_SERVIDOR_HISTORICO = "dof_historico"
TOOL_BUSCAR = f"mcp__{NOMBRE_SERVIDOR_HISTORICO}__buscar_historico"
TOOL_LEER_CANDIDATA = f"mcp__{NOMBRE_SERVIDOR_HISTORICO}__leer_candidata"

MIN_PALABRAS_FRASE = 2
# Generoso a propósito: el nombre legal completo de un ordenamiento son 9 o 10
# palabras y es la mejor frase posible. Lo que hace daño es lo corto y genérico,
# no lo largo: el match es de substring, así que alargar solo puede discriminar más.
MAX_PALABRAS_FRASE = 14


def _texto(payload: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": payload}]}


def _error(mensaje: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": f"ERROR: {mensaje}"}], "is_error": True}


def _mensaje_sin_texto(cod_nota: int, resultado: dof_api.TextoNota) -> str:
    """Mensaje para `disponible=False` (EP-01).

    Nunca promete un PDF o una imagen que los flags no confirman: el caso real
    `codNota 4432291` tiene `existe_doc`, `existe_imagen` y `existe_pdf` los
    tres en falso, así que el mensaje tiene que poder decir "no hay nada" tan
    fácil como "existe como PDF".
    """
    url = dof_api.URL_PUBLICA.format(cod_nota=cod_nota)
    if resultado.existe_pdf or resultado.existe_imagen:
        formato = "PDF" if resultado.existe_pdf else "imagen"
        return (
            f"codNota {cod_nota} no tiene texto extraíble por esta vía, pero existe "
            f"como {formato}. Documento oficial: {url}"
        )
    return (
        f"codNota {cod_nota} no tiene ninguna versión digital disponible en el DOF "
        f"(ni HTML, ni imagen, ni PDF), solo el título indexado. Referencia: {url}"
    )


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


class Registro:
    """La evidencia de la etapa `antecedentes`: qué se buscó y qué devolvió el DOF.

    Existe porque R16 no se le pide al modelo, se le impone: una frase que no
    aparezca literal en el expediente nunca llega al endpoint, y un `cod_nota`
    que la búsqueda no haya devuelto nunca puede citarse después. El agente no
    puede fabricar ninguna de las dos cosas, y las dos quedan escritas en el
    dossier para que alguien las repita.
    """

    def __init__(self, textos_fuente: dict[int, str]) -> None:
        self._fuente = normalizar(" ".join(textos_fuente.values()))
        self.consultas: list[dict[str, Any]] = []
        self.rechazadas: list[dict[str, str]] = []
        # Pre-registrados: los eventos propios del expediente ya son evidencia.
        self.vistos: dict[int, dict[str, Any]] = {}

    def es_literal(self, frase: str) -> bool:
        return normalizar(frase) in self._fuente

    def registrar(self, coincidencias) -> None:
        for c in coincidencias:
            self.vistos.setdefault(c.cod_nota, {"fecha": c.fecha, "titulo": c.titulo,
                                                "dependencia": c.dependencia})

    def conocido(self, cod_nota: int) -> bool:
        return int(cod_nota) in self.vistos


def servidor_historico(registro: Registro):
    """Servidor MCP para `antecedentes`, atado a UN expediente.

    Las herramientas se construyen aquí dentro porque cierran sobre el registro:
    cada expediente investiga con su propia superficie y su propia evidencia.
    """

    @tool(
        "buscar_historico",
        "Busca en TODO el histórico del DOF las publicaciones cuyo título contenga una frase. "
        "La frase DEBE aparecer literal en el expediente que estás investigando: si la "
        "parafraseas, la herramienta la rechaza. Usa el nombre del ordenamiento o de la "
        "materia tal como está escrito en el documento (2 a 6 palabras, sin números de NOM).",
        {"frase": str, "limite": int},
    )
    async def buscar_historico(args: dict[str, Any]) -> dict[str, Any]:
        frase = (args.get("frase") or "").strip()
        limite = max(1, min(int(args.get("limite") or 20), 40))

        palabras = frase.split()
        if not (MIN_PALABRAS_FRASE <= len(palabras) <= MAX_PALABRAS_FRASE):
            # También se registra: un rechazo que no queda escrito es evidencia perdida.
            registro.rechazadas.append(
                {"frase": frase, "motivo": f"{len(palabras)} palabras, fuera del rango permitido"}
            )
            return _error(
                f"'{frase}' tiene {len(palabras)} palabras. Usa entre {MIN_PALABRAS_FRASE} y "
                f"{MAX_PALABRAS_FRASE}: menos devuelve decenas de miles de filas irrelevantes, "
                "más no encuentra nada porque el match es de substring exacto."
            )
        if not registro.es_literal(frase):
            registro.rechazadas.append({"frase": frase, "motivo": "no aparece literal en el expediente"})
            return _error(
                f"'{frase}' no aparece textualmente en el expediente. Copia la frase tal cual "
                "del título o del cuerpo de alguna de sus publicaciones; no la reformules."
            )

        try:
            resultado = dof_api.buscar_por_titulo(frase, limite=limite)
        except Exception as exc:
            return _error(f"El DOF falló al buscar '{frase}': {exc}")

        registro.registrar(resultado.coincidencias)
        registro.consultas.append(
            {"frase": frase, "total": resultado.total, "devueltas": len(resultado.coincidencias)}
        )
        if resultado.total > 500:
            aviso = (f"ADVERTENCIA: {resultado.total} resultados. La frase es demasiado genérica "
                     "y estas filas probablemente no son del mismo asunto. Busca algo más específico.")
        else:
            aviso = ""
        return _texto(json.dumps(
            {"frase": frase, "total_en_el_dof": resultado.total, "aviso": aviso,
             "resultados": [c.to_dict() for c in resultado.coincidencias]},
            ensure_ascii=False, indent=1))

    @tool(
        "leer_candidata",
        "Devuelve el texto oficial de una publicación que ya te haya devuelto `buscar_historico`. "
        "Úsala solo cuando el título no baste para decidir si pertenece al hilo.",
        {"cod_nota": int},
    )
    async def leer_candidata(args: dict[str, Any]) -> dict[str, Any]:
        cod_nota = int(args["cod_nota"])
        if not registro.conocido(cod_nota):
            return _error(
                f"La nota {cod_nota} no salió en ninguna de tus búsquedas. Solo puedes leer "
                "publicaciones que el DOF ya te devolvió: búscala primero."
            )
        try:
            resultado = dof_api.texto_nota(cod_nota)
        except Exception as exc:
            return _error(f"No pude leer la nota {cod_nota}: {exc}")

        if not resultado.disponible:
            return _texto(_mensaje_sin_texto(cod_nota, resultado))

        cuerpo = resultado.texto
        if len(cuerpo) > LIMITE_TEXTO:
            cuerpo = cuerpo[:LIMITE_TEXTO] + "\n\n[...texto truncado...]"
        return _texto(f"codNota {cod_nota} — {dof_api.URL_PUBLICA.format(cod_nota=cod_nota)}\n\n{cuerpo}")

    return create_sdk_mcp_server(
        name=NOMBRE_SERVIDOR_HISTORICO,
        version="0.1.0",
        tools=[buscar_historico, leer_candidata],
    )


def servidor_dof(sin_texto: set[int]):
    """Servidor MCP in-process con las herramientas del DOF (Etapa A).

    `sin_texto` es un contenedor mutable — mismo patrón que `Registro` en
    `servidor_historico`: el tool `texto_nota` agrega ahí los `cod_nota` que
    resultaron sin texto disponible, para que `agente_dia` los reporte en
    `_meta.fuente_incompleta` sin depender de que el modelo lo declare (EP-01).
    """

    @tool(
        "texto_nota",
        "Devuelve el texto oficial completo de una publicación del DOF a partir de su codNota. "
        "Úsala solo para las notas que de verdad parecen relevantes: el texto es largo.",
        {"cod_nota": int},
    )
    async def texto_nota(args: dict[str, Any]) -> dict[str, Any]:
        cod_nota = int(args["cod_nota"])
        try:
            resultado = dof_api.texto_nota(cod_nota)
        except LookupError as exc:
            return _error(str(exc))
        except Exception as exc:  # red caída, 500 del DOF, etc.
            return _error(f"No pude leer la nota {cod_nota}: {exc}")

        if not resultado.disponible:
            sin_texto.add(cod_nota)
            return _texto(_mensaje_sin_texto(cod_nota, resultado))

        cuerpo = resultado.texto
        if len(cuerpo) > LIMITE_TEXTO:
            cuerpo = cuerpo[:LIMITE_TEXTO] + "\n\n[...texto truncado...]"
        return _texto(f"codNota {cod_nota} — {dof_api.URL_PUBLICA.format(cod_nota=cod_nota)}\n\n{cuerpo}")

    return create_sdk_mcp_server(
        name=NOMBRE_SERVIDOR,
        version="0.1.0",
        tools=[texto_nota, titulos_del_dia],
    )
