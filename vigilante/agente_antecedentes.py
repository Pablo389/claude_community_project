"""Etapa C — Antecedentes: la historia anterior al Vigilante.

Es la única etapa que sale a buscar hacia atrás, y existe por una razón
empírica: en 21 días de agosto de 2026 la Etapa B encontró cero hilos con más
de un evento real. No es defecto suyo, es la cadencia del DOF -entre un proyecto
de NOM y su definitiva pasan meses o años-, así que la continuidad no puede
salir de acumular días propios. Sale de buscar el histórico (R14).

Cómo se prueba una arista (R16). El DOF **no** referencia por fecha: el decreto
que reforma el Reglamento de Tránsito menciona el Diario una sola vez, en su
propio transitorio. Referencia por NOMBRE, en el título. Por eso la única
herramienta del agente rechaza cualquier frase que no aparezca literal en el
expediente, y después Python descarta cualquier `cod_nota` que no haya salido de
una búsqueda real. El modelo elige qué pertenece al hilo; no elige la evidencia.

Cara y estable (R15): el resultado se persiste en
`estado/antecedentes/<cod_ancla>.json`. Un archivo por investigación, no un
diccionario compartido: se borra, se rehace y se lee uno sin tocar los demás.

La llave es el `cod_nota` del primer evento observado por la Etapa A, nunca el
slug -que el modelo reescribe en cada corrida- ni el antecedente más antiguo
-que se movería hacia atrás justo cuando la investigación tiene éxito-.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

from . import dof_api
from .agente import ejecutar_agente, extraer_json
from .config import RAIZ, Giro, cargar_giro
from .herramientas import TOOL_BUSCAR, TOOL_LEER_CANDIDATA, Registro, servidor_historico
from .render import a_markdown_antecedentes

MODELO_POR_DEFECTO = "claude-opus-5"
MAX_TURNOS = 60
LIMITE_FUENTE = 15_000  # caracteres por publicación propia dentro del prompt

ESTADO = RAIZ / "estado"
SALIDAS = RAIZ / "salidas"
DOSSIERS = ESTADO / "antecedentes"
NIVELES = {"confirmado", "probable"}
FORMATO_EVENTO = "%d-%m-%Y"


def ancla(expediente: dict[str, Any]) -> int | None:
    """El `cod_nota` del primer evento observado. Es la identidad del expediente.

    Los eventos vienen ya ordenados por la Etapa B. Los antecedentes que
    encuentre esta etapa NO pueden volverse ancla: la llave se movería hacia
    atrás en cada corrida y el caché caro se perdería.
    """
    eventos = expediente.get("eventos") or []
    return int(eventos[0]["cod_nota"]) if eventos else None


def cargar_expedientes() -> list[dict[str, Any]]:
    ruta = ESTADO / "expedientes.json"
    if not ruta.exists():
        raise FileNotFoundError(
            "No hay estado/expedientes.json todavía. Corre `python -m vigilante expedientes` primero."
        )
    return json.loads(ruta.read_text(encoding="utf-8")).get("expedientes") or []


def buscar_expediente(expedientes: list[dict[str, Any]], referencia: str) -> dict[str, Any]:
    """Acepta el slug legible o el `cod_nota` ancla. La llave real es el entero."""
    for exp in expedientes:
        if exp.get("id") == referencia or str(ancla(exp)) == referencia:
            return exp
    ids = "\n  ".join(f"{e.get('id')} ({ancla(e)})" for e in expedientes)
    raise LookupError(f"No encontré el expediente '{referencia}'. Disponibles:\n  {ids}")


def titulos_dof() -> dict[int, str]:
    """`cod_nota` -> título oficial, leído de `salidas/`. Determinista, sin red.

    Hace falta porque el expediente solo guarda la prosa del modelo (`que_paso`),
    y el título es justo donde el DOF nombra al ordenamiento.
    """
    titulos: dict[int, str] = {}
    for ruta in sorted(SALIDAS.glob("*.json")):
        try:
            reporte = json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for h in reporte.get("hallazgos") or []:
            if h.get("cod_nota") and h.get("titulo"):
                titulos[int(h["cod_nota"])] = h["titulo"]
    return titulos


def _textos_fuente(
    expediente: dict[str, Any], titulos: dict[int, str], verboso: bool = True
) -> dict[int, str]:
    """Título oficial + texto de cada publicación propia del expediente.

    Es la fuente contra la que se valida R16: solo frases que aparezcan aquí
    pueden convertirse en búsqueda. El título va incluido porque a veces el
    cuerpo no repite el nombre del ordenamiento.
    """
    textos: dict[int, str] = {}
    for evento in expediente.get("eventos") or []:
        cod = int(evento["cod_nota"])
        titulo = titulos.get(cod, "")
        try:
            textos[cod] = f"{titulo}\n{dof_api.texto_nota(cod)}"
        except Exception as exc:
            if verboso:
                print(f"   ! no pude leer la nota {cod}: {exc}")
            if titulo:
                textos[cod] = titulo
    return textos


INSTRUCCIONES = """\
Eres el investigador de antecedentes del Vigilante del DOF. Te dan UN expediente
-lo que el Vigilante alcanzó a ver de un asunto- y tu trabajo es reconstruir la
historia anterior a que el Vigilante existiera, con pruebas.

