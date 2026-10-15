#!/usr/bin/env bash
# Publica la página de inicio en Cloudflare Pages, apuntando a la API de Cloud Run.
# Genera dist/pages/ (copia de web/static con su propio config.js) y la sube con Wrangler.
# Uso: deploy/cloudflare-pages.sh          genera y publica
#      SOLO_GENERAR=1 deploy/cloudflare-pages.sh   solo genera dist/pages/
# Requiere Node.js (para npx) y, la primera vez, `npx wrangler@4.141.0 login`.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.env
OUT="${OUT:-dist/pages}"

if [[ -z "$API_URL" ]]; then
  : "${PROJECT_ID:?Falta PROJECT_ID o API_URL en deploy/config.env}"
  API_URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" \
    --format 'value(status.url)')
fi
[[ "$API_URL" == https://* ]] || { echo "API_URL no válida: '$API_URL'" >&2; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT"
cp -R web/static/. "$OUT/"

# La página lee los límites de aquí en vez de llamar a /api/config: así una visita no despierta Cloud Run.
cat > "$OUT/config.js" <<JS
// Generado por deploy/cloudflare-pages.sh. No editar: se sobrescribe en cada publicación.
window.EPUBTAILOR = {
  api: "${API_URL}",
  limits: { max_mb: ${MAX_MB}, max_pages: ${MAX_PAGES}, ocr: false }
};
JS

# Cabeceras de Cloudflare Pages:
# - config.js sin caché, para que un cambio de API se aplique al momento.
# - noindex en las direcciones secundarias (<versión>.<proyecto>.pages.dev), que repiten la página
#   principal. La dirección principal (<proyecto>.pages.dev) sí se indexa.
cat > "$OUT/_headers" <<'HDR'
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
/config.js
  Cache-Control: no-cache
https://:version.:project.pages.dev/*
  X-Robots-Tag: noindex
HDR

# --- Buscadores ---
SITE="${SITE_URL%/}"
[[ "$SITE" == https://* ]] || { echo "SITE_URL no válida: '$SITE_URL'" >&2; exit 1; }
LASTMOD=$(git log -1 --format=%cs -- web/static 2>/dev/null || true)
LASTMOD="${LASTMOD:-$(date +%F)}"

# Código de Search Console: admite el código suelto o la etiqueta <meta ...> completa.
VERIF="$GOOGLE_SITE_VERIFICATION"
[[ "$VERIF" == *content=* ]] && VERIF=$(sed -E 's/.*content="([^"]*)".*/\1/' <<<"$VERIF")
[[ -z "$VERIF" || "$VERIF" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "GOOGLE_SITE_VERIFICATION no válido: '$VERIF'" >&2; exit 1; }

# La página elige el idioma con ?lang=es|en; sin parámetro, según el navegador (x-default).
SEO_TAGS=$(mktemp)
{
  [[ -n "$VERIF" ]] && echo "<meta name=\"google-site-verification\" content=\"$VERIF\">"
  echo "<meta property=\"og:url\" content=\"$SITE/\">"
  echo "<link rel=\"alternate\" hreflang=\"es\" href=\"$SITE/?lang=es\">"
  echo "<link rel=\"alternate\" hreflang=\"en\" href=\"$SITE/?lang=en\">"
  echo "<link rel=\"alternate\" hreflang=\"x-default\" href=\"$SITE/\">"
} > "$SEO_TAGS"
grep -q '^<!--SEO-->$' "$OUT/index.html" || { echo "Falta la marca <!--SEO--> en index.html" >&2; exit 1; }
awk -v f="$SEO_TAGS" '$0 == "<!--SEO-->" { while ((getline l < f) > 0) print l; next } { print }' \
  "$OUT/index.html" > "$OUT/index.tmp" && mv "$OUT/index.tmp" "$OUT/index.html"
rm -f "$SEO_TAGS"

cat > "$OUT/robots.txt" <<TXT
User-agent: *
Allow: /

Sitemap: $SITE/sitemap.xml
TXT

alternates() {
  echo "    <xhtml:link rel=\"alternate\" hreflang=\"es\" href=\"$SITE/?lang=es\"/>"
  echo "    <xhtml:link rel=\"alternate\" hreflang=\"en\" href=\"$SITE/?lang=en\"/>"
  echo "    <xhtml:link rel=\"alternate\" hreflang=\"x-default\" href=\"$SITE/\"/>"
}
{
  echo '<?xml version="1.0" encoding="UTF-8"?>'
  echo '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">'
  for u in "$SITE/" "$SITE/?lang=es" "$SITE/?lang=en"; do
    echo "  <url>"
    echo "    <loc>$u</loc>"
    echo "    <lastmod>$LASTMOD</lastmod>"
    alternates
    echo "  </url>"
  done
  echo '</urlset>'
} > "$OUT/sitemap.xml"

echo "Página generada en $OUT/ (API: $API_URL; sitio: $SITE; verificación de Google: ${VERIF:-no})"
[[ "${SOLO_GENERAR:-0}" == 1 ]] && exit 0

npx --yes wrangler@4.141.0 pages deploy "$OUT" --project-name "$PAGES_PROJECT" --branch main --commit-dirty=true
