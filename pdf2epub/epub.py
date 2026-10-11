"""Estructura final (capítulos, TOC) y escritura del archivo EPUB 3 (compatible con Kindle)."""
from __future__ import annotations

import bisect
import collections
import datetime as dt
import html
import re
import uuid
import zipfile

from .analyze import CAPTION_RE, esc
from .model import Asset, Block

CSS = """\
/* Sin font-family ni font-size en body: el Kindle respeta la fuente y tamaño que elijas. */
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; padding: 0; line-height: 1.35; text-align: justify;
       hyphens: auto; -webkit-hyphens: auto; -epub-hyphens: auto; }
p { margin: 0; text-indent: 1.4em; orphans: 2; widows: 2; }
p.ni, h1 + p, h2 + p, h3 + p, h4 + p { text-indent: 0; }
p.center { text-align: center; text-indent: 0; margin: .6em 0; }
p.right { text-align: right; text-indent: 0; }
p.quote { margin: .6em 1.5em; text-indent: 0; }
p.li { text-indent: -1.1em; margin-left: 1.5em; text-align: left; }
p.toc { text-indent: 0; text-align: left; margin: .15em 0; }
p.fn { font-size: .82em; text-indent: 0; margin: .15em 0 .15em 0; line-height: 1.25; }
h1, h2, h3, h4 { text-align: left; text-indent: 0; hyphens: none; -webkit-hyphens: none;
                 page-break-after: avoid; line-height: 1.2; }
h1 { font-size: 1.6em; margin: 1.4em 0 .7em; }
h2 { font-size: 1.3em; margin: 1.2em 0 .6em; }
h3 { font-size: 1.12em; margin: 1.1em 0 .5em; }
h4 { font-size: 1em; margin: 1em 0 .4em; }
figure { margin: 1em 0; padding: 0; text-align: center; text-indent: 0; page-break-inside: avoid; }
figure img { max-width: 100%; height: auto; }
figcaption { font-size: .85em; text-align: center; text-indent: 0; margin-top: .4em; line-height: 1.25; }
div.page { margin: 0; padding: 0; text-align: center; page-break-after: always; }
div.page img { max-width: 100%; max-height: 100%; }
table { border-collapse: collapse; margin: 1em auto; font-size: .9em; }
td, th { border: 1px solid #888; padding: .25em .45em; text-align: left; vertical-align: top; }
th { font-weight: bold; }
code { font-family: monospace; font-size: .92em; }
pre { font-family: monospace; font-size: .8em; line-height: 1.3; text-align: left; white-space: pre-wrap;
      hyphens: none; -webkit-hyphens: none; margin: .7em 0; padding: .4em .5em; border-left: 2px solid #999; }
pre code { font-size: 1em; }
sup, sub { font-size: .75em; line-height: 0; }
a { color: inherit; }
"""

STOP = {
    "es": "el la los las de que y en un una es se no por con para su al lo como más pero sus le ya o este sí porque esta entre cuando muy sin sobre también me hasta hay donde quien desde todo nos durante".split(),
    "en": "the of and to in is that it was for on are as with his they at be this from have or by one had not but what all were when we there can an your which their said if do will each about how up out them then".split(),
    "pt": "o a os as de que e do da em um uma para com não por mais se na no os dos das como mas foi ao ele são seu sua ou quando muito nos já está eu também só pelo pela até isso ela entre era depois sem".split(),
    "fr": "le la les de des du un une et est en que qui dans pour pas sur au avec ce il elle se ne plus par son sa ses mais ou où comme nous vous ils elles être avoir été cette sont".split(),
    "de": "der die das und ist in den von zu mit sich des auf für nicht ein eine als auch es an werden aus er hat dass sie nach wird bei einer um am sind noch wie einem über so zum".split(),
    "it": "il lo la i gli le di che e un una è in per con non si da su come ma più del della dei delle al alla sono anche ha ho nel nella questo questa se ci".split(),
}
LABEL = {"es": "Páginas", "en": "Pages", "pt": "Páginas", "fr": "Pages", "de": "Seiten", "it": "Pagine"}