El DOF no numera sus casos. No hay folio que amarre una publicación con su
antecedente. Lo que sí hay es el NOMBRE del ordenamiento o de la materia,
escrito en el título. Ese nombre es la llave, y por eso solo puedes buscar
frases que aparezcan LITERALES en el expediente que te entrego: la herramienta
rechaza cualquier paráfrasis. No es una molestia, es el punto: una búsqueda que
alguien más puede repetir es lo único que hace auditable esta etapa.

Método:
1. Lee el expediente. Identifica cómo se llama el asunto: el ordenamiento que
   reforma, la NOM que actualiza, la materia que regula. El nombre suele estar
   completo en el título de la publicación.
2. Busca con `buscar_historico` usando esa frase, copiada tal cual. Prueba
   varias si la primera devuelve demasiado o muy poco. Nunca uses números de
   NOM: el número cambia a lo largo del hilo y el match de substring te
   devuelve decenas de miles de filas.
3. De lo que devuelve el DOF, decide caso por caso si pertenece al MISMO asunto.
   Usa `leer_candidata` cuando el título no baste.
4. Ordena la historia y di qué está vigente hoy.

Un hilo normativo típico se ve así, y reconocerlo es la mitad del trabajo:
proyecto (PROY-NOM) -> respuesta a los comentarios -> norma definitiva ->
criterios o modificaciones posteriores. La definitiva deroga a la anterior del
mismo número.

Reglas duras:
- Solo puedes citar `cod_nota` que el DOF te haya devuelto en una búsqueda.
  Inventar uno es el peor error posible y se detecta automáticamente.
- Cada antecedente lleva `cita`: una frase copiada literal del título o del
  texto de ESA publicación que justifique por qué pertenece al hilo.
- `nivel` es `confirmado` cuando la publicación es inequívocamente del mismo
  asunto y `probable` cuando es plausible pero podría ser otro asunto de
  materia parecida. Ante la duda, `probable`. Nunca subas de nivel para que la
  historia se vea mejor.
- Si el histórico no arroja nada del mismo asunto, `sin_historia` es true y
  `antecedentes` va vacío. Es un resultado válido: hay publicaciones que de
  verdad nacen solas.
- No repitas los eventos que el expediente ya tiene. Solo lo que él no vio.
- Escribe en español, en voz activa, para un director de operaciones sin
  formación jurídica.

