"""prefiltro.py: el embudo determinista (R2). Calibrado a recall, no a precisión.

Estas pruebas fijan el comportamiento que el commit 47274ab ya corrigió una vez
(match por palabra completa, no por substring) para que no se repita el error.
"""

from __future__ import annotations

from tests.conftest import hacer_nota
from vigilante.prefiltro import prefiltrar


class TestMatchPorDependencia:
    def test_dependencia_vigilada_entra(self, giro):
        nota = hacer_nota(1, "Algo sin palabras clave", dependencia="SECRETARIA DE SALUD")
        candidatos, descartadas = prefiltrar([nota], giro)
        assert len(candidatos) == 1
        assert descartadas == []

    def test_dependencia_no_vigilada_sin_palabra_clave_se_descarta(self, giro):
        nota = hacer_nota(1, "Algo genérico", dependencia="SECRETARIA DE CULTURA")
        candidatos, descartadas = prefiltrar([nota], giro)
        assert candidatos == []
        assert descartadas == [nota]

    def test_match_de_dependencia_ignora_acentos_y_mayusculas(self, giro):
        nota = hacer_nota(1, "Algo", dependencia="secretaría de salud")
        candidatos, _ = prefiltrar([nota], giro)
        assert len(candidatos) == 1


class TestMatchPorPalabraCompleta:
    """El bug que ya se corrigió: `iva` no debe pegar en `privativa`, ni `isr` en un acrónimo."""

    def test_iva_no_pega_en_privativa(self, giro):
        nota = hacer_nota(1, "Sanción privativa de la libertad", dependencia="SECRETARIA DE CULTURA")
        candidatos, descartadas = prefiltrar([nota], giro)
        assert candidatos == []
        assert descartadas == [nota]

    def test_iva_si_pega_como_palabra_suelta(self, giro):
        nota = hacer_nota(1, "Se actualiza la tasa del IVA", dependencia="SECRETARIA DE CULTURA")
        candidatos, _ = prefiltrar([nota], giro)
        assert len(candidatos) == 1
        assert "iva" in candidatos[0].motivos[0]

    def test_clave_con_guion_hace_match_al_final_de_titulo(self, giro):
        # `nom-` termina en no-alfanumérico: el patrón no exige límite de palabra al final.
        nota = hacer_nota(1, "Publicación de la NOM-137-SSA1-2008", dependencia="SECRETARIA DE CULTURA")
        candidatos, _ = prefiltrar([nota], giro)
        assert len(candidatos) == 1


class TestExclusion:
    def test_excluida_gana_aunque_haya_palabra_clave(self, giro):
        nota = hacer_nota(
            1,
            "Convocatoria a concurso para registro sanitario",
            dependencia="SECRETARIA DE SALUD",
        )
        candidatos, descartadas = prefiltrar([nota], giro)
        assert candidatos == []
        assert descartadas == [nota]


class TestPuntajeYRecorte:
    def test_puntaje_suma_dependencia_y_palabras_clave(self, giro):
        nota = hacer_nota(1, "Registro sanitario de dispositivo medico", dependencia="SECRETARIA DE SALUD")
        candidatos, _ = prefiltrar([nota], giro)
        # PESO_DEPENDENCIA (2) + 2 palabras clave * PESO_PALABRA_CLAVE (3) = 8
        assert candidatos[0].puntaje == 8

    def test_recorta_a_max_candidatos_y_lo_demas_va_a_descartadas(self, giro):
        # giro.max_candidatos == 3; metemos 5 notas todas con match.
        notas = [
            hacer_nota(i, "Registro sanitario", dependencia="SECRETARIA DE SALUD")
            for i in range(1, 6)
        ]
        candidatos, descartadas = prefiltrar(notas, giro)
        assert len(candidatos) == 3
        assert len(descartadas) == 2

    def test_candidatos_finales_ordenados_por_cod_nota_no_por_puntaje(self, giro):
        notas = [
            hacer_nota(3, "Registro sanitario", dependencia="SECRETARIA DE SALUD"),
            hacer_nota(1, "Registro sanitario de dispositivo medico", dependencia="SECRETARIA DE SALUD"),
            hacer_nota(2, "Registro sanitario", dependencia="SECRETARIA DE SALUD"),
        ]
        candidatos, _ = prefiltrar(notas, giro)
        assert [c.nota.cod_nota for c in candidatos] == [1, 2, 3]

    def test_descartadas_tambien_ordenadas_por_cod_nota(self, giro):
        notas = [hacer_nota(i, "Sin relevancia", dependencia="SECRETARIA DE CULTURA") for i in (5, 2, 8)]
        _, descartadas = prefiltrar(notas, giro)
        assert [n.cod_nota for n in descartadas] == [2, 5, 8]

    def test_sin_notas_no_truena(self, giro):
        candidatos, descartadas = prefiltrar([], giro)
        assert candidatos == []
        assert descartadas == []
