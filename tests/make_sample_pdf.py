"""Genera un PDF de prueba difícil: texto justificado con guiones, títulos, cabeceras,
números de página, imagen, gráfico vectorial, tabla, notas y dos columnas."""
import io
import sys

from PIL import Image, ImageDraw
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (BaseDocTemplate, Frame, Image as RLImage, NextPageTemplate, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle, FrameBreak)

LOREM = ("La conversión de documentos es un problema sorprendentemente difícil: el formato PDF describe dónde "
         "se dibuja cada carácter, no cómo se organiza el texto. Un buen conversor debe reconstruir los "
         "párrafos, eliminar los guiones de final de línea, respetar las figuras y los acentos (á, é, í, ó, ú, ñ) "
         "y conservar la justificación original sin dejar espacios enormes entre las palabras. ")


def photo():
    im = Image.new("RGB", (900, 600))
    d = ImageDraw.Draw(im)
    for y in range(600):
        d.line([(0, y), (900, y)], fill=(int(255 * y / 600), 120, 255 - int(255 * y / 600)))
    for i in range(0, 900, 60):
        d.ellipse([i, 200 + (i % 120), i + 80, 280 + (i % 120)], outline=(255, 255, 255), width=4)
    b = io.BytesIO()
    im.save(b, "JPEG")
    b.seek(0)
    return b


def build(path):
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["Normal"], fontName="Times-Roman", fontSize=10.5, leading=14,
                          alignment=TA_JUSTIFY, firstLineIndent=14, hyphenationLang="es_ES",
                          uriWordBreak=None, embeddedHyphenation=1, splitLongWords=1)
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=14, spaceBefore=6)
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=14, leading=18, spaceAfter=8, spaceBefore=10)
    cap = ParagraphStyle("c", parent=body, fontSize=9, leading=11, firstLineIndent=0, alignment=1)

    def deco(c, doc):
        c.saveState()
        c.setFont("Helvetica", 8)
        c.drawString(1.8 * cm, A5[1] - 1.1 * cm, "Manual de pruebas — Conversor")
        c.drawCentredString(A5[0] / 2, 1.0 * cm, str(doc.page))
        c.restoreState()

    W, H = A5
    one = Frame(1.8 * cm, 1.8 * cm, W - 3.6 * cm, H - 3.8 * cm, id="f")
    gap = 0.6 * cm
    cw = (W - 3.6 * cm - gap) / 2
    left = Frame(1.8 * cm, 1.8 * cm, cw, H - 3.8 * cm, id="l")
    right = Frame(1.8 * cm + cw + gap, 1.8 * cm, cw, H - 3.8 * cm, id="r")
    doc = BaseDocTemplate(path, pagesize=A5, title="Manual de pruebas", author="Equipo QA")
    doc.addPageTemplates([PageTemplate("one", [one], onPage=deco), PageTemplate("two", [left, right], onPage=deco)])

    S = []
    def chapter(title, key):
        p = Paragraph(f'<a name="{key}"/>{title}', h1)
        p._bookmarkName = key
        S.append(p)
        return p

    chapter("Capítulo 1. Texto y párrafos", "c1")
    for _ in range(5):
        S.append(Paragraph(LOREM * 2, body))
    S.append(Paragraph("1.1 Una sección más corta", h2))
    for _ in range(3):
        S.append(Paragraph(LOREM, body))
    S.append(Paragraph("«Esto es una cita centrada»", ParagraphStyle("q", parent=body, alignment=1, firstLineIndent=0)))
    S.append(Paragraph(LOREM * 2, body))
    S.append(PageBreak())

    chapter("Capítulo 2. Imágenes y gráficos", "c2")
    S.append(Paragraph(LOREM, body))
    S.append(RLImage(photo(), width=8 * cm, height=5.33 * cm))
    S.append(Paragraph("Figura 1. Una fotografía de ejemplo con degradado.", cap))
    S.append(Paragraph(LOREM, body))
    d = Drawing(260, 140)
    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 30, 20, 210, 100
    bc.data = [[3, 5, 8, 6, 9]]
    bc.categoryAxis.categoryNames = ["A", "B", "C", "D", "E"]
    bc.bars[0].fillColor = colors.HexColor("#c0392b")
    d.add(bc)
    S.append(d)
    S.append(Paragraph("Figura 2. Gráfico vectorial de barras.", cap))
    S.append(Paragraph(LOREM * 2, body))
    t = Table([["Concepto", "2023", "2024"], ["Ventas", "120", "150"], ["Costes", "80", "95"], ["Margen", "40", "55"]],
              colWidths=[4 * cm, 2.5 * cm, 2.5 * cm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, colors.black),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)]))
    S.append(Paragraph("Tabla 1. Resultados anuales.", cap))
    S.append(t)
    S.append(Paragraph(LOREM, body))
    S.append(NextPageTemplate("two"))
    S.append(PageBreak())

    chapter("Capítulo 3. Dos columnas", "c3")
    S.append(FrameBreak) if False else None
    for _ in range(14):
        S.append(Paragraph(LOREM, body))

    doc.build(S)


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "sample.pdf")
