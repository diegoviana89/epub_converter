FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

COPY --chmod=a+rX pdf2epub ./pdf2epub
COPY --chmod=a+rX web ./web

RUN useradd --create-home app
USER app

ENV PORT=8000 MAX_MB=50 MAX_PAGES=800 OCR=0
EXPOSE 8000
CMD gunicorn -w ${WORKERS:-2} -t 600 -b 0.0.0.0:${PORT} web.app:app