Termina SIEMPRE tu respuesta con un único bloque de código ```json que cumpla
exactamente este esquema (sin comentarios, sin texto después del bloque):

```json
{
  "sin_historia": false,
  "narrativa": "3 a 6 frases: de dónde viene este asunto y en qué punto está hoy.",
  "antecedentes": [
    {
      "cod_nota": 5074071,
      "papel": "raiz | proyecto | respuesta_comentarios | definitiva | reforma | criterio | serie | otro",
      "que_paso": "una frase",
      "por_que_pertenece": "el vínculo con el expediente, en una frase",
      "cita": "frase literal copiada de esa publicación",
      "nivel": "confirmado | probable"
    }
  ],
  "vigente": {"cod_nota": 5787790, "por_que": "por qué esta es la que rige hoy"}
}
```"""


def _prompt(expediente: dict[str, Any], textos: dict[int, str], giro: Giro) -> str:
    lineas = [
        f"## Negocio vigilado: {giro.nombre}",
        "",
        giro.descripcion,
        "",
        "## Expediente a investigar",
        "",
        f"**{expediente.get('titulo')}**",
        f"categoría `{expediente.get('categoria')}` · estado `{expediente.get('estado')}`",
        "",
        "### Lo que el Vigilante ya vio",
    ]
    for evento in expediente.get("eventos") or []:
        lineas.append(
            f"- {evento.get('fecha')} · codNota {evento.get('cod_nota')} · {evento.get('que_paso')}"
        )
    lineas += [
        "",
        "### Texto oficial de esas publicaciones",
        "",
        "Las frases que uses para buscar tienen que salir de aquí, literales.",
        "",
    ]
    for cod, texto in textos.items():
        recorte = texto[:LIMITE_FUENTE]
        if len(texto) > LIMITE_FUENTE:
            recorte += "\n[...texto truncado...]"
        lineas += [f"#### codNota {cod}", "```", recorte, "```", ""]

    lineas.append("Reconstruye la historia de este expediente.")
    return "\n".join(lineas)


def _opciones(modelo: str, registro: Registro) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=modelo,
        system_prompt=INSTRUCCIONES,
        mcp_servers={"dof_historico": servidor_historico(registro)},
        allowed_tools=[TOOL_BUSCAR, TOOL_LEER_CANDIDATA],
        disallowed_tools=["Bash", "Write", "Edit", "NotebookEdit", "Read", "Glob", "Grep", "Task",
                          "WebSearch", "WebFetch"],
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=MAX_TURNOS,
    )


def _fecha(valor: str | None) -> date:
    try:
        return datetime.strptime(valor or "", FORMATO_EVENTO).date()
    except ValueError:
        return date.max


def _validar(
    crudo: dict[str, Any], expediente: dict[str, Any], registro: Registro, verboso: bool = True
) -> dict[str, Any]:
    """R16 en Python: nada que el DOF no haya devuelto sobrevive aquí.

    `fecha` y `titulo` se toman del registro de búsquedas, no de lo que el
    modelo escribió: son datos del DOF y no hay razón para dejar que los
    transcriba.
    """
    propios = {int(e["cod_nota"]) for e in expediente.get("eventos") or []}

    antecedentes: list[dict[str, Any]] = []
    for item in crudo.get("antecedentes") or []:
        try:
            cod = int(item.get("cod_nota"))
        except (TypeError, ValueError):
            continue
        if not registro.conocido(cod):
            if verboso:
                print(f"   ! descarto codNota {cod}: no salió en ninguna búsqueda")
            continue
        if cod in propios:
            continue  # ya es un evento del expediente, no un antecedente
        oficial = registro.vistos[cod]
        antecedentes.append(
            {
                "cod_nota": cod,
                "fecha": oficial["fecha"],
                "titulo": oficial["titulo"],
                "url": dof_api.URL_PUBLICA.format(cod_nota=cod),
                "papel": item.get("papel") or "otro",
                "que_paso": item.get("que_paso"),
                "por_que_pertenece": item.get("por_que_pertenece"),
                "cita": item.get("cita"),
                "nivel": item.get("nivel") if item.get("nivel") in NIVELES else "probable",
            }
        )
    antecedentes.sort(key=lambda a: (_fecha(a["fecha"]), a["cod_nota"]))

    vigente = crudo.get("vigente") or None
    if vigente:
        try:
            cod = int(vigente.get("cod_nota"))
        except (TypeError, ValueError):
            cod = None
        if cod is None or not registro.conocido(cod):
            if verboso and cod is not None:
                print(f"   ! descarto vigente {cod}: no salió en ninguna búsqueda")
            vigente = None
        else:
            vigente = {
                "cod_nota": cod,
                "fecha": registro.vistos[cod]["fecha"],
                "titulo": registro.vistos[cod]["titulo"],
                "url": dof_api.URL_PUBLICA.format(cod_nota=cod),
                "por_que": vigente.get("por_que"),
            }

    return {
        "sin_historia": bool(crudo.get("sin_historia")) or not antecedentes,
        "narrativa": crudo.get("narrativa"),
        "antecedentes": antecedentes,
        "vigente": vigente,
    }


async def investigar(
    expediente: dict[str, Any],
    giro: Giro | None = None,
    modelo: str = MODELO_POR_DEFECTO,
    verboso: bool = True,
) -> dict[str, Any]:
    """Investiga UN expediente y escribe su dossier. Devuelve el dossier."""
    giro = giro or cargar_giro()
    clave = ancla(expediente)
    if clave is None:
        raise ValueError(f"El expediente '{expediente.get('id')}' no tiene eventos")

    oficiales = titulos_dof()
    if verboso:
        print(f"→ Leyendo las {len(expediente.get('eventos') or [])} publicaciones del expediente...")
    textos = _textos_fuente(expediente, oficiales, verboso)
    if not textos:
        raise RuntimeError("No pude leer ninguna publicación del expediente; sin fuente no hay búsqueda")

    # Los eventos propios entran al registro con su título REAL del DOF: el
    # `que_paso` es prosa del modelo y acabaría citado como si fuera oficial.
    registro = Registro(textos)
    registro.registrar(
        dof_api.Coincidencia(
            cod_nota=int(e["cod_nota"]),
            titulo=oficiales.get(int(e["cod_nota"]), str(e.get("que_paso") or "")),
            fecha=str(e.get("fecha") or ""),
            dependencia="",
        )
        for e in expediente.get("eventos") or []
    )

    if verboso:
        print(f"→ Investigando el histórico del DOF con {modelo}...")
    texto_final, resultado = await ejecutar_agente(
        _prompt(expediente, textos, giro), _opciones(modelo, registro), verboso
    )
    dossier = _validar(extraer_json(texto_final), expediente, registro, verboso)

    dossier |= {
        "ancla": clave,
        "expediente_id": expediente.get("id"),
        "titulo": expediente.get("titulo"),
        # La evidencia de R16: con esto cualquiera repite la investigación.
        "consultas": registro.consultas,
        "frases_rechazadas": registro.rechazadas,
        "_meta": {
            "modelo": modelo,
            "investigado_el": date.today().isoformat(),
            "notas_vistas": len(registro.vistos),
            "turnos": resultado.num_turns,
            "costo_usd": resultado.total_cost_usd,
            "duracion_ms": resultado.duration_ms,
            "session_id": resultado.session_id,
        },
    }

    DOSSIERS.mkdir(parents=True, exist_ok=True)
    (DOSSIERS / f"{clave}.json").write_text(
        json.dumps(dossier, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (DOSSIERS / f"{clave}.md").write_text(a_markdown_antecedentes(dossier), encoding="utf-8")
    return dossier
