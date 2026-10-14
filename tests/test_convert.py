import re
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_sample_pdf import build  # noqa: E402
from pdf2epub.convert import convert  # noqa: E402
from pdf2epub.model import Opts  # noqa: E402


@pytest.fixture(scope="module")
def epub(tmp_path_factory):
    d = tmp_path_factory.mktemp("t")
    pdf = d / "sample.pdf"
    build(str(pdf))
    out = d / "sample.epub"
    convert(str(pdf), str(out), Opts())
    return out


def text_of(epub):
    z = zipfile.ZipFile(epub)
    return "\n".join(z.read(n).decode() for n in z.namelist() if n.startswith("OEBPS/text/"))


def test_mimetype_first_and_stored(epub):
    z = zipfile.ZipFile(epub)
    assert z.namelist()[0] == "mimetype"
    assert z.infolist()[0].compress_type == zipfile.ZIP_STORED


def test_no_soft_hyphens_or_broken_words(epub):
    t = text_of(epub)
    assert "­" not in t
    assert not re.search(r"[a-záéíóúñ]- [a-záéíóúñ]", re.sub(r"<[^>]+>", "", t))


def test_headers_and_page_numbers_removed(epub):
    assert "Manual de pruebas — Conversor" not in text_of(epub)


def test_figures_have_captions_and_images(epub):
    t = text_of(epub)
    assert t.count("<figure") >= 3
    assert "Figura 1." in t and "Tabla 1." in t


def test_chart_labels_not_leaked_as_text(epub):
    assert "<p>9 8 7" not in text_of(epub)


def test_two_columns_read_in_order(epub):
    ps = re.findall(r"<p[^>]*>([^<]*)", zipfile.ZipFile(epub).read("OEBPS/text/ch_003.xhtml").decode())
    assert len({len(p) for p in ps}) == 1      # ningún párrafo mezcla líneas de las dos columnas


def test_toc_has_three_chapters(epub):
    nav = zipfile.ZipFile(epub).read("OEBPS/nav.xhtml").decode()
    assert nav.count("Capítulo") == 3


def test_epubcheck(epub):
    epubcheck = pytest.importorskip("epubcheck")
    r = epubcheck.EpubCheck(str(epub))
    assert r.valid, r.messages


def _line(text, x0, x1, base, size=10.0):
    from pdf2epub.analyze import Line, Run
    return Line([Run(text, False, False, False, False, False, None)], x0, base - size, x1, base + 2, size, base, 0)


def test_compound_hyphen_kept_at_line_end():
    import collections
    from pdf2epub.analyze import _join
    vocab = collections.Counter({"rule": 3, "open-source": 2, "chatgpt": 2, "applications": 4})
    text = lambda a, b: "".join(r[0] for r in _join([_line(a, 0, 100, 10), _line(b, 0, 100, 22)], vocab))
    assert text("focused on rule-", "based systems") == "focused on rule-based systems"
    assert text("many open-", "source models") == "many open-source models"
    assert text("Chat-", "GPT platform") == "ChatGPT platform"
    assert text("modern applica-", "tions run") == "modern applications run"


def test_bullet_glyph_duplicates_and_loose_markers():
    from pdf2epub.analyze import attach_markers, drop_glyph_dupes
    lines = [_line("» LLMs as engines", 93, 300, 50), _line("»", 103, 107, 50, size=14.7),
             _line("1.", 86, 101, 100, size=14.0), _line("Choose software vendors", 108, 300, 100)]
    out = attach_markers(drop_glyph_dupes(lines))
    assert [l.text for l in out] == ["» LLMs as engines", "1. Choose software vendors"]


def _lowres_art():
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (240, 140), "white")
    d = ImageDraw.Draw(im)
    for k in range(0, 240, 12):
        d.line([(k, 0), (k + 100, 140)], fill=(20, 40, 160), width=2)
    d.text((10, 10), "MCU 36", fill="black")
    return im


