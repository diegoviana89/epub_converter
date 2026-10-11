"""Punto de entrada de alto nivel: convert(pdf, epub, opts)."""
from __future__ import annotations

import logging
import os
import re

import pymupdf

from . import images
from .analyze import analyze
from .epub import detect_lang, finalize_blocks, write_epub
from .model import Opts

log = logging.getLogger("pdf2epub")


def _title_from_name(path: str) -> str:
    return re.sub(r"[_\s]+", " ", os.path.splitext(os.path.basename(path))[0]).strip().title()


def convert(pdf_path: str, out_path: str | None = None, opts: Opts | None = None, progress=None) -> str:
    opts = opts or Opts()
    out_path = out_path or os.path.splitext(pdf_path)[0] + ".epub"
    doc = pymupdf.open(pdf_path)
    if doc.needs_pass:
        raise SystemExit("El PDF está protegido con contraseña.")
    md = doc.metadata or {}
    title = (opts.title or md.get("title") or "").strip()
    if not title or re.search(r"\.(pdf|docx?|indd)$|^microsoft word|^untitled", title, re.I):
        title = _title_from_name(pdf_path)
    author = (opts.author or md.get("author") or "").strip()

    blocks, ctx = analyze(doc, opts, progress)
    blocks = finalize_blocks(blocks)
    if not blocks:
        raise SystemExit("No se pudo extraer contenido (¿PDF escaneado? prueba --ocr o --mode pages).")
    lang = opts.lang or detect_lang(blocks)
    outline = doc.get_toc(simple=True)

    # Portada: página 1 renderizada
    cover = images.render_cover(doc[0], opts)
    chapters, entries = write_epub(out_path, blocks, ctx.assets, outline,
                                   {"title": title, "author": author}, cover, lang)
    log.info("Listo: %s (%d capítulos, %d entradas de índice, %d imágenes, idioma %s)",
             out_path, chapters, entries, len({b.asset for b in blocks if b.asset >= 0}), lang)
    return out_path