def detect_lang(blocks: list[Block]) -> str:
    words = re.findall(r"[^\W\d_]+", " ".join(b.text for b in blocks[:400] if b.kind == "p").lower())[:6000]
    if not words:
        return "es"
    cnt = collections.Counter(words)
    scores = {l: sum(cnt[w] for w in set(sw)) for l, sw in STOP.items()}
    return max(scores, key=scores.get)


def norm(s: str) -> str:
    return re.sub(r"[\W_]+", " ", s.lower()).strip()


# --------------------------------------------------------------------------- estructura
def finalize_blocks(blocks: list[Block]) -> list[Block]:
    # niveles de título por tamaño
    keys = sorted({b.hkey for b in blocks if b.kind == "h" and b.hkey}, key=lambda k: (-k[0], -k[1]))
    rank = {k: min(i + 1, 4) for i, k in enumerate(keys)}
    for b in blocks:
        if b.kind == "h":
            b.level = rank.get(b.hkey, 3)
    # pies de figura
    out: list[Block] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b.kind in ("img", "table") and b.cls != "chart-skip":
            nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            if nxt and nxt.kind == "p" and CAPTION_RE.match(nxt.text) and len(nxt.text) < 400 and "li" not in nxt.cls:
                b.caption = nxt.html
                if b.alt.startswith(("Figura", "Tabla")):
                    b.alt = nxt.text[:120]
                out.append(b)
                i += 2
                continue
            prev = out[-1] if out else None
            if (b.cls == "table" or b.kind == "table") and prev and prev.kind == "p" and \
                    re.match(r"^(tabla|table|cuadro)\b", prev.text, re.I) and len(prev.text) < 250:
                b.caption, b.cap_top = prev.html, True
                out.pop()
        out.append(b)
        i += 1
    # primer párrafo tras título/figura sin sangría
    for j, b in enumerate(out):
        if b.kind == "p" and j > 0 and out[j - 1].kind in ("h", "img", "table", "pageimg") and "li" not in b.cls:
            b.cls = (b.cls + " ni").strip()
    return out


def resolve_outline(blocks: list[Block], outline: list):
    """Asocia las entradas del índice del PDF con bloques. Devuelve [(nivel, título, idx)]."""
    first_by_page: dict[int, int] = {}
    heads_by_page: dict[int, list[int]] = collections.defaultdict(list)
    for i, b in enumerate(blocks):
        first_by_page.setdefault(b.page, i)
        if b.kind == "h":
            heads_by_page[b.page].append(i)
    pages_sorted = sorted(first_by_page)
    entries = []
    for lvl, title, pg in outline:
        if pg is None or pg < 1 or not title.strip():
            continue
        p0 = pg - 1
        nt = norm(title)
        idx = None
        for pp in (p0, p0 + 1):
            for i in heads_by_page.get(pp, []):
                nb = norm(blocks[i].text)
                if nb and (nb == nt or (len(nt) > 4 and (nb in nt or nt in nb))):
                    idx = i
                    break
            if idx is not None:
                break
        if idx is None:
            k = bisect.bisect_left(pages_sorted, p0)
            if k >= len(pages_sorted):
                continue
            start = first_by_page[pages_sorted[k]]
            for i in range(start, min(start + 6, len(blocks))):
                b = blocks[i]
                if b.kind == "p" and norm(b.text) == nt:
                    b.kind, b.level = "h", min(lvl, 4)
                    b.html = esc(b.text)
                    idx = i
                    break
            if idx is None:
                idx = start
        else:
            blocks[idx].level = min(max(lvl, 1), 4)
        entries.append((lvl, title.strip(), idx))
    return entries


