# Conector Chiletrabajos

Extrae ofertas publicadas en **Chiletrabajos.cl** mediante HTML público. No necesita autenticación ni Playwright.

- Búsqueda: `GET /encuentra-un-empleo` con parámetros públicos de texto, fecha y ciudad.
- Los resultados del listado son HTML estático y se paginan de 30 en 30.
- Cada oferta tiene una página de detalle HTML con descripción completa y beneficios.
- `robots.txt` permite el uso general y sólo excluye `/ofertasmuchomas` y `/partners`, rutas que este conector no utiliza.

## Instalación

Desde la raíz del proyecto:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r 2.chiletrabajos/requirements.txt
```

Requiere Python 3.11 o superior. No instalar paquetes globalmente.

## Uso

```bash
.venv/bin/python 2.chiletrabajos/scraper.py \
  --query "desarrollador backend python junior" \
  --location Chile \
  --days 30
```

### Argumentos

| Argumento | Obligatorio | Valor predeterminado | Descripción |
|---|---:|---:|---|
| `--query` | Sí | — | Texto enviado al buscador del portal. |
| `--location` | No | `Chile` | `Chile` busca en todo el país. Una ciudad disponible en el selector del portal usa su filtro oficial. Una ubicación desconocida se filtra localmente. |
| `--days` | No | `30` | Ventana exacta, inclusiva, expresada en días. |
| `--max-results` | No | Sin límite | Máximo de ofertas finales y de páginas de detalle solicitadas. |
| `--delay` | No | `1.5` | Espera mínima entre peticiones, en segundos. Mínimo permitido: 1. |
| `--output-dir` | No | `2.chiletrabajos/results` | Carpeta del JSON fechado. |
| `--help` | No | — | Muestra la ayuda. |

La configuración de red y valores predeterminados está en `2.chiletrabajos/config.json`:

- `base_url`, `location` y `days`.
- `delay_seconds`, `timeout_seconds`, `max_retries` y `backoff_seconds`.
- `user_agent` identificable.
- `output_dir`.

Los argumentos CLI tienen prioridad sobre sus valores equivalentes en el archivo.

## Funcionamiento

1. Construye la búsqueda pública con la palabra clave.
2. Para ventanas de hasta 30 días envía el filtro del portal `fecha=6` (“Hace un mes”).
3. Recorre todas las páginas siguiendo el enlace `rel="next"` hasta la última.
4. Extrae de cada tarjeta el ID, URL, empresa, ciudad, fecha y resumen.
5. Descarta anticipadamente fechas anteriores al día límite.
6. Ordena las candidatas por fecha descendente y solicita cada detalle respetando el delay.
7. Obtiene fecha exacta, empresa, ubicación, categoría, salario, descripción, beneficios y tags.
8. Vuelve a aplicar el filtro exacto de fecha usando el timestamp del detalle.
9. Deduplica por `job_id` o URL y guarda una lista ordenada.

### Normalización específica

- **Fecha:** fechas españolas del listado y timestamp del detalle interpretados en `America/Santiago`, incluyendo cambios de horario de verano.
- **Modalidad:** `remoto`, `híbrido` o `presencial` sólo ante declaraciones explícitas en beneficios o frases como “modalidad híbrida”. Si hay señales contradictorias o no hay datos, queda `null`.
- **Ubicación:** la ciudad informada; para modalidad remota se usa `Remoto`.
- **Salario:** texto tal como aparece en la tabla del detalle. No se convierte ni se inventa moneda o periodicidad.
- **Descripción:** cuerpo completo del aviso, seguido de los beneficios estructurados del portal cuando existen.
- **Tags:** categoría y etiquetas públicas del detalle, sin duplicados.

## Salida

Cada ejecución crea:

```text
2.chiletrabajos/results/chiletrabajos_YYYYMMDDTHHMMSSZ.json
```

Ejemplo:

```text
2.chiletrabajos/results/chiletrabajos_20261116T015853Z.json
```

Es una lista JSON plana. Cada oferta contiene exactamente:

```text
source, job_id, title, company, location, modality, salary,
published_at, url, description, tags, scraped_at
```

No se agregan metadatos de búsqueda. Los valores no disponibles se guardan como `null` y una búsqueda sin coincidencias genera `[]`. El comando imprime únicamente la ruta del archivo por stdout; los logs van por stderr.

## Reintentos, límites y errores

- Delay de al menos 1 segundo entre todas las peticiones, incluidos los detalles.
- Reintentos con backoff para errores de red, `429`, `500`, `502`, `503` y `504`.
- Se respeta `Retry-After`.
- Un error HTTP no recuperable, una respuesta que no sea HTML o un cambio de estructura detienen la ejecución con código distinto de cero.
- No se generan ofertas parciales si falla un detalle.
- No se intentan evadir CAPTCHAs, autenticación, bloqueos ni límites.

## Consolidado

Desde la raíz, después de ejecutar los conectores de la misma búsqueda:

```bash
.venv/bin/python aggregate.py --output jobs.json \
  1.get_on_board/results/get_on_board_YYYYMMDDTHHMMSSZ.json \
  2.chiletrabajos/results/chiletrabajos_YYYYMMDDTHHMMSSZ.json
```

Sustituir los ejemplos por las rutas efectivamente generadas. No usar comodines que mezclen búsquedas históricas.

## Pruebas

Desde la raíz, sin acceso a Internet:

```bash
.venv/bin/python -m unittest discover -s 2.chiletrabajos/tests -v
```

Cubren el `id="buscador"` duplicado del portal, exclusión de ofertas laterales, paginación, fechas españolas y zona horaria, detalles, beneficios, modalidades, salario, tags, filtro de ciudad, fechas exactas, límite de resultados y deduplicación.
