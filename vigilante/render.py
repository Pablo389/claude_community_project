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


ETIQUETA_VENCIMIENTO = {
    "vencido": "Vencido",
    "proximo": "Próximo (≤ 15 días)",
    "cerrado": "Cerrado",
}


def a_markdown_expedientes(estado: dict[str, Any]) -> str:
    """Vista humana de `estado/expedientes.json` (Etapa B).

    Igual que en `a_markdown`, la prosa se deriva del JSON: nada de esto
    se le pide al modelo en texto libre. Vencimientos primero porque es lo
    más accionable, luego expedientes abiertos por severidad, cerrados al
    final, y una sección de auditoría del filtro si aplica.
    """
    meta = estado.get("_meta", {})
    expedientes = estado.get("expedientes") or []
    vencimientos = estado.get("vencimientos") or []
    abiertos = [e for e in expedientes if e.get("estado") == "abierto"]
    cerrados = [e for e in expedientes if e.get("estado") != "abierto"]
    abiertos = sorted(abiertos, key=lambda e: ORDEN_SEVERIDAD.get(e.get("severidad"), 9))

    lineas = [
        "# Vigilante del DOF — Expedientes",
        "",
        f"**Fecha de referencia:** {meta.get('fecha_referencia', '?')}  ",
        f"**Cobertura:** {meta.get('dias_procesados', 0)} días con publicación relevante procesados.  ",
        "",
        "_La historia solo cubre desde que el Vigilante empezó a correr para este giro: "
        "un expediente puede tener antecedentes anteriores que aquí no aparecen "
        "(eso lo resuelve el comando `antecedentes`, todavía pendiente)._",
        "",
    ]

    titulo_legible = {
        ev.get("cod_nota"): e.get("titulo")
        for e in expedientes
        for ev in (e.get("eventos") or [])
        if e.get("titulo")
    }

    urgentes = [v for v in vencimientos if v.get("estado") in ("vencido", "proximo")]
    lineas += ["## Vencimientos próximos y vencidos", ""]
    if not urgentes:
        lineas += ["Ningún plazo detectado vence en los próximos 15 días ni está vencido.", ""]
    else:
        for v in urgentes:
            cod = v.get("cod_nota")
            url = URL_PUBLICA.format(cod_nota=cod) if cod else ""
            dias = v.get("dias_restantes")
            etiqueta = ETIQUETA_VENCIMIENTO.get(v.get("estado"), v.get("estado"))
            detalle = f"vencido hace {-dias} días" if isinstance(dias, int) and dias < 0 else f"en {dias} días"
            lineas.append(
                f"- **[{etiqueta}]** {v.get('fecha_limite')} ({detalle}) — "
                f"{titulo_legible.get(cod) or v.get('titulo') or 'Sin título'} · `{v.get('severidad', '?')}` · "
                f"[codNota {cod}]({url})"
            )
        lineas.append("")

    lineas += ["## Expedientes abiertos", ""]
    if not abiertos:
        lineas += ["No hay expedientes abiertos.", ""]
    else:
        for exp in abiertos:
            lineas += _bloque_expediente(exp)

    lineas += ["## Expedientes cerrados", ""]
    if not cerrados:
        lineas += ["No hay expedientes cerrados.", ""]
    else:
        for exp in cerrados:
            lineas += _bloque_expediente(exp)

    costo = meta.get("costo_usd")
    lineas += [
        "---",
        "",
        f"<sub>Generado por el Vigilante del DOF con {meta.get('modelo', '?')} · "
        f"{meta.get('turnos', '?')} turnos · "
        f"{'$' + format(costo, '.4f') if isinstance(costo, (int, float)) else 'costo n/d'} · "
        "fuente: salidas/*.json de la Etapa A</sub>",
        "",
    ]
    return "\n".join(lineas)


def _bloque_expediente(exp: dict[str, Any]) -> list[str]:
    limite = exp.get("proxima_fecha_limite") or "sin fecha límite"
    lineas = [
        f"### {exp.get('titulo', 'Sin título')}",
        "",
        f"`{exp.get('severidad', '?')}` · `{exp.get('categoria', '?')}` · materia: *{exp.get('materia', '?')}* · "
        f"próximo límite: {limite}",
        "",
        f"**Qué sigue.** {exp.get('que_sigue', '—')}",
        "",
        f"**Por qué este estado.** {exp.get('por_que_este_estado', '—')}",
        "",
        "**Eventos:**",
    ]
    for ev in exp.get("eventos") or []:
        lineas.append(f"- {ev.get('fecha')} · codNota {ev.get('cod_nota')} · {ev.get('que_paso', '—')}")
    lineas += [
        "",
        f"_Primer evento observado por el Vigilante: {exp.get('primer_evento_observado', '?')} "
        "(no necesariamente el inicio real del asunto)._",
        "",
    ]
    return lineas


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
