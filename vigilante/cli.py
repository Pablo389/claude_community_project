"""Interfaz de línea de comandos.

    python -m vigilante dia                  # el DOF de hoy
    python -m vigilante dia 28-08-2026       # una fecha concreta
    python -m vigilante dia 28-08-2026 --solo-prefiltro   # sin gastar tokens
    python -m vigilante expedientes          # Etapa B: expedientes desde salidas/
    python -m vigilante expedientes --solo-proyeccion --hoy 2026-08-29   # sin gastar tokens
    python -m vigilante antecedentes                       # lista los expedientes
    python -m vigilante antecedentes suplemento-pnic-2026  # Etapa C: su historia previa
    python -m vigilante antecedentes suplemento-pnic-2026 --buscar "Ley de Infraestructura de la Calidad"

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

from .agente_antecedentes import (
    MODELO_POR_DEFECTO as MODELO_ANTECEDENTES_POR_DEFECTO,
    ancla,
    buscar_expediente,
    cargar_expedientes,
    investigar,
)
from .agente_dia import MODELO_POR_DEFECTO, analizar_dia
from .agente_expedientes import (
    MODELO_POR_DEFECTO as MODELO_EXPEDIENTES_POR_DEFECTO,
    barrido_vencimientos,
    construir_proyeccion,
    correlacionar,
)
from .config import RAIZ, cargar_giro
from .dof_api import buscar_por_titulo, notas_del_dia
from .prefiltro import prefiltrar
from .render import a_markdown, sin_publicacion

SALIDAS = RAIZ / "salidas"
ESTADO_DIR = RAIZ / "estado"
ANTECEDENTES_DIR = ESTADO_DIR / "antecedentes"
LIMITE_BUSQUEDA = 20
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


def _validar_hoy(valor: str | None) -> date:
    if not valor:
        return date.today()
    try:
        return date.fromisoformat(valor)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Fecha inválida '{valor}'. Formato esperado: YYYY-MM-DD") from exc


async def _comando_expedientes(args: argparse.Namespace) -> int:
    if args.solo_proyeccion:
        proyeccion = construir_proyeccion()
        print(f"→ {len(proyeccion)} días con publicación relevante en salidas/")
        for dia in proyeccion:
            print(f"\n{dia['fecha']} — {dia['veredicto']}")
            for h in dia["hallazgos"]:
                print(f"   H {h['cod_nota']} [{h['categoria']}/{h['severidad']}] {h['titulo'][:70]}"
                      f" (límite: {h['fecha_limite']})")
        vencimientos = barrido_vencimientos(proyeccion, args.hoy)
        print(f"\n→ Barrido de vencimientos contra {args.hoy.isoformat()} ({len(vencimientos)} plazos)")
        for v in vencimientos:
            print(f"   [{v['estado']:<8}] {v['fecha_limite']} ({v['dias_restantes']:+d}d) {v['titulo'][:60]}")
        return 0

    print(f"Vigilante del DOF · Etapa B (expedientes) · referencia {args.hoy.isoformat()}")
    print("→ Levantando proyección de salidas/ y armando hilos con el modelo...")
    estado = await correlacionar(modelo=args.modelo, hoy=args.hoy)
    costo = estado.get("_meta", {}).get("costo_usd")
    print(f"✓ {len(estado['expedientes'])} expedientes · {len(estado['vencimientos'])} plazos"
          + (f" · ${costo:.4f}" if costo else ""))
    print(f"✓ {(ESTADO_DIR / 'expedientes.json').relative_to(RAIZ)}")
    print(f"✓ {(ESTADO_DIR / 'expedientes.md').relative_to(RAIZ)}")
    return 0


async def _comando_antecedentes(args: argparse.Namespace) -> int:
    expedientes = cargar_expedientes()

    if not args.expediente:
        print(f"→ {len(expedientes)} expedientes en estado/expedientes.json")
        for exp in expedientes:
            clave = ancla(exp)
            investigado = (ANTECEDENTES_DIR / f"{clave}.json").exists()
            print(f"   [{'investigado' if investigado else 'sin historia':<12}] "
                  f"{clave} · {exp.get('id')}")
        print("\nElige uno: python -m vigilante antecedentes <slug o cod_nota>")
        return 0

    expediente = buscar_expediente(expedientes, args.expediente)
    print(f"Vigilante del DOF · Etapa C · {expediente.get('id')} (ancla {ancla(expediente)})")

    if args.buscar:
        # Vista previa determinista: la misma búsqueda que hará el agente, gratis.
        # La frase va a mano a propósito: la `materia` de la Etapa B es prosa del
        # modelo y no encuentra nada ('tránsito carreteras federales' -> 0 filas).
        resultado = buscar_por_titulo(args.buscar, LIMITE_BUSQUEDA)
        print(f"→ '{resultado.frase}' → {resultado.total} en el DOF, "
              f"{len(resultado.coincidencias)} revisadas")
        for c in resultado.coincidencias:
            print(f"   {c.fecha}  cod {c.cod_nota}  {c.titulo[:88]}")
        if not resultado.coincidencias:
            print("   (0 resultados: la frase no aparece literal en ningún título del DOF)")
        return 0

    dossier = await investigar(expediente, giro=cargar_giro(args.giro), modelo=args.modelo)
    antecedentes = dossier.get("antecedentes") or []
    confirmados = sum(1 for a in antecedentes if a.get("nivel") == "confirmado")
    costo = dossier.get("_meta", {}).get("costo_usd")
    print(f"✓ {len(antecedentes)} antecedentes ({confirmados} confirmados) · "
          f"{len(dossier.get('consultas') or [])} búsquedas"
          + (f" · ${costo:.4f}" if costo else ""))
    print(f"✓ {(ANTECEDENTES_DIR / f'{ancla(expediente)}.md').relative_to(RAIZ)}")
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

    p_exp = sub.add_parser("expedientes", help="Etapa B: continuidad entre días")
    p_exp.add_argument("--modelo", default=MODELO_EXPEDIENTES_POR_DEFECTO)
    p_exp.add_argument("--hoy", type=_validar_hoy, default=_validar_hoy(None),
                       help="Fecha de referencia para vencimientos, YYYY-MM-DD (hoy por defecto)")
    p_exp.add_argument("--solo-proyeccion", action="store_true",
                       help="Solo muestra la proyección y el barrido de vencimientos, sin llamar al modelo")

    p_ant = sub.add_parser("antecedentes", help="Etapa C: historia previa de un expediente")
    p_ant.add_argument("expediente", nargs="?", default=None,
                       help="Slug del expediente o su cod_nota ancla. Sin argumento, los lista")
    p_ant.add_argument("--giro", default=None, help="Ruta a un giro.yaml alternativo")
    p_ant.add_argument("--modelo", default=MODELO_ANTECEDENTES_POR_DEFECTO)
    p_ant.add_argument("--buscar", default=None, metavar="FRASE",
                       help="Solo corre esta búsqueda contra el histórico, sin llamar al modelo")

    args = parser.parse_args(argv)

    try:
        if args.comando == "dia":
            return asyncio.run(_comando_dia(args))
        if args.comando == "antecedentes":
            return asyncio.run(_comando_antecedentes(args))
        return asyncio.run(_comando_expedientes(args))
    except NotImplementedError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"✗ {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
