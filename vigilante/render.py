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


def _turnos(n: Any) -> str:
    return f"{n} turno" if n == 1 else f"{n} turnos"


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
        f"{_turnos(meta.get('turnos', '?'))} · "
        f"{'$' + format(costo, '.4f') if isinstance(costo, (int, float)) else 'costo n/d'} · "
        "fuente: API SIDOF (Segob)</sub>",
        "",
    ]
    return "\n".join(lineas)



def a_markdown_expedientes(estado: dict[str, Any]) -> str:
    """Vista humana de `estado/expedientes.json` (Etapa B).

    Un expediente aparece en exactamente una sección. El vencimiento no es una
    categoría sino el orden de la primera: cruzar "tiene plazo" con
    "sigue abierto" da cuatro cuadrantes, pero al usuario solo le importan tres
    cosas -actúa hoy, vigila, archivado- y listarlas por separado duplicaba
    expedientes en el documento.
    """
    meta = estado.get("_meta", {})
    expedientes = estado.get("expedientes") or []
    dias_por_limite = {v["fecha_limite"]: v["dias_restantes"] for v in estado.get("vencimientos") or []}

    abiertos = [e for e in expedientes if e.get("estado") == "abierto"]
    cerrados = [e for e in expedientes if e.get("estado") != "abierto"]

    con_plazo = sorted(
        (e for e in abiertos if e.get("proxima_fecha_limite")),
        key=lambda e: e["proxima_fecha_limite"],
    )
    sin_plazo = sorted(
        (e for e in abiertos if not e.get("proxima_fecha_limite")),
        key=lambda e: ORDEN_SEVERIDAD.get(e.get("severidad"), 9),
    )
    # Un asunto sin pendiente no debería tener el reloj corriendo: si pasa,
    # es un error de clasificación del modelo y hay que verlo, no esconderlo.
    incoherentes = [
        e for e in cerrados
        if e.get("proxima_fecha_limite") and dias_por_limite.get(e["proxima_fecha_limite"], -1) >= 0
    ]

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
        "_«Sin pendiente» significa que no se detecta continuación regulatoria, "
        "no que el pendiente ya se haya atendido internamente._",
        "",
        "## Acción con fecha",
        "",
    ]
    if not con_plazo:
        lineas += ["Ningún expediente abierto tiene plazo detectado.", ""]
    for exp in con_plazo:
        lineas += _bloque_expediente(exp, dias_por_limite)

    lineas += ["## En el radar", ""]
    if not sin_plazo:
        lineas += ["Ningún expediente abierto sin plazo.", ""]
    for exp in sin_plazo:
        lineas += _bloque_expediente(exp, dias_por_limite)

    lineas += ["## Sin pendiente", ""]
    if not cerrados:
        lineas += ["Ninguno.", ""]
    else:
        for exp in cerrados:
            eventos = exp.get("eventos") or []
            cod = eventos[-1].get("cod_nota") if eventos else None
            url = URL_PUBLICA.format(cod_nota=cod) if cod else ""
            lineas.append(
                f"- {exp.get('titulo', exp.get('id'))} · `{exp.get('categoria', '?')}`"
                + (f" · [codNota {cod}]({url})" if cod else "")
            )
        lineas.append("")

    if incoherentes:
        lineas += [
            "## Revisar la clasificación",
            "",
            "Estos expedientes quedaron como sin pendiente pero tienen un plazo vigente:",
            "",
        ]
        for exp in incoherentes:
            lineas.append(f"- {exp.get('titulo', exp.get('id'))} — límite {exp['proxima_fecha_limite']}")
        lineas.append("")

    costo = meta.get("costo_usd")
    lineas += [
        "---",
        "",
        f"<sub>Generado por el Vigilante del DOF con {meta.get('modelo', '?')} · "
        f"{_turnos(meta.get('turnos', '?'))} · "
        f"{'$' + format(costo, '.4f') if isinstance(costo, (int, float)) else 'costo n/d'} · "
        "fuente: salidas/*.json de la Etapa A</sub>",
        "",
    ]
    return "\n".join(lineas)


def _bloque_expediente(exp: dict[str, Any], dias_por_limite: dict[str, int]) -> list[str]:
    limite = exp.get("proxima_fecha_limite")
    if limite:
        dias = dias_por_limite.get(limite)
        if isinstance(dias, int):
            cuando = f"vencido hace {-dias} días" if dias < 0 else f"en {dias} días"
            plazo = f"**{limite}** ({cuando})"
        else:
            plazo = f"**{limite}**"
    else:
        plazo = "sin plazo detectado"

    lineas = [
        f"### {exp.get('titulo', 'Sin título')}",
        "",
        f"{plazo} · `{exp.get('severidad', '?')}` · `{exp.get('categoria', '?')}` · "
        f"materia: *{exp.get('materia', '?')}*",
        "",
        f"**Qué sigue.** {exp.get('que_sigue', '—')}",
        "",
        f"**Por qué sigue abierto.** {exp.get('por_que_este_estado', '—')}",
        "",
        "**Eventos:**",
    ]
    for ev in exp.get("eventos") or []:
        cod = ev.get("cod_nota")
        url = URL_PUBLICA.format(cod_nota=cod) if cod else ""
        lineas.append(f"- {ev.get('fecha')} · [codNota {cod}]({url}) · {ev.get('que_paso', '—')}")
    lineas += [
        "",
        f"_Primer evento observado: {exp.get('primer_evento_observado', '?')} "
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
