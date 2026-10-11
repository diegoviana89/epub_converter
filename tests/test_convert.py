import re
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
