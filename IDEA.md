# Vigilante del DOF

## 1. El negocio

### El problema

El Diario Oficial de la Federación publica entre 60 y 120 notas por día hábil.
Ahí salen las NOMs nuevas, las modificaciones fiscales, los cambios a reglas de comercio
exterior y los plazos que obligan a una empresa mexicana. Casi todo es irrelevante para
cualquier empresa concreta, y lo poco que aplica llega sin aviso y con reloj corriendo.

Hoy una PyME resuelve esto de tres formas, todas malas:

- **No lo revisa.** Se enteran cuando llega la multa o cuando un cliente les rechaza
  producto por etiquetado.
- **Le paga a un despacho.** Entre \$8,000 y \$40,000 MXN al mes por un boletín genérico,
  no filtrado por su giro, que igual alguien tiene que leer e interpretar.
- **Alguien interno lo hojea.** 30-60 minutos diarios de una persona que no es abogada,
  con cobertura real cercana a cero.

El costo de fallar no es el tiempo de lectura: es la multa, el producto detenido en aduana
o la línea de negocio que se cae por un registro vencido.

### La propuesta

Un agente que cada día lee el DOF completo, filtra contra el perfil específico de UN negocio
y entrega un reporte accionable: qué se publicó, por qué le pega a este negocio, qué hay que
hacer y para cuándo. Con la cita al documento oficial, siempre.

La diferencia contra un boletín regulatorio no es el resumen. Es que el filtro conoce
tu giro, tus obligaciones vigentes y tus dependencias, y que **descartar es parte del
producto**: un "hoy no te pega nada, revisé 73 publicaciones" entregado con
trazabilidad vale tanto como una alerta.

### A quién le sirve

PyMEs y medianas en sectores regulados donde el DOF es vinculante y el área legal es
una persona o cero personas: importadores y distribuidores (dispositivos médicos, alimentos,
químicos), manufactura sujeta a NOMs, transporte y logística, agroindustria, fintech.
Perfil típico: 20-300 empleados, sin abogado regulatorio de planta.

También sirve, con el mismo motor, a despachos contables y de comercio exterior que quieren
dar este servicio a su cartera: un `giro.yaml` por cliente.

### Por qué ahora

La API del SIDOF (Segob) expone el Diario completo en JSON, gratis y sin llave: el sumario
del día con dependencia y título, y el texto oficial íntegro de cada nota. El insumo
siempre estuvo público; lo que no existía era algo capaz de leer 80 documentos jurídicos
al día y decidir cuáles de ellos le pegan a *tu* CEDIS en Guadalajara.

### Modelo de negocio

Suscripción mensual por perfil vigilado, con precio muy por debajo de la retención de un
despacho. El costo marginal por día es del orden de centavos de dólar. La expansión natural
es más perfiles por cuenta (una empresa con varias razones sociales, un despacho con su
cartera) y la Etapa B como funcionalidad premium.

### Límites honestos

Esto no es asesoría legal y no debe venderse como tal: es *detección y priorización*.
El entregable dice "esto salió, esto parece pegarte, aquí está el documento" y quien
decide sigue siendo la empresa o su abogado. La cobertura es el DOF, no diarios
oficiales estatales ni resoluciones no publicadas.

---

## 2. Reglas técnicas de funcionamiento

Estas son las decisiones de diseño que hay que respetar al extender el proyecto.
No son preferencias de estilo: cada una resuelve un problema concreto.

### R1 — El DOF se lee por API, nunca por búsqueda web

La ingesta es `https://sidof.segob.gob.mx/dof/sidof`, determinista y completa:

| Endpoint | Devuelve |
|---|---|
| `GET /notas/{DD-MM-YYYY}` | sumario del día: `codNota`, `titulo`, `codOrgaDos`, `codSeccion`, edición |
| `GET /notas/nota/{codNota}` | nota completa; el texto oficial viene en `cadenaContenido` como HTML |
| `GET /diarios/porFecha/{DD-MM-YYYY}` | ediciones publicadas (MAT / VES / EXT) |

`WebSearch` existe en el agente **solo para enriquecer** hallazgos ya confirmados
(¿esta NOM venía como proyecto?, ¿cuál era el valor anterior?). Usar búsqueda web
para *descubrir* qué publicó el DOF produce cobertura parcial y afirmaciones inventadas.

