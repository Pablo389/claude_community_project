"""agente_expedientes.py: los tres pasos deterministas de la Etapa B (R15).

No se prueba el paso 3 (la llamada al modelo): es justo la parte que esta
etapa reduce a lo mínimo. Se prueban la proyección, el barrido de
vencimientos y la validación/enriquecimiento posteriores al modelo, que son
donde vive la garantía R7 (nada se afirma sin respaldo en `salidas/`).
"""

from __future__ import annotations

import json
from datetime import date

from vigilante import agente_expedientes as ae


def _escribir_salida(tmp_path, nombre: str, veredicto: str, hallazgos: list[dict]) -> None:
    (tmp_path / f"{nombre}.json").write_text(
        json.dumps({"fecha": nombre, "veredicto": veredicto, "hallazgos": hallazgos}), encoding="utf-8"
    )


def _hallazgo(cod_nota=1, **kw) -> dict:
    base = {
        "cod_nota": cod_nota,
        "titulo": "Título",
        "dependencia": "SECRETARIA DE SALUD",
        "categoria": "nom",
        "severidad": "alta",
        "fecha_limite": None,
        "que_cambia": "Cambia algo",
        "es_correccion": False,
    }
    base.update(kw)
    return base


class TestConstruirProyeccion:
    def test_lee_todos_los_json_de_salidas_ordenados_por_fecha(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae, "SALIDAS", tmp_path)
        _escribir_salida(tmp_path, "2026-08-28", "impacto_alto", [_hallazgo(1)])
        _escribir_salida(tmp_path, "2026-08-27", "sin_impacto", [])
        dias = ae.construir_proyeccion()
        assert [d["fecha"] for d in dias] == ["2026-08-27", "2026-08-28"]

    def test_solo_proyecta_los_campos_declarados(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae, "SALIDAS", tmp_path)
        _escribir_salida(tmp_path, "2026-08-28", "impacto_alto", [
            _hallazgo(1, campo_extra="no debería sobrevivir")
        ])
        dias = ae.construir_proyeccion()
        assert "campo_extra" not in dias[0]["hallazgos"][0]
        assert set(dias[0]["hallazgos"][0]) == set(ae.CAMPOS_HALLAZGO)

    def test_dia_sin_hallazgos_queda_con_lista_vacia(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae, "SALIDAS", tmp_path)
        _escribir_salida(tmp_path, "2026-08-28", "sin_impacto", [])
        dias = ae.construir_proyeccion()
        assert dias[0]["hallazgos"] == []

    def test_carpeta_vacia_da_lista_vacia(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae, "SALIDAS", tmp_path)
        assert ae.construir_proyeccion() == []

    def test_es_correccion_sobrevive_a_la_proyeccion(self, tmp_path, monkeypatch):
        # EP-02: el flag lo calculó Etapa A; esta etapa solo lo arrastra.
        monkeypatch.setattr(ae, "SALIDAS", tmp_path)
        _escribir_salida(tmp_path, "2026-08-28", "impacto_bajo", [
            _hallazgo(1, es_correccion=True),
        ])
        dias = ae.construir_proyeccion()
        assert dias[0]["hallazgos"][0]["es_correccion"] is True


class TestBarridoVencimientos:
    def test_clasifica_vencido_proximo_y_futuro(self):
        hoy = date(2026, 8, 28)
        proyeccion = [{"fecha": "x", "hallazgos": [
            _hallazgo(1, fecha_limite="2026-08-20"),  # vencido
            _hallazgo(2, fecha_limite="2026-09-05"),  # próximo (8 días)
            _hallazgo(3, fecha_limite="2027-01-01"),  # futuro
        ]}]
        filas = ae.barrido_vencimientos(proyeccion, hoy)
        estados = {f["cod_nota"]: f["estado"] for f in filas}
        assert estados == {1: "vencido", 2: "proximo", 3: "futuro"}

    def test_limite_de_15_dias_es_inclusivo(self):
        hoy = date(2026, 8, 28)
        proyeccion = [{"fecha": "x", "hallazgos": [_hallazgo(1, fecha_limite="2026-09-12")]}]  # +15
        filas = ae.barrido_vencimientos(proyeccion, hoy)
        assert filas[0]["estado"] == "proximo"
        assert filas[0]["dias_restantes"] == 15

    def test_sin_fecha_limite_no_genera_fila(self):
        proyeccion = [{"fecha": "x", "hallazgos": [_hallazgo(1, fecha_limite=None)]}]
        assert ae.barrido_vencimientos(proyeccion, date.today()) == []

    def test_fecha_limite_mal_formada_se_ignora_sin_tronar(self):
        proyeccion = [{"fecha": "x", "hallazgos": [_hallazgo(1, fecha_limite="28-08-2026")]}]  # no ISO
        assert ae.barrido_vencimientos(proyeccion, date.today()) == []

    def test_filas_ordenadas_por_fecha_limite(self):
        proyeccion = [{"fecha": "x", "hallazgos": [
            _hallazgo(1, fecha_limite="2026-12-01"),
            _hallazgo(2, fecha_limite="2026-01-01"),
        ]}]
        filas = ae.barrido_vencimientos(proyeccion, date(2026, 1, 1))
        assert [f["cod_nota"] for f in filas] == [2, 1]


