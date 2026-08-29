# Vigilante del DOF

Agente que lee el Diario Oficial de la Federación todos los días, filtra lo que le pega a
un giro concreto (NOMs nuevas, cambios fiscales, comercio exterior) y redacta un reporte
accionable con cita al documento oficial.

Construido con el [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview)
sobre la API pública del SIDOF (Segob).

**La idea de negocio y las reglas técnicas de diseño están en [IDEA.md](IDEA.md). Léelo antes de extender el proyecto.**

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

## Uso

```bash
python -m vigilante dia                            # el DOF de hoy
python -m vigilante dia 28-08-2026                 # una fecha concreta (DD-MM-YYYY)
python -m vigilante dia 28-08-2026 --solo-prefiltro  # ver candidatos sin gastar tokens
python -m vigilante dia 28-08-2026 --modelo claude-sonnet-5
python -m vigilante expedientes                    # Etapa B (pendiente)
```

Cada corrida escribe `salidas/YYYY-MM-DD.json` (datos) y `salidas/YYYY-MM-DD.md` (reporte).

Para vigilar otro negocio, edita `giro.yaml` — o pásale otro con `--giro cliente-b.yaml`.

## Estructura

```
giro.yaml                      Perfil del negocio vigilado: el filtro vive aquí
vigilante/
  dof_api.py                   Cliente de la API del SIDOF  (determinista)
  config.py                    Carga de giro.yaml            (determinista)
  prefiltro.py                 ~80 notas -> ~20 candidatos   (determinista)
  herramientas.py              Servidor MCP: texto_nota, titulos_del_dia
  agente_dia.py                Etapa A: resumen del día
  agente_expedientes.py        Etapa B: continuidad entre días (stub)
  render.py                    JSON del agente -> Markdown
  cli.py                       Comandos
salidas/                       Reportes por día
estado/                        Expedientes acumulados (Etapa B)
```

## Cómo fluye una corrida

```
API del DOF ──► prefiltro ──► agente ──┬──► salidas/YYYY-MM-DD.json
 ~73 notas      ~20 notas      lee 2-5  └──► salidas/YYYY-MM-DD.md
 (Python)       (Python)       textos
                               (Claude)
```

Sin caché, a propósito: el Diario cambia durante el día y esto está pensado para correr
detrás de un cron. Ver la regla R9 en [IDEA.md](IDEA.md).
