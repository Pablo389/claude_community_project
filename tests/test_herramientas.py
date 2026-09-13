"""herramientas.py: la clase Registro, guardarraíl real de R16.

`buscar_historico` y `leer_candidata` viven detrás de un servidor MCP y no se
prueban aquí (arrancar el protocolo MCP para una prueba unitaria no vale la
complejidad); lo que sí se prueba es `Registro`, que es donde vive la decisión
dura: qué frase cuenta como "literal" y qué `cod_nota` cuenta como "visto".
"""

from __future__ import annotations

from vigilante.dof_api import Coincidencia, TextoNota
from vigilante.herramientas import Registro, _mensaje_sin_texto


def _coincidencia(cod_nota=1, titulo="T", fecha="01-01-2020", dependencia="X") -> Coincidencia:
    return Coincidencia(cod_nota=cod_nota, titulo=titulo, fecha=fecha, dependencia=dependencia)


def _sin_texto(existe_doc=False, existe_imagen=False, existe_pdf=False) -> TextoNota:
    return TextoNota(texto="", disponible=False, existe_doc=existe_doc,
                      existe_imagen=existe_imagen, existe_pdf=existe_pdf)


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


class TestMensajeSinTexto:
    """EP-01: el mensaje nunca promete un PDF/imagen que los flags no confirman."""

    def test_sin_ninguna_version_digital(self):
        # Caso real: codNota 4432291 (1917), los tres flags en False.
        mensaje = _mensaje_sin_texto(4432291, _sin_texto())
        assert "existe como" not in mensaje  # no debe prometer nada que no confirmó
        assert "https://sidof.segob.gob.mx/notas/4432291" in mensaje
        assert "ninguna versión digital" in mensaje

    def test_existe_como_pdf(self):
        mensaje = _mensaje_sin_texto(1, _sin_texto(existe_pdf=True))
        assert "existe como PDF" in mensaje

    def test_existe_como_imagen_sin_pdf(self):
        mensaje = _mensaje_sin_texto(1, _sin_texto(existe_imagen=True))
        assert "existe como imagen" in mensaje

    def test_pdf_tiene_prioridad_sobre_imagen_en_el_mensaje(self):
        mensaje = _mensaje_sin_texto(1, _sin_texto(existe_imagen=True, existe_pdf=True))
        assert "existe como PDF" in mensaje
