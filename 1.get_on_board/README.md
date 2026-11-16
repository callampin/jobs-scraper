# Conector Get on Board

Extrae ofertas publicadas en **Get on Board** mediante su API JSON pública. No requiere autenticación, navegador ni Playwright.

- Fuente: `https://www.getonbrd.com/api/v0/search/jobs`
- Cobertura predeterminada: ofertas disponibles para Chile (`country_code=CL`), incluidas las remotas que admiten postulantes desde Chile.
- La API entrega la descripción completa, empresa, tags y ubicación en el listado. No se hace una petición adicional por oferta.

## Instalación

Ejecutar una sola vez desde la raíz del proyecto:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r 1.get_on_board/requirements.txt
```

Requiere Python 3.11 o superior. No instalar paquetes globalmente.

## Uso

Desde la raíz del proyecto:

```bash
.venv/bin/python 1.get_on_board/scraper.py \
  --query "desarrollador backend python junior" \
  --location Chile \
  --days 30
```

La palabra clave se puede escribir libremente; debe ir entre comillas si contiene espacios:

```bash
.venv/bin/python 1.get_on_board/scraper.py --query "backend .NET" --days 30
```

### Argumentos

| Argumento | Obligatorio | Valor predeterminado | Descripción |
|---|---:|---:|---|
| `--query` | Sí | — | Cargo, tecnología o búsqueda libre enviada a la API. |
| `--location` | No | `Chile` | `Chile` incluye ofertas remotas disponibles desde Chile. Una ciudad o región, como `Santiago`, aplica un filtro local adicional y normalmente excluye ofertas sólo remotas. |
| `--days` | No | `30` | Ventana de publicación, inclusiva, desde el inicio de la ejecución. Debe ser al menos 1. |
| `--max-results` | No | Sin límite | Detiene la paginación al obtener ese número de ofertas válidas y únicas. |
| `--delay` | No | `1.5` | Espera mínima entre peticiones, en segundos. No admite menos de 1. |
| `--output-dir` | No | `1.get_on_board/results` | Carpeta donde se guarda el archivo fechado. |
| `--help` | No | — | Muestra la ayuda del comando. |

La configuración de API mantiene los demás valores operativos fuera del código y se puede editar en `1.get_on_board/config.json`:

- `api_url` y `per_page` (entre 1 y 120).
- `location` y `days` predeterminados.
- `delay_seconds`, `timeout_seconds`, `max_retries` y `backoff_seconds`.
- `user_agent` identificable.
- `output_dir`.

Los argumentos de línea de comandos tienen prioridad sobre los valores predeterminados equivalentes.

## Funcionamiento

1. Solicita `/api/v0/search/jobs` con la consulta, `country_code=CL`, paginación y expansión de empresa, tags, ciudades y regiones.
2. Recorre `meta.total_pages`. Si la API no entrega ese valor, continúa hasta una página vacía o una página con menos de `per_page` elementos.
3. Convierte `published_at` desde timestamp Unix a ISO 8601 UTC.
4. Conserva sólo fechas dentro de `[scraped_at - days, scraped_at]`. Las fechas ausentes o inválidas se descartan y se contabilizan.
5. Deduplica por `job_id` o URL.
6. Convierte a texto las secciones HTML de requisitos, funciones, proyecto, condiciones y deseables.
7. Ordena el archivo final por fecha de publicación descendente.

El `source` es siempre `get_on_board`. La modalidad se traduce así:

| API | Salida |
|---|---|
| `no_remote` | `presencial` |
| `hybrid` | `híbrido` |
| `fully_remote` | `remoto` |
| `remote_local` | `remoto` |
| `temporarily_remote`, ausente o desconocida | `null` |

Los salarios publicados por este portal se representan como rango bruto mensual en USD, por ejemplo `USD 2200 - 3500 brutos/mes`. Si no hay valores publicados, se usa `null`.

## Salida

Cada ejecución crea:

```text
1.get_on_board/results/get_on_board_YYYYMMDDTHHMMSSZ.json
```

Ejemplo:

```text
1.get_on_board/results/get_on_board_20261116T010308Z.json
```

La fecha del nombre está en UTC. El contenido es una lista JSON plana en la que cada oferta tiene exactamente estos campos:

```text
source, job_id, title, company, location, modality, salary,
published_at, url, description, tags, scraped_at
```

No se agregan campos de búsqueda ni metadatos al interior del archivo. Al terminar, el comando muestra los logs por stderr e imprime **únicamente la ruta del archivo por stdout**, para que pueda capturarse desde un script o agente.

## Consolidado para la web

Después de ejecutar los conectores de una misma búsqueda, combinar únicamente sus rutas actuales:

```bash
.venv/bin/python aggregate.py --output jobs.json \
  1.get_on_board/results/get_on_board_20261116T010308Z.json
```

Sustituir el ejemplo por la ruta efectivamente generada. No usar comodines que incluyan búsquedas antiguas. `jobs.json` se regenera en cada búsqueda; los archivos individuales fechados permanecen como historial.

## Logs, reintentos y errores

Los logs informan cada página, cuántas ofertas se recibieron y el resumen de guardadas, fuera de fecha, sin fecha, fuera de ubicación, duplicadas e inválidas.

- Reintentos con backoff exponencial para errores de red, `429`, `500`, `502`, `503` y `504`.
- Se respeta `Retry-After` cuando está presente.
- Un error HTTP no recuperable, una respuesta inválida o una página repetida terminan con código de salida distinto de cero.
- Un resultado sin coincidencias no es un error: genera `[]`.
- No se intentan evadir CAPTCHAs, autenticación, límites ni protecciones anti-bot.

## Pruebas

Desde la raíz:

```bash
.venv/bin/python -m unittest discover -s 1.get_on_board/tests -v
```

Las pruebas no requieren acceso a Internet. Cubren normalización, fechas, paginación, límite de resultados, ubicación, duplicados, reintentos HTTP y consolidación del JSON.
