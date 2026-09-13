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

### Sobre la autenticación

El SDK no llama a la API directamente: lanza el binario `claude` como subproceso y ese
resuelve las credenciales. Si ya tienes sesión de Claude Code en la máquina, el comando
corre **sin** `ANTHROPIC_API_KEY` usando ese login (Keychain en macOS) y se factura a tu
cuenta. Cómodo para desarrollo local, inservible para lo demás:

- En un servidor, contenedor o CI no hay login interactivo: hace falta la API key.
- Los [términos del Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) prohíben
  que un producto de terceros use login o rate limits de claude.ai. Para operar esto como
  servicio, API key obligatoria.
- Los límites de una suscripción son de uso interactivo; varias corridas seguidas los topan.

`ANTHROPIC_API_KEY` tiene precedencia sobre el login, así que pasar de uno a otro no
requiere tocar código.

## Uso

```bash
python -m vigilante dia                            # el DOF de hoy
python -m vigilante dia 28-08-2026                 # una fecha concreta (DD-MM-YYYY)
python -m vigilante dia 28-08-2026 --solo-prefiltro  # ver candidatos sin gastar tokens
python -m vigilante dia 28-08-2026 --modelo claude-sonnet-5

python -m vigilante expedientes                    # Etapa B: hilos entre días, desde salidas/
python -m vigilante expedientes --solo-proyeccion --hoy 2026-08-29  # sin gastar tokens

python -m vigilante antecedentes                                    # lista los expedientes
python -m vigilante antecedentes suplemento-pnic-2026                # Etapa C: su historia previa
python -m vigilante antecedentes suplemento-pnic-2026 --buscar "Ley de Infraestructura de la Calidad"
```

`dia` escribe `salidas/YYYY-MM-DD.json` (datos) y `salidas/YYYY-MM-DD.md` (reporte). `expedientes`
escribe `estado/expedientes.json` y `.md`. `antecedentes` escribe un dossier por expediente en
`estado/antecedentes/<ancla>.json` y `.md`.

Para vigilar otro negocio, edita `giro.yaml` — o pásale otro con `--giro cliente-b.yaml`.

## Estructura

```
giro.yaml                      Perfil del negocio vigilado: el filtro vive aquí
vigilante/
  dof_api.py                   Cliente de la API del SIDOF  (determinista)
  config.py                    Carga de giro.yaml            (determinista)
  prefiltro.py                 ~80 notas -> ~20 candidatos   (determinista)
  herramientas.py              Servidor MCP: texto_nota, titulos_del_dia, buscar_por_titulo
  agente_dia.py                Etapa A: resumen del día
  agente_expedientes.py        Etapa B: continuidad entre días, sin red ni herramientas
  agente_antecedentes.py       Etapa C: historia previa de un expediente, por búsqueda literal
  render.py                    JSON del agente -> Markdown
  cli.py                       Comandos: dia, expedientes, antecedentes
salidas/                       Reportes por día (Etapa A)
estado/                        expedientes.json/.md (Etapa B) y antecedentes/<ancla>.json/.md (Etapa C)
```

## Cómo fluye una corrida

```
Etapa A (dia)          API del DOF ──► prefiltro ──► agente ──┬──► salidas/YYYY-MM-DD.json
                        ~73 notas      ~20 notas      lee 2-5  └──► salidas/YYYY-MM-DD.md
                        (Python)       (Python)       textos
                                                       (Claude)

Etapa B (expedientes)  salidas/*.json ──► proyección ──► agente ──► estado/expedientes.json/.md
                                          (Python)        1 llamada, sin red

Etapa C (antecedentes) 1 expediente ──► agente busca por título en el histórico ──► estado/antecedentes/<ancla>.json/.md
                                        (Claude + buscar_por_titulo)
```

Sin caché, a propósito: el Diario cambia durante el día y esto está pensado para correr
detrás de un cron. Ver la regla R9 en [IDEA.md](IDEA.md). Cada etapa lee su propia fuente
y tiene su propio permiso de red — ver R10 en [IDEA.md](IDEA.md).
