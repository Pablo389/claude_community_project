"""dof_api.py: cliente del SIDOF. Se mockea httpx.Client — nunca se golpea la red real.

Los fixtures de payload replican la forma exacta documentada en el módulo
(cabeceras de dependencia sin `titulo`, `messageCode` distinto de 200, HTML 4.01 crudo).
"""

from __future__ import annotations

import pytest

from vigilante import dof_api


class _RespuestaFalsa:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _ClienteFalso:
    """Sustituye httpx.Client: registra la ruta pedida y devuelve un payload fijo."""

    def __init__(self, payload: dict | Exception, capturar: list[str] | None = None):
        self._payload = payload
        self._capturar = capturar

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url: str):
        if self._capturar is not None:
            self._capturar.append(url)
        if isinstance(self._payload, Exception):
            raise self._payload
        return _RespuestaFalsa(self._payload)


def _mockear_cliente(monkeypatch, payload, capturar=None):
    monkeypatch.setattr(dof_api.httpx, "Client", lambda **kw: _ClienteFalso(payload, capturar))


class TestHtmlATexto:
    def test_quita_tags_y_colapsa_espacios(self):
        html = "<html><body><p>Hola&nbsp;&nbsp;mundo</p><p>Segundo párrafo</p></body></html>"
        assert dof_api.html_a_texto(html) == "Hola mundo\nSegundo párrafo"

    def test_ignora_script_y_style(self):
        html = "<style>.x{color:red}</style><p>Texto real</p><script>alert(1)</script>"
        assert dof_api.html_a_texto(html) == "Texto real"

    def test_html_vacio_no_truena(self):
        assert dof_api.html_a_texto("") == ""
        assert dof_api.html_a_texto(None) == ""


class TestNotasDelDia:
    def test_filas_sin_titulo_son_encabezados_y_se_descartan(self, monkeypatch):
        payload = {
            "messageCode": 200,
            "NotasMatutinas": [
                {"codNota": 2, "titulo": "", "codOrgaDos": "SECRETARIA DE SALUD"},
                {"codNota": 1, "titulo": "Una nota real", "codOrgaDos": "SECRETARIA DE SALUD"},
            ],
        }
        _mockear_cliente(monkeypatch, payload)
        diario = dof_api.notas_del_dia("28-08-2026")
        assert [n.cod_nota for n in diario.notas] == [1]

    def test_notas_ordenadas_por_cod_nota_entre_ediciones(self, monkeypatch):
        payload = {
            "messageCode": 200,
            "NotasMatutinas": [{"codNota": 5, "titulo": "T5", "codOrgaDos": "X"}],
            "NotasVespertinas": [{"codNota": 1, "titulo": "T1", "codOrgaDos": "X"}],
            "NotasExtraordinarias": [{"codNota": 3, "titulo": "T3", "codOrgaDos": "X"}],
        }
        _mockear_cliente(monkeypatch, payload)
        diario = dof_api.notas_del_dia("28-08-2026")
        assert [n.cod_nota for n in diario.notas] == [1, 3, 5]
        assert [n.edicion for n in diario.notas] == ["VES", "EXT", "MAT"]

    def test_dia_inhabil_sin_notas(self, monkeypatch):
        _mockear_cliente(monkeypatch, {"messageCode": 200})
        diario = dof_api.notas_del_dia("01-01-2026")
        assert diario.notas == []
        assert diario.hubo_publicacion is False

    def test_dependencia_ausente_usa_marcador(self, monkeypatch):
        payload = {"messageCode": 200, "NotasMatutinas": [{"codNota": 1, "titulo": "T"}]}
        _mockear_cliente(monkeypatch, payload)
        diario = dof_api.notas_del_dia("28-08-2026")
        assert diario.notas[0].dependencia == "SIN DEPENDENCIA"

    def test_message_code_distinto_de_200_lanza(self, monkeypatch):
        _mockear_cliente(monkeypatch, {"messageCode": 500, "response": "boom"})
        with pytest.raises(RuntimeError, match="500"):
            dof_api.notas_del_dia("28-08-2026")

    def test_url_publica_es_estable(self):
        nota = dof_api.Nota(
            cod_nota=123, titulo="T", dependencia="D", poder="P",
            edicion="MAT", seccion="1", fecha="28-08-2026",
        )
        assert nota.url == "https://sidof.segob.gob.mx/notas/123"


class TestBuscarPorTitulo:
    def test_frase_vacia_lanza_sin_llamar_a_la_red(self, monkeypatch):
        llamado = []
        _mockear_cliente(monkeypatch, {"messageCode": 200, "Notas": []}, capturar=llamado)
        with pytest.raises(ValueError):
            dof_api.buscar_por_titulo("   ")
        assert llamado == []

    def test_frase_se_url_encodea(self, monkeypatch):
        capturado = []
        _mockear_cliente(monkeypatch, {"messageCode": 200, "totalRegistros": 0, "Notas": []}, capturar=capturado)
        dof_api.buscar_por_titulo("Ley de Infraestructura de la Calidad")
        assert "Ley%20de%20Infraestructura%20de%20la%20Calidad" in capturado[0]

    def test_filtra_filas_sin_cod_nota_o_sin_titulo(self, monkeypatch):
        payload = {
            "messageCode": 200,
            "totalRegistros": 3,
            "Notas": [
                {"codNota": 1, "titulo": "Válida", "fecha": "01-01-2020"},
                {"codNota": None, "titulo": "Sin cod_nota"},
                {"codNota": 2, "titulo": ""},
            ],
        }
        _mockear_cliente(monkeypatch, payload)
        resultado = dof_api.buscar_por_titulo("materia")
        assert [c.cod_nota for c in resultado.coincidencias] == [1]
        assert resultado.total == 3

    def test_total_cae_a_len_coincidencias_si_falta_totalregistros(self, monkeypatch):
        payload = {"messageCode": 200, "Notas": [{"codNota": 1, "titulo": "T", "fecha": "x"}]}
        _mockear_cliente(monkeypatch, payload)
        resultado = dof_api.buscar_por_titulo("materia")
        assert resultado.total == 1


class TestTextoNota:
    def test_nota_inexistente_lanza_lookup_error(self, monkeypatch):
        _mockear_cliente(monkeypatch, {"messageCode": 200, "Nota": None})
        with pytest.raises(LookupError):
            dof_api.texto_nota(999)

    def test_convierte_cadena_contenido_de_html_a_texto(self, monkeypatch):
        payload = {"messageCode": 200, "Nota": {"cadenaContenido": "<p>Texto oficial</p>"}}
        _mockear_cliente(monkeypatch, payload)
        assert dof_api.texto_nota(1) == "Texto oficial"