def _figures_pdf(path):
    """Página con un icono vectorial al margen y una figura incrustada a baja resolución (~70 ppp)."""
    import io
    import pymupdf
    from PIL import Image, ImageDraw
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=595)
    para = ("Los iconos del margen señalan consejos y advertencias que acompañan al texto; si se pierden, "
            "el lector no sabe qué tipo de nota está leyendo. ") * 3
    page.insert_textbox(pymupdf.Rect(90, 60, 370, 200), para, fontsize=10, align=3)
    page.draw_circle((62, 75), 14, color=(0, 0, 0), fill=(1, 0.9, 0), width=1.5)   # icono «TIP»
    page.draw_bezier((55, 70), (60, 60), (66, 60), (70, 72), color=(0, 0, 0), width=1.2)
    buf = io.BytesIO()
    _lowres_art().save(buf, "PNG")
    page.insert_image(pymupdf.Rect(90, 230, 370, 393), stream=buf.getvalue())   # 240 px en 280 pt
    page.insert_textbox(pymupdf.Rect(90, 410, 370, 520), para, fontsize=10, align=3)
    doc.save(path)


@pytest.fixture(scope="module")
def figures_epub(tmp_path_factory):
    d = tmp_path_factory.mktemp("f")
    _figures_pdf(str(d / "fig.pdf"))
    out = d / "fig.epub"
    convert(str(d / "fig.pdf"), str(out), Opts())
    return out


def test_margin_icon_kept(figures_epub):
    xhtml = text_of(figures_epub)
    assert '<figure class="icon">' in xhtml
    # el icono va delante del párrafo que señala
    assert xhtml.index('class="icon"') < xhtml.index("Los iconos del margen")


def test_low_res_figure_is_smoothed_not_blocky(figures_epub):
    import io
    from PIL import Image, ImageChops, ImageStat
    z = zipfile.ZipFile(figures_epub)
    name = re.search(r'<figure><img src="\.\./images/([^"]+)"', text_of(figures_epub)).group(1)
    got = Image.open(io.BytesIO(z.read("OEBPS/images/" + name))).convert("L")
    assert got.width >= 240                       # nunca por debajo de los píxeles originales
    # debe parecerse al original ampliado con Lanczos; el redibujado de MuPDF (vecino más próximo)
    # deja escalones que se alejan mucho de esa referencia
    ref = _lowres_art().convert("L").resize(got.size, Image.LANCZOS)
    assert ImageStat.Stat(ImageChops.difference(got, ref)).mean[0] < 3


def _stacked_figures_pdf(path):
    """Cabecera corrida con el folio en otra línea y dos figuras apiladas, cada una con su pie debajo."""
    import pymupdf
    doc = pymupdf.open()
    body = ("El robot se desplaza sobre ruedas fijas y orientables; la tracción y la dirección se reparten "
            "entre motores distintos según la configuración elegida para el vehículo. ") * 4
    for k in range(5):
        page = doc.new_page(width=440, height=666)
        page.insert_text((224, 42), "1.2 Estructura mecánica", fontsize=9)
        page.insert_text((378, 42), str(13 + k), fontsize=9)
        if k == 2:
            for y0, cap in ((54, "Fig. 1.15. Un robot móvil triciclo"), (160, "Fig. 1.16. Un robot móvil tipo coche")):
                page.draw_rect(pymupdf.Rect(170, y0, 270, y0 + 70), color=(0, 0, 0), width=1)
                page.draw_circle((195, y0 + 55), 10, color=(0, 0, 0), width=1)
                page.draw_circle((245, y0 + 55), 10, color=(0, 0, 0), width=1)
                page.draw_bezier((175, y0 + 30), (200, y0 + 5), (240, y0 + 5), (265, y0 + 30), color=(0, 0, 0))
                page.insert_text((150, y0 + 84), cap, fontsize=9)
            page.insert_textbox(pymupdf.Rect(53, 270, 387, 600), body, fontsize=10, align=3)
        else:
            page.insert_textbox(pymupdf.Rect(53, 60, 387, 600), body + body, fontsize=10, align=3)
    doc.save(path)


def test_stacked_figures_keep_their_captions_and_header_dropped(tmp_path):
    _stacked_figures_pdf(str(tmp_path / "s.pdf"))
    convert(str(tmp_path / "s.pdf"), str(tmp_path / "s.epub"), Opts())
    xhtml = text_of(tmp_path / "s.epub")
    assert "Estructura mecánica" not in xhtml                 # cabecera corrida fuera
    figs = re.findall(r"<figure>.*?</figure>", xhtml, re.S)
    caps = [re.sub(r"<[^>]+>", "", re.search(r"<figcaption>(.*?)</figcaption>", f, re.S).group(1))
            for f in figs if "<figcaption>" in f]
    assert caps == ["Fig. 1.15. Un robot móvil triciclo", "Fig. 1.16. Un robot móvil tipo coche"]