def plain(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


class Chapter:
    def __init__(self, start: int, end: int, title: str, num: int):
        self.start, self.end, self.title, self.num = start, end, title, num
        self.file = f"text/ch_{num:03d}.xhtml"


def plan_book(blocks: list[Block], outline: list, lang: str):
    """Decide capítulos y entradas de índice."""
    n = len(blocks)
    label = LABEL.get(lang, "Pages")
    entries = resolve_outline(blocks, outline) if outline else []
    if not entries:
        heads = [(b.level, b.text, i) for i, b in enumerate(blocks) if b.kind == "h"]
        cap = 2 if len(heads) > 300 else 3
        entries = [(l, t, i) for l, t, i in heads if l <= cap]
    levels = collections.Counter(l for l, _, _ in entries)
    split_level = next((l for l in sorted(levels) if levels[l] >= 2), None)
    starts = {0}
    if split_level is not None:
        starts |= {i for l, _, i in entries if l <= split_level}
    # trozos grandes sin estructura -> partir por páginas
    pages = [b.page for b in blocks]
    est = [len(b.html) + 60 for b in blocks]
    bounds = sorted(starts) + [n]
    final = set()
    for a, b in zip(bounds, bounds[1:]):
        final.add(a)
        acc = 0
        for i in range(a, b):
            acc += est[i]
            if acc > 220_000 and i + 1 < b:
                final.add(i + 1)
                acc = 0
    # sin ninguna estructura: trozos de ~25 páginas
    if len(final) == 1 and n and pages[-1] - pages[0] > 40:
        last = pages[0]
        for i, p in enumerate(pages):
            if p - last >= 25:
                final.add(i)
                last = p
    starts_sorted = sorted(final)
    chapters: list[Chapter] = []
    title_at = {}
    for l, t, i in entries:
        title_at.setdefault(i, t)
    for k, s in enumerate(starts_sorted):
        e = starts_sorted[k + 1] if k + 1 < len(starts_sorted) else n
        t = title_at.get(s)
        if not t:
            hb = next((blocks[i] for i in range(s, min(e, s + 4)) if blocks[i].kind == "h"), None)
            t = hb.text if hb else f"{label} {pages[s] + 1}–{pages[e - 1] + 1}"
        chapters.append(Chapter(s, e, t, k + 1))
    if not entries:
        entries = [(1, c.title, c.start) for c in chapters]
    return chapters, entries


# --------------------------------------------------------------------------- escritura
def _block_html(b: Block, assets: list[Asset]) -> str:
    idattr = f' id="{b.id}"' if b.id else ""
    if b.kind == "p":
        c = f' class="{b.cls}"' if b.cls else ""
        return f"<p{c}{idattr}>{b.html}</p>"
    if b.kind == "h":
        lv = max(1, min(b.level or 2, 4))
        return f"<h{lv}{idattr}>{b.html}</h{lv}>"
    if b.kind == "table":
        return b.html
    if b.kind == "code":
        return f"<pre{idattr}><code>{b.html}</code></pre>"
    if b.kind == "pageimg":
        a = assets[b.asset]
        return f'<div class="page"{idattr}><img src="../images/{a.name}" alt="{html.escape(b.alt)}"/></div>'
    if b.kind == "img":
        a = assets[b.asset]
        w = f' style="width:{b.width_pct}%"' if b.width_pct < 100 else ""
        cap = f"<figcaption>{b.caption}</figcaption>" if b.caption else ""
        top = cap if b.cap_top else ""
        bottom = "" if b.cap_top else cap
        return (f'<figure{idattr}>{top}<img src="../images/{a.name}" alt="{html.escape(b.alt, quote=True)}"{w}/>'
                f"{bottom}</figure>")
    return ""


def _xhtml(title: str, body: str, lang: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}" xml:lang="{lang}">\n'
        f'<head><meta charset="utf-8"/><title>{html.escape(title)}</title>'
        '<link rel="stylesheet" type="text/css" href="../styles.css"/></head>\n'
        f"<body>\n{body}\n</body>\n</html>\n"
    )


def _nest(entries, render):
    """entries: [(nivel, título, href)] -> HTML anidado <ol>."""
    out, stack, prev = [], [], 0
    fixed = []
    for l, t, h in entries:
        l = max(1, min(l, prev + 1))
        fixed.append((l, t, h))
        prev = l
    cur = 0
    for l, t, h in fixed:
        if l > cur:
            out.append("<ol>" * (l - cur))
        else:
            out.append("</li>" + "</ol></li>" * (cur - l))
        out.append(render(t, h))
        cur = l
    out.append("</li>" + "</ol></li>" * (cur - 1) + "</ol>" if cur else "")
    return "".join(out)


