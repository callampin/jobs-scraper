# Conector Laborum

Extrae ofertas públicas de **Laborum Chile** usando su API JSON interna, sin autenticación, Playwright ni renderizado de navegador.

- Búsqueda: `POST /api/avisos/searchNormalizado`.
- Detalle: `GET /api/candidates/fichaAvisoNormalizada/{job_id}`.
- Identificador público de sitio requerido por la API: `x-site-id: BMCL`.
- Dominio: `https://www.laborum.cl`.

Las rutas de la API son las mismas que consume el frontend público del portal. No se usan sesiones, cookies privadas, proxies ni mecanismos de evasión.

## Instalación

Desde la raíz del proyecto:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r 4.laborum/requirements.txt
```

Requiere Python 3.11 o superior.

## Uso

```bash
.venv/bin/python 4.laborum/scraper.py \
  --query "desarrollador backend python junior" \
  --location Chile \
  --days 30
```

### Argumentos

| Argumento | Obligatorio | Valor predeterminado | Descripción |
|---|---:|---:|---|
| `--query` | Sí | — | Texto enviado a la búsqueda de Laborum. |
| `--location` | No | `Chile` | `Chile` incluye todo el país. Otra ciudad o región se compara localmente con los campos de ubicación. |
| `--days` | No | `30` | Ventana exacta, inclusiva, en días. |
| `--max-results` | No | Sin límite | Máximo de ofertas finales y detalles solicitados. |
| `--delay` | No | `2.0` | Espera mínima entre peticiones. No admite menos de 1 segundo. |
| `--output-dir` | No | `4.laborum/results` | Carpeta del JSON fechado. |
| `--help` | No | — | Muestra la ayuda. |

Configuración en `4.laborum/config.json`:

- `base_url`, `site_id`, `search_path` y `detail_path`.
- `page_size` (máximo 100).
- `location` y `days` predeterminados.
- `delay_seconds`, `timeout_seconds`, `max_retries` y `backoff_seconds`.
- `user_agent` identificable.
- `output_dir`.

Los argumentos CLI tienen prioridad sobre sus equivalentes del archivo.

## Funcionamiento

1. Envía `POST /api/avisos/searchNormalizado` con `pageSize=100` y páginas 0-based.
2. Incluye `query` y, cuando la ventana es de hasta 31 días, un filtro público de fecha:
   - Hasta 3, 4, 5 o 6 días.
   - Hasta una semana.
   - Hasta 15 días.
   - Hasta un mes.
3. Recorre todas las páginas según `total` de la API.
4. Filtra por país, ubicación solicitada y fecha preliminar del listado.
5. Ordena candidatas por fecha descendente.
6. Solicita el detalle normalizado de cada oferta, respetando el delay.
7. Descarta ofertas inactivas, fechas fuera de la ventana exacta o ubicación no coincidente.
8. Deduplica por `job_id` o URL y guarda una lista ordenada.

### Normalización

- **Fecha:** `fechaHoraPublicacion` con zona `America/Santiago`; se entrega en ISO 8601 UTC.
- **Empresa:** denominación pública; si el portal la declara confidencial y no entrega nombre, se usa `"Confidencial"`.
- **Ubicación:** ciudad y región del detalle. Una oferta remota usa `"Remoto"`.
- **Modalidad:** valor estructurado `modalidadTrabajo`: `Remoto`, `Híbrido` o `Presencial`. Desconocida queda `null`.
- **Salario:** mínimos/máximos, tipo y frecuencia estructurados. Ejemplo: `$ 1.200.000 - $ 2.000.000 (BRUTO, por Mes)`. No se añade una moneda que la API no informa.
- **Descripción:** HTML completo del aviso; se agregan los beneficios normalizados bajo una sección `Beneficios`.
- **Tags:** área, subárea y conocimientos estructurados, sin duplicados.
- **URL:** ruta canónica `seoFriendlyUrl` del detalle.

## Salida

```text
4.laborum/results/laborum_YYYYMMDDTHHMMSSZ.json
```

Ejemplo real:

```text
4.laborum/results/laborum_20261116T022357Z.json
```

Es una lista JSON plana. Cada oferta contiene exactamente los 12 campos comunes:

```text
source, job_id, title, company, location, modality, salary,
published_at, url, description, tags, scraped_at
```

Los valores no disponibles quedan en `null`; una búsqueda vacía genera `[]`. El comando imprime únicamente la ruta del archivo por stdout.

## Errores y límites

- Delay mínimo de 1 segundo; valor predeterminado conservador de 2 segundos.
- Reintentos con backoff para errores de red, `429` y `5xx`, respetando `Retry-After`.
- Una página vacía antes de completar `total`, un cambio de esquema, un error HTTP no recuperable o un detalle inválido detienen la ejecución.
- No se generan resultados parciales si el proceso falla.
- No se evaden CAPTCHAs, bloqueos, login ni límites.
- `robots.txt` permite las rutas públicas utilizadas; se respetan sus exclusiones conocidas.

## Consolidado

Desde la raíz, usando las rutas actuales de la misma búsqueda:

```bash
.venv/bin/python aggregate.py --output jobs.json \
  1.get_on_board/results/get_on_board_YYYYMMDDTHHMMSSZ.json \
  2.chiletrabajos/results/chiletrabajos_YYYYMMDDTHHMMSSZ.json \
  4.laborum/results/laborum_YYYYMMDDTHHMMSSZ.json
```

Sustituir los ejemplos por las rutas generadas en la ejecución actual.

## Pruebas

Desde la raíz, sin acceso a Internet:

```bash
.venv/bin/python -m unittest discover -s 4.laborum/tests -v
```

Cubren fechas, filtros públicos, paginación 0-based, salario estructurado, ubicación remota, empresa confidencial, beneficios, tags, ofertas inactivas, límite de resultados y deduplicación.
