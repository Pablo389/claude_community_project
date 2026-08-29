"""Interfaz de línea de comandos.

    python -m vigilante dia                  # el DOF de hoy
    python -m vigilante dia 28-08-2026       # una fecha concreta
    python -m vigilante dia 28-08-2026 --solo-prefiltro   # sin gastar tokens
    python -m vigilante expedientes          # Etapa B (pendiente)

Cada corrida golpea la API del DOF en vivo y vuelve a razonar el día completo.
No hay caché: el Diario cambia durante el día (edición vespertina, extraordinarias)
y este comando está pensado para vivir detrás de un cron.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import date
from pathlib import Path

from .agente_dia import MODELO_POR_DEFECTO, analizar_dia
from .agente_expedientes import correlacionar
from .config import RAIZ, cargar_giro
from .dof_api import notas_del_dia
from .prefiltro import prefiltrar
from .render import a_markdown, sin_publicacion

SALIDAS = RAIZ / "salidas"
FORMATO_FECHA = re.compile(r"^\d{2}-\d{2}-\d{4}$")


def _validar_fecha(valor: str | None) -> str:
    if not valor:
        return date.today().strftime("%d-%m-%Y")
    if not FORMATO_FECHA.match(valor):
        raise argparse.ArgumentTypeError(f"Fecha inválida '{valor}'. Formato esperado: DD-MM-YYYY")
    return valor


def _guardar(fecha: str, markdown: str, reporte: dict | None) -> Path:
    SALIDAS.mkdir(parents=True, exist_ok=True)
    dia, mes, anio = fecha.split("-")
    base = SALIDAS / f"{anio}-{mes}-{dia}"
    base.with_suffix(".md").write_text(markdown, encoding="utf-8")
    if reporte is not None:
        base.with_suffix(".json").write_text(
            json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return base.with_suffix(".md")


async def _comando_dia(args: argparse.Namespace) -> int:
    fecha = args.fecha
    giro = cargar_giro(args.giro)

    print(f"Vigilante del DOF · {fecha} · {giro.nombre}")
    print("→ Consultando el DOF...")
    diario = notas_del_dia(fecha)

    if not diario.hubo_publicacion:
        print("   El DOF no publicó ediciones en esta fecha.")
        ruta = _guardar(fecha, sin_publicacion(fecha, giro.nombre), None)
        print(f"✓ {ruta.relative_to(RAIZ)}")
        return 0

    candidatos, descartadas = prefiltrar(diario.notas, giro)
    print(f"   {len(diario.notas)} notas → {len(candidatos)} candidatos ({len(descartadas)} descartadas)")

    if args.solo_prefiltro:
        for c in candidatos:
            print(f"   [{c.puntaje}] {c.nota.cod_nota} {c.nota.dependencia[:34]:<34} {c.nota.titulo[:70]}")
        return 0

    if not candidatos:
        print("   Ningún candidato: nada que analizar.")

    print(f"→ Analizando con {args.modelo}...")
    reporte = await analizar_dia(diario, giro, candidatos, modelo=args.modelo)

    ruta = _guardar(fecha, a_markdown(reporte), reporte)
    hallazgos = len(reporte.get("hallazgos") or [])
    costo = reporte.get("_meta", {}).get("costo_usd")
    print(f"✓ {reporte.get('veredicto')} · {hallazgos} hallazgos" + (f" · ${costo:.4f}" if costo else ""))
    print(f"✓ {ruta.relative_to(RAIZ)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vigilante", description="Vigilante del DOF")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_dia = sub.add_parser("dia", help="Analiza el DOF de una fecha (hoy por defecto)")
    p_dia.add_argument("fecha", nargs="?", type=_validar_fecha, default=_validar_fecha(None),
                       help="DD-MM-YYYY")
    p_dia.add_argument("--giro", default=None, help="Ruta a un giro.yaml alternativo")
    p_dia.add_argument("--modelo", default=MODELO_POR_DEFECTO)
    p_dia.add_argument("--solo-prefiltro", action="store_true",
                       help="Solo muestra los candidatos, sin llamar al modelo")

    sub.add_parser("expedientes", help="Etapa B: continuidad entre días (pendiente)")

    args = parser.parse_args(argv)

    try:
        if args.comando == "dia":
            return asyncio.run(_comando_dia(args))
        correlacionar()
        return 0
    except NotImplementedError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"✗ {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
