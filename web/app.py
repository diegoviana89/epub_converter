"""Servidor web: sube un PDF y descarga el EPUB.

Desarrollo:  python -m web.app
Producción:  gunicorn -w 2 -t 600 -b 0.0.0.0:8000 web.app:app
"""
from __future__ import annotations

import io
import logging
import os
import re
import shutil
import tempfile
import unicodedata

import pymupdf
from flask import Flask, jsonify, request, send_file, send_from_directory

from pdf2epub.convert import convert
from pdf2epub.model import Opts

MAX_MB = int(os.environ.get("MAX_MB", "50"))
MAX_PAGES = int(os.environ.get("MAX_PAGES", "800"))
# El OCR está desactivado en el servicio hasta nueva decisión (unos 4 s por página; ver RENDIMIENTO.md).
# Se activa con OCR=1, siempre que Tesseract esté instalado.
OCR_AVAILABLE = os.environ.get("OCR") == "1" and shutil.which("tesseract") is not None

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024
log = logging.getLogger("pdf2epub.web")


def _error(msg: str, code: int = 400):
    return jsonify(error=msg), code


def _safe_name(filename: str) -> str:
    base = os.path.splitext(os.path.basename(filename or ""))[0]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = re.sub(r"[^\w.-]+", "_", base).strip("._")
    return (base or "libro")[:80]


def _text(field: str, limit: int = 200) -> str | None:
    v = (request.form.get(field) or "").strip()
    return v[:limit] or None


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/config")
def config():
    return jsonify(max_mb=MAX_MB, max_pages=MAX_PAGES, ocr=OCR_AVAILABLE)


@app.post("/api/convert")
def api_convert():
    f = request.files.get("pdf")
    if not f or not f.filename:
        return _error("No se ha recibido ningún PDF.")
    name = _safe_name(f.filename)

    mode = request.form.get("mode", "reflow")
    tables = request.form.get("tables", "image")
    if mode not in ("reflow", "pages") or tables not in ("image", "html"):
        return _error("Opciones no válidas.")
    ocr = request.form.get("ocr") == "1"
    if ocr and not OCR_AVAILABLE:
        return _error("El OCR no está disponible en este servidor.")

    opts = Opts(mode=mode, tables=tables, ocr=ocr,
                keep_headers=request.form.get("keep_headers") == "1",
                title=_text("title"), author=_text("author"))

    tmp = tempfile.mkdtemp(prefix="pdf2epub-")
    try:
        pdf_path = os.path.join(tmp, name + ".pdf")
        f.save(pdf_path)
        try:
            with pymupdf.open(pdf_path) as doc:
                if not doc.is_pdf:
                    return _error("El archivo no es un PDF.")
                if doc.needs_pass:
                    return _error("El PDF está protegido con contraseña.")
                if doc.page_count > MAX_PAGES:
                    return _error(f"El PDF tiene {doc.page_count} páginas; el máximo es {MAX_PAGES}.")
        except (pymupdf.FileDataError, RuntimeError):
            return _error("No se pudo abrir el archivo: no es un PDF válido o está dañado.")

        out_path = os.path.join(tmp, name + ".epub")
        try:
            convert(pdf_path, out_path, opts)
        except SystemExit as e:  # convert() informa de errores de usuario con SystemExit
            return _error(str(e), 422)
        except Exception:
            log.exception("Fallo al convertir %s", name)
            return _error("Error interno al convertir el PDF.", 500)

        with open(out_path, "rb") as fh:
            data = io.BytesIO(fh.read())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return send_file(data, mimetype="application/epub+zip", as_attachment=True,
                     download_name=name + ".epub")


@app.errorhandler(413)
def too_large(_):
    return _error(f"El archivo supera el máximo de {MAX_MB} MB.", 413)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(debug=True, port=int(os.environ.get("PORT", "8000")))
