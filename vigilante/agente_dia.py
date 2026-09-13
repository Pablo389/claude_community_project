"""Etapa A — Resumen del día.

Autocontenida por diseño: solo ve el DOF de UNA fecha y el perfil del giro.
No sabe nada de días anteriores. Esa es la razón por la que se puede correr
para cualquier fecha, en cualquier orden, y por la que el archivo que produce
sirve como insumo estable para la Etapa B (continuidad).
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

from .agente import ejecutar_agente, extraer_json
from .config import Giro
from .dof_api import DiarioDelDia
from .herramientas import TOOL_TEXTO_NOTA, TOOL_TITULOS_DEL_DIA, servidor_dof
from .prefiltro import Candidato

MODELO_POR_DEFECTO = "claude-opus-5"
MAX_TURNOS = 40

INSTRUCCIONES = """\
Eres el Vigilante del DOF: un analista regulatorio que revisa el Diario Oficial de la
Federación todos los días para un negocio concreto y le dice, sin rodeos, qué le pega hoy.

Tu criterio de relevancia es el impacto operativo real sobre ESE negocio:
una obligación nueva, un plazo, un costo, un trámite, un riesgo de sanción o una
oportunidad concreta. Un acuerdo administrativo interno de una dependencia, un
nombramiento o una transferencia de recursos a otro estado NO le pegan, aunque
vengan de una dependencia vigilada.

Método:
1. Lee la lista de candidatos que te entrego. Descarta por título lo que es obviamente
   irrelevante para este giro. Sé estricto: la mayoría de los días, casi nada aplica.
2. Para los que sí pueden pegarle, y SOLO para esos, usa `texto_nota` para leer el texto
   oficial. Nunca afirmes lo que dice una publicación sin haberla leído.
3. Si sospechas que el prefiltro dejó fuera algo relevante, usa `titulos_del_dia`
   para revisar el sumario completo del día y rescátalo.
4. Si algo amerita contexto externo (por ejemplo si una NOM ya venía como proyecto,
   o cuál era el valor anterior de un parámetro), puedes usar WebSearch. Máximo 3
   búsquedas, y solo para hallazgos que ya confirmaste como relevantes.

Reglas duras:
- Cada hallazgo debe citar el `cod_nota` exacto de la publicación que lo respalda.
- No inventes fechas, montos, números de NOM ni plazos. Si el texto no lo dice,
  el campo va en null y lo explicas.
- Si no encontraste nada que le pegue al negocio, el veredicto es `sin_impacto` y
  `hallazgos` va vacío. Un día sin novedades es una respuesta correcta y valiosa;
  inflar el reporte con paja es el peor error que puedes cometer.
- Escribe en español, en voz activa, para un director de operaciones sin formación
  jurídica. Cero lenguaje ceremonial.

Termina SIEMPRE tu respuesta con un único bloque de código ```json que cumpla exactamente
este esquema (sin comentarios, sin texto después del bloque):

```json
{
  "veredicto": "impacto_alto | impacto_moderado | impacto_bajo | sin_impacto",
  "resumen_ejecutivo": "2 a 4 frases. Qué pasó hoy y qué hay que hacer.",
  "hallazgos": [
    {
      "cod_nota": 5797377,
      "titulo": "título tal como aparece en el DOF",
      "dependencia": "dependencia emisora",
      "categoria": "nom | sanitario | fiscal | comercio_exterior | laboral | otro",
      "severidad": "alta | media | baja",
      "que_cambia": "qué dice la publicación, en 1-3 frases",
      "por_que_nos_pega": "el vínculo explícito con este negocio",
      "accion": "la siguiente acción concreta, empezando con un verbo",
      "area_responsable": "área o rol que debe ejecutarla",
      "fecha_limite": "YYYY-MM-DD o null",
      "vigencia": "cuándo entra en vigor, en palabras del documento, o null"
    }
  ],
  "revisados_y_descartados": [
    {"cod_nota": 5797380, "por_que_no": "una línea"}
  ]
}
```"""


def _prompt(fecha: str, giro: Giro, candidatos: list[Candidato], total_notas: int) -> str:
    lineas = [
        f"## Negocio vigilado: {giro.nombre}",
        "",
        giro.descripcion,
        "",
        "### Obligaciones que ya le aplican",
        *(f"- {o}" for o in giro.obligaciones_vigentes),
        "",
        f"## DOF del {fecha}",
        f"El Diario publicó {total_notas} notas. Un prefiltro determinista "
        f"(dependencias vigiladas + palabras clave del giro) dejó {len(candidatos)} candidatos.",
        "El prefiltro es tonto: solo hace match de texto. Tú decides qué es real.",
        "",
        "### Candidatos",
    ]
    for c in candidatos:
        lineas.append(
            f"- codNota {c.nota.cod_nota} | {c.nota.edicion} | {c.nota.dependencia}\n"
            f"  {c.nota.titulo}\n"
            f"  (match: {'; '.join(c.motivos)})"
        )
    lineas += [
        "",
        f"Analiza el día {fecha} y entrega tu reporte.",
    ]
    return "\n".join(lineas)


def _opciones(modelo: str, sin_texto: set[int]) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=modelo,
        system_prompt=INSTRUCCIONES,
        mcp_servers={"dof": servidor_dof(sin_texto)},
        allowed_tools=[TOOL_TEXTO_NOTA, TOOL_TITULOS_DEL_DIA, "WebSearch"],
        # Fuera del contexto del agente: no tiene nada que escribir ni ejecutar.
        disallowed_tools=["Bash", "Write", "Edit", "NotebookEdit", "Read", "Glob", "Grep", "Task"],
        # dontAsk + allowed_tools = superficie fija; nada se queda esperando aprobación.
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=MAX_TURNOS,
    )


async def analizar_dia(
    diario: DiarioDelDia,
    giro: Giro,
    candidatos: list[Candidato],
    modelo: str = MODELO_POR_DEFECTO,
    verboso: bool = True,
) -> dict[str, Any]:
    """Corre el agente sobre un día y devuelve el reporte estructurado."""
    prompt = _prompt(diario.fecha, giro, candidatos, len(diario.notas))
    # EP-01: `servidor_dof` llena este set con los cod_nota que resultaron sin
    # texto disponible durante el run, para reportar cobertura incompleta sin
    # depender de que el modelo lo declare.
    sin_texto: set[int] = set()
    texto_final, resultado = await ejecutar_agente(prompt, _opciones(modelo, sin_texto), verboso)

    reporte = extraer_json(texto_final)
    reporte["fecha"] = diario.fecha
    reporte["giro"] = giro.nombre
    reporte["_meta"] = {
        "modelo": modelo,
        "notas_publicadas": len(diario.notas),
        "candidatos_prefiltro": len(candidatos),
        "turnos": resultado.num_turns,
        "costo_usd": resultado.total_cost_usd,
        "duracion_ms": resultado.duration_ms,
        "session_id": resultado.session_id,
        "fuente_incompleta": sorted(sin_texto),
    }
    return reporte
