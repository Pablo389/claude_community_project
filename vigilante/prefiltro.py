"""Prefiltro determinista: de ~80 notas del día a un puñado de candidatos.

Es a propósito generoso (orientado a recall). Su trabajo no es decidir qué
te impacta, sino tirar el ruido evidente y dejar que el agente juzgue.
Todo lo que descarta sigue disponible para el agente vía la herramienta
`titulos_del_dia`, para que pueda rescatar algo si el filtro se equivocó.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Giro, normalizar
from .dof_api import Nota

PESO_DEPENDENCIA = 2
PESO_PALABRA_CLAVE = 3


@dataclass
class Candidato:
    nota: Nota
    puntaje: int
    motivos: list[str]

    def to_dict(self) -> dict:
        return {**self.nota.to_dict(), "puntaje": self.puntaje, "motivos": self.motivos}


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

        golpes = [k for k in claves if k in titulo]
        if golpes:
            puntaje += PESO_PALABRA_CLAVE * len(golpes)
            motivos.append("palabras clave: " + ", ".join(golpes))

        if puntaje:
            candidatos.append(Candidato(nota=nota, puntaje=puntaje, motivos=motivos))
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