def _booktabs_pdf(path):
    """Tabla sin rejilla (estilo booktabs): título encima y tres filetes horizontales."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=440, height=666)
    text = ("Los parámetros de cada articulación se resumen en la tabla siguiente, que el lector debe poder "
            "consultar con sus filas y columnas intactas. ") * 3
    page.insert_textbox(pymupdf.Rect(53, 60, 387, 160), text, fontsize=10, align=3)
    page.insert_text((105, 190), "Tabla 2.1. Parámetros del brazo plano", fontsize=9)
    for y in (199, 212, 250):
        page.draw_line((53, y), (387, y), width=0.5)
    for k, row in enumerate((("Enlace", "ai", "alfa", "theta"), ("1", "a1", "0", "t1"), ("2", "a2", "0", "t2"))):
        for x, cell in zip((60, 150, 240, 330), row):
            page.insert_text((x, 209 + 13 * k + (2 if k else 0)), cell, fontsize=9)
    page.insert_textbox(pymupdf.Rect(53, 270, 387, 400), text, fontsize=10, align=3)
    doc.save(path)


@pytest.mark.parametrize("mode", ["image", "html"])
def test_booktabs_table_kept_as_table(tmp_path, mode):
    _booktabs_pdf(str(tmp_path / "t.pdf"))
    convert(str(tmp_path / "t.pdf"), str(tmp_path / "t.epub"), Opts(tables=mode))
    xhtml = text_of(tmp_path / "t.epub")
    paras = [re.sub(r"<[^>]+>", "", p).strip() for p in re.findall(r"<p[^>]*>(.*?)</p>", xhtml, re.S)]
    assert not any(p in ("a1", "a2", "Enlace") or p.startswith(("Enlace", "1 a1")) for p in paras)
    if mode == "image":
        assert re.search(r"<figure><figcaption><strong>Tabla 2\.1\.</strong>[^<]*</figcaption><img", xhtml) or \
            re.search(r"<figure><figcaption>Tabla 2\.1\.[^<]*</figcaption><img", xhtml)
    else:
        table = re.search(r"<table>.*?</table>", xhtml, re.S).group(0)
        assert "<caption>" in table and "Tabla 2.1." in table
        rows = [[re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<t[hd]>(.*?)</t[hd]>", r)]
                for r in re.findall(r"<tr>(.*?)</tr>", table)]
        assert rows == [["Enlace", "ai", "alfa", "theta"], ["1", "a1", "0", "t1"], ["2", "a2", "0", "t2"]]


def _scan_pdf(path):
    """Libro escaneado: una página de texto rasterizada y una lámina (foto a página completa, sin texto)."""
    import io
    import pymupdf
    from PIL import Image, ImageDraw
    para = ("Este libro escaneado tiene texto que solo se puede leer reconociendo la imagen. "
            "La segunda hoja es una lámina sin palabras que debe conservarse como imagen. ") * 4
    src = pymupdf.open()
    src.new_page(width=420, height=595).insert_textbox(pymupdf.Rect(50, 60, 370, 540), para, fontsize=12)
    scan = src[0].get_pixmap(dpi=200, colorspace=pymupdf.csGRAY).tobytes("png")
    im = Image.new("RGB", (900, 1270))
    d = ImageDraw.Draw(im)
    for k in range(0, 1270, 8):
        d.ellipse((k % 700, k, k % 700 + 220, k + 150), fill=((k * 7) % 255, (k * 3) % 255, (k * 11) % 255))
    photo = io.BytesIO()
    im.save(photo, "JPEG")
    doc = pymupdf.open()
    for data in (scan, photo.getvalue()):
        page = doc.new_page(width=420, height=595)
        page.insert_image(page.rect, stream=data)
    doc.save(path)


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract no está instalado")
def test_ocr_keeps_full_page_plate_as_image(tmp_path):
    _scan_pdf(str(tmp_path / "s.pdf"))
    convert(str(tmp_path / "s.pdf"), str(tmp_path / "s.epub"), Opts(ocr=True))
    xhtml = text_of(tmp_path / "s.epub")
    assert "reconociendo" in xhtml                 # la página de texto pasó por el OCR
    assert xhtml.count('<div class="page"') == 1   # y la lámina no se perdió