class TestValidarYEnriquecer:
    def test_descarta_eventos_con_cod_nota_inexistente_en_proyeccion(self):
        proyeccion = [{"fecha": "x", "hallazgos": [_hallazgo(1, fecha_limite=None)]}]
        crudos = [{
            "id": "exp-1", "estado": "abierto", "severidad": "alta",
            "eventos": [
                {"fecha": "01-01-2026", "cod_nota": 1, "que_paso": "real"},
                {"fecha": "02-01-2026", "cod_nota": 999, "que_paso": "inventado"},
            ],
        }]
        expedientes = ae._validar_y_enriquecer(crudos, proyeccion)
        assert len(expedientes) == 1
        assert [e["cod_nota"] for e in expedientes[0]["eventos"]] == [1]

    def test_expediente_sin_eventos_validos_se_omite(self):
        proyeccion = [{"fecha": "x", "hallazgos": [_hallazgo(1)]}]
        crudos = [{
            "id": "exp-fantasma", "estado": "abierto", "severidad": "alta",
            "eventos": [{"fecha": "01-01-2026", "cod_nota": 999, "que_paso": "inventado"}],
        }]
        assert ae._validar_y_enriquecer(crudos, proyeccion) == []

    def test_primer_evento_observado_y_proxima_fecha_limite_se_derivan(self):
        proyeccion = [{"fecha": "x", "hallazgos": [
            _hallazgo(1, fecha_limite="2026-05-01"),
            _hallazgo(2, fecha_limite="2026-01-01"),
        ]}]
        crudos = [{
            "id": "exp-1", "estado": "abierto", "severidad": "alta",
            "eventos": [
                {"fecha": "10-02-2026", "cod_nota": 1, "que_paso": "segundo cronológicamente"},
                {"fecha": "05-01-2026", "cod_nota": 2, "que_paso": "primero cronológicamente"},
            ],
        }]
        exp = ae._validar_y_enriquecer(crudos, proyeccion)[0]
        assert exp["primer_evento_observado"] == "05-01-2026"
        assert exp["proxima_fecha_limite"] == "2026-01-01"
        assert exp["historia_completa"] is False

    def test_proxima_fecha_limite_none_si_ningun_evento_tiene_plazo(self):
        proyeccion = [{"fecha": "x", "hallazgos": [_hallazgo(1, fecha_limite=None)]}]
        crudos = [{
            "id": "exp-1", "estado": "cerrado", "severidad": "baja",
            "eventos": [{"fecha": "01-01-2026", "cod_nota": 1, "que_paso": "algo"}],
        }]
        exp = ae._validar_y_enriquecer(crudos, proyeccion)[0]
        assert exp["proxima_fecha_limite"] is None

    def test_orden_final_abiertos_primero_luego_por_severidad(self):
        proyeccion = [{"fecha": "x", "hallazgos": [
            _hallazgo(1), _hallazgo(2), _hallazgo(3),
        ]}]
        crudos = [
            {"id": "b-cerrado-alta", "estado": "cerrado", "severidad": "alta",
             "eventos": [{"fecha": "01-01-2026", "cod_nota": 1, "que_paso": "x"}]},
            {"id": "a-abierto-baja", "estado": "abierto", "severidad": "baja",
             "eventos": [{"fecha": "01-01-2026", "cod_nota": 2, "que_paso": "x"}]},
            {"id": "c-abierto-alta", "estado": "abierto", "severidad": "alta",
             "eventos": [{"fecha": "01-01-2026", "cod_nota": 3, "que_paso": "x"}]},
        ]
        ids = [e["id"] for e in ae._validar_y_enriquecer(crudos, proyeccion)]
        assert ids == ["c-abierto-alta", "a-abierto-baja", "b-cerrado-alta"]


class TestPromptMarcaFeDeErratas:
    """EP-02: la marca `[FE DE ERRATAS]` en el prompt de Etapa B es determinista."""

    def test_hallazgo_correccion_lleva_la_marca(self):
        proyeccion = [{"fecha": "28-08-2026", "veredicto": "impacto_bajo",
                       "hallazgos": [_hallazgo(1, es_correccion=True)]}]
        prompt = ae._prompt(proyeccion)
        assert "[FE DE ERRATAS]" in prompt

    def test_hallazgo_normal_no_lleva_la_marca(self):
        proyeccion = [{"fecha": "28-08-2026", "veredicto": "impacto_bajo",
                       "hallazgos": [_hallazgo(1, es_correccion=False)]}]
        prompt = ae._prompt(proyeccion)
        assert "[FE DE ERRATAS]" not in prompt

    def test_dia_sin_hallazgos_no_truena(self):
        proyeccion = [{"fecha": "28-08-2026", "veredicto": "sin_impacto", "hallazgos": []}]
        prompt = ae._prompt(proyeccion)
        assert "Sin hallazgos ese día." in prompt
