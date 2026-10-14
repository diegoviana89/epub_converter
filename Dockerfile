FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

COPY pdf2epub ./pdf2epub
COPY web ./web
# chmod en un RUN y no con COPY --chmod: Cloud Build usa el constructor clásico, sin BuildKit.
RUN chmod -R a+rX /app

RUN useradd --create-home app
USER app

ENV PORT=8000 MAX_MB=50 MAX_PAGES=800 OCR=0 ALLOWED_ORIGINS=""
EXPOSE 8000
# exec: Gunicorn recibe directamente las señales de parada (Cloud Run envía SIGTERM).
# --max-requests: cada worker se recicla tras ~20 conversiones y devuelve la memoria (RENDIMIENTO.md §4).
CMD exec gunicorn -w ${WORKERS:-2} -t 600 --max-requests 20 --max-requests-jitter 5 \
    -b 0.0.0.0:${PORT} web.app:app
