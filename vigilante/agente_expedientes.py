"""Etapa B — Expedientes: continuidad entre días.

Función pura de `salidas/*.json` (R15): se recomputa completa en cada corrida,
sin caché ni fold incremental.

**Esta etapa no toca la red y no tiene herramientas.** Es lo que separa a las
tres etapas: `dia` es la que lee el DOF y juzga relevancia, `expedientes` solo
agrupa lo que ya tenemos, y `antecedentes` (pendiente) será la única que sale a
buscar historia. Si dos hallazgos son ambiguos, no se agrupan y el expediente
queda abierto: resolver esa ambigüedad es trabajo de `antecedentes`.

Cuatro pasos, y solo el tercero llama al modelo:

  1. Proyección compacta de `salidas/` (Python).
  2. Barrido de vencimientos: aritmética de calendario, no juicio (Python).
  3. Identidad de hilo: ¿estos eventos son el mismo expediente? (Claude, 1 llamada).
  4. Validación y render (Python).

R14 aplica hacia adelante: la `materia` que aquí se fija es la que después
alimenta `antecedentes` para buscar el histórico real del DOF por título.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

from .agente import ejecutar_agente, extraer_json
from .config import RAIZ
from .render import ORDEN_SEVERIDAD, a_markdown_expedientes

MODELO_POR_DEFECTO = "claude-opus-5"
DIAS_PROXIMO = 15  # a partir de aquí un vencimiento cuenta como "próximo"

SALIDAS = RAIZ / "salidas"
ESTADO = RAIZ / "estado"

CAMPOS_HALLAZGO = (
    "cod_nota",
    "titulo",
    "dependencia",
    "categoria",
    "severidad",
    "fecha_limite",
    "que_cambia",
)

FORMATO_EVENTO = "%d-%m-%Y"


# --------------------------------------------------------------------------
# Paso 1 — Proyección compacta
# --------------------------------------------------------------------------
def construir_proyeccion() -> list[dict[str, Any]]:
    """Lee todos los `salidas/*.json` y arma la línea de tiempo del giro.

    Ordenada cronológicamente por nombre de archivo (YYYY-MM-DD ordena bien como
    cadena). Los días inhábiles solo dejan un `.md` y por construcción no salen.
    Solo se proyectan los hallazgos: lo descartado se queda fuera porque los
    reportes diarios no guardan su título, y recuperarlo obligaría a llamar al
    DOF, que es justo lo que esta etapa no hace.
    """
    dias: list[dict[str, Any]] = []
    for ruta in sorted(SALIDAS.glob("*.json")):
        reporte = json.loads(ruta.read_text(encoding="utf-8"))
        dias.append(
            {
                "fecha": reporte.get("fecha") or f"{ruta.stem[8:10]}-{ruta.stem[5:7]}-{ruta.stem[0:4]}",
                "veredicto": reporte.get("veredicto"),
                "hallazgos": [
                    {campo: h.get(campo) for campo in CAMPOS_HALLAZGO}
                    for h in (reporte.get("hallazgos") or [])
                ],
            }
        )
    return dias


# --------------------------------------------------------------------------
# Paso 2 — Barrido de vencimientos (sin modelo)
# --------------------------------------------------------------------------
def barrido_vencimientos(proyeccion: list[dict[str, Any]], hoy: date) -> list[dict[str, Any]]:
    """Aritmética de calendario sobre todos los `fecha_limite` de la historia.

    Clasificación: `vencido`, `proximo` (<= 15 días) o `futuro`. Nada de esto
    necesita criterio del modelo: es una resta de fechas.
    """
    filas: list[dict[str, Any]] = []
    for dia in proyeccion:
        for h in dia["hallazgos"]:
            limite = h.get("fecha_limite")
            if not limite:
                continue
            try:
                fecha_limite = date.fromisoformat(limite)
            except ValueError:
                continue
            dias_restantes = (fecha_limite - hoy).days
            if dias_restantes < 0:
                estado = "vencido"
            elif dias_restantes <= DIAS_PROXIMO:
                estado = "proximo"
            else:
                estado = "futuro"
            filas.append(
                {
                    "cod_nota": h["cod_nota"],
                    "titulo": h.get("titulo"),
                    "categoria": h.get("categoria"),
                    "severidad": h.get("severidad"),
                    "fecha_limite": limite,
                    "dias_restantes": dias_restantes,
                    "estado": estado,
                }
            )
    filas.sort(key=lambda f: f["fecha_limite"])
    return filas


# --------------------------------------------------------------------------
# Paso 3 — Identidad de hilo (una sola llamada al agente, sin herramientas)
# --------------------------------------------------------------------------
INSTRUCCIONES = """\
Eres el archivista del Vigilante del DOF. Tu única pregunta es: de todos los
hallazgos que el Vigilante ya reportó día por día, ¿cuáles pertenecen al mismo
hilo regulatorio? Un hilo es el mismo ASUNTO aunque el número de norma cambie,
aunque la dependencia lo redacte distinto, aunque pasen semanas entre eventos
(proyecto de NOM -> respuesta a comentarios -> NOM definitiva, o varios oficios
de un mismo trámite).