Detalles de la fuente que el código ya absorbe: las filas del sumario sin `titulo` son
encabezados de dependencia, no publicaciones. Un día inhábil devuelve `messageCode: 200`
con arreglos vacíos. La URL citable estable es `https://sidof.segob.gob.mx/notas/{codNota}`
(`dof.gob.mx` bloquea peticiones automatizadas).

### R2 — Embudo de tres capas, con el LLM lo más tarde posible

```
API del DOF  ──►  prefiltro determinista  ──►  agente
 ~73 notas         ~15-25 candidatos          lee 2-5 textos completos
 (Python)          (Python)                   (Claude)
```

El prefiltro es Python puro: match de `codOrgaDos` contra `dependencias_vigiladas` y de
título contra `palabras_clave`, menos `palabras_excluidas`. Está calibrado a **recall, no
a precisión**: su trabajo es tirar ruido evidente, no decidir relevancia. Eso lo hace el agente.

### R3 — El prefiltro es auditable por el agente

El agente tiene la herramienta `titulos_del_dia`, que devuelve el sumario completo
incluyendo lo que el prefiltro descartó, para poder rescatar un falso negativo.
Sin esa herramienta, un error del filtro de keywords es invisible y definitivo.

### R4 — El servidor MCP es pasivo; el agente es el que decide

`create_sdk_mcp_server` expone dos funciones de solo lectura (`texto_nota`,
`titulos_del_dia`). No razonan, no se ejecutan solas: el agente las dispara.
Toda la I/O contra el DOF vive en `dof_api.py` y las herramientas solo la envuelven,
para que el pipeline determinista y el agente compartan exactamente el mismo cliente.

### R5 — Superficie de herramientas fija, sin prompts de permiso

`allowed_tools` con la lista exacta + `permission_mode="dontAsk"`: lo que no esté
en la lista se deniega en vez de esperar aprobación. `Bash`, `Write`, `Edit`, `Read`
y `Task` se quitan del contexto con `disallowed_tools`, y `setting_sources=[]` evita que
la configuración del proyecto cambie el comportamiento sin que nadie lo note. Un agente
headless que pregunta es un agente colgado.

### R6 — El agente emite datos; la plantilla emite el documento