def write_epub(path: str, blocks: list[Block], assets: list[Asset], outline: list, meta: dict,
               cover: tuple | None, lang: str):
    chapters, entries = plan_book(blocks, outline, lang)
    starts = [c.start for c in chapters]

    def chapter_of(idx: int) -> Chapter:
        return chapters[max(0, bisect.bisect_right(starts, idx) - 1)]

    toc = []
    for l, t, i in entries:
        ch = chapter_of(i)
        href = ch.file
        if i != ch.start:
            if not blocks[i].id:
                blocks[i].id = f"b{i}"
            href += f"#{blocks[i].id}"
        toc.append((l, plain(t) or "—", href))

    title = meta.get("title") or "Documento"
    author = meta.get("author") or ""
    uid = f"urn:uuid:{uuid.uuid4()}"
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    used_assets = sorted({b.asset for b in blocks if b.asset >= 0})
    manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
                '<item id="css" href="styles.css" media-type="text/css"/>']
    spine = []
    for c in chapters:
        manifest.append(f'<item id="c{c.num}" href="{c.file}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{c.num}"/>')
    for k in used_assets:
        a = assets[k]
        manifest.append(f'<item id="i{k}" href="images/{a.name}" media-type="{a.media}"/>')
    cover_meta = ""
    if cover:
        data, media, _, _ = cover
        ext = "jpg" if media == "image/jpeg" else "png"
        manifest.append(f'<item id="cover-image" href="images/cover.{ext}" media-type="{media}" properties="cover-image"/>')
        cover_meta = '<meta name="cover" content="cover-image"/>'

    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" '
        f'xml:lang="{lang}">\n<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'<dc:identifier id="uid">{uid}</dc:identifier>\n<dc:title>{html.escape(title)}</dc:title>\n'
        f"<dc:language>{lang}</dc:language>\n"
        + (f"<dc:creator>{html.escape(author)}</dc:creator>\n" if author else "")
        + f'<meta property="dcterms:modified">{now}</meta>\n{cover_meta}\n</metadata>\n'
        f"<manifest>\n{chr(10).join(manifest)}\n</manifest>\n"
        f'<spine toc="ncx">\n{chr(10).join(spine)}\n</spine>\n</package>\n'
    )

    nav_body = ('<nav epub:type="toc" id="toc"><h1>' + html.escape(title) + "</h1>"
                + _nest(toc, lambda t, h: f'<li><a href="{h}">{html.escape(t)}</a>') + "</nav>")
    nav = _xhtml(title, nav_body, lang).replace("../styles.css", "styles.css")

    def ncx_points():
        out, play, depth = [], 0, 0
        prev = 0
        for l, t, h in toc:
            l = max(1, min(l, prev + 1))
            prev = l
            while depth >= l:
                out.append("</navPoint>")
                depth -= 1
            play += 1
            out.append(f'<navPoint id="n{play}" playOrder="{play}"><navLabel><text>{html.escape(t)}</text></navLabel>'
                       f'<content src="{h}"/>')
            depth += 1
        out.append("</navPoint>" * depth)
        return "".join(out)

    ncx = ('<?xml version="1.0" encoding="utf-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
           f'<head><meta name="dtb:uid" content="{uid}"/><meta name="dtb:depth" content="3"/>'
           '<meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>'
           f"<docTitle><text>{html.escape(title)}</text></docTitle><navMap>{ncx_points()}</navMap></ncx>")

    container = ('<?xml version="1.0"?>\n<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                 "</rootfiles></container>")

    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        D = zipfile.ZIP_DEFLATED
        z.writestr("META-INF/container.xml", container, D)
        z.writestr("OEBPS/content.opf", opf, D)
        z.writestr("OEBPS/nav.xhtml", nav, D)
        z.writestr("OEBPS/toc.ncx", ncx, D)
        z.writestr("OEBPS/styles.css", CSS, D)
        for c in chapters:
            body = "\n".join(_block_html(b, assets) for b in blocks[c.start:c.end])
            z.writestr("OEBPS/" + c.file, _xhtml(c.title, body, lang), D)
        for k in used_assets:
            a = assets[k]
            z.writestr(f"OEBPS/images/{a.name}", a.data, zipfile.ZIP_STORED)
        if cover:
            data, media, _, _ = cover
            z.writestr(f"OEBPS/images/cover.{'jpg' if media == 'image/jpeg' else 'png'}", data, zipfile.ZIP_STORED)
    return len(chapters), len(toc)