No es tu trabajo evaluar de nuevo si algo le pega al negocio: eso ya lo decidió
el Vigilante día a día. Tu trabajo es agrupar y narrar.

No tienes herramientas. Todo lo que hay que saber está en la proyección que te
entrego. Si dos hallazgos podrían ser el mismo asunto pero la información no
alcanza para afirmarlo, NO los agrupes: déjalos como expedientes separados y
marca `abierto`. Resolver esa ambigüedad le toca a otra etapa que sí puede
buscar el histórico del DOF. Agrupar por corazonada es el peor error posible
aquí, porque inventa una historia que nadie va a auditar.

Un hallazgo que no forma hilo con nada más es un expediente de un solo evento.
Eso es normal y correcto: no fuerces agrupaciones para que se vea más interesante.

Para cada expediente decide si está `abierto` (falta una resolución, corre un
plazo, hay una respuesta pendiente) o `cerrado` (la publicación fue definitiva y
no hay pendiente detectable en lo que viste).

Reglas duras:
- No inventes eventos, fechas ni cod_nota. Cada evento debe citar un `cod_nota`
  que exista tal cual en la proyección.
- `materia` es la frase de búsqueda que se usará después contra el histórico del
  DOF: 2 a 4 palabras, solo sustantivos de la materia, SIN números, SIN guiones,
  SIN la palabra "NOM" (el número de norma cambia a lo largo del hilo y "NOM"
  hace match de substring con miles de textos irrelevantes; la materia es lo
  estable).
- Si no tienes evidencia de un pendiente, el expediente va `cerrado`. No
  inventes un "qué sigue" que la proyección no respalde.
- Escribe en español, en voz activa, sin lenguaje ceremonial.

