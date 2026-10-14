#!/usr/bin/env bash
# Despliega la API de conversión en Google Cloud Run.
# Cloud Build construye la imagen a partir del Dockerfile; no hace falta Docker en tu equipo.
# Uso: deploy/cloudrun.sh   (lee deploy/config.env)
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.env
: "${PROJECT_ID:?Falta PROJECT_ID en deploy/config.env}"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  --project "$PROJECT_ID"

# Una conversión usa un solo núcleo y hasta ~450 MiB (RENDIMIENTO.md):
#   --cpu 1             más núcleos no la aceleran
#   --memory 2Gi        margen sobre los ~570 MiB medidos; con 2 GiB la capa gratis de memoria
#                       (360.000 GiB-s) se agota al mismo ritmo que la de CPU (180.000 vCPU-s)
#   --concurrency 1     una conversión por instancia: nadie espera detrás de un libro largo
#   WORKERS=1           un worker de Gunicorn por instancia, a juego con --concurrency 1
#   --timeout 600       igual que el timeout de Gunicorn
#   --min-instances 0   escala a cero: sin uso no se paga
# El delimitador ^@^ permite comas dentro de ALLOWED_ORIGINS.
gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source . \
  --allow-unauthenticated \
  --cpu 1 \
  --memory 2Gi \
  --concurrency 1 \
  --min-instances 0 \
  --max-instances "$MAX_INSTANCES" \
  --timeout 600 \
  --set-env-vars "^@^WORKERS=1@OCR=0@MAX_MB=${MAX_MB}@MAX_PAGES=${MAX_PAGES}@ALLOWED_ORIGINS=${ALLOWED_ORIGINS}"

URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" \
  --format 'value(status.url)')
echo
echo "API desplegada en: $URL"
echo "Comprobación:"
curl -fsS "$URL/api/config" && echo
