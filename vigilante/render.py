"""Render del reporte estructurado a Markdown legible.

La prosa se deriva del JSON, no al revés: el agente produce datos, la plantilla
produce el documento. Así el formato del reporte nunca varía entre corridas.
"""

from __future__ import annotations

from typing import Any

from .dof_api import URL_PUBLICA

ETIQUETA_VEREDICTO = {
    "impacto_alto": "Impacto alto — requiere acción esta semana",
    "impacto_moderado": "Impacto moderado — agendar",
    "impacto_bajo": "Impacto bajo — informativo",
    "sin_impacto": "Sin impacto para el giro",
}

ORDEN_SEVERIDAD = {"alta": 0, "media": 1, "baja": 2}


def a_markdown(reporte: dict[str, Any]) -> str:
    meta = reporte.get("_meta", {})
    veredicto = reporte.get("veredicto", "sin_impacto")
    hallazgos = sorted(
        reporte.get("hallazgos") or [],
        key=lambda h: ORDEN_SEVERIDAD.get(h.get("severidad"), 9),
    )

    lineas = [
        f"# Vigilante del DOF — {reporte.get('fecha', '?')}",
        "",
        f"**Giro:** {reporte.get('giro', '?')}  ",
        f"**Veredicto:** {ETIQUETA_VEREDICTO.get(veredicto, veredicto)}  ",
        f"**Cobertura:** {meta.get('notas_publicadas', '?')} notas publicadas, "
        f"{meta.get('candidatos_prefiltro', '?')} revisadas a detalle, "
        f"{len(hallazgos)} con impacto.",
        "",
        "## Resumen",
        "",
        reporte.get("resumen_ejecutivo", "_Sin resumen._"),
        "",
    ]

    if not hallazgos:
        lineas += ["## Hallazgos", "", "Nada en el Diario de hoy le pega al negocio.", ""]
    else:
        lineas += ["## Hallazgos", ""]
        for i, h in enumerate(hallazgos, 1):
            cod = h.get("cod_nota")
            url = URL_PUBLICA.format(cod_nota=cod) if cod else ""
            limite = h.get("fecha_limite") or "sin fecha límite explícita"
            lineas += [
                f"### {i}. {h.get('titulo', 'Sin título')}",
                "",
                f"`{h.get('severidad', '?')}` · `{h.get('categoria', '?')}` · "
                f"{h.get('dependencia', '?')} · [codNota {cod}]({url})",
                "",
                f"**Qué cambia.** {h.get('que_cambia', '—')}",
                "",
                f"**Por qué nos pega.** {h.get('por_que_nos_pega', '—')}",
                "",
                f"**Acción.** {h.get('accion', '—')} "
                f"— *{h.get('area_responsable', 'sin asignar')}*, límite: {limite}.",
                "",
            ]
            if h.get("vigencia"):
                lineas += [f"**Vigencia.** {h['vigencia']}", ""]

    descartados = reporte.get("revisados_y_descartados") or []
    if descartados:
        lineas += ["## Revisado y descartado", ""]
        for d in descartados:
            cod = d.get("cod_nota")
            url = URL_PUBLICA.format(cod_nota=cod) if cod else ""
            lineas.append(f"- [{cod}]({url}) — {d.get('por_que_no', '—')}")
        lineas.append("")

    costo = meta.get("costo_usd")
    lineas += [
        "---",
        "",
        f"<sub>Generado por el Vigilante del DOF con {meta.get('modelo', '?')} · "
        f"{meta.get('turnos', '?')} turnos · "
        f"{'$' + format(costo, '.4f') if isinstance(costo, (int, float)) else 'costo n/d'} · "
        "fuente: API SIDOF (Segob)</sub>",
        "",
    ]
    return "\n".join(lineas)


def sin_publicacion(fecha: str, giro_nombre: str) -> str:
    return "\n".join(
        [
            f"# Vigilante del DOF — {fecha}",
            "",
            f"**Giro:** {giro_nombre}",
            "",
            "El DOF no publicó ediciones en esta fecha (fin de semana o día inhábil).",
            "",
        ]
    )
