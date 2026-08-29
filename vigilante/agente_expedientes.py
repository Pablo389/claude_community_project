"""Etapa B — Continuidad entre días. PENDIENTE.

Contrato ya definido, implementación fuera del alcance del MVP:

  Entrada : todos los `salidas/*.json` que existan (la Etapa A es su única fuente;
            esta etapa NUNCA vuelve a leer el DOF crudo).
  Trabajo : agrupar hallazgos de distintos días que pertenecen al mismo hilo
            regulatorio -> un "expediente" (ej. NOM-253 como proyecto en julio,
            respuesta a comentarios en agosto, definitiva en octubre), detectar
            plazos que se acercan y marcar hilos abiertos sin resolución.
  Salida  : `estado/expedientes.json` + `estado/expedientes.md`.

La memoria entre días vive en archivos derivados, no en sesiones del SDK:
regenerable, inspeccionable y versionable en git.
"""

from __future__ import annotations


def correlacionar() -> None:
    raise NotImplementedError(
        "Etapa B (expedientes) no implementada todavía. "
        "Corre `dia` para varias fechas primero: sus JSON en salidas/ son su insumo."
    )