Termina SIEMPRE tu respuesta con un único bloque de código ```json que cumpla
exactamente este esquema (sin comentarios, sin texto después del bloque):

```json
{
  "expedientes": [
    {
      "id": "slug-kebab-case-estable",
      "titulo": "el asunto en palabras, no el título del DOF",
      "materia": "frase de 2 a 4 palabras que describe la materia",
      "categoria": "nom | sanitario | fiscal | comercio_exterior | laboral | otro",
      "estado": "abierto | cerrado",
      "severidad": "alta | media | baja",
      "eventos": [{"fecha": "DD-MM-YYYY", "cod_nota": 123, "que_paso": "una frase"}],
      "que_sigue": "qué se espera que pase o qué hay que hacer",
      "por_que_este_estado": "una frase justificando abierto o cerrado"
    }
  ]
}
```"""


def _prompt(proyeccion: list[dict[str, Any]]) -> str:
    lineas = [
        "## Historia observada por el Vigilante del DOF",
        f"({len(proyeccion)} días con publicación relevante para el giro)",
        "",
    ]
    for dia in proyeccion:
        lineas.append(f"### {dia['fecha']} — veredicto: {dia['veredicto']}")
        if not dia["hallazgos"]:
            lineas += ["Sin hallazgos ese día.", ""]
            continue
        for h in dia["hallazgos"]:
            lineas.append(
                f"- cod_nota {h['cod_nota']} | {h.get('categoria')} | {h.get('severidad')} | "
                f"límite: {h.get('fecha_limite') or 'sin fecha'} | {h.get('dependencia')}\n"
                f"  título: {h.get('titulo')}\n"
                f"  qué cambia: {h.get('que_cambia')}"
            )
        lineas.append("")
    lineas.append("Arma los expedientes.")
    return "\n".join(lineas)


def _opciones(modelo: str) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=modelo,
        system_prompt=INSTRUCCIONES,
        # Sin herramientas: `["*"]` las quita todas del contexto del agente.
        disallowed_tools=["*"],
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=2,
    )


# --------------------------------------------------------------------------
# Paso 4 — Validación y render (sin modelo)
# --------------------------------------------------------------------------
def _validar_y_enriquecer(
    expedientes_crudos: list[dict[str, Any]], proyeccion: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Aplica los guardarraíles que el prompt pide pero que no hay que confiarle al modelo.

    Descarta eventos cuyo `cod_nota` no exista en la proyección (R7: nada se
    afirma sin respaldo) y deriva en Python los campos que no hay razón para
    pedirle al modelo: `primer_evento_observado`, `proxima_fecha_limite` a partir
    de los `fecha_limite` reales de la Etapa A, e `historia_completa`.
    """
    hallazgos: dict[int, dict[str, Any]] = {
        h["cod_nota"]: h for dia in proyeccion for h in dia["hallazgos"]
    }

    expedientes: list[dict[str, Any]] = []
    for exp in expedientes_crudos:
        eventos = [e for e in (exp.get("eventos") or []) if e.get("cod_nota") in hallazgos]
        if len(eventos) < len(exp.get("eventos") or []):
            print(f"   ! expediente '{exp.get('id')}': descarté eventos con cod_nota inexistente")
        if not eventos:
            print(f"   ! expediente '{exp.get('id')}' sin eventos válidos, se omite")
            continue

        eventos.sort(key=lambda e: (datetime.strptime(e["fecha"], FORMATO_EVENTO).date(), e["cod_nota"]))
        limites = sorted(
            l for e in eventos if (l := hallazgos[e["cod_nota"]].get("fecha_limite"))
        )

        expedientes.append(
            {
                **exp,
                "eventos": eventos,
                "primer_evento_observado": eventos[0]["fecha"],
                # Siempre falso: el Vigilante solo ve desde que lo prendieron.
                # Lo cerrará el comando `antecedentes`.
                "historia_completa": False,
                "proxima_fecha_limite": limites[0] if limites else None,
            }
        )

    expedientes.sort(
        key=lambda e: (
            e.get("estado") != "abierto",
            ORDEN_SEVERIDAD.get(e.get("severidad"), 9),
            e.get("id", ""),
        )
    )
    return expedientes


async def correlacionar(
    modelo: str = MODELO_POR_DEFECTO,
    hoy: date | None = None,
    verboso: bool = True,
) -> dict[str, Any]:
    """Corre los cuatro pasos y escribe `estado/expedientes.json` + `.md`."""
    hoy = hoy or date.today()
    proyeccion = construir_proyeccion()
    vencimientos = barrido_vencimientos(proyeccion, hoy)

    meta: dict[str, Any] = {
        "modelo": None,
        "dias_procesados": len(proyeccion),
        "turnos": 0,
        "costo_usd": 0.0,
        "session_id": None,
        "fecha_referencia": hoy.isoformat(),
    }
    expedientes: list[dict[str, Any]] = []

    if proyeccion:
        texto, resultado = await ejecutar_agente(_prompt(proyeccion), _opciones(modelo), verboso)
        expedientes = _validar_y_enriquecer(extraer_json(texto).get("expedientes") or [], proyeccion)
        meta |= {
            "modelo": modelo,
            "turnos": resultado.num_turns,
            "costo_usd": resultado.total_cost_usd,
            "session_id": resultado.session_id,
        }

    estado = {"expedientes": expedientes, "vencimientos": vencimientos, "_meta": meta}

    ESTADO.mkdir(parents=True, exist_ok=True)
    (ESTADO / "expedientes.json").write_text(
        json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ESTADO / "expedientes.md").write_text(a_markdown_expedientes(estado), encoding="utf-8")
    return estado
