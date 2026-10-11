"""Estructuras de datos compartidas."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Opts:
    mode: str = "reflow"          # reflow | pages
    tables: str = "image"         # image | html
    ocr: bool = False
    ocr_lang: str = "spa+eng"
    fallback: bool = True         # páginas ilegibles/escaneadas -> imagen de página
    keep_headers: bool = False    # conservar cabeceras/pies repetidos
    jpeg_quality: int = 85
    max_image_px: int = 1800
    page_dpi: int = 200
    lang: str | None = None
    title: str | None = None
    author: str | None = None


@dataclass
class Asset:
    name: str
    data: bytes
    media: str
    w: int
    h: int


@dataclass
class Block:
    kind: str                      # p | h | img | table | pageimg | fn
    html: str = ""
    text: str = ""
    level: int = 0
    page: int = 0
    cls: str = ""
    asset: int = -1
    caption: str = ""              # html del pie de figura
    cap_top: bool = False
    id: str = ""
    hkey: tuple | None = None
    width_pct: int = 100
    alt: str = ""