El agente termina con un bloque ` ```json ` de esquema fijo (`veredicto`,
`resumen_ejecutivo`, `hallazgos[]`, `revisados_y_descartados[]`) y `render.py` lo
convierte a Markdown. Nunca se le pide Markdown al modelo: si el reporte es JSON,
se puede validar, comparar entre días, filtrar por severidad y alimentar la Etapa B.
Cada corrida guarda ambos: `salidas/YYYY-MM-DD.json` y `.md`.

### R7 — Cada afirmación cita su `codNota`

Regla en el system prompt: no se afirma lo que dice una publicación sin haberla leído
con `texto_nota`, no se inventan fechas ni montos (campo en `null` si el texto no lo dice),
y todo hallazgo lleva el `codNota` que lo respalda. En este producto una alucinación no es
una molestia, es una decisión de negocio equivocada.

### R8 — "Sin impacto" es una respuesta de primera clase

El veredicto `sin_impacto` con `hallazgos: []` es un resultado correcto y frecuente.
El prompt lo dice explícitamente porque el sesgo natural de un LLM es justificar su
existencia inflando el reporte, y ese es el fallo que mata la confianza del usuario.

### R9 — Sin caché: cada corrida vuelve a leer y a razonar el día

El DOF cambia durante el día (la vespertina y las extraordinarias aparecen después),
así que correr dos veces la misma fecha debe volver a golpear la API. La estabilidad
entre corridas se busca por construcción, no por caché: input ordenado por `codNota`,
esquema de salida fijo, y la prosa derivada del JSON. La salida se sobreescribe.

### R10 — Una etapa por archivo, un archivo por etapa

- **Etapa A (`agente_dia.py`)** — autocontenida: ve UNA fecha y el `giro.yaml`, nada más.
  Por eso se puede correr para cualquier día, en cualquier orden, sin estado previo.
- **Etapa B (`agente_expedientes.py`, pendiente)** — lee los `salidas/*.json` de la
  Etapa A, nunca el DOF crudo, y arma expedientes: hilos regulatorios que cruzan
  varios días (proyecto de NOM → respuesta a comentarios → definitiva), plazos
  que se acercan, pendientes sin resolver.

### R11 — La memoria entre días son archivos, no sesiones del SDK

`resume` / `fork_session` sirven para conversaciones. Aquí la continuidad es un
artefacto derivado (`salidas/*.json` → `estado/expedientes.json`): regenerable,
inspeccionable, versionable y sin crecimiento ilimitado de contexto.

### R12 — El `giro.yaml` es el producto

Todo lo específico del negocio vive en ese archivo: dependencias, palabras clave,
obligaciones vigentes. Nada de eso se codifica en Python ni en el prompt. Cambiar el
`giro.yaml` cambia por completo qué considera relevante el sistema, y es lo que
permite un perfil por cliente.

### R13 — Subagentes solo cuando el contexto duela

Hoy corre un solo agente, a propósito. El texto de una nota son 3-45 mil caracteres;
cuando leer 6 u 8 empiece a degradar el resumen final, el paso siguiente es un subagente
`analista` que lea cada nota y devuelva 200 palabras estructuradas, para que el texto
legal completo nunca entre al contexto principal. Antes de eso, es complejidad sin beneficio.

### R14 — La historia profunda se reconstruye del DOF, no de nuestros archivos

Un hilo regulatorio suele tener antecedentes anteriores a que el Vigilante existiera.
Eso no se resuelve acumulando días propios, se resuelve buscando en el histórico del DOF
con `GET /buscarNotas/titulo/{frase}/{pagina}/{limite}/fecha/desc`.

**Se busca por materia, nunca por número de NOM.** Dos razones, ambas verificadas:

- El endpoint hace match de substring y el guion divide en OR: `NOM-253` devuelve 144,835
  resultados y `NOM` 147,788, porque pega dentro de «nombre» y «denominadas».
  Las frases de 2-4 palabras sí discriminan: `sangre humana` devuelve 17.
- **El número cambia a lo largo del hilo.** El mismo asunto fue norma técnica (1986),
  NOM de emergencia SSA 01/92, NOM-003-SSA2-1993, NOM-253-SSA1-2012 y proyecto de
  NOM-253-SSA1-2024. Buscar por número pierde los antecedentes; la materia es estable.

Guardarraíl: la herramienta rechaza la consulta si `totalRegistros > 200` y pide acotar
la frase. El agente se autocorrige sin umbrales escritos en el prompt.

Límite: la búsqueda es solo sobre títulos. Un hilo cuyos títulos no comparten vocabulario
no se enlaza.

### R15 — Recomputar lo barato, cachear lo caro

La Etapa B se recomputa completa en cada corrida (~600 tokens por día de historia: un año
cabe por menos de un dólar), así que no hay fold incremental, ni `dias_procesados`, ni
doble conteo. Es una función pura de `salidas/`.

La investigación de antecedentes es lo contrario: cuesta decenas de llamadas de herramienta
por expediente y su resultado no cambia (la fe de erratas de 1986 seguirá siendo de 1986).
Por eso vive en un comando aparte, `antecedentes`, que persiste en `estado/antecedentes.json`
y el recompute consume como entrada. Meterla dentro del recompute lo convertiría en un loop
agéntico largo que redescubre lo mismo cada día.

---

## 3. Estado actual

| Componente | Estado |
|---|---|
| Cliente de la API del DOF (`dof_api.py`) | Funcionando, verificado contra días hábiles e inhábiles |
| Perfil del giro (`giro.yaml`, `config.py`) | Funcionando |
| Prefiltro determinista (`prefiltro.py`) | Funcionando (73 notas → 14 candidatos en 28-08-2026) |
| Herramientas MCP (`herramientas.py`) | Funcionando |
| Etapa A, agente del día (`agente_dia.py`) | Funcionando |
| Render a Markdown (`render.py`) | Funcionando |
| CLI (`cli.py`) | `dia` funcionando; `expedientes` es stub |
| Etapa B, expedientes | Pendiente. Diseño cerrado: 4 pasos, 1 llamada al modelo (R15) |
| Comando `antecedentes` | Pendiente. Viable y verificado contra el DOF (R14) |
| Entrega (correo / Slack) y cron | Fuera del alcance del MVP |
