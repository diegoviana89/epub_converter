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

# Cabeceras de Cloudflare Pages: config.js sin caché para que un cambio de API se aplique al momento.
cat > "$OUT/_headers" <<'HDR'
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
/config.js
  Cache-Control: no-cache
HDR

echo "Página generada en $OUT/ (API: $API_URL)"
[[ "${SOLO_GENERAR:-0}" == 1 ]] && exit 0

npx --yes wrangler@4.141.0 pages deploy "$OUT" --project-name "$PAGES_PROJECT" --branch main --commit-dirty=true
