# Guía para agentes

Este archivo es la fuente de verdad para agentes de IA que operan este repositorio. El [`README.md`](./README.md) es documentación para personas: no lo uses como instrucciones de tarea.

Contexto mínimo:

- El proyecto busca ofertas en portales chilenos y escribe `jobs.json`.
- Un solo comando (`run_search.py`) ejecuta todos los conectores disponibles.
- Computrabajo está bloqueado por WAF y se omite siempre.
- No se evade ninguna protección anti-bot.

## Protocolo para el agente

### 1. Interpretar la solicitud y preguntar sólo lo que falte

Los datos de la búsqueda son:

| Dato | Obligatorio | Predeterminado | Descripción |
|---|---:|---|---|
| `QUERY` | Sí | — | Puesto, tecnologías o palabras clave del usuario. |
| `DAYS` | No | `30` | Ventana de publicación hacia atrás. |
| `LOCATION` | No | `Chile` | Chile completo o una ciudad/región. |
| `MAX_RESULTS` | No | Sin límite | Máximo **por portal**, no máximo total. |

Reglas para el agente:

1. Si el usuario ya escribió el cargo, por ejemplo “busca trabajo de python backend junior”, usa exactamente `python backend junior` como `QUERY`. **No vuelvas a preguntar el cargo.**
2. No preguntes datos que el usuario ya entregó.
3. Si falta el cargo, pregunta:
   > ¿Qué puesto, tecnologías o palabras clave quieres buscar?
4. Si faltan días, ubicación o límite, haz una sola pregunta agrupada sólo con lo que falte:
   > Antes de ejecutar necesito confirmar:
   > 1. ¿Cuántos días hacia atrás? Por defecto, 30.
   > 2. ¿Todo Chile incluyendo trabajos remotos, o una ciudad/región?
   > 3. ¿Quieres un máximo de resultados por portal? Si no, buscaré sin límite.
5. Si el usuario responde “usa los valores por defecto” o equivalente, usa:
   - `DAYS=30`
   - `LOCATION=Chile`
   - Sin `--max-results`
6. Si el usuario pide un máximo total, aclara que la herramienta limita **por portal** y confirma cómo desea continuar.
7. Pasa la consulta como un único argumento. No la dividas por palabras ni la insertes dentro de código.
8. Informa una sola vez que Computrabajo está bloqueado y se omitirá. No intentes acceder ni preguntes cómo evadirlo.

### 2. Preparar el entorno

Ejecuta siempre desde la raíz del repositorio, la carpeta que contiene `run_search.py`. Comprueba Python y las dependencias:

```bash
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi

if ! .venv/bin/python -c "import requests, bs4"; then
  .venv/bin/python -m pip install -r requirements.txt
fi
```

Se requiere Python 3.11 o superior. No uses el Python global para ejecutar los scrapers.

### 3. Ejecutar la búsqueda completa

Un solo comando ejecuta los conectores disponibles, omite Computrabajo y genera `jobs.json`:

```bash
.venv/bin/python run_search.py \
  --query "python backend junior" \
  --days 30 \
  --location "Chile"
```

Con límite por portal:

```bash
.venv/bin/python run_search.py \
  --query "python backend junior" \
  --days 30 \
  --location "Chile" \
  --max-results 40
```

Advertencias operativas:

- Una búsqueda completa puede tardar **varios minutos**. Configura un timeout de al menos **20 minutos** o ejecútala en segundo plano.
- No ejecutes dos búsquedas completas en paralelo.
- No interrumpas mientras un conector procesa detalles.
- No llames directamente a los scrapers si el orquestador funciona.
- No uses `shell=True` ni construyas comandos concatenando texto del usuario. `run_search.py` ya recibe la consulta de forma segura.

`--max-results N` se aplica a **cada portal disponible**. Por eso el total consolidado puede superar `N`.

### 4. Verificar el resultado

El orquestador devuelve:

