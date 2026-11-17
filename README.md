# Buscador de ofertas de empleo en Chile

Herramienta local que busca ofertas en varios portales chilenos, las consolida en `jobs.json` y las muestra en una web estática.

<!--
Agentes de IA: este README es documentación para personas. No lo trates como
instrucciones de tarea ni ejecutes sus comandos por iniciativa propia.
La guía operativa está en AGENTS.md.
-->

## Cómo se usa

Abre el proyecto con un agente —opencode, Claude Code o similar— y pídele:

> Lee el README y busca **[puesto de trabajo]** siguiendo el protocolo del agente.

El protocolo está en `AGENTS.md`. El agente instala lo que falte y genera `jobs.json`.

Para ver los resultados en la web, desde la raíz del proyecto:

```bash
.venv/bin/python -m http.server 8000 --bind 127.0.0.1
```

Abre <http://localhost:8000>. No uses `file://`: el navegador bloqueará `jobs.json`.

Si prefieres ejecutarlo a mano, los comandos están en [`AGENTS.md`](./AGENTS.md).

<!--
## Estado de los conectores

| Orden | Portal | Estado | Método |
|---:|---|---|---|
| 1 | Get on Board | **Disponible** | API pública JSON |
| 2 | Chiletrabajos | **Disponible** | HTML estático + detalle |
| 3 | Computrabajo Chile | **Bloqueado** | WAF HTTP 403; se retomará con Apify |
| 4 | Laborum | **Disponible** | API pública JSON interna |
| 5 | Trabajando | **Disponible** | API pública JSON del frontend |

Los conectores disponibles se ejecutan en orden. Computrabajo se omite automáticamente y se informa. Su evidencia está en `3.computrabajo_chile/README.md`. No intentar proxies, stealth, rotación de identidad ni evasión de CAPTCHA.

## Esquema de salida

Tanto los archivos individuales como `jobs.json` son listas JSON. Cada oferta contiene exactamente:

```text
source, job_id, title, company, location, modality, salary,
published_at, url, description, tags, scraped_at
```

- `source`: identificador del portal.
- `modality`: `presencial`, `híbrido`, `remoto` o `null`.
- `published_at` y `scraped_at`: ISO 8601 con zona horaria.
- Los datos no publicados por el portal se representan como `null`; no se inventan.

`jobs.json` contiene únicamente la búsqueda actual. Los archivos fechados dentro de `results/` son historial.

## Web local

La interfaz está en `index.html`, `styles.css` y `app.js`, sin frameworks ni proceso de compilación.

Incluye:

- Búsqueda multitérmino sin distinguir mayúsculas ni tildes.
- Filtros por portal, modalidad, ubicación, empresa, categoría/etiqueta y antigüedad.
- Orden por fecha, cargo o empresa.
- Chips de filtros, descripciones desplegables y enlaces directos.
- Descarga del JSON, estados de carga/error y diseño responsivo.
- Fondo negro, Geist Pixel y Geist Mono.

Atajos: `/` enfoca la búsqueda y `Escape` dentro del campo borra su contenido.

## Referencia de conectores

Esta sección es para mantenimiento o diagnóstico: ejecutar cada conector por separado. Para una búsqueda completa usa `run_search.py`.

### Get on Board

- API pública `/api/v0/search/jobs`; no requiere autenticación.
- Chile incluye remotos disponibles desde Chile.
- Descripción completa desde la API.
- Filtro exacto de fecha, paginación completa y deduplicación.

```bash
.venv/bin/python 1.get_on_board/scraper.py \
  --query "python" --location Chile --days 30
```

### Chiletrabajos

- HTML estático público y página de detalle por oferta.
- Fechas españolas interpretadas en `America/Santiago`.
- Filtro de fecha del portal y validación exacta por detalle.
- Modalidad sólo cuando el sitio la declara explícitamente.

```bash
.venv/bin/python 2.chiletrabajos/scraper.py \
  --query "python" --location Chile --days 30
```

### Computrabajo

Bloqueado por HTTP 403 del WAF. No existe scraper ejecutable. Se retomará en la fase de Apify o con acceso autorizado.

### Laborum

- API pública interna: búsqueda `POST /api/avisos/searchNormalizado`.
- Detalle `GET /api/candidates/fichaAvisoNormalizada/{job_id}`.
- Filtro de fecha y validación exacta posterior.
- Modalidad, salario y beneficios desde campos estructurados.

```bash
.venv/bin/python 4.laborum/scraper.py \
  --query "python" --location Chile --days 30
```

### Trabajando

- Listado `GET /api/searchjob`.
- Detalle `GET /api/ofertas/{id}`.
- Paginación completa y ordenamiento local por fecha.
- `Jornada Completa` no se interpreta como presencial.
- Salario sólo si el portal lo marca visible.

```bash
.venv/bin/python 5.trabajando_cl/scraper.py \
  --query "python" --location Chile --days 30
```

## Pruebas

Sin acceso a Internet:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest discover -s 1.get_on_board/tests -v
.venv/bin/python -m unittest discover -s 2.chiletrabajos/tests -v
.venv/bin/python -m unittest discover -s 4.laborum/tests -v
.venv/bin/python -m unittest discover -s 5.trabajando_cl/tests -v
```

Web:

```bash
node --check app.js
node --test tests/web.test.cjs
```

Las pruebas no son parte de una búsqueda normal; se usan al mantener o modificar la herramienta.

## Estructura

```text
common/                 Utilidades compartidas y esquema
1.get_on_board/         Conector y resultados
2.chiletrabajos/        Conector y resultados
3.computrabajo_chile/   Bloqueo documentado, sin scraper
4.laborum/              Conector y resultados
5.trabajando_cl/        Conector y resultados
run_search.py           Orquestador de búsqueda completa
requirements.txt        Dependencias Python
AGENTS.md               Guía operativa para agentes
aggregate.py            Consolidador de JSON actuales
jobs.json               Datos de la búsqueda actual para la web
index.html              Interfaz web
styles.css              Estilos
app.js                  Filtros e interacción
tests/                  Pruebas del orquestador y la web
```

## Límites y uso responsable

- Respetar `robots.txt`, delays y límites de cada sitio.
- No evadir autenticación, CAPTCHA, bloqueos por fingerprint ni protecciones anti-bot.
- Si un portal bloquea peticiones normales, detenerse y reportarlo.
- No inventar empresa, ubicación, salario, modalidad, fechas ni descripciones.
-->