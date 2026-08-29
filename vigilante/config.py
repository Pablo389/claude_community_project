"""Carga del perfil del giro (giro.yaml)."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
GIRO_POR_DEFECTO = RAIZ / "giro.yaml"


def normalizar(texto: str) -> str:
    """Minúsculas y sin acentos: el DOF mezcla `SECRETARÍA` y `SECRETARIA`."""
    sin_acentos = unicodedata.normalize("NFKD", texto or "")
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    return sin_acentos.lower().strip()


@dataclass
class Giro:
    nombre: str
    descripcion: str
    dependencias_vigiladas: list[str] = field(default_factory=list)
    palabras_clave: list[str] = field(default_factory=list)
    palabras_excluidas: list[str] = field(default_factory=list)
    obligaciones_vigentes: list[str] = field(default_factory=list)
    max_candidatos: int = 25

    @property
    def dependencias_norm(self) -> set[str]:
        return {normalizar(d) for d in self.dependencias_vigiladas}

    @property
    def claves_norm(self) -> list[str]:
        return [normalizar(k) for k in self.palabras_clave]

    @property
    def excluidas_norm(self) -> list[str]:
        return [normalizar(k) for k in self.palabras_excluidas]


def cargar_giro(ruta: Path | str | None = None) -> Giro:
    ruta = Path(ruta) if ruta else GIRO_POR_DEFECTO
    if not ruta.exists():
        raise FileNotFoundError(f"No encontré el perfil del giro en {ruta}")
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    return Giro(
        nombre=datos.get("nombre", "Sin nombre"),
        descripcion=(datos.get("descripcion") or "").strip(),
        dependencias_vigiladas=datos.get("dependencias_vigiladas") or [],
        palabras_clave=datos.get("palabras_clave") or [],
        palabras_excluidas=datos.get("palabras_excluidas") or [],
        obligaciones_vigentes=datos.get("obligaciones_vigentes") or [],
        max_candidatos=int(datos.get("max_candidatos") or 25),
    )
