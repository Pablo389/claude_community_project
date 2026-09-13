"""agente_dia.py: solo se prueba el cableado determinista -EP-01
(`fuente_incompleta` en `_meta`) y EP-02 (marca `[FE DE ERRATAS]` en el
prompt)-, no la llamada real al modelo, que es justo lo que esta etapa
delega a Claude.

`servidor_dof` se mockea para poder capturar el `sin_texto: set[int]` que
`_opciones` construye y le pasa; `ejecutar_agente` se mockea para simular
que el tool `texto_nota` lo llenó durante el run, sin correr el agente real.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tests.conftest import hacer_nota
from vigilante import agente_dia
from vigilante.config import Giro
from vigilante.dof_api import DiarioDelDia
from vigilante.prefiltro import Candidato

REPORTE_JSON = '```json\n{"veredicto": "sin_impacto", "hallazgos": []}\n```'


def _candidato(cod_nota=1, titulo="T", es_correccion=False, **kw) -> Candidato:
    return Candidato(
        nota=hacer_nota(cod_nota, titulo, **kw),
        puntaje=5,
        motivos=["palabras clave: x"],
        es_correccion=es_correccion,
    )


def _resultado(**kw) -> SimpleNamespace:
    base = dict(num_turns=1, total_cost_usd=0.01, duration_ms=100, session_id="s1")
    base.update(kw)
    return SimpleNamespace(**base)


def test_fuente_incompleta_se_propaga_a_meta(monkeypatch):
    capturado: dict = {}

    def fake_servidor_dof(sin_texto):
        capturado["sin_texto"] = sin_texto
        return {"type": "sdk", "name": "dof", "instance": None}

    async def fake_ejecutar_agente(prompt, opciones, verboso):
        # Simula que el tool texto_nota encontró codNota 4432291 sin texto
        # disponible durante el run (caso real: DECRETO Ley Electoral, 1917).
        capturado["sin_texto"].add(4432291)
        return REPORTE_JSON, _resultado()

    monkeypatch.setattr(agente_dia, "servidor_dof", fake_servidor_dof)
    monkeypatch.setattr(agente_dia, "ejecutar_agente", fake_ejecutar_agente)

    diario = DiarioDelDia(fecha="28-08-2026", notas=[])
    giro = Giro(nombre="X", descripcion="")

    reporte = asyncio.run(
        agente_dia.analizar_dia(diario, giro, [], modelo="test-model", verboso=False)
    )

    assert reporte["_meta"]["fuente_incompleta"] == [4432291]


def test_sin_notas_sin_texto_da_lista_vacia(monkeypatch):
    def fake_servidor_dof(sin_texto):
        return {"type": "sdk", "name": "dof", "instance": None}

    async def fake_ejecutar_agente(prompt, opciones, verboso):
        return REPORTE_JSON, _resultado()

    monkeypatch.setattr(agente_dia, "servidor_dof", fake_servidor_dof)
    monkeypatch.setattr(agente_dia, "ejecutar_agente", fake_ejecutar_agente)

    diario = DiarioDelDia(fecha="28-08-2026", notas=[])
    giro = Giro(nombre="X", descripcion="")

    reporte = asyncio.run(
        agente_dia.analizar_dia(diario, giro, [], modelo="test-model", verboso=False)
    )

    assert reporte["_meta"]["fuente_incompleta"] == []


def test_cada_corrida_usa_su_propio_set_de_sin_texto(monkeypatch):
    # Dos corridas seguidas no deben compartir estado (R9: sin caché entre runs).
    sets_capturados: list[set[int]] = []

    def fake_servidor_dof(sin_texto):
        sets_capturados.append(sin_texto)
        return {"type": "sdk", "name": "dof", "instance": None}

    async def fake_ejecutar_agente(prompt, opciones, verboso):
        sets_capturados[-1].add(1)
        return REPORTE_JSON, _resultado()

    monkeypatch.setattr(agente_dia, "servidor_dof", fake_servidor_dof)
    monkeypatch.setattr(agente_dia, "ejecutar_agente", fake_ejecutar_agente)

    diario = DiarioDelDia(fecha="28-08-2026", notas=[])
    giro = Giro(nombre="X", descripcion="")

    asyncio.run(agente_dia.analizar_dia(diario, giro, [], modelo="test-model", verboso=False))
    asyncio.run(agente_dia.analizar_dia(diario, giro, [], modelo="test-model", verboso=False))

    assert sets_capturados[0] is not sets_capturados[1]


class TestPromptMarcaFeDeErratas:
    """EP-02: la marca `[FE DE ERRATAS]` en el prompt es puramente determinista."""

    def test_candidato_correccion_lleva_la_marca(self):
        candidatos = [_candidato(1, "Fe de erratas a la NOM-137-SSA1-2008", es_correccion=True)]
        prompt = agente_dia._prompt("28-08-2026", Giro(nombre="X", descripcion=""), candidatos, 10)
        assert "[FE DE ERRATAS]" in prompt

    def test_candidato_normal_no_lleva_la_marca(self):
        candidatos = [_candidato(1, "Registro sanitario de dispositivo medico", es_correccion=False)]
        prompt = agente_dia._prompt("28-08-2026", Giro(nombre="X", descripcion=""), candidatos, 10)
        assert "[FE DE ERRATAS]" not in prompt

    def test_marca_va_junto_al_candidato_correcto_no_a_todos(self):
        candidatos = [
            _candidato(1, "Registro sanitario de dispositivo medico", es_correccion=False),
            _candidato(2, "Fe de erratas a la NOM-137-SSA1-2008", es_correccion=True),
        ]
        prompt = agente_dia._prompt("28-08-2026", Giro(nombre="X", descripcion=""), candidatos, 10)
        assert prompt.count("[FE DE ERRATAS]") == 1
        linea_1 = [l for l in prompt.splitlines() if "codNota 1" in l][0]
        linea_2 = [l for l in prompt.splitlines() if "codNota 2" in l][0]
        assert "[FE DE ERRATAS]" not in linea_1
        assert "[FE DE ERRATAS]" in linea_2
