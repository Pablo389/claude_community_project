"""Fixtures compartidas. Todas las pruebas son deterministas: nada de red ni de LLM."""

from __future__ import annotations

import pytest

from vigilante.config import Giro
from vigilante.dof_api import Nota


@pytest.fixture
def giro() -> Giro:
    """Un recorte realista de giro.yaml: importadora de dispositivos médicos."""
    return Giro(
        nombre="Importadora y distribuidora de dispositivos médicos",
        descripcion="Empresa que importa dispositivos médicos y los distribuye.",
        dependencias_vigiladas=[
            "SECRETARIA DE SALUD",
            "COMISION FEDERAL PARA LA PROTECCION CONTRA RIESGOS SANITARIOS",
        ],
        palabras_clave=["nom-", "dispositivo medico", "registro sanitario", "iva", "isr"],
        palabras_excluidas=["convocatoria a concurso", "aviso notarial"],
        obligaciones_vigentes=["NOM-137-SSA1-2008"],
        max_candidatos=3,
    )


def hacer_nota(cod_nota: int, titulo: str, dependencia: str = "SECRETARIA DE SALUD", **kw) -> Nota:
    return Nota(
        cod_nota=cod_nota,
        titulo=titulo,
        dependencia=dependencia,
        poder="Ejecutivo",
        edicion=kw.get("edicion", "MAT"),
        seccion=kw.get("seccion", "1"),
        fecha=kw.get("fecha", "28-08-2026"),
        pagina=kw.get("pagina", 0),
    )
