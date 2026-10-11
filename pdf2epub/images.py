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
           prefer_jpeg: bool | None = None, photo_quality: int | None = None) -> tuple[bytes, str, int, int]:
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
        img.save(buf, "JPEG", quality=photo_quality or opts.jpeg_quality, optimize=True)
        return buf.getvalue(), "image/jpeg", *img.size
    if img.mode == "RGB" and img.getcolors(maxcolors=256) is not None:
        img = img.convert("P", palette=Image.ADAPTIVE, colors=256)
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue(), "image/png", *img.size


FIG_DPI = 220.0       # resolución objetivo de figuras: legible al ampliar en un Kindle de 300 ppp


def _target_size(rect: pymupdf.Rect, dpi: float, opts: Opts) -> tuple[int, int]:
    scale = dpi / 72
    w, h = rect.width * scale, rect.height * scale
    k = min(1.0, opts.max_image_px / max(w, h, 1))
    return max(1, round(w * k)), max(1, round(h * k))


def _embedded(page: pymupdf.Page, xref: int) -> Image.Image | None:
    """Píxeles originales de una imagen incrustada (con su máscara aplanada sobre blanco)."""
    doc = page.parent
    try:
        pix = pymupdf.Pixmap(doc, xref)
        smask = doc.extract_image(xref).get("smask") or 0
        if smask:
            pix = pymupdf.Pixmap(pix, pymupdf.Pixmap(doc, smask))
        if pix.colorspace is None or pix.colorspace.n not in (1, 3):
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        if pix.alpha:
            img = Image.frombytes("RGBA" if pix.n == 4 else "LA", (pix.width, pix.height), pix.samples)
            bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
            return Image.alpha_composite(bg, img.convert("RGBA")).convert("RGB")
        return pixmap_to_image(pix)
    except Exception:
        return None


def render_clip(page: pymupdf.Page, rect: pymupdf.Rect, opts: Opts,
                native_dpi: float | None = None, sole_image: dict | None = None):
    """Renderiza una región de la página tal como se ve (máscaras, recortes y vectores incluidos).

    MuPDF amplía las imágenes sin suavizar (vecino más próximo): una figura de 90 ppp dibujada a 150
    sale dentada y el texto que contiene se rompe. Por eso:
      - si la región es una sola imagen incrustada, se usan sus píxeles originales;
      - si no, se renderiza a varias veces la resolución nativa y se reduce con un filtro Lanczos.
    En ambos casos las imágenes de baja resolución se amplían con Lanczos hasta FIG_DPI.
    """
    rect = (rect + (-1, -1, 1, 1)) & page.rect
    if rect.is_empty:
        return None
    dpi = min(300.0, max(FIG_DPI, native_dpi or FIG_DPI))
    size = _target_size(rect, dpi, opts)
    if sole_image is not None and sole_image.get("xref"):
        img = _embedded(page, sole_image["xref"])
        if img is not None:
            if img.width < size[0]:
                img = img.resize(_target_size(rect, dpi, opts), Image.LANCZOS)
            return encode(img, opts, photo_quality=max(opts.jpeg_quality, 90))
    # supermuestreo al doble de lo pedido y reducción suave (sin pasar de ~3x el tamaño final)
    hi = max(dpi, min(2 * dpi, 3 * opts.max_image_px / max(rect.width, rect.height) * 72))
    pix = page.get_pixmap(clip=rect, dpi=int(hi), alpha=False, colorspace=pymupdf.csRGB)
    img = pixmap_to_image(pix)
    if img.size != size:
        img = img.resize(size, Image.LANCZOS)
    return encode(img, opts, photo_quality=max(opts.jpeg_quality, 90))


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


def render_icon(page: pymupdf.Page, rect: pymupdf.Rect, opts: Opts):
    """Icono pequeño (vectorial casi siempre): resolución alta para que no se vea pixelado."""
    rect = (rect + (-1, -1, 1, 1)) & page.rect
    if rect.is_empty:
        return None
    pix = page.get_pixmap(clip=rect, dpi=400, alpha=False, colorspace=pymupdf.csRGB)
    img = pixmap_to_image(pix)
    return encode(img, opts, prefer_jpeg=False)
