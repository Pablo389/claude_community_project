"""render.py: R15b (un expediente, una sección) y los casos límite del render de Etapa A.

El JSON del agente nunca se prueba aquí formateado por el LLM: se le inyectan
diccionarios de mano para fijar el contrato de `render.py`, que es lo único
que decide cómo se ve el documento final.
"""

from __future__ import annotations

from vigilante.render import a_markdown, a_markdown_antecedentes, a_markdown_expedientes, sin_publicacion


def _expediente(id_, estado, severidad="alta", proxima_fecha_limite=None, **kw) -> dict:
    base = {
        "id": id_,
        "titulo": f"Expediente {id_}",
        "estado": estado,
        "severidad": severidad,
        "categoria": "nom",
        "proxima_fecha_limite": proxima_fecha_limite,
        "eventos": [{"fecha": "01-01-2026", "cod_nota": 1, "que_paso": "algo"}],
        "primer_evento_observado": "01-01-2026",
    }
    base.update(kw)
    return base


class TestSeccionUnica:
    """Un expediente aparece en exactamente una de las tres secciones (R15b)."""

    def test_abierto_con_plazo_va_solo_en_accion_con_fecha(self):
        estado = {
            "expedientes": [_expediente("e1", "abierto", proxima_fecha_limite="2026-09-01")],
            "vencimientos": [{"fecha_limite": "2026-09-01", "dias_restantes": 5}],
            "_meta": {},
        }
        md = a_markdown_expedientes(estado)
        assert md.count("Expediente e1") == 1
        seccion_accion = md.split("## En el radar")[0]
        assert "Expediente e1" in seccion_accion

    def test_abierto_sin_plazo_va_solo_en_el_radar(self):
        estado = {
            "expedientes": [_expediente("e2", "abierto", proxima_fecha_limite=None)],
            "vencimientos": [],
            "_meta": {},
        }
        md = a_markdown_expedientes(estado)
        assert md.count("Expediente e2") == 1
        assert "Expediente e2" in md.split("## En el radar")[1].split("## Sin pendiente")[0]

    def test_cerrado_va_solo_en_sin_pendiente(self):
        estado = {
            "expedientes": [_expediente("e3", "cerrado")],
            "vencimientos": [],
            "_meta": {},
        }
        md = a_markdown_expedientes(estado)
        assert md.count("Expediente e3") == 1
        assert "Expediente e3" in md.split("## Sin pendiente")[1]

    def test_ningun_expediente_da_las_tres_secciones_vacias(self):
        estado = {"expedientes": [], "vencimientos": [], "_meta": {}}
        md = a_markdown_expedientes(estado)
        assert "Ningún expediente abierto tiene plazo detectado." in md
        assert "Ningún expediente abierto sin plazo." in md
        assert "Ninguno." in md


class TestRevisarClasificacion:
    """Un `cerrado` con plazo vigente es un error de clasificación (R15b) y debe verse."""

    def test_cerrado_con_plazo_vigente_aparece_en_revisar_clasificacion(self):
        estado = {
            "expedientes": [_expediente("e4", "cerrado", proxima_fecha_limite="2026-09-01")],
            "vencimientos": [{"fecha_limite": "2026-09-01", "dias_restantes": 5}],
            "_meta": {},
        }
        md = a_markdown_expedientes(estado)
        assert "## Revisar la clasificación" in md
        assert "Expediente e4" in md.split("## Revisar la clasificación")[1]

    def test_cerrado_con_plazo_ya_vencido_no_cuenta_como_incoherente(self):
        # dias_restantes < 0 en el barrido: el plazo ya pasó, no hay contradicción viva.
        estado = {
            "expedientes": [_expediente("e5", "cerrado", proxima_fecha_limite="2026-01-01")],
            "vencimientos": [{"fecha_limite": "2026-01-01", "dias_restantes": -10}],
            "_meta": {},
        }
        md = a_markdown_expedientes(estado)
        assert "## Revisar la clasificación" not in md

    def test_sin_incoherencias_no_aparece_la_seccion(self):
        estado = {
            "expedientes": [_expediente("e6", "abierto", proxima_fecha_limite="2026-09-01")],
            "vencimientos": [{"fecha_limite": "2026-09-01", "dias_restantes": 5}],
            "_meta": {},
        }
        md = a_markdown_expedientes(estado)
        assert "## Revisar la clasificación" not in md


class TestAMarkdownDia:
    def test_sin_hallazgos_dice_nada_le_pega(self):
        md = a_markdown({"fecha": "28-08-2026", "giro": "X", "veredicto": "sin_impacto", "hallazgos": []})
        assert "Nada en el Diario de hoy le pega al negocio." in md

    def test_hallazgos_ordenados_por_severidad(self):
        reporte = {
            "fecha": "28-08-2026", "giro": "X", "veredicto": "impacto_alto",
            "hallazgos": [
                {"titulo": "Baja", "severidad": "baja", "cod_nota": 1},
                {"titulo": "Alta", "severidad": "alta", "cod_nota": 2},
            ],
        }
        md = a_markdown(reporte)
        assert md.index("Alta") < md.index("Baja")

    def test_veredicto_desconocido_no_truena(self):
        md = a_markdown({"fecha": "x", "giro": "X", "veredicto": "algo_nuevo", "hallazgos": []})
        assert "algo_nuevo" in md

    def test_fuente_incompleta_aparece_cuando_no_esta_vacia(self):
        reporte = {
            "fecha": "x", "giro": "X", "veredicto": "sin_impacto", "hallazgos": [],
            "_meta": {"fuente_incompleta": [4432291]},
        }
        md = a_markdown(reporte)
        assert "## Fuente incompleta" in md
        assert "4432291" in md

    def test_fuente_incompleta_no_aparece_si_esta_vacia(self):
        reporte = {
            "fecha": "x", "giro": "X", "veredicto": "sin_impacto", "hallazgos": [],
            "_meta": {"fuente_incompleta": []},
        }
        md = a_markdown(reporte)
        assert "## Fuente incompleta" not in md


class TestAMarkdownAntecedentes:
    def _dossier(self, **kw) -> dict:
        base = {
            "titulo": "Un expediente", "expediente_id": "exp-1", "ancla": 100,
            "narrativa": None, "antecedentes": [], "vigente": None,
            "consultas": [], "frases_rechazadas": [], "fuente_incompleta": [],
            "_meta": {},
        }
        base.update(kw)
        return base

    def test_fuente_incompleta_aparece_cuando_no_esta_vacia(self):
        # Caso real: codNota 4432291 (DECRETO Ley Electoral, 1917), sin texto.
        md = a_markdown_antecedentes(self._dossier(fuente_incompleta=[4432291]))
        assert "4432291" in md
        assert "sin texto verificable" in md

    def test_fuente_incompleta_no_aparece_si_esta_vacia(self):
        md = a_markdown_antecedentes(self._dossier(fuente_incompleta=[]))
        assert "sin texto verificable" not in md

    def test_sin_historia_no_truena(self):
        md = a_markdown_antecedentes(self._dossier())
        assert "## Sin historia previa" in md


def test_sin_publicacion_es_estable():
    md = sin_publicacion("01-01-2026", "Mi negocio")
    assert "Mi negocio" in md
    assert "no publicó ediciones" in md
