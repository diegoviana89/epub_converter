"""Servidor web: sube un PDF y descarga el EPUB.

Desarrollo:  python -m web.app
Producción:  gunicorn -w 2 -t 600 -b 0.0.0.0:8000 web.app:app  (ver Dockerfile y DESPLIEGUE.md)
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import unicodedata

import pymupdf
from flask import Flask, Response, jsonify, request, send_from_directory

from pdf2epub.convert import convert
from pdf2epub.model import Opts

MAX_MB = int(os.environ.get("MAX_MB", "50"))
MAX_PAGES = int(os.environ.get("MAX_PAGES", "800"))
# El OCR está desactivado en el servicio hasta nueva decisión (unos 4 s por página; ver RENDIMIENTO.md).
# Se activa con OCR=1, siempre que Tesseract esté instalado.
OCR_AVAILABLE = os.environ.get("OCR") == "1" and shutil.which("tesseract") is not None
# Orígenes que pueden llamar a la API desde otro dominio (la página en Cloudflare Pages), separados
# por comas: "https://epubtailor.pages.dev,https://epubtailor.com". Vacío: solo el mismo origen.
ALLOWED_ORIGINS = {o.strip().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()}
CHUNK = 256 * 1024

app = Flask(__name__, static_folder="static", static_url_path="")
# 1 MB de margen para los demás campos del formulario multipart: un PDF de MAX_MB justos no da 413.
app.config["MAX_CONTENT_LENGTH"] = (MAX_MB + 1) * 1024 * 1024
log = logging.getLogger("pdf2epub.web")

# Mensajes de error en español (por defecto) o en inglés (?lang=en, lo envía la página).
MESSAGES = {
    "es": {
        "no_pdf": "No se ha recibido ningún PDF.",
        "bad_opts": "Opciones no válidas.",
        "no_ocr": "El OCR no está disponible en este servidor.",
        "not_pdf": "El archivo no es un PDF.",
        "password": "El PDF está protegido con contraseña.",
        "too_many_pages": "El PDF tiene {pages} páginas; el máximo es {max}.",
        "unreadable": "No se pudo abrir el archivo: no es un PDF válido o está dañado.",
        "internal": "Error interno al convertir el PDF.",
        "too_large": "El archivo supera el máximo de {mb} MB.",
    },
    "en": {
        "no_pdf": "No PDF was received.",
        "bad_opts": "Invalid options.",
        "no_ocr": "OCR isn't available on this server.",
        "not_pdf": "The file isn't a PDF.",
        "password": "The PDF is password-protected.",
        "too_many_pages": "The PDF has {pages} pages; the maximum is {max}.",
        "unreadable": "The file couldn't be opened: it isn't a valid PDF or it's damaged.",
        "internal": "Internal error while converting the PDF.",
        "too_large": "The file is over the {mb} MB limit.",
    },
}
# Errores de usuario de convert() (SystemExit, en español) traducidos al inglés.
CONVERT_ERRORS_EN = {
    "El PDF está protegido con contraseña.": MESSAGES["en"]["password"],
    "No se pudo extraer contenido (¿PDF escaneado? prueba --ocr o --mode pages).":
        "No content could be extracted (is it a scanned PDF?). Try the “pages as images” document type.",
}


def _lang() -> str:
    return "en" if request.args.get("lang") == "en" else "es"


def _error(key: str, code: int = 400, **fmt):
    return jsonify(error=MESSAGES[_lang()][key].format(**fmt)), code


def _safe_name(filename: str) -> str:
    base = os.path.splitext(os.path.basename(filename or ""))[0]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = re.sub(r"[^\w.-]+", "_", base).strip("._")
    return (base or "libro")[:80]


def _text(field: str, limit: int = 200) -> str | None:
    v = (request.form.get(field) or "").strip()
    return v[:limit] or None


@app.after_request
def cors(resp):
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if origin and origin in ALLOWED_ORIGINS and request.path.startswith("/api/"):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Max-Age"] = "86400"
        resp.vary.add("Origin")
    return resp


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
        return _error("no_pdf")
    name = _safe_name(f.filename)

    mode = request.form.get("mode", "reflow")
    tables = request.form.get("tables", "image")
    if mode not in ("reflow", "pages") or tables not in ("image", "html"):
        return _error("bad_opts")
    ocr = request.form.get("ocr") == "1"
    if ocr and not OCR_AVAILABLE:
        return _error("no_ocr")

    opts = Opts(mode=mode, tables=tables, ocr=ocr,
                keep_headers=request.form.get("keep_headers") == "1",
                title=_text("title"), author=_text("author"))

    tmp = tempfile.mkdtemp(prefix="pdf2epub-")
    streaming = False  # si la respuesta lleva el EPUB, el directorio se borra al terminar de enviarlo
    try:
        pdf_path = os.path.join(tmp, name + ".pdf")
        f.save(pdf_path)
        try:
            with pymupdf.open(pdf_path) as doc:
                if not doc.is_pdf:
                    return _error("not_pdf")
                if doc.needs_pass:
                    return _error("password")
                if doc.page_count > MAX_PAGES:
                    return _error("too_many_pages", pages=doc.page_count, max=MAX_PAGES)
        except (pymupdf.FileDataError, RuntimeError):
            return _error("unreadable")

        out_path = os.path.join(tmp, name + ".epub")
        try:
            convert(pdf_path, out_path, opts)
        except SystemExit as e:  # convert() informa de errores de usuario con SystemExit
            msg = str(e)
            return jsonify(error=CONVERT_ERRORS_EN.get(msg, msg) if _lang() == "en" else msg), 422
        except Exception:
            log.exception("Fallo al convertir %s", name)
            return _error("internal", 500)
        os.remove(pdf_path)

        # El EPUB se envía por partes, sin Content-Length (Transfer-Encoding: chunked). Así no se carga
        # entero en memoria y Cloud Run no le aplica su límite de 32 MiB por respuesta.
        resp = Response(_chunks(out_path), mimetype="application/epub+zip")
        resp.headers["Content-Disposition"] = f'attachment; filename="{name}.epub"'
        resp.call_on_close(lambda: shutil.rmtree(tmp, ignore_errors=True))
        streaming = True
        return resp
    finally:
        if not streaming:
            shutil.rmtree(tmp, ignore_errors=True)


def _chunks(path: str):
    with open(path, "rb") as fh:
        while block := fh.read(CHUNK):
            yield block


@app.errorhandler(413)
def too_large(_):
    return _error("too_large", 413, mb=MAX_MB)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(debug=True, port=int(os.environ.get("PORT", "8000")))
