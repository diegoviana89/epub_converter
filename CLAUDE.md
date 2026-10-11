# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`pdf2epub`: a local PDF → EPUB 3 converter for Kindle. It rebuilds the document's structure (paragraphs, headings, figures, footnotes, columns, TOC) instead of copying text one line at a time. The code, comments, log messages and user-facing strings are in Spanish, so keep that convention. The only dependencies are `pymupdf` and `Pillow`. OCR (`--ocr`) needs a system Tesseract install.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m pdf2epub libro.pdf -v                  # writes libro.epub next to the PDF; -v logs what was detected
python -m pdf2epub carpeta/ -o epubs/            # batch convert a folder
python -m pdf2epub ejemplo/sample.pdf -o /tmp/x.epub --mode pages   # every page as an image

pip install pytest epubcheck
pytest -q tests                                  # all tests
pytest -q tests/test_convert.py::test_toc_has_three_chapters   # a single test
```

`tests/make_sample_pdf.py` builds a deliberately hard PDF at test time: hyphenation, repeated headers and page numbers, a photo, a vector chart, a table, two columns and three chapters. A module-scoped fixture converts it once, and every test inspects the resulting zip. `test_epubcheck` is skipped if the `epubcheck` package is not installed. `ejemplo/` holds a sample PDF and its EPUB output for manual checks.

## Architecture

The pipeline in `pdf2epub/convert.py::convert()` runs in this order:

1. **`analyze.analyze(doc, opts)`** (`analyze.py`, the core and largest module) turns the PDF into a flat `list[Block]` plus a `Ctx`, which holds the shared `assets` list and the document statistics. It makes two passes:
   - **Pass 1 (extraction):** `extract_lines` runs on each page. The page is classified as `text`, `pageimg` (scanned, or garbled when the garble ratio from `textfix.garble_count` is above 8%) or `blank`. The pass also collects global stats: body font size (the most common size), line pitch (`ctx.lead`), and the monospace and bold ratios. Paragraph and heading detection depends on these stats.
   - **Repeated headers and footers** are detected across pages by zone and text key, then dropped unless `--keep-headers` is set.
   - **Pass 2 (flow):** for each page, `detect_gutter` handles two columns and `find_regions` finds images, vector drawings and tables, which become rendered image regions. The text lines inside those regions are excluded, so chart labels don't leak into the text. The remaining lines go through `Flow`, which joins them into paragraphs, removes end-of-line hyphens, joins paragraphs that cross a page break and moves footnotes to the end of their paragraph. Most of the heuristic thresholds live here. The README says to tune them in `analyze.py` when a specific book converts badly.
2. **`textfix.clean`** handles character cleanup: ligatures, private-use characters, `(cid:NN)`, combining accents and odd spaces.
3. **`images.py`** renders clips, pages and the cover through PyMuPDF. It picks JPEG for photos and PNG for line art, caps size at `max_image_px`, and can encode as grayscale.
4. **`epub.finalize_blocks`** does post-processing, `detect_lang` guesses the language, and **`plan_book`** splits the book into chapters. It uses the PDF outline (`doc.get_toc`) mapped onto blocks by `resolve_outline`, falls back to detected headings, and splits oversized chunks by size or by roughly 25-page groups. **`write_epub`** writes the EPUB 3 zip: `mimetype` must be the first entry and stored uncompressed, followed by `OEBPS/text/ch_NNN.xhtml`, `nav.xhtml`, the CSS and the images.

`model.py` defines the shared data types:
- `Opts`: maps one-to-one to the CLI flags in `cli.py`.
- `Asset`: an image's bytes, file name and size.
- `Block`: has a `kind` of `p | h | img | table | pageimg | fn`. Image-backed blocks point into `ctx.assets` by index (`asset`).

## Design constraints

- The CSS in `epub.py` intentionally sets no `font-family` or `font-size` on `body`, so the reader's Kindle font settings apply. Justification and hyphenation come from `text-align: justify` / `hyphens: auto` plus the detected `lang`, not from the source layout.
- Pages that can't be extracted reliably fall back to full-page images rather than producing garbage text (`--no-fallback` disables this).
- Tables are rendered as images by default; `--tables html` emits them as HTML instead.
