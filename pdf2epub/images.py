"""Renderizado y codificación de imágenes (figuras, tablas, páginas)."""
from __future__ import annotations

import io

import pymupdf
from PIL import Image, ImageChops

from .model import Opts


def _is_gray(img: Image.Image) -> bool:
    if img.mode == "L":
        return True
    small = img.resize((48, 48))
    r, g, b = small.split()
    return (ImageChops.difference(r, g).getbbox() is None
            and ImageChops.difference(g, b).getbbox() is None)


def pixmap_to_image(pix: pymupdf.Pixmap) -> Image.Image:
    if pix.n == 1:
        return Image.frombytes("L", (pix.width, pix.height), pix.samples)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def encode(img: Image.Image, opts: Opts, *, gray16: bool = False,
           prefer_jpeg: bool | None = None) -> tuple[bytes, str, int, int]:
    """Devuelve (bytes, media_type, w, h). Elige JPEG para fotos y PNG para dibujos."""
    if max(img.size) > opts.max_image_px:
        img.thumbnail((opts.max_image_px, opts.max_image_px), Image.LANCZOS)
    if img.mode != "L" and _is_gray(img):
        img = img.convert("L")
    buf = io.BytesIO()
    if gray16 and img.mode == "L":
        # Los Kindle E-Ink muestran 16 grises: PNG nítido y pequeño para texto
        img = img.point(lambda p: (p // 16) * 17)
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue(), "image/png", *img.size
    few_colors = img.getcolors(maxcolors=4096) is not None
    use_jpeg = (not few_colors) if prefer_jpeg is None else prefer_jpeg
    if use_jpeg:
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")
        img.save(buf, "JPEG", quality=opts.jpeg_quality, optimize=True)
        return buf.getvalue(), "image/jpeg", *img.size
    if img.mode == "RGB" and img.getcolors(maxcolors=256) is not None:
        img = img.convert("P", palette=Image.ADAPTIVE, colors=256)
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue(), "image/png", *img.size


def render_clip(page: pymupdf.Page, rect: pymupdf.Rect, opts: Opts,
                native_dpi: float | None = None):
    """Renderiza una región de la página tal como se ve (máscaras, recortes y vectores incluidos)."""
    rect = (rect + (-1, -1, 1, 1)) & page.rect
    if rect.is_empty:
        return None
    dpi = min(300.0, max(150.0, native_dpi or 220.0))
    px_w = rect.width / 72 * dpi
    if px_w > opts.max_image_px:
        dpi *= opts.max_image_px / px_w
    pix = page.get_pixmap(clip=rect, dpi=int(dpi), alpha=False, colorspace=pymupdf.csRGB)
    return encode(pixmap_to_image(pix), opts)


def render_page(page: pymupdf.Page, opts: Opts, has_photos: bool):
    pix = page.get_pixmap(dpi=int(opts.page_dpi), alpha=False, colorspace=pymupdf.csRGB)
    img = pixmap_to_image(pix)
    if not has_photos:
        img = img.convert("L") if _is_gray(img) else img
        if img.mode == "L":
            return encode(img, opts, gray16=True)
    return encode(img, opts, prefer_jpeg=True)


def render_cover(page: pymupdf.Page, opts: Opts):
    r = page.rect
    dpi = min(200.0, 1600 / r.height * 72)
    pix = page.get_pixmap(dpi=int(dpi), alpha=False, colorspace=pymupdf.csRGB)
    return encode(pixmap_to_image(pix), opts, prefer_jpeg=True)