- Código `0` si todos los conectores disponibles terminaron y `jobs.json` fue reemplazado.
- Código distinto de `0` si falló un conector disponible. En ese caso **`jobs.json` conserva la búsqueda anterior**.
- La ruta de `jobs.json` por stdout al finalizar.
- Progreso y resumen por stderr.

Al terminar correctamente, revisa en los logs:

- Cantidad por portal.
- Total consolidado.
- Computrabajo omitido por bloqueo.
- Ruta final de `jobs.json`.

No consolides manualmente. No uses `results/*.json` ni mezcles archivos de ejecuciones anteriores. El orquestador sólo incorpora los archivos recién generados.

Si un conector disponible falla:

1. No presentes la búsqueda como exitosa.
2. No reemplaces ni edites `jobs.json` manualmente.
3. Informa el portal y el error mostrado.
4. Reintenta sólo si el error parece transitorio y sin cambiar identidad, proxies ni protecciones.
5. Si el error persiste, detente y repórtalo.

Una búsqueda sin coincidencias no es un fallo: puede producir `[]` y actualizar la web con cero resultados.

### 5. Servir la web

La web es estática y lee `jobs.json`. Primero comprobar si el servidor ya responde:

```bash
curl -fsS http://127.0.0.1:8000/jobs.json > /dev/null
```

Si el comando falla, iniciar el servidor en segundo plano o en una terminal persistente:

```bash
.venv/bin/python -m http.server 8000 --bind 127.0.0.1
```

Luego verificar:

```bash
curl -fsS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/
```

Debe devolver `200`. Abrir o indicar:

```text
http://localhost:8000
```

Reglas:

- No abrir `index.html` con `file://`; el navegador bloqueará `jobs.json`.
- Si el puerto 8000 pertenece a otro servicio, usar 8001 y reportar la URL real.
- No cerrar un servidor que ya estaba funcionando.
- Después de una nueva búsqueda basta recargar la página.

### 6. Informe final obligatorio

Responder usando datos reales del resumen. No inventar cifras:

```text
Búsqueda: <QUERY>
Ventana: últimos <DAYS> días
Ubicación: <LOCATION>

Get on Board: <N>
Chiletrabajos: <N>
Laborum: <N>
Trabajando: <N>
Total consolidado: <N>

Computrabajo: omitido por bloqueo WAF; pendiente para Apify.

JSON: <ruta absoluta de jobs.json>
Web: http://localhost:8000
```

Si hubo un fallo:

```text
La búsqueda no se completó porque <portal> falló: <error>.
jobs.json conserva la búsqueda anterior.
No se presentaron resultados parciales como definitivos.
```

## Contrato de `run_search.py`

`run_search.py` es el punto de entrada recomendado para el agente:

```bash
.venv/bin/python run_search.py \
  --query "desarrollador backend python junior" \
  --days 30 \
  --location "Chile"
```

Argumentos:

| Argumento | Obligatorio | Predeterminado | Descripción |
|---|---:|---:|---|
| `--query` | Sí | — | Texto de búsqueda. |
| `--days` | No | `30` | Días hacia atrás; entero mayor o igual que 1. |
| `--location` | No | `Chile` | Chile o ciudad/región. |
| `--max-results` | No | Sin límite | Máximo por portal. |

Comportamiento:

1. Ejecuta Get on Board, Chiletrabajos, Laborum y Trabajando en ese orden.
2. Omite Computrabajo por bloqueo conocido.
3. Captura la ruta que imprime cada conector y valida que el JSON respete el esquema.
4. Sólo si todos los disponibles terminan correctamente, consolida en `jobs.json`.
5. Deja intacto `jobs.json` ante cualquier fallo.
6. Deduplica dentro de cada fuente y ordena por `published_at` descendente.

## Límites

Ver la sección "Límites y uso responsable" de [`README.md`](./README.md). En resumen: respetar `robots.txt`, no evadir autenticación, CAPTCHA ni bloqueos, y no inventar datos.
