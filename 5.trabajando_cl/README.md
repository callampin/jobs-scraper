# Conector Trabajando

Extrae ofertas públicas de **Trabajando.com Chile** mediante los endpoints JSON de su frontend. No requiere autenticación, Playwright ni renderizado de navegador.

- Búsqueda: `GET /api/searchjob`.
- Detalle: `GET /api/ofertas/{id}`.
- Dominio: `https://www.trabajando.cl`.
- Cobertura predeterminada: Chile.

Los endpoints son los mismos que utiliza la web pública. No se usan sesiones, cookies privadas, proxies ni mecanismos de evasión.

## Instalación

Desde la raíz del proyecto:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r 5.trabajando_cl/requirements.txt
```

Requiere Python 3.11 o superior.

## Uso

```bash
.venv/bin/python 5.trabajando_cl/scraper.py \
  --query "desarrollador backend python junior" \
  --location Chile \
  --days 30
```

### Argumentos

| Argumento | Obligatorio | Valor predeterminado | Descripción |
|---|---:|---:|---|
| `--query` | Sí | — | Texto enviado como `cargo` a la búsqueda pública. |
| `--location` | No | `Chile` | `Chile` incluye todo el portal. Otra ciudad/región se filtra localmente sobre `ubicacion`. |
| `--days` | No | `30` | Ventana exacta, inclusiva, en días. |
| `--max-results` | No | Sin límite | Máximo de ofertas finales y detalles solicitados. |
| `--delay` | No | `1.5` | Espera mínima entre peticiones. Mínimo permitido: 1 segundo. |
| `--output-dir` | No | `5.trabajando_cl/results` | Carpeta del JSON fechado. |
| `--help` | No | — | Muestra la ayuda. |

Configuración en `5.trabajando_cl/config.json`:

- `base_url`, `search_path` y `detail_path`.
- `location` y `days` predeterminados.
- `delay_seconds`, `timeout_seconds`, `max_retries` y `backoff_seconds`.
- `user_agent` identificable.
- `output_dir`.

Los argumentos CLI tienen prioridad sobre sus valores equivalentes.

## Funcionamiento

1. Consulta `GET /api/searchjob` con:
   - `palabraClave=`.
   - `cargo=<query>`.
   - `pagina=N`, comenzando en 1.
   - `orden=RANKING`.
   - `tipoOrden=DESC`.
2. Lee `cantidadRegistros`, `cantidadPaginas` y `registrosPorPagina`; recorre todas las páginas declaradas.
3. Extrae ID, título, empresa, jornada, ubicación y fecha de cada tarjeta.
4. Descarta fechas anteriores al día límite y aplica el filtro de ubicación si corresponde.
5. Deduplica candidatas y las ordena por fecha descendente.
6. Consulta `GET /api/ofertas/{id}` para obtener el detalle completo.
7. Descarta ofertas no publicadas, fuera de la ventana exacta o inválidas.
8. Guarda el JSON normalizado y ordenado.

### Normalización

- **Fecha:** `fechaPublicacion` del listado, interpretada en `America/Santiago` y convertida a ISO 8601 UTC.
- **Empresa:** `nombreEmpresaFantasia`; si `ofertaConfidencial=true`, se usa `"Empresa Confidencial"`.
- **Ubicación:** comuna y región. Si la jornada es Teletrabajo, se usa `"Remoto"`.
- **Modalidad:** sólo desde valores explícitos de `nombreJornada`:
  - `Teletrabajo` → `remoto`.
  - `Mixta (Teletrabajo + Presencial)` → `híbrido`.
  - `Jornada Completa` u otros valores no equivalen a presencial: quedan `null`.
- **Salario:** sólo si `mostrarSueldo=true` y `sueldo>0`; incluye el nombre de moneda entregado. Ejemplo: `$ 2.200.000 (Pesos Chilenos)`.
- **Descripción:** HTML completo de `descripcionOferta`, convertido a texto.
- **Tags:** área, categorías y habilidades estructuradas, sin duplicados.
- **URL:** `https://www.trabajando.cl/trabajo/{slug}`.

## Salida

```text
5.trabajando_cl/results/trabajando_cl_YYYYMMDDTHHMMSSZ.json
```

Ejemplo real:

```text
5.trabajando_cl/results/trabajando_cl_20261116T023459Z.json
```

Es una lista JSON plana. Cada oferta contiene exactamente:

```text
source, job_id, title, company, location, modality, salary,
published_at, url, description, tags, scraped_at
```

Los valores no disponibles quedan en `null`; una búsqueda sin coincidencias genera `[]`. El comando imprime únicamente la ruta por stdout.

## Errores y límites

- Delay mínimo de 1 segundo entre todas las peticiones.
- Reintentos con backoff para errores de red, `429` y `5xx`, respetando `Retry-After`.
- Una página vacía antes de completar la paginación declarada, un cambio de esquema o un detalle inválido detienen la ejecución.
- No se generan resultados parciales si el proceso falla.
- No se evaden CAPTCHAs, bloqueos, login ni límites.
- `robots.txt` permite las rutas públicas utilizadas; se respetan sus exclusiones.

## Consolidado

Desde la raíz, usando las rutas actuales de la misma búsqueda:

```bash
.venv/bin/python aggregate.py --output jobs.json \
  1.get_on_board/results/get_on_board_YYYYMMDDTHHMMSSZ.json \
  2.chiletrabajos/results/chiletrabajos_YYYYMMDDTHHMMSSZ.json \
  4.laborum/results/laborum_YYYYMMDDTHHMMSSZ.json \
  5.trabajando_cl/results/trabajando_cl_YYYYMMDDTHHMMSSZ.json
```

Sustituir los ejemplos por las rutas generadas en la ejecución actual.

## Pruebas

Desde la raíz, sin acceso a Internet:

```bash
.venv/bin/python -m unittest discover -s 5.trabajando_cl/tests -v
```

Cubren paginación, fechas, filtro de ubicación, empresa confidencial, modalidad, salario visible/oculto, descripción, tags, ofertas inactivas, fechas exactas, límite de resultados y deduplicación.
