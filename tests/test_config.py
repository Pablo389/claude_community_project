"""config.py: normalización de texto y carga de giro.yaml."""

from __future__ import annotations

import pytest

from vigilante.config import Giro, cargar_giro, normalizar


class TestNormalizar:
    def test_quita_acentos(self):
        assert normalizar("SECRETARÍA") == "secretaria"

    def test_minusculas_y_recorte(self):
        assert normalizar("  Comisión Federal  ") == "comision federal"

    def test_texto_vacio_no_truena(self):
        assert normalizar("") == ""
        assert normalizar(None) == ""


class TestGiro:
    def test_dependencias_norm_son_comparables_con_dof(self):
        g = Giro(nombre="x", descripcion="", dependencias_vigiladas=["SECRETARÍA DE SALUD"])
        # El DOF manda `codOrgaDos` a veces con acento, a veces sin: R (normalizar) lo absorbe.
        assert "secretaria de salud" in g.dependencias_norm

    def test_claves_y_excluidas_se_normalizan_igual(self):
        g = Giro(nombre="x", descripcion="", palabras_clave=["CoFePris"], palabras_excluidas=["Edicto"])
        assert g.claves_norm == ["cofepris"]
        assert g.excluidas_norm == ["edicto"]


class TestCargarGiro:
    def test_ruta_inexistente_lanza(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            cargar_giro(tmp_path / "no-existe.yaml")

    def test_carga_valores_completos(self, tmp_path):
        ruta = tmp_path / "giro.yaml"
        ruta.write_text(
            """
nombre: "Mi negocio"
descripcion: "Una descripción"
dependencias_vigiladas:
  - SECRETARIA DE SALUD
palabras_clave:
  - cofepris
palabras_excluidas:
  - edicto
obligaciones_vigentes:
  - "NOM-137-SSA1-2008"
max_candidatos: 10
""",
            encoding="utf-8",
        )
        g = cargar_giro(ruta)
        assert g.nombre == "Mi negocio"
        assert g.max_candidatos == 10
        assert g.dependencias_vigiladas == ["SECRETARIA DE SALUD"]
        assert g.obligaciones_vigentes == ["NOM-137-SSA1-2008"]

    def test_campos_faltantes_usan_default(self, tmp_path):
        ruta = tmp_path / "giro.yaml"
        ruta.write_text("nombre: Mínimo\n", encoding="utf-8")
        g = cargar_giro(ruta)
        assert g.descripcion == ""
        assert g.dependencias_vigiladas == []
        assert g.palabras_clave == []
        assert g.max_candidatos == 25

    def test_yaml_vacio_no_truena(self, tmp_path):
        ruta = tmp_path / "giro.yaml"
        ruta.write_text("", encoding="utf-8")
        g = cargar_giro(ruta)
        assert g.nombre == "Sin nombre"
