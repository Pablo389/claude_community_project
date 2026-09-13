"""Prefiltro determinista: de ~80 notas del día a un puñado de candidatos.

Es a propósito generoso (orientado a recall). Su trabajo no es decidir qué
te impacta, sino tirar el ruido evidente y dejar que el agente juzgue.
Todo lo que descarta sigue disponible para el agente vía la herramienta
`titulos_del_dia`, para que pueda rescatar algo si el filtro se equivocó.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .config import Giro, normalizar
from .dof_api import Nota

PESO_DEPENDENCIA = 2
PESO_PALABRA_CLAVE = 3


def es_correccion(titulo: str) -> bool:
    """Detecta una fe de erratas por su título (EP-02).

    El DOF las nombra de forma consistente ("Fe de erratas a ...", "FE de
    erratas ..."), nunca por número de norma — confirmado contra 6,902 casos
    históricos y el ejemplo de 1986 que ya documenta R14. Ancla al inicio del
    título porque ahí es donde el DOF siempre lo pone.
    """
    return normalizar(titulo).startswith("fe de erratas")


@lru_cache(maxsize=512)
def _patron(clave: str) -> re.Pattern[str]:
    """Match por palabra completa, no por substring.

    Sin esto, la clave `iva` pega en «privativa» y `isr` en cualquier acrónimo:
    los falsos positivos más caros del prefiltro son los de tres letras.
    """
    return re.compile(rf"(?<!\w){re.escape(clave)}(?!\w)" if clave[-1].isalnum()
                      else rf"(?<!\w){re.escape(clave)}")


@dataclass
class Candidato:
    nota: Nota
    puntaje: int
    motivos: list[str]
    es_correccion: bool = False

    def to_dict(self) -> dict:
        return {
            **self.nota.to_dict(),
            "puntaje": self.puntaje,
            "motivos": self.motivos,
            "es_correccion": self.es_correccion,
        }


def prefiltrar(notas: list[Nota], giro: Giro) -> tuple[list[Candidato], list[Nota]]:
    """Devuelve (candidatos, descartadas)."""
    dependencias = giro.dependencias_norm
    claves = giro.claves_norm
    excluidas = giro.excluidas_norm

    candidatos: list[Candidato] = []
    descartadas: list[Nota] = []

    for nota in notas:
        titulo = normalizar(nota.titulo)
        dependencia = normalizar(nota.dependencia)

        if any(exc in titulo for exc in excluidas):
            descartadas.append(nota)
            continue

        puntaje = 0
        motivos: list[str] = []

        if dependencia in dependencias:
            puntaje += PESO_DEPENDENCIA
            motivos.append(f"dependencia vigilada: {nota.dependencia}")

        golpes = [k for k in claves if _patron(k).search(titulo)]
        if golpes:
            puntaje += PESO_PALABRA_CLAVE * len(golpes)
            motivos.append("palabras clave: " + ", ".join(golpes))

        if puntaje:
            candidatos.append(Candidato(
                nota=nota, puntaje=puntaje, motivos=motivos,
                es_correccion=es_correccion(nota.titulo),
            ))
        else:
            descartadas.append(nota)

    # Se recorta por puntaje, pero se entrega ordenado por codNota para que el
    # agente vea el día en el orden en que se publicó.
    candidatos.sort(key=lambda c: (-c.puntaje, c.nota.cod_nota))
    recortados = candidatos[: giro.max_candidatos]
    descartadas.extend(c.nota for c in candidatos[giro.max_candidatos :])
    recortados.sort(key=lambda c: c.nota.cod_nota)
    descartadas.sort(key=lambda n: n.cod_nota)

    return recortados, descartadas
