# Despliegue: API en Cloud Run y página en Cloudflare Pages

```
Navegador ──► Cloudflare Pages (index.html, config.js, logos)        gratis, sin límite de tráfico
    │
    └──── POST /api/convert ──► Cloud Run (Flask + Gunicorn)          se paga por segundo de conversión
```

- **La página** (`web/static/`) se publica como sitio estático en Cloudflare Pages. Su `config.js` lleva la
  URL de la API y los límites, así que una visita no llama a Cloud Run: solo lo despierta una conversión.
- **La API** se despliega en Cloud Run a partir del `Dockerfile`. Escala a cero: sin conversiones no hay gasto.
- La página llama a la API desde otro dominio, así que la API solo responde con CORS a los orígenes de
  `ALLOWED_ORIGINS`.

Todo se configura en [`deploy/config.env`](deploy/config.env) y se publica con dos scripts.

## Antes de empezar (una sola vez)

1. **Google Cloud**
   - Crea un proyecto en <https://console.cloud.google.com> y asócialo a una cuenta de facturación
     (Cloud Run lo exige aunque el uso quede dentro de la capa gratuita).
   - Instala la CLI `gcloud` (<https://cloud.google.com/sdk/docs/install>) e inicia sesión:
     ```bash
     gcloud auth login
     ```
   - **Pon una alerta de presupuesto**: consola → Facturación → Presupuestos y alertas → p. ej. 5 USD/mes.
     Solo avisa, no corta el servicio; el tope real de gasto lo pone `MAX_INSTANCES`.
2. **Cloudflare**
   - Crea una cuenta en <https://dash.cloudflare.com> e instala Node.js (para `npx`).
   - Inicia sesión y crea el proyecto de Pages (sustituye `epubtailor` si cambias `PAGES_PROJECT`):
     ```bash
     npx wrangler@4.141.0 login
     npx wrangler@4.141.0 pages project create epubtailor --production-branch main
     ```
     Si el nombre ya está cogido, elige otro y ponlo en `PAGES_PROJECT` y en `ALLOWED_ORIGINS`.
3. **Edita `deploy/config.env`**: como mínimo `PROJECT_ID`, y comprueba que `ALLOWED_ORIGINS` contiene
   `https://<PAGES_PROJECT>.pages.dev`.

## Publicar

```bash
deploy/cloudrun.sh            # 1. API: construye la imagen con Cloud Build y la despliega (5–10 min la 1.ª vez)
deploy/cloudflare-pages.sh    # 2. Página: genera dist/pages/ con la URL de la API y la sube
```

El orden importa la primera vez: el segundo script le pide a `gcloud` la URL del servicio de Cloud Run.
Después, cada script se puede repetir por separado (cambios en la página → solo el 2; en el código → solo el 1).

La primera vez, `gcloud` puede preguntar si crear el repositorio de imágenes de Artifact Registry: responde que sí.

Para revisar la página sin publicarla: `SOLO_GENERAR=1 deploy/cloudflare-pages.sh` y abre `dist/pages/`.

## Configuración de Cloud Run y por qué

| Ajuste | Valor | Motivo (datos de RENDIMIENTO.md) |
|---|---|---|
| `--cpu` | `1` | La conversión usa un solo núcleo; más vCPU no la aceleran |
| `--memory` | `2Gi` | Pico medido de ~570 MiB en el contenedor. Con 2 GiB la capa gratis de memoria (360.000 GiB-s) dura lo mismo que la de CPU (180.000 vCPU-s) |
| `--concurrency` / `WORKERS` | `1` / `1` | Una conversión por instancia: nadie espera detrás de un libro largo |
| `--max-instances` | `3` | Tope de conversiones a la vez y, por tanto, del gasto |
| `--min-instances` | `0` | Escala a cero. El precio: unos segundos de arranque en frío en la primera conversión |
| `--timeout` | `600` | Igual que el timeout de Gunicorn; un libro de 800 páginas tarda ~2–3 min |
| `MAX_MB` | `30` | Cloud Run rechaza peticiones de más de 32 MiB por HTTP/1 |
| `OCR` | `0` | OCR desactivado (decisión del 13/10/2026). Tesseract sigue en la imagen |

La respuesta con el EPUB se envía por partes (`Transfer-Encoding: chunked`), así que los EPUB de más de
32 MiB (p. ej. libros con muchas fotos) sí se pueden descargar.

**Coste orientativo** (precios de cloud.google.com/run/pricing, octubre de 2026): la capa gratis mensual
da 180.000 vCPU-s, unas 1.000 conversiones de libros de 600 páginas o unas 16.000 de 50 páginas, suponiendo
que la nube sea 1,5–2× más lenta que el portátil de la prueba (no medido). Cloud Build y Artifact Registry
(construir y guardar la imagen) pueden añadir algún céntimo; no se ha comprobado su capa gratis.

## Dominio propio (opcional)

- **Página**: en el panel de Cloudflare → Workers & Pages → el proyecto → *Custom domains*. Añade el dominio
  a `ALLOWED_ORIGINS` (p. ej. `https://epubtailor.pages.dev,https://epubtailor.com`) y vuelve a ejecutar
  `deploy/cloudrun.sh`.
- **API**: puede quedarse en su dirección `*.run.app`; el usuario nunca la ve.
- No actives el proxy de Cloudflare (nube naranja) delante de la API: corta las peticiones a los 100 s.

## Google Search Console (gratis)

`deploy/cloudflare-pages.sh` ya publica lo que necesitan los buscadores:

- `robots.txt` y `sitemap.xml`, con las direcciones de `SITE_URL`.
- Dos páginas HTML: `/` en español y `/en/` en inglés. `deploy/prerender_en.mjs` genera la segunda a partir
  de `web/static/i18n.js` (mismo cambio que hace el navegador, pero ya hecho), para que Google lea el inglés
  sin ejecutar JavaScript. Cada página tiene su `canonical`, enlazadas con `hreflang` (también en el sitemap),
  y datos estructurados JSON-LD `WebApplication`.
- Los botones ES/EN pasan de una a otra. `/` ya no elige idioma según el navegador (Googlebot navega en
  inglés y vería otra cosa que su HTML); quien eligió inglés antes pasa a `/en/`. En local (sin `/en/`) la
  página traduce en el sitio como antes.
- `404.html`: sin él, Cloudflare Pages devuelve la página de inicio con código 200 en cualquier dirección.
- `noindex` en las direcciones secundarias `<versión>.<proyecto>.pages.dev`, para que no compitan con la principal.

Pasos (una sola vez):

1. Entra en <https://search.google.com/search-console> con tu cuenta de Google y añade una propiedad de
   tipo **Prefijo de URL** con `https://epubtailor.pages.dev/`. (La de tipo *Dominio* necesita DNS propio,
   y `pages.dev` no es tuyo.)
2. Elige el método **Etiqueta HTML** y copia la etiqueta `<meta name="google-site-verification" ...>`.
3. Pégala en `GOOGLE_SITE_VERIFICATION` dentro de `deploy/config.env` (sirve el código suelto o la etiqueta
   entera) y publica: `deploy/cloudflare-pages.sh`.
4. Vuelve a Search Console y pulsa **Verificar**. No borres la etiqueta después: Google la comprueba de vez en cuando.
5. En **Sitemaps**, envía `sitemap.xml`.
6. En **Inspección de URLs**, inspecciona `https://epubtailor.pages.dev/` y pulsa **Solicitar
   indexación** (una sola vez al día: la cuota es baja). Si quieres, también `/en/`, al día siguiente.

Google tarda de días a semanas en indexar. Si más adelante usas un dominio propio, cambia `SITE_URL`, crea
una propiedad nueva para ese dominio y añade a `_headers` (en el script) la regla
`https://:project.pages.dev/*` con `X-Robots-Tag: noindex` para que `pages.dev` no compita con él.

## Comprobar que funciona

```bash
curl https://<servicio>.run.app/api/config        # {"max_mb":30,"max_pages":800,"ocr":false}
```

Después abre `https://<PAGES_PROJECT>.pages.dev`, convierte `ejemplo/sample.pdf` y comprueba que se descarga
el EPUB. Si la página dice que se perdió la conexión con el servidor, lo más probable es que su dominio no
esté en `ALLOWED_ORIGINS`.

Registros del servicio: consola → Cloud Run → `epubtailor-api` → Registros, o
`gcloud run services logs read epubtailor-api --region us-east1`.

## Desplegar en un VPS en vez de Cloud Run

El mismo `Dockerfile` sirve para un VPS (página y API juntas en el mismo servidor). Ahí no hacen falta
`config.js` ni CORS, y `MAX_MB` puede seguir en 50:

```bash
docker build -t pdf2epub-web:latest .
docker run -d --name pdf2epub --restart unless-stopped -p 8000:8000 pdf2epub-web:latest
```

Pon delante un proxy con HTTPS (p. ej. Caddy) y, si usas Cloudflare, sin el proxy activo por el corte de 100 s.
