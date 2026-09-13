"""agente_antecedentes.py: las partes deterministas de la Etapa C.

El corazón de R16 vive en `_validar`: nada que el DOF no haya devuelto en una
búsqueda sobrevive, sin importar lo que el modelo haya escrito. Se prueba
junto con `ancla` (la llave estable, R15/R14) y `buscar_expediente`.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from vigilante import agente_antecedentes as aa
from vigilante import dof_api
from vigilante.dof_api import Coincidencia
from vigilante.herramientas import Registro


def _expediente(**kw) -> dict:
    base = {
        "id": "exp-1",
        "titulo": "Un asunto",
        "estado": "abierto",
        "eventos": [
            {"fecha": "10-02-2026", "cod_nota": 100, "que_paso": "primero"},
            {"fecha": "05-01-2026", "cod_nota": 50, "que_paso": "segundo por fecha pero listado antes"},
        ],
    }
    base.update(kw)
    return base


def _registro_con(*coincidencias: Coincidencia) -> Registro:
    reg = Registro({0: "texto fuente"})
    reg.registrar(coincidencias)
    return reg


class TestAncla:
    def test_toma_el_primer_evento_de_la_lista(self):
        # `ancla` confía en que la Etapa B ya ordenó eventos: no reordena aquí.
        exp = _expediente()
        assert aa.ancla(exp) == 100

    def test_expediente_sin_eventos_da_none(self):
        assert aa.ancla({"eventos": []}) is None
        assert aa.ancla({}) is None


class TestBuscarExpediente:
    def test_encuentra_por_slug(self):
        expedientes = [_expediente(id="a"), _expediente(id="b")]
        assert aa.buscar_expediente(expedientes, "b")["id"] == "b"

    def test_encuentra_por_cod_nota_ancla(self):
        expedientes = [_expediente(id="a")]
        assert aa.buscar_expediente(expedientes, "100")["id"] == "a"

    def test_no_encontrado_lanza_con_lista_de_disponibles(self):
        expedientes = [_expediente(id="a")]
        with pytest.raises(LookupError, match=r"no-existe") as exc:
            aa.buscar_expediente(expedientes, "no-existe")
        assert "a (100)" in str(exc.value)


class TestCargarExpedientes:
    def test_sin_archivo_lanza_con_instruccion(self, tmp_path, monkeypatch):
        monkeypatch.setattr(aa, "ESTADO", tmp_path)
        with pytest.raises(FileNotFoundError, match="expedientes"):
            aa.cargar_expedientes()

    def test_carga_la_lista_de_expedientes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(aa, "ESTADO", tmp_path)
        (tmp_path / "expedientes.json").write_text(
            json.dumps({"expedientes": [_expediente(id="a")]}), encoding="utf-8"
        )
        assert aa.cargar_expedientes()[0]["id"] == "a"


class TestTextosFuente:
    """EP-01: `_textos_fuente` cae a solo-título y registra `fuente_incompleta`
    cuando `texto_nota` devuelve `disponible=False` o falla."""

    def test_disponible_incluye_texto_completo(self, monkeypatch):
        monkeypatch.setattr(
            aa.dof_api, "texto_nota",
            lambda cod: dof_api.TextoNota(texto="cuerpo real", disponible=True,
                                           existe_doc=True, existe_imagen=True, existe_pdf=True),
        )
        textos, incompletos = aa._textos_fuente(_expediente(), {100: "Titulo 100", 50: "Titulo 50"},
                                                 verboso=False)
        assert incompletos == set()
        assert "cuerpo real" in textos[100]
        assert "cuerpo real" in textos[50]

    def test_no_disponible_cae_a_titulo_y_se_registra_incompleto(self, monkeypatch):
        # Caso real: codNota 4432291 (1917), texto vacío.
        monkeypatch.setattr(
            aa.dof_api, "texto_nota",
            lambda cod: dof_api.TextoNota(texto="", disponible=False,
                                           existe_doc=False, existe_imagen=False, existe_pdf=False),
        )
        textos, incompletos = aa._textos_fuente(_expediente(), {100: "Titulo 100", 50: "Titulo 50"},
                                                 verboso=False)
        assert incompletos == {100, 50}
        assert textos[100] == "Titulo 100"

    def test_excepcion_de_red_tambien_cuenta_como_incompleto(self, monkeypatch):
        def falla(cod):
            raise RuntimeError("boom")
        monkeypatch.setattr(aa.dof_api, "texto_nota", falla)
        textos, incompletos = aa._textos_fuente(_expediente(), {100: "Titulo 100", 50: "Titulo 50"},
                                                 verboso=False)
        assert incompletos == {100, 50}
        assert textos[100] == "Titulo 100"

    def test_sin_titulo_ni_texto_el_cod_nota_queda_fuera_de_textos(self, monkeypatch):
        monkeypatch.setattr(
            aa.dof_api, "texto_nota",
            lambda cod: dof_api.TextoNota(texto="", disponible=False,
                                           existe_doc=False, existe_imagen=False, existe_pdf=False),
        )
        textos, incompletos = aa._textos_fuente(_expediente(), {}, verboso=False)
        assert incompletos == {100, 50}
        assert textos == {}


class TestFecha:
    def test_parsea_formato_dof(self):
        assert aa._fecha("28-08-2026") == date(2026, 8, 28)

    def test_invalida_o_ausente_va_al_final(self):
        assert aa._fecha(None) == date.max
        assert aa._fecha("no es una fecha") == date.max


class TestValidar:
    """R16 en Python: la garantía dura de toda la etapa."""

    def test_descarta_cod_nota_que_ninguna_busqueda_devolvio(self):
        registro = _registro_con()  # nada buscado
        crudo = {"antecedentes": [{"cod_nota": 5074071, "papel": "raiz", "nivel": "confirmado"}]}
        resultado = aa._validar(crudo, _expediente(), registro, verboso=False)
        assert resultado["antecedentes"] == []
        assert resultado["sin_historia"] is True

    def test_acepta_cod_nota_que_si_salio_en_una_busqueda(self):
        registro = _registro_con(
            Coincidencia(cod_nota=999, titulo="Antecedente real", fecha="01-01-2000", dependencia="X")
        )
        crudo = {"antecedentes": [{"cod_nota": 999, "papel": "proyecto", "nivel": "confirmado",
                                    "cita": "cita literal"}]}
        resultado = aa._validar(crudo, _expediente(), registro, verboso=False)
        assert len(resultado["antecedentes"]) == 1
        ant = resultado["antecedentes"][0]
        assert ant["titulo"] == "Antecedente real"  # viene del registro, no del modelo
        assert ant["fecha"] == "01-01-2000"
        assert resultado["sin_historia"] is False

    def test_no_duplica_un_evento_que_ya_es_propio_del_expediente(self):
        registro = _registro_con(
            Coincidencia(cod_nota=100, titulo="Evento propio", fecha="10-02-2026", dependencia="X")
        )
        crudo = {"antecedentes": [{"cod_nota": 100, "papel": "raiz", "nivel": "confirmado"}]}
        resultado = aa._validar(crudo, _expediente(), registro, verboso=False)
        assert resultado["antecedentes"] == []

    def test_nivel_invalido_cae_a_probable(self):
        registro = _registro_con(
            Coincidencia(cod_nota=999, titulo="T", fecha="01-01-2000", dependencia="X")
        )
        crudo = {"antecedentes": [{"cod_nota": 999, "papel": "otro", "nivel": "muy_seguro"}]}
        resultado = aa._validar(crudo, _expediente(), registro, verboso=False)
        assert resultado["antecedentes"][0]["nivel"] == "probable"

    def test_cod_nota_no_entero_se_ignora_sin_tronar(self):
        registro = _registro_con()
        crudo = {"antecedentes": [{"cod_nota": "no-es-numero", "nivel": "confirmado"}]}
        resultado = aa._validar(crudo, _expediente(), registro, verboso=False)
        assert resultado["antecedentes"] == []

    def test_antecedentes_ordenados_por_fecha(self):
        registro = _registro_con(
            Coincidencia(cod_nota=1, titulo="Más nuevo", fecha="01-01-2020", dependencia="X"),
            Coincidencia(cod_nota=2, titulo="Más viejo", fecha="01-01-1990", dependencia="X"),
        )
        crudo = {"antecedentes": [
            {"cod_nota": 1, "nivel": "confirmado"},
            {"cod_nota": 2, "nivel": "confirmado"},
        ]}
        resultado = aa._validar(crudo, _expediente(), registro, verboso=False)
        assert [a["cod_nota"] for a in resultado["antecedentes"]] == [2, 1]

    def test_vigente_no_probado_se_descarta(self):
        registro = _registro_con()
        crudo = {"antecedentes": [], "vigente": {"cod_nota": 12345, "por_que": "inventado"}}
        resultado = aa._validar(crudo, _expediente(), registro, verboso=False)
        assert resultado["vigente"] is None

    def test_vigente_probado_se_conserva_con_datos_del_registro(self):
        registro = _registro_con(
            Coincidencia(cod_nota=12345, titulo="La vigente", fecha="01-01-2024", dependencia="X")
        )
        crudo = {"antecedentes": [], "vigente": {"cod_nota": 12345, "por_que": "es la definitiva"}}
        resultado = aa._validar(crudo, _expediente(), registro, verboso=False)
        assert resultado["vigente"]["titulo"] == "La vigente"
        assert resultado["vigente"]["por_que"] == "es la definitiva"

    def test_sin_historia_true_si_no_hay_antecedentes_aunque_el_modelo_diga_false(self):
        registro = _registro_con()
        crudo = {"sin_historia": False, "antecedentes": []}
        resultado = aa._validar(crudo, _expediente(), registro, verboso=False)
        assert resultado["sin_historia"] is True
