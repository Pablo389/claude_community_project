"""herramientas.py: la clase Registro, guardarraíl real de R16.

`buscar_historico` y `leer_candidata` viven detrás de un servidor MCP y no se
prueban aquí (arrancar el protocolo MCP para una prueba unitaria no vale la
complejidad); lo que sí se prueba es `Registro`, que es donde vive la decisión
dura: qué frase cuenta como "literal" y qué `cod_nota` cuenta como "visto".
"""

from __future__ import annotations

from vigilante.dof_api import Coincidencia
from vigilante.herramientas import Registro


def _coincidencia(cod_nota=1, titulo="T", fecha="01-01-2020", dependencia="X") -> Coincidencia:
    return Coincidencia(cod_nota=cod_nota, titulo=titulo, fecha=fecha, dependencia=dependencia)


class TestEsLiteral:
    def test_frase_presente_en_la_fuente(self):
        reg = Registro({100: "El Programa Nacional de Infraestructura de la Calidad"})
        assert reg.es_literal("Programa Nacional de Infraestructura de la Calidad") is True

    def test_frase_ausente(self):
        reg = Registro({100: "Un texto cualquiera"})
        assert reg.es_literal("Frase que no está") is False

    def test_ignora_acentos_y_mayusculas(self):
        reg = Registro({100: "Reglamento de Tránsito en Carreteras Federales"})
        assert reg.es_literal("reglamento de transito en carreteras federales") is True

    def test_frase_parcial_no_cuenta_si_no_es_substring(self):
        reg = Registro({100: "Ley General de Salud"})
        assert reg.es_literal("Ley General de Salud y Seguridad") is False


class TestRegistrarYConocido:
    def test_cod_nota_visto_queda_conocido(self):
        reg = Registro({0: "x"})
        reg.registrar([_coincidencia(cod_nota=5074071)])
        assert reg.conocido(5074071) is True
        assert reg.conocido(999) is False

    def test_conocido_acepta_string_numerica(self):
        reg = Registro({0: "x"})
        reg.registrar([_coincidencia(cod_nota=42)])
        assert reg.conocido("42") is True

    def test_registrar_no_pisa_la_primera_version_del_cod_nota(self):
        # setdefault: si el mismo cod_nota vuelve a salir en otra búsqueda, se
        # conserva el primer título/fecha vistos, no el más reciente.
        reg = Registro({0: "x"})
        reg.registrar([_coincidencia(cod_nota=1, titulo="Primero")])
        reg.registrar([_coincidencia(cod_nota=1, titulo="Segundo")])
        assert reg.vistos[1]["titulo"] == "Primero"

    def test_nada_visto_al_inicio(self):
        reg = Registro({0: "x"})
        assert reg.vistos == {}
        assert reg.conocido(1) is False
