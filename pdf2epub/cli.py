from __future__ import annotations

import argparse
import logging
import os
import sys

from .convert import convert
from .model import Opts


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="pdf2epub",
        description="Convierte PDF a EPUB (reflowable, justificado, con imágenes ampliables) para Kindle.")
    ap.add_argument("inputs", nargs="+", help="archivos PDF o carpetas que los contengan")
    ap.add_argument("-o", "--output", help="archivo EPUB de salida (solo con un PDF) o carpeta de salida")
    ap.add_argument("--mode", choices=["reflow", "pages"], default="reflow",
                    help="reflow: texto real que se adapta a la pantalla (por defecto). "
                         "pages: cada página como imagen (máxima fidelidad visual, sin reflujo).")
    ap.add_argument("--tables", choices=["image", "html"], default="image",
                    help="tablas como imagen ampliable (por defecto) o como tabla HTML")
    ap.add_argument("--ocr", action="store_true", help="aplicar OCR (Tesseract) a páginas escaneadas")
    ap.add_argument("--ocr-lang", default="spa+eng", help="idiomas de Tesseract (por defecto spa+eng)")
    ap.add_argument("--no-fallback", action="store_true",
                    help="no sustituir por imagen las páginas con texto ilegible")
    ap.add_argument("--keep-headers", action="store_true", help="conservar cabeceras y pies de página")
    ap.add_argument("--title"), ap.add_argument("--author")
    ap.add_argument("--lang", help="código de idioma (es, en, pt...). Por defecto se detecta")
    ap.add_argument("--jpeg-quality", type=int, default=85)
    ap.add_argument("--max-image-px", type=int, default=1800, help="lado máximo de las imágenes")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="%(message)s")
    opts = Opts(mode=a.mode, tables=a.tables, ocr=a.ocr, ocr_lang=a.ocr_lang, fallback=not a.no_fallback,
                keep_headers=a.keep_headers, jpeg_quality=a.jpeg_quality, max_image_px=a.max_image_px,
                lang=a.lang, title=a.title, author=a.author)

    files = []
    for p in a.inputs:
        if os.path.isdir(p):
            files += sorted(os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(".pdf"))
        else:
            files.append(p)
    if not files:
        ap.error("no hay PDFs para convertir")

    def progress(stage, i, n):
        if sys.stderr.isatty():
            print(f"\r  {stage} {i}/{n}", end="", file=sys.stderr, flush=True)
            if i == n:
                print(file=sys.stderr)

    for f in files:
        if len(files) == 1 and a.output and not os.path.isdir(a.output):
            out = a.output
        else:
            base = os.path.splitext(os.path.basename(f))[0] + ".epub"
            out = os.path.join(a.output if a.output else os.path.dirname(os.path.abspath(f)), base)
            os.makedirs(os.path.dirname(out), exist_ok=True)
        print(f"{f} -> {out}")
        convert(f, out, opts, progress)


if __name__ == "__main__":
    main()
