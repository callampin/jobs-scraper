# Computrabajo Chile — bloqueado

**Estado: no implementado. Se retomará en la fase de Apify.**

No existe un scraper ejecutable en esta carpeta porque el portal bloquea el acceso desde el entorno del proyecto. No se implementaron proxies, navegadores stealth ni otros mecanismos para evadir la protección.

## Evidencia del bloqueo

Fecha de comprobación: 16 de noviembre de 2026.

Peticiones HTTP normales con User-Agent identificable:

| Ruta | Resultado |
|---|---|
| `https://cl.computrabajo.com/` | `403 Forbidden` |
| `https://cl.computrabajo.com/trabajo-de-python` | `403 Forbidden` |
| `https://cl.computrabajo.com/robots.txt` | `403 Forbidden` |

Características de la respuesta:

- Servidor: `awselb/2.0`.
- Cuerpo HTML de aproximadamente 118 bytes con título `403 Forbidden`.
- El bloqueo ocurre antes de entregar el contenido del portal.
- No es una página con CAPTCHA ni un error de JavaScript.

También se realizó una prueba puntual con **Playwright + Chromium estándar**, sin stealth, proxies ni modificación de fingerprint:

```text
Estado HTTP: 403
Título: 403 Forbidden
URL final: https://cl.computrabajo.com/trabajo-de-python
Contenido renderizado: 117 bytes
```

Playwright no aporta ninguna ventaja porque el bloqueo se produce en el WAF/balanceador del sitio, antes del renderizado.

## Decisión

- No usar Playwright ni solicitudes alternativas para este portal.
- No intentar evadir CAPTCHAs, bloqueos, fingerprints ni límites.
- No generar datos de Computrabajo mientras no exista una vía de acceso autorizada.
- Retomarlo durante la integración con Apify o cuando el portal habilite una API/acceso permitido.

## Impacto

Computrabajo no tiene archivos de resultados y no participa en `jobs.json`. Los demás conectores continúan siendo independientes.

## Al retomarlo

Antes de escribir código, verificar una de estas vías:

1. Acceso autorizado del portal mediante API o token.
2. Actor de Apify aprobado para esta fuente.
3. Una vía de acceso pública que no requiera eludir protecciones.

La salida deberá cumplir exactamente el esquema común de 12 campos y el mismo contrato CLI de los demás conectores.
