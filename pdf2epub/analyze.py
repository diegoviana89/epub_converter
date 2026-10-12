"""Análisis de maquetación: PDF -> lista de bloques (párrafos, títulos, figuras...)."""
from __future__ import annotations

import collections
import html
import logging
import re
from dataclasses import dataclass

import pymupdf

from . import images
from .model import Asset, Block, Opts
from .textfix import clean, garble_count

log = logging.getLogger("pdf2epub")

Run = collections.namedtuple("Run", "text bold italic sup sub mono href")

TERMINAL = re.compile(r"[.?!…:;][\"'”’»)\]]*\s*$")
LIST_RE = re.compile(r"^(?:[•▪◦‣∙●■□◆▶►»›➢➤✓✔❯\-–—·]\s+|\(?\d{1,3}[.)]\s+|\(?[a-zA-Z][.)]\s+|\(?[ivxIVX]{1,5}[.)]\s+)")
MARKER_RE = re.compile(r"^(?:[•▪◦‣∙●■□◆▶►»›➢➤✓✔❯·]|\(?\d{1,3}[.)]|\(?[a-zA-Z][.)])$")
NUMBERED_RE = re.compile(r"^(?:\d{1,4}|[ivxlcdm]{1,7})\s+\S|\S\s+(?:\d{1,4}|[ivxlcdm]{1,7})$", re.I)
LEADER_RE = re.compile(r"\s*(?:\.\s?){4,}\s*(?:\d{1,4}|[ivxlcdm]{1,7})\s*$", re.I)
WORD_RE = re.compile(r"[^\W\d_]+(?:[-‐‑][^\W\d_]+)*")
CALLOUT_RE = re.compile(r"^\d{1,2}\s+\S")
SECNUM_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3})+\.?$|^[A-Z]\.\d{1,3}(?:\.\d{1,3})*$")
SHY_MID_RE = re.compile(r"\w­\w")
HY_MID_RE = re.compile(r"[^\W\d_][-‐‑][^\W\d_]")
# segundas partes que en inglés casi siempre forman compuestos con guion (rule-based, data-driven)
COMPOUND_TAILS = set("based driven related specific oriented friendly aware level scale wide free like "
                     "made sized term time ready proof facing".split())
PAGE_NUM_RE = re.compile(r"^\W*(?:p[áa]g(?:ina)?\.?\s*|page\s*)?(\d{1,4}|[ivxlcdm]{1,7})(?:\s*(?:/|de|of)\s*\d{1,4})?\W*$", re.I)
CAPTION_RE = re.compile(r"^(fig(?:ura|ure|\.)?|imagen|image|gr[áa]fic[oa]|cuadro|esquema|ilustraci[óo]n|foto|lámina|plate|tabla|table)\b", re.I)


def esc(s: str) -> str:
    return html.escape(s, quote=False)


# --------------------------------------------------------------------------- líneas
@dataclass
class Line:
    runs: list
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    base: float
    page: int
    bstart: bool = False
    col: int = -1
    gl: float = 0.0
    gr: float = 0.0
    toc: bool = False       # línea de una página de índice impreso
    leader: bool = False    # entrada de índice con puntos guía (ya eliminados)

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)

    @property
    def bold_frac(self) -> float:
        tot = sum(len(r.text.strip()) for r in self.runs) or 1
        return sum(len(r.text.strip()) for r in self.runs if r.bold) / tot

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


TEXT_FLAGS = pymupdf.TEXT_MEDIABOX_CLIP  # sin PRESERVE_LIGATURES: MuPDF expande fi/fl/ffi


def extract_lines(page: pymupdf.Page, pno: int, tp=None):
    d = page.get_text("dict", flags=TEXT_FLAGS, textpage=tp)
    links = [(l["from"], l["uri"]) for l in page.get_links()
             if l.get("kind") == pymupdf.LINK_URI and l.get("uri", "").startswith(("http", "mailto"))]
    lines: list[Line] = []
    bad = 0
    pitches: list[float] = []
    for b in d["blocks"]:
        if b["type"] != 0:
            continue
        prev = None
        for i, l in enumerate(b["lines"]):
            dx, dy = l["dir"]
            spans = [s for s in l["spans"] if s["text"]]
            for s in spans:
                bad += garble_count(s["text"])
            if abs(dy) > 0.2 or dx < 0 or not spans:
                continue
            if not "".join(s["text"] for s in spans).strip():
                continue
            dom = max(spans, key=lambda s: len(s["text"].strip()))
            size, base = dom["size"], dom["origin"][1]
            runs = []
            for s in spans:
                t = clean(s["text"])
                if not t:
                    continue
                fn, fl = s["font"].lower(), s["flags"]
                bold = bool(fl & 16) or any(k in fn for k in ("bold", "black", "heavy"))
                ital = bool(fl & 2) or "italic" in fn or "oblique" in fn
                mono = bool(fl & 8) or any(k in fn for k in ("mono", "courier", "consolas", "menlo"))
                small = s["size"] < size * 0.8
                sup = small and s["origin"][1] < base - 0.18 * size
                sub = small and s["origin"][1] > base + 0.18 * size
                href = None
                if links:
                    cx = (s["bbox"][0] + s["bbox"][2]) / 2
                    cy = (s["bbox"][1] + s["bbox"][3]) / 2
                    for r, u in links:
                        if r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1:
                            href = u
                            break
                runs.append(Run(t, bold, ital, sup, sub, mono, href))
            if not runs:
                continue
            x0, y0, x1, y1 = l["bbox"]
            ln = Line(runs, x0, y0, x1, y1, size, base, pno, bstart=(prev is None))
            if prev is not None and abs(prev.size - size) < 0.3 and 0 < base - prev.base < 2.5 * size:
                pitches.append((base - prev.base) / size)
            lines.append(ln)
            prev = ln
    return lines, bad, pitches


# --------------------------------------------------------------------------- contexto
@dataclass
class PageInfo:
    pno: int
    lines: list
    imgs: list
    mode: str = "text"      # text | pageimg | blank
    ocr: bool = False


class Ctx:
    def __init__(self, doc: pymupdf.Document, opts: Opts):
        self.doc, self.opts = doc, opts
        self.assets: list[Asset] = []
        self.body = 11.0
        self.lead = 1.2
        self.bold_heading_ok = True
        self.ignore_mono = False
        self.vocab: collections.Counter = collections.Counter()   # palabras vistas dentro de líneas
        self.flat_cache: dict = {}

    def add_asset(self, data: bytes, media: str, w: int, h: int) -> int:
        idx = len(self.assets)
        ext = "jpg" if media == "image/jpeg" else "png"
        self.assets.append(Asset(f"img_{idx + 1:04d}.{ext}", data, media, w, h))
        return idx


def _pct(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(p * len(vals)))]


# --------------------------------------------------------------------------- flujo de párrafos
class _Cur:
    def __init__(self, kind, lines, key=None):
        self.kind, self.lines, self.key = kind, lines, key


class Flow:
    def __init__(self, ctx: Ctx, out: list, kind: str = "p"):
        self.ctx, self.out, self.kind = ctx, out, kind
        self.cur: _Cur | None = None
        self.pending: list[Block] = []
        self.cap: list[Line] | None = None     # pie de figura en curso (ver feed)
        self.prev: Line | None = None
        self.after_obj = False
        self.dropcap: Line | None = None
        self.dc_zone: Line | None = None
        self.callouts = False            # justo después de un bloque de código

    # -- API
    def _flush_cap(self):
        cap, self.cap = self.cap, None
        blk = self._make_para(cap) if cap else None
        if blk is not None:
            self.pending.append(blk)

    def add_object(self, blk: Block):
        if self.cap is not None:
            self._flush_cap()
        if (self.cur is not None and self.cur.kind == "p"
                and CAPTION_RE.match(self.cur.lines[0].text.strip())):
            self.close()               # un pie de figura no es un párrafo que la figura interrumpa
        if self.cur is not None and self.cur.kind == "p":
            self.pending.append(blk)
        else:
            self.close()
            self.out.append(blk)
        self.after_obj = True

    def hard_break(self, blk: Block | None = None):
        self.close()
        if blk:
            self.out.append(blk)
        self.prev = None
        self.after_obj = False

    def feed(self, ln: Line):
        t = ln.text.strip()
        if len(t) == 1 and t.isalpha() and ln.size >= 1.8 * self.ctx.body:
            self.dropcap = ln          # letra capital: se pega a la línea siguiente
            return
        if self.cap is not None:
            last = self.cap[-1]
            if (ln.page == last.page and abs(ln.size - last.size) < 0.3 and not CAPTION_RE.match(t)
                    and 0 < ln.base - last.base <= 1.7 * ln.size):
                self.cap.append(ln)    # segunda línea del pie
                return
            self._flush_cap()
        if self.after_obj and self.pending and self.cur is not None and self.cur.kind == "p" and CAPTION_RE.match(t):
            # pie de una figura que interrumpe un párrafo: va con la figura y el párrafo sigue abierto
            self.cap = [ln]
            return
        if self.dropcap is not None:
            dc = self.dropcap
            if ln.page != dc.page:
                self.dropcap = None
            elif ln.text[:1].islower():   # la primera línea en minúscula de la página lleva la capital
                self.dropcap = None
                r0 = ln.runs[0]
                ln.runs = [r0._replace(text=dc.text.strip() + r0.text.lstrip())] + ln.runs[1:]
                self.dc_zone = dc
        dz = self.dc_zone
        if dz is not None:
            if ln.page == dz.page and ln.y0 < dz.y1:
                ln.x0 = min(ln.x0, dz.x0)   # líneas sangradas por la capital: van a ras
            else:
                self.dc_zone = None
        cur = self.cur
        # código: líneas en monoespaciada, un bloque <pre> que conserva líneas y sangría
        if self.kind != "fn" and self._is_code(ln):
            cross = self.after_obj or (cur is not None and cur.lines[-1].page != ln.page)
            if (cur is not None and cur.kind == "code"
                    and (cross or ln.base - cur.lines[-1].base <= 4.2 * ln.size)):
                cur.lines.append(ln)
            else:
                self.close()
                self.cur = _Cur("code", [ln])
            self.prev = ln
            self.after_obj = False
            self.callouts = True
            return
        # notas numeradas tras un listado ("1 Requires the package"): lista, no títulos
        if self.callouts:
            if CALLOUT_RE.match(t):
                self.close()
                self.cur = _Cur("p", [ln], "callout")
                self.prev = ln
                self.after_obj = False
                return
            if not (cur is not None and cur.kind == "p" and CALLOUT_RE.match(cur.lines[0].text.lstrip())
                    and not self._new_para(cur.lines[-1], ln, False, cur.lines[0])):
                self.callouts = False
        hk = None if self.kind == "fn" else self._heading_key(ln)
        if (hk and cur is not None and cur.kind == "p" and LIST_RE.match(cur.lines[0].text.lstrip())
                and abs(ln.size - cur.lines[-1].size) <= 0.7
                and not self._new_para(cur.lines[-1], ln, False, cur.lines[0])):
            hk = None                  # continuación en negrita de un elemento de lista
        if hk:
            cross = self.after_obj or (self.prev and self.prev.page != ln.page)
            if (cur and cur.kind == "h" and cur.key == hk and not cross
                    and 0 <= ln.base - cur.lines[-1].base <= 1.9 * ln.size):
                cur.lines.append(ln)
            else:
                self.close()
                self.cur = _Cur("h", [ln], hk)
        else:
            if cur is not None and cur.kind in ("h", "code"):
                self.close()
                cur = None
            if cur is None:
                self.cur = _Cur("p", [ln])
            else:
                prev = cur.lines[-1]
                cross = (self.after_obj or prev.page != ln.page
                         or (prev.col != ln.col) )
                if self._new_para(prev, ln, cross, cur.lines[0]):
                    self.close()
                    self.cur = _Cur("p", [ln])
                else:
                    cur.lines.append(ln)
        self.prev = ln
        self.after_obj = False

    def close(self):
        if self.cap is not None:
            self._flush_cap()
        cur = self.cur
        if cur is not None:
            self.cur = None
            blk = (self._make_heading(cur) if cur.kind == "h" else
                   self._make_code(cur.lines) if cur.kind == "code" else
                   self._make_para(cur.lines, cur.key == "callout"))
            if blk is not None:
                if self.kind == "fn":
                    blk.cls = (blk.cls + " fn").strip()
                self.out.append(blk)
        if self.pending:
            self.out.extend(self.pending)
            self.pending = []

    # -- decisiones
    def _is_code(self, ln: Line) -> bool:
        return not (self.ctx.ignore_mono or ln.toc) and _mono_line(ln)

    def _heading_key(self, ln: Line):
        c = self.ctx
        t = ln.text.strip()
        if len(t) < 2 or len(t) > 160 or ln.toc:
            return None
        colw = max(ln.gr - ln.gl, 1)
        width = ln.x1 - ln.x0
        if ln.size >= c.body * 1.12:
            return (round(ln.size * 2) / 2, 1 if ln.bold_frac > 0.6 else 0)
        if LIST_RE.match(t):          # elemento de lista en negrita, no un título
            return None
        if (c.bold_heading_ok and ln.bold_frac > 0.85 and len(t) <= 90 and width < 0.85 * colw
                and ln.size >= c.body * 0.95 and not t.endswith((",", ";"))):
            return (round(ln.size * 2) / 2, 1)
        letters = [ch for ch in t if ch.isalpha()]
        if (len(letters) >= 4 and t.isupper() and len(t) <= 70 and width < 0.8 * colw
                and abs(ln.size - c.body) < 1.0):
            return (round(ln.size * 2) / 2, 0)
        return None

    def _new_para(self, prev: Line, ln: Line, cross: bool, first: Line | None = None) -> bool:
        c = self.ctx
        size = ln.size
        if prev.toc and (prev.leader or not ln.toc):
            return True                # cada entrada del índice impreso, su propio párrafo
        if abs(prev.size - ln.size) > 0.7:
            return True
        if (first is not None and first is not ln and CAPTION_RE.match(first.text.strip())
                and abs(ln.size - first.size) < 0.3
                and ((ln.page == prev.page and not cross and 0 < ln.base - prev.base <= 1.7 * size)
                     or (ln.page == prev.page + 1 and ln.bstart))   # el pie sigue en la página siguiente
                and abs(ln.x0 - first.x0) < 2 * size and not CAPTION_RE.match(ln.text.strip())):
            return False               # pie de figura de varias líneas (título + descripción)
        txt = ln.text.lstrip()
        if LIST_RE.match(txt):
            return True
        # sangría francesa: el resto de un elemento de lista va alineado tras la viñeta
        hanging = (first is not None and LIST_RE.match(first.text.lstrip())
                   and ln.x0 >= first.x0 + 0.3 * size and ln.x0 <= first.x0 + 4 * size)
        indent, pind = ln.x0 - ln.gl, prev.x0 - prev.gl
        if not hanging and 0.9 * size < indent < 6 * size and indent - pind > 0.6 * size:
            return True
        term = bool(TERMINAL.search(prev.text))
        if not cross and (ln.base - prev.base) > c.lead * size * 1.3:
            return True
        short = prev.x1 < prev.gr - 1.8 * size
        if term and short:
            return True
        if ln.bstart and term and prev.x1 < prev.gr - 0.8 * size:
            return True
        return False

    # -- construcción de bloques
    def _make_heading(self, cur: _Cur):
        runs = _join(cur.lines, self.ctx.vocab)
        text = "".join(r[0] for r in runs).strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            return None
        return Block("h", html=esc(text), text=text, page=cur.lines[0].page, hkey=cur.key)

    def _make_code(self, lines: list[Line]):
        # ancho de carácter de la fuente monoespaciada, para pasar la sangría a espacios
        cw = [(l.x1 - l.x0) / len(l.text) for l in lines if len(l.text.strip()) >= 8]
        cw = sorted(cw)[len(cw) // 2] if cw else 0.6 * lines[0].size
        left = min(l.x0 for l in lines)
        gaps = sorted(b.base - a.base for a, b in zip(lines, lines[1:]) if a.page == b.page and b.base > a.base)
        pitch = gaps[len(gaps) // 2] if gaps else lines[0].size * 1.2
        rows = []
        for i, l in enumerate(lines):
            if i and l.page == lines[i - 1].page and l.base - lines[i - 1].base > 1.6 * pitch:
                rows.append("")            # línea en blanco del listado original
            ind = " " * max(0, round((l.x0 - left) / max(cw, 0.1)))
            rows.append(esc(ind) + _runs_html([r._replace(mono=False) for r in l.runs], True).rstrip())
        text = "\n".join(l.text for l in lines)
        return Block("code", html="\n".join(rows), text=text, page=lines[0].page)

    def _make_para(self, lines: list[Line], callout: bool = False):
        runs = _join(lines, self.ctx.vocab)
        text = re.sub(r"\s+", " ", "".join(r[0] for r in runs)).strip()
        if not text:
            return None
        first = lines[0]
        size = first.size
        colw = max(first.gr - first.gl, 1)
        cc = (first.gl + first.gr) / 2
        cls = []
        if callout:
            return Block("p", html=_runs_html(runs, self.ctx.ignore_mono), text=text,
                         page=first.page, cls="li")
        if first.toc:
            return Block("p", html=_runs_html(runs, self.ctx.ignore_mono), text=text,
                         page=first.page, cls="toc")
        if LIST_RE.match(text):
            cls.append("li")
        if "li" in cls:
            pass                        # una viñeta corta no es texto centrado ni cita
        elif (all(abs((l.x0 + l.x1) / 2 - cc) < 0.04 * colw and (l.x1 - l.x0) < 0.9 * colw for l in lines)
                and (first.x0 - first.gl) > 0.08 * colw):
            cls.append("center")
        elif all(l.x0 - l.gl > 0.3 * colw and abs(l.x1 - l.gr) < 0.03 * colw for l in lines):
            cls.append("right")
        elif all(l.x0 - l.gl > 2.2 * size for l in lines):
            cls.append("quote")
        return Block("p", html=_runs_html(runs, self.ctx.ignore_mono), text=text,
                     page=first.page, cls=" ".join(cls))


def _keep_hyphen(left: str, right: str, vocab) -> bool:
    """¿El guion de fin de línea es parte de la palabra (rule-based) y no un corte?"""
    lo, ro = left.lower(), right.lower()
    if not vocab or not lo or not ro:
        return False
    joined, hyph = vocab[lo + ro], vocab[lo + "-" + ro]
    if hyph or joined:
        return hyph > joined
    if ro in COMPOUND_TAILS and len(lo) >= 2:
        return True
    # sin evidencia directa: compuesto si ambas mitades son palabras conocidas
    return len(lo) >= 3 and len(ro) >= 3 and vocab[lo] >= 2 and vocab[ro] >= 2


def _join(lines: list[Line], vocab=None) -> list[list]:
    """Une líneas en una lista de runs, des-guionando cortes de palabra."""
    out: list[list] = []
    for i, ln in enumerate(lines):
        new = [list(r) for r in ln.runs]
        if i > 0 and out:
            tail = "".join(r[0] for r in out).rstrip(" ")
            head = ln.text.lstrip()[:1]
            sep = " "
            hyphen = tail[-1:] in ("-", "‐", "‑")
            left = re.search(r"([^\W\d_]+)[-‐‑]$", tail) if hyphen else None
            right = re.match(r"[^\W\d_]+", ln.text.lstrip()) if hyphen else None
            if tail.endswith("­"):
                _strip_end(out, "­")
                sep = ""
            elif hyphen and left and head.islower():
                if _keep_hyphen(left.group(1), right.group(0) if right else "", vocab):
                    _strip_end(out, "")       # conserva el guion, quita el espacio final
                else:
                    _strip_end(out, tail[-1])
                sep = ""
            elif hyphen and head and (head.isupper() or head.isdigit()):
                if left and right and vocab and vocab[(left.group(1) + right.group(0)).lower()] > \
                        vocab[(left.group(1) + "-" + right.group(0)).lower()]:
                    _strip_end(out, tail[-1])     # Chat-GPT -> ChatGPT
                sep = ""
            elif tail.endswith(("—", "/")) or head in ("—",):
                sep = ""
            if sep and new:
                new[0][0] = sep + new[0][0]
        out.extend(new)
    merged: list[list] = []
    for r in out:
        if merged and tuple(merged[-1][1:]) == tuple(r[1:]):
            merged[-1][0] += r[0]
        else:
            merged.append(r)
    for r in merged:
        r[0] = r[0].replace("­", "")
    # normalizar espacios entre runs
    text_all = re.sub(r" {2,}", " ", "".join(r[0] for r in merged))
    del text_all
    for i, r in enumerate(merged):
        r[0] = re.sub(r" {2,}", " ", r[0])
        if i and merged[i - 1][0].endswith(" ") and r[0].startswith(" "):
            r[0] = r[0][1:]
    if merged:
        merged[0][0] = merged[0][0].lstrip()
        merged[-1][0] = merged[-1][0].rstrip()
    return [r for r in merged if r[0]]


def _strip_end(runs: list[list], ch: str):
    for r in reversed(runs):
        t = r[0].rstrip(" ")
        if t:
            r[0] = t[: -len(ch)] if ch and t.endswith(ch) else t
            return


def _runs_html(runs, ignore_mono: bool) -> str:
    parts = []
    for text, bold, ital, sup, sub, mono, href in runs:
        if not text:
            continue
        core = text.strip(" ")
        lead = text[: len(text) - len(text.lstrip(" "))]
        trail = text[len(text.rstrip(" ")):] if core else ""
        if not core:
            parts.append(text)
            continue
        s = esc(core)
        if mono and not ignore_mono:
            s = f"<code>{s}</code>"
        if sup:
            s = f"<sup>{s}</sup>"
        if sub:
            s = f"<sub>{s}</sub>"
        if bold:
            s = f"<strong>{s}</strong>"
        if ital:
            s = f"<em>{s}</em>"
        if href:
            s = f'<a href="{html.escape(href)}">{s}</a>'
        parts.append(lead + s + trail)
    return "".join(parts)


# --------------------------------------------------------------------------- columnas
def detect_gutter(lines: list[Line]):
    if len(lines) < 6:
        return None
    x0, x1 = min(l.x0 for l in lines), max(l.x1 for l in lines)
    w = x1 - x0
    if w < 100:
        return None
    narrow = [l for l in lines if (l.x1 - l.x0) < 0.62 * w]
    if len(narrow) < 5:
        return None
    lo, hi = int(x0 + 0.3 * w), int(x0 + 0.7 * w)
    cover = [0] * (hi - lo + 2)
    for l in narrow:
        for x in range(max(lo, int(l.x0)), min(hi, int(l.x1)) + 1):
            cover[x - lo] += 1
    tol = max(1, int(0.04 * len(narrow)))
    best, start = None, None
    for i, c in enumerate(cover[:-1] + [tol + 1]):
        if c <= tol:
            start = i if start is None else start
        elif start is not None:
            if best is None or i - start > best[1]:
                best = (start, i - start)
            start = None
    if not best or best[1] < 9:
        return None
    g = lo + best[0] + best[1] / 2
    left = sum(1 for l in narrow if l.x1 <= g + 3)
    right = sum(1 for l in narrow if l.x0 >= g - 3)
    if left < 0.25 * len(narrow) or right < 0.25 * len(narrow):
        return None
    return g


def drop_glyph_dupes(lines: list[Line]) -> list[Line]:
    """Quita viñetas sueltas dibujadas encima de otra línea que ya las contiene."""
    out = []
    for l in lines:
        t = l.text.strip()
        if len(t) <= 2 and not any(ch.isalnum() for ch in t) and any(
                m is not l and m.x0 - 1 <= l.x0 and l.x1 <= m.x1 + 1
                and abs(m.base - l.base) < 0.5 * max(m.size, l.size) and t in m.text
                for m in lines):
            continue
        out.append(l)
    return out


def attach_markers(lines: list[Line]) -> list[Line]:
    """Pega a su texto los marcadores de lista sueltos ("1.", "•") en la misma línea base."""
    drop = set()
    for i, m in enumerate(lines):
        t = m.text.strip()
        if not MARKER_RE.match(t):
            continue
        cands = [l for l in lines if l is not m and abs(l.base - m.base) < 0.35 * l.size
                 and 0 <= l.x0 - m.x1 < 3 * l.size and not MARKER_RE.match(l.text.strip())]
        if not cands:
            continue
        tgt = min(cands, key=lambda l: l.x0)
        r0 = tgt.runs[0]
        tgt.runs = [r0._replace(text=t + " " + r0.text.lstrip())] + tgt.runs[1:]
        tgt.x0 = m.x0
        drop.add(i)
    return [l for i, l in enumerate(lines) if i not in drop]


def _trim_runs(runs: list, keep: int) -> list:
    out, n = [], 0
    for r in runs:
        if n >= keep:
            break
        out.append(r._replace(text=r.text[: keep - n]))
        n += len(r.text)
    return out


def mark_toc(lines: list[Line], body: float) -> None:
    """Página de índice impreso: entradas sin puntos guía ni números de página."""
    if sum(1 for l in lines if LEADER_RE.search(l.text)) < 5:
        return
    for l in lines:
        if l.size >= 1.8 * body:
            continue                    # el título "Índice"
        l.toc = True
        m = LEADER_RE.search(l.text)
        if m:
            l.leader = True
            l.runs = _trim_runs(l.runs, m.start()) or l.runs


def merge_same_row(lines: list[Line], gutter: float | None = None) -> list[Line]:
    """Une fragmentos que están en la misma línea visual (p. ej. números sueltos, o palabras de una
    línea justificada muy espaciada que el PDF trae por separado)."""
    lines = sorted(lines, key=lambda l: (round(l.cy), l.x0))
    out: list[Line] = []
    for ln in lines:
        if out:
            p = out[-1]
            gap = ln.x0 - p.x1
            wide_word_gap = (p.text.endswith(" ") and gap < 3 * ln.size and abs(p.base - ln.base) < 0.15 * ln.size
                             and not (gutter is not None and p.x1 <= gutter <= ln.x0))
            # número de sección separado de su título ("2.8.3      Closed Chain")
            sec_num = (SECNUM_RE.match(p.text.strip()) is not None and gap < 6 * ln.size
                       and abs(p.base - ln.base) < 0.15 * ln.size)
            if (abs(p.cy - ln.cy) < 0.3 * ln.size and 0 <= gap
                    and (gap < 0.7 * ln.size or wide_word_gap or sec_num)
                    and abs(p.size - ln.size) < 0.8):
                p.runs = p.runs + [Run(" ", False, False, False, False, False, None)] + ln.runs
                p.x1, p.y1 = max(p.x1, ln.x1), max(p.y1, ln.y1)
                p.toc, p.leader = p.toc or ln.toc, p.leader or ln.leader
                continue
        out.append(ln)
    return out


# --------------------------------------------------------------------------- figuras
def _grow(bbox: pymupdf.Rect, lines: list[Line], body: float) -> pymupdf.Rect:
    """Incluye en la figura las etiquetas cortas pegadas (números de ejes, leyendas)."""
    bbox = pymupdf.Rect(bbox)
    d = body * 1.2
    for _ in range(3):
        zone = pymupdf.Rect(bbox.x0 - d, bbox.y0 - d, bbox.x1 + d, bbox.y1 + d)
        grown = False
        for l in lines:
            r = pymupdf.Rect(l.x0, l.y0, l.x1, l.y1)
            t = l.text.strip()
            # etiqueta: corta, o en letra claramente menor que el cuerpo (leyendas, ejes); nunca un pie
            label = len(t) <= 14 or (l.size <= 0.85 * body and len(t) <= 45 and not CAPTION_RE.match(t))
            if label and l.size <= body * 1.15 and not bbox.contains(r) and zone.intersects(r):
                bbox |= r
                grown = True
        if not grown:
            break
    return bbox


def _components(rects: list[pymupdf.Rect], infl: float = 5.0, cell: float = 6.0):
    parent = list(range(len(rects)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    owner: dict = {}
    for i, r in enumerate(rects):
        cx0, cx1 = int((r.x0 - infl) // cell), int((r.x1 + infl) // cell)
        cy0, cy1 = int((r.y0 - infl) // cell), int((r.y1 + infl) // cell)
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                j = owner.setdefault((cx, cy), i)
                if j != i:
                    parent[find(i)] = find(j)
    groups: dict = {}
    for i, r in enumerate(rects):
        g = groups.setdefault(find(i), [pymupdf.Rect(r), []])
        g[0] |= r
        g[1].append(i)
    return list(groups.values())


def _inline_image(page: pymupdf.Page, bbox, store: dict):
    """Bytes de una imagen en línea (sin xref), buscada por su posición en la página."""
    if "blocks" not in store:
        store["blocks"] = [b for b in page.get_text("dict")["blocks"] if b["type"] == 1]
    r = pymupdf.Rect(bbox)
    for b in store["blocks"]:   # los bloques vienen recortados y no siempre coinciden al punto
        q = pymupdf.Rect(b["bbox"])
        inter = (q & r).get_area()
        if inter and inter >= 0.85 * max(q.get_area(), r.get_area()):
            return b.get("image")
    return None


def _flat_image(doc: pymupdf.Document, xref: int, cache: dict, data: bytes | None = None) -> bool:
    """¿Imagen sin detalle (degradado, sombra, color liso)? Se mira la proporción de bordes nítidos."""
    key = xref or (hash(data) if data else None)
    if key is None:
        return False
    if key in cache:
        return cache[key]
    flat = False
    try:
        pix = pymupdf.Pixmap(doc, xref) if xref else pymupdf.Pixmap(data)
        if pix.alpha or (pix.colorspace and pix.colorspace.n not in (1, 3)) or not pix.colorspace:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            if pix.alpha:
                pix = pymupdf.Pixmap(pix, 0)
        # sin reducir de más: a muy baja resolución una sombra difuminada parece un borde
        while pix.width > 320 and pix.height > 32:
            pix.shrink(1)
        w, h, n, s = pix.width, pix.height, pix.n, pix.samples
        gray = [sum(s[i:i + n]) / n for i in range(0, w * h * n, n)]
        diffs = sharp = 0
        for y in range(h):
            row = y * w
            for x in range(w):
                v = gray[row + x]
                if x + 1 < w:
                    diffs += 1
                    sharp += abs(v - gray[row + x + 1]) > 40
                if y + 1 < h:
                    diffs += 1
                    sharp += abs(v - gray[row + w + x]) > 40
        flat = diffs > 0 and sharp / diffs < 0.01
    except Exception as e:
        log.debug("No se pudo analizar la imagen %s: %s", key, e)
    cache[key] = flat
    return flat


def _straddled(r, lines) -> bool:
    """¿Hay texto corrido que entra y sale del rectángulo? Entonces es un fondo, no una figura."""
    return any(len(l.text.strip()) > 14 and l.y0 < r.y1 and l.y1 > r.y0 and l.x0 < r.x1 and l.x1 > r.x0
               and (l.x0 < r.x0 - 20 or l.x1 > r.x1 + 20) for l in lines)


def _mono_line(ln: Line) -> bool:
    chars = [(len(r.text.strip()), r.mono) for r in ln.runs if r.text.strip()]
    tot = sum(n for n, _ in chars)
    return tot > 0 and sum(n for n, m in chars if m) / tot >= 0.9


def _code_box(bbox, lines, rects_only: bool, page_w: float) -> bool:
    """Recuadro de fondo con un fragmento de código (o un marco vacío): es texto, no una figura."""
    inside = [l for l in lines if bbox.x0 <= (l.x0 + l.x1) / 2 <= bbox.x1 and bbox.y0 <= l.cy <= bbox.y1]
    if not inside:               # sin texto: marco de rectángulos o franja separadora
        return rects_only or (bbox.width > 0.6 * page_w and bbox.height < 0.2 * bbox.width)
    return sum(len(l.text.strip()) for l in inside) >= 8 and all(_mono_line(l) for l in inside)


def _text_box(bbox, lines, body: float) -> bool:
    """Recuadro de fondo liso con texto en una sola columna (p. ej. "En este capítulo")."""
    inside = [l for l in lines if bbox.x0 <= (l.x0 + l.x1) / 2 <= bbox.x1 and bbox.y0 <= l.cy <= bbox.y1]
    # texto corrido de verdad: las etiquetas sueltas de una gráfica («1», «2», «−5») no cuentan
    inside = [l for l in inside if len(l.text.strip()) >= 12]
    if len(inside) < 3:
        return False
    x0s = [l.x0 for l in inside]
    return max(x0s) - min(x0s) < 3 * body


def find_regions(page: pymupdf.Page, lines: list[Line], imgs: list, table_rects, repeated, body: float = 11.0,
                 flat_cache: dict | None = None):
    """Regiones gráficas (imágenes + dibujos vectoriales agrupados)."""
    pr = page.rect
    parea = pr.width * pr.height
    rects: list[pymupdf.Rect] = []
    raster: list[bool] = []
    native: list[float] = []
    flat: list[bool] = []          # sin detalle: imagen plana o solo rectángulos/rectas
    bleed: list[bool] = []
    boxy: list[bool] = []          # solo rectángulos (marcos, fondos)
    src: list = []                 # info de la imagen incrustada (None para dibujos)
    curvy: list[bool] = []         # dibujo con curvas (ilustración, no filete ni marco)
    strokes: list[int] = []        # número de trazos del dibujo
    inline: dict = {}
    cache = flat_cache if flat_cache is not None else {}
    outside = lambda q: q.x0 < pr.x0 - 1 or q.y0 < pr.y0 - 1 or q.x1 > pr.x1 + 1 or q.y1 > pr.y1 + 1
    for im in imgs:
        r = pymupdf.Rect(im["bbox"]) & pr
        if r.is_empty or r.width < 20 or r.height < 20:
            continue
        if r.width * r.height > 0.85 * parea:
            continue
        if im.get("xref") in repeated and r.width * r.height < 0.08 * parea:
            continue
        rects.append(r)
        raster.append(True)
        native.append(im["width"] / r.width * 72 if r.width else 0)
        xref = im.get("xref")
        flat.append(_flat_image(page.parent, xref, cache,
                                None if xref else _inline_image(page, r, inline)))
        bleed.append(outside(pymupdf.Rect(im["bbox"])))
        boxy.append(False)
        curvy.append(False)
        strokes.append(0)
        src.append(im)
    try:
        drawings = page.get_drawings()
    except Exception:
        drawings = []
    for d in drawings:
        r0 = pymupdf.Rect(d["rect"])
        r = pymupdf.Rect(r0.x0 - 0.5, r0.y0 - 0.5, r0.x1 + 0.5, r0.y1 + 0.5) & pr   # evita rectángulos de ancho 0
        if r.is_empty or r.is_infinite or r.width * r.height > 0.85 * parea:
            continue
        if min(r.width, r.height) < 1.5:
            # subrayados / tachados: líneas finas que tocan texto
            if r.width > r.height and any(
                    r.x0 >= l.x0 - 2 and r.x1 <= l.x1 + 2 and l.y1 - 0.4 * l.size <= r.y0 <= l.y1 + 2
                    for l in lines):
                continue      # subrayado de un texto
        if d.get("fill") == (1.0, 1.0, 1.0) and not d.get("color"):
            continue
        rects.append(r)
        raster.append(False)
        native.append(0)
        flat.append(all(it[0] in ("re", "qu", "l") for it in d["items"]))
        boxy.append(all(it[0] in ("re", "qu") for it in d["items"]))
        curvy.append(any(it[0] == "c" for it in d["items"]))
        strokes.append(len(d["items"]))
        bleed.append(outside(r0))
        src.append(None)
    # piezas decorativas (lisas o degradadas que sangran o quedan bajo texto corrido): fuera antes
    # de agrupar, para que no arrastren a un icono o a un recuadro vecino
    keep = [i for i in range(len(rects))
            if not (flat[i] and (bleed[i] or (raster[i] and _straddled(rects[i], lines))))]
    rects, raster, native, flat, boxy, src, curvy, strokes = ([seq[i] for i in keep]
                                              for seq in (rects, raster, native, flat, boxy, src, curvy, strokes))
    if not rects:
        return []
    out = []
    caplines = _caption_lines(lines)
    # iconos al margen (TIP, NOTE, WARNING...): piezas pequeñas fuera de la columna de texto. Se
    # agrupan aparte, antes que el resto, para que no se fundan con un recuadro o filete vecino.
    prose = [l for l in lines if len(l.text.strip()) > 30]
    if len(prose) >= 3:
        text_left, text_right = _pct([l.x0 for l in prose], 0.1), _pct([l.x1 for l in prose], 0.9)
        margin = [i for i, r in enumerate(rects)
                  if r.width <= 0.16 * pr.width and (r.x1 <= text_left + 2 or r.x0 >= text_right - 2)]
        if margin:
            used: set = set()
            for mbox, midx in _components([rects[i] for i in margin]):
                for ibox, iidx in _split_stack([rects[i] for i in margin], midx):
                    real = [margin[i] for i in iidx]
                    if ibox.width >= 12 and ibox.height >= 12 and not all(flat[i] for i in real):
                        out.append((ibox, any(raster[i] for i in real), None, None, "icon"))
                        used.update(real)
            # lo que no resultó ser un icono (parte de una figura que asoma al margen) sigue su curso
            rest = [i for i in range(len(rects)) if i not in used]
            rects, raster, native, flat, boxy, src, curvy, strokes = ([seq[i] for i in rest]
                                                      for seq in (rects, raster, native, flat, boxy, src, curvy, strokes))
    for bbox, idxs in _components(rects):
        # estrecho o bajo: solo es figura si es un dibujo denso (un mecanismo, un esquema a mano alzada)
        dense = min(bbox.width, bbox.height) >= 20 and sum(strokes[i] for i in idxs) >= 60
        if (bbox.width < 40 or bbox.height < 30) and not dense:
            continue
        if all(flat[i] for i in idxs) and (_straddled(bbox, lines) or _text_box(bbox, lines, body)
                                           or _code_box(bbox, lines, all(boxy[i] for i in idxs), pr.width)):
            continue
        has_raster = any(raster[i] for i in idxs)
        # pequeño y sin detalle (filete, marco suelto): fuera. Un dibujo pequeño con curvas o muchas
        # piezas (un mecanismo, un esquema) sí es una figura
        detailed = len(idxs) >= 12 or sum(curvy[i] for i in idxs) >= 3 or dense
        if bbox.width * bbox.height < 0.015 * parea and not has_raster and not detailed:
            continue
        bbox = _grow(bbox, [l for l in lines if id(l) not in caplines], body)
        if bbox.width > 0.92 * pr.width and bbox.height > 0.85 * pr.height:
            continue
        if any((bbox & t).get_area() > 0.5 * bbox.get_area() for t in table_rects):
            continue
        inside = [l for l in lines if bbox.x0 <= (l.x0 + l.x1) / 2 <= bbox.x1 and bbox.y0 <= l.cy <= bbox.y1]
        nchars = sum(len(l.text) for l in inside)
        if nchars > 500 and not has_raster:       # recuadro con texto corrido, no una figura
            continue
        nd = [native[i] for i in idxs if raster[i] and native[i]]
        # una sola imagen que ocupa toda la región: se pueden usar sus píxeles originales
        sole = None
        if len(idxs) == 1 and raster[idxs[0]] and src[idxs[0]] is not None and not inside:
            ib = pymupdf.Rect(src[idxs[0]]["bbox"])
            t = src[idxs[0]].get("transform") or (1, 0, 0, 1, 0, 0)
            if (abs(t[1]) < 1e-3 and abs(t[2]) < 1e-3 and t[0] > 0 and t[3] > 0
                    and ib.get_area() >= 0.9 * bbox.get_area() and (bbox & ib).get_area() >= 0.98 * ib.get_area()):
                sole = src[idxs[0]]
        out.append((bbox, has_raster, max(nd) if nd else None, sole, "fig"))
    # al crecer para incluir sus etiquetas, una figura puede invadir la de debajo (gráficas en
    # rejilla): se recorta donde empieza la otra para no duplicar trozos
    figs = sorted((i for i, o in enumerate(out) if o[4] == "fig"), key=lambda i: out[i][0].y0)
    for i in figs:
        top = out[i][0]
        for j in figs:
            low = out[j][0]
            if (j != i and low.y0 > top.y0 + 5 and low.y0 < top.y1 and low.x0 < top.x1 and low.x1 > top.x0
                    and low.y0 - top.y0 > 30):
                top = pymupdf.Rect(top.x0, top.y0, top.x1, low.y0 - 1)
        out[i] = (top,) + out[i][1:]
    return out


def _caption_lines(lines: list[Line]) -> set:
    """Líneas que forman un pie de figura ("Figura 3.1. ..." y sus líneas siguientes): una figura
    no debe tragarse la última línea corta de su pie como si fuera una etiqueta."""
    out: set = set()
    cur = None
    for l in sorted(lines, key=lambda l: (l.y0, l.x0)):
        t = l.text.strip()
        if CAPTION_RE.match(t) and re.match(r"^\S+\s*\d", t):
            cur = l
            out.add(id(l))
        elif (cur is not None and abs(l.size - cur.size) < 0.3 and abs(l.x0 - cur.x0) < 2 * l.size
              and 0 < l.base - cur.base <= 1.7 * l.size):
            cur = l
            out.add(id(l))
        else:
            cur = None
    return out


def _split_stack(rects, idxs, gap: float = 4.0):
    """Separa iconos apilados en el margen que el agrupado unió: corta por huecos verticales."""
    order = sorted(idxs, key=lambda i: rects[i].y0)
    groups: list[list[int]] = []
    bottom = None
    for i in order:
        if bottom is None or rects[i].y0 > bottom + gap:
            groups.append([])
            bottom = rects[i].y1
        groups[-1].append(i)
        bottom = max(bottom, rects[i].y1)
    out = []
    for g in groups:
        box = pymupdf.Rect(rects[g[0]])
        for i in g[1:]:
            box |= rects[i]
        # fila baja (la etiqueta «TIP», «REMEMBER»... dibujada con trazos) pegada debajo de un icono
        if out and box.height < 14 and box.y0 - out[-1][0].y1 < 12 and box.width <= out[-1][0].width * 1.6:
            out[-1] = (out[-1][0] | box, out[-1][1] + g)
            continue
        out.append((box, g))
    return out


# --------------------------------------------------------------------------- análisis principal
def _zone_rows(lines: list[Line], H: float) -> dict:
    """Texto de cada fila de cabecera/pie (líneas a la misma altura unidas): el folio y el título
    corrido suelen venir en líneas separadas ("1.2 Robot Mechanical Structure" ... "13")."""
    rows: dict = collections.defaultdict(list)
    for l in lines:
        if l.y1 < 0.12 * H or l.y0 > 0.88 * H:
            rows[round(l.base / 2)].append(l)
    out = {}
    for ls in rows.values():
        t = re.sub(r"\s+", " ", " ".join(x.text.strip() for x in sorted(ls, key=lambda x: x.x0))).strip()
        for x in ls:
            out[id(x)] = t
    return out


def analyze(doc: pymupdf.Document, opts: Opts, progress=None):
    ctx = Ctx(doc, opts)
    n = doc.page_count
    pages: list[PageInfo] = []
    size_count: collections.Counter = collections.Counter()
    pitches: list[float] = []
    xref_pages: dict[int, set] = collections.defaultdict(set)
    mono_chars = bold_chars = all_chars = 0
    shy_mid = hy_mid = 0

    # ---- pasada 1: extracción
    for pno in range(n):
        page = doc[pno]
        pr = page.rect
        imgs = page.get_image_info(xrefs=True)
        for im in imgs:
            if im.get("xref"):
                xref_pages[im["xref"]].add(pno)
        if opts.mode == "pages":
            pages.append(PageInfo(pno, [], imgs, "pageimg"))
            continue
        lines, bad, pit = extract_lines(page, pno)
        chars = sum(len(l.text.strip()) for l in lines)
        # texto fuera de las zonas de cabecera/pie: una página-imagen con solo el pie sigue siendo imagen
        body_chars = sum(len(l.text.strip()) for l in lines
                         if l.y1 >= 0.12 * pr.height and l.y0 <= 0.88 * pr.height)
        big_img = any(pymupdf.Rect(im["bbox"]).get_area() >= 0.8 * pr.width * pr.height for im in imgs)
        info = PageInfo(pno, lines, imgs)
        for l in lines:
            t = l.text
            shy_mid += len(SHY_MID_RE.findall(t))
            hy_mid += len(HY_MID_RE.findall(t))
        if body_chars < 25 and big_img:
            if opts.ocr:
                try:
                    tp = page.get_textpage_ocr(language=opts.ocr_lang, dpi=300, full=True)
                    info.lines, bad, pit = extract_lines(page, pno, tp)
                    info.ocr = True
                    chars = sum(len(l.text.strip()) for l in info.lines)
                except Exception as e:  # tesseract no instalado, etc.
                    log.warning("Página %d: OCR falló (%s); se usa imagen de página", pno + 1, e)
                    info.mode = "pageimg"
            else:
                info.mode = "pageimg"
                log.info("Página %d parece escaneada -> imagen (usa --ocr para extraer texto)", pno + 1)
        elif chars >= 30 and bad / max(chars, 1) > 0.08:
            if opts.fallback:
                info.mode = "pageimg"
                log.warning("Página %d tiene texto ilegible (%d%% basura) -> imagen de página", pno + 1,
                            100 * bad // max(chars, 1))
        elif chars == 0 and not imgs and not page.get_drawings():
            info.mode = "blank"
        if info.mode == "text":
            for l in info.lines:
                k = len(l.text.strip())
                size_count[round(l.size * 2) / 2] += k
                all_chars += k
                mono_chars += sum(len(r.text) for r in l.runs if r.mono)
                bold_chars += sum(len(r.text) for r in l.runs if r.bold)
            pitches.extend(pit)
        pages.append(info)
        if progress:
            progress("leyendo", pno + 1, n)

    # Algunos PDF usan el guion suave (U+00AD) como guion visible dentro de la línea ("Johnny­Five").
    # Si es lo habitual en el documento, se convierte en guion normal antes de nada.
    if shy_mid >= 5 and shy_mid > hy_mid:
        log.info("El PDF usa guiones suaves como guiones visibles (%d casos)", shy_mid)
        for info in pages:
            for l in info.lines:
                if any("­" in r.text for r in l.runs):
                    l.runs = [r._replace(text=r.text.replace("­", "-")) for r in l.runs]
    for info in pages:
        for l in info.lines:
            toks = [t.replace("‐", "-").replace("‑", "-").lower() for t in WORD_RE.findall(l.text)]
            for t in toks[1:-1]:           # la primera y la última pueden ser trozos de palabra
                ctx.vocab[t] += 1
                if "-" in t:
                    ctx.vocab.update(t.split("-"))

    if size_count:
        ctx.body = size_count.most_common(1)[0][0]
    if pitches:
        pitches.sort()
        ctx.lead = pitches[len(pitches) // 2]
    ctx.ignore_mono = all_chars > 0 and mono_chars / all_chars > 0.5
    ctx.bold_heading_ok = all_chars == 0 or bold_chars / all_chars < 0.4
    log.info("Cuerpo de texto: %.1f pt, interlineado %.2f, páginas: %d", ctx.body, ctx.lead, n)

    # ---- cabeceras / pies repetidos
    drop_keys: set = set()
    drop_bands: dict = collections.defaultdict(list)   # zona -> alturas de cabeceras/pies con folio
    if not opts.keep_headers and opts.mode != "pages":
        zone_pages: dict = collections.defaultdict(set)
        band_pages: dict = collections.defaultdict(set)
        for info in pages:
            if info.mode != "text":
                continue
            H = doc[info.pno].rect.height
            row = _zone_rows(info.lines, H)
            for l in info.lines:
                z = "t" if l.y1 < 0.12 * H else "b" if l.y0 > 0.88 * H else None
                if z:
                    key = (z, re.sub(r"\d+", "#", l.text.strip().lower()))
                    zone_pages[key].add(info.pno)
                    if NUMBERED_RE.search(row[id(l)]):
                        band_pages[(z, round(l.base))].add(info.pno)
        thr = max(3, int(0.25 * n))
        drop_keys = {k for k, v in zone_pages.items() if len(v) >= thr and k[1]}
        # títulos corridos que cambian en cada capítulo ("CAPÍTULO 3 Título  41"): se reconocen
        # por estar siempre a la misma altura y llevar el número de página
        for (z, y), ps in band_pages.items():
            near = set().union(*(v for (z2, y2), v in band_pages.items() if z2 == z and abs(y2 - y) <= 2))
            if len(near) >= thr:
                drop_bands[z].append(y)
    repeated_xrefs = {x for x, ps in xref_pages.items() if len(ps) >= max(3, 0.3 * n)}

    # ---- pasada 2: flujo
    blocks: list[Block] = []
    flow = Flow(ctx, blocks)
    last_g = None
    for info in pages:
        pno = info.pno
        page = doc[pno]
        pr = page.rect
        if info.mode == "blank":
            continue
        if info.mode == "pageimg":
            data, media, w, h = images.render_page(page, opts, has_photos=bool(info.imgs))
            a = ctx.add_asset(data, media, w, h)
            flow.hard_break(Block("pageimg", page=pno, asset=a, alt=f"Página {pno + 1}"))
            if progress:
                progress("convirtiendo", pno + 1, n)
            continue

        lines = info.lines
        # cabeceras/pies y números de página
        keep = []
        row = _zone_rows(lines, pr.height)
        for l in lines:
            z = "t" if l.y1 < 0.12 * pr.height else "b" if l.y0 > 0.88 * pr.height else None
            if z and not opts.keep_headers:
                t = l.text.strip()
                if (z, re.sub(r"\d+", "#", t.lower())) in drop_keys or PAGE_NUM_RE.match(t):
                    continue
                if NUMBERED_RE.search(row[id(l)]) and any(abs(l.base - y) <= 2 for y in drop_bands[z]):
                    continue
            keep.append(l)
        lines = attach_markers(drop_glyph_dupes(keep))
        mark_toc(lines, ctx.body)

        # tablas
        table_items = []
        table_rects = []
        try:
            for tab in page.find_tables().tables:
                rows = tab.extract()
                r = pymupdf.Rect(tab.bbox)
                # una "celda" con texto corrido largo es un recuadro alrededor de prosa, no una tabla;
                # una rejilla casi vacía son las barras y guías de una gráfica: va como dibujo
                cells = [c for row in rows for c in row]
                empty = sum(1 for c in cells if not (c or "").strip()) / max(len(cells), 1)
                if (len(rows) >= 2 and rows and len(rows[0]) >= 2 and r.width > 0.2 * pr.width
                        and any(c and c.strip() for c in cells) and empty < 0.85
                        and max(len(c or "") for c in cells) <= 300):
                    table_rects.append(r)
                    table_items.append((r, rows, tab))
        except Exception as e:
            log.debug("find_tables falló en pág %d: %s", pno + 1, e)
        for r, rows in rule_tables(page, lines, ctx.body):
            if not any((r & t).get_area() > 0.3 * r.get_area() for t in table_rects):
                table_rects.append(r)
                table_items.append((r, rows, None))

        # regiones gráficas
        regions = find_regions(page, lines, info.imgs, table_rects, repeated_xrefs, ctx.body, ctx.flat_cache)
        covered = [r for r, *_ in regions] + table_rects
        if info.ocr:
            covered = table_rects
        lines = [l for l in lines
                 if not any(r.x0 - 1 <= (l.x0 + l.x1) / 2 <= r.x1 + 1 and r.y0 - 1 <= l.cy <= r.y1 + 1 for r in covered)]

        # separar notas al pie (líneas pequeñas al final de la página)
        lines = merge_same_row(lines, detect_gutter(lines))
        g = detect_gutter(lines)
        if g is None and last_g is not None and len(lines) >= 4:
            cross = sum(1 for l in lines if l.x0 < last_g - 3 and l.x1 > last_g + 3)
            wide = sum(1 for l in lines if (l.x1 - l.x0) > 0.62 * (max(x.x1 for x in lines) - min(x.x0 for x in lines)))
            if cross <= 0.1 * len(lines) and wide <= 0.2 * len(lines):
                g = last_g         # página casi vacía de una maquetación a dos columnas
        last_g = g if g is not None else (last_g if not lines else None)
        for l in lines:
            if g is None:
                l.col = 0
            elif l.x1 <= g + 3:
                l.col = 0
            elif l.x0 >= g - 3:
                l.col = 1
            else:
                l.col = -1
        if g is None:
            lines.sort(key=lambda l: (l.y0, l.x0))
        # geometría de columna
        groups = collections.defaultdict(list)
        for l in lines:
            groups[l.col].append(l)
        allw = [l for l in lines if l.size >= ctx.body * 0.9] or lines
        geo_all = (_pct([l.x0 for l in allw], 0.1), _pct([l.x1 for l in allw], 0.9)) if allw else (0, pr.width)
        geo = {}
        for c, ls in groups.items():
            # el margen izquierdo lo marca el texto corrido, no títulos ni recuadros en negrita
            ls2 = ([l for l in ls if abs(l.size - ctx.body) < 0.6 and l.bold_frac < 0.5]
                   or [l for l in ls if l.size >= ctx.body * 0.9] or ls)
            geo[c] = (_pct([l.x0 for l in ls2], 0.1), _pct([l.x1 for l in ls2], 0.9)) if c != -1 else geo_all
        for l in lines:
            l.gl, l.gr = geo.get(l.col, geo_all)
        # elementos no textuales
        items: list = [("line", l.y0, l.x0, l.col, l) for l in lines]
        tw = geo_all[1] - geo_all[0]
        for r, has_raster, nat, sole, rkind in regions:
            if info.ocr:
                continue
            if rkind == "icon":
                res = images.render_icon(page, r, opts)
                if res:
                    blk = Block("img", page=pno, asset=ctx.add_asset(*res), alt="Icono", cls="icon")
                    # antes de la primera línea que tiene al lado
                    items.append(("obj", r.y0 - 0.6 * ctx.body, -1, 0 if g is None else (0 if r.x1 <= g else 1), blk))
                continue
            res = images.render_clip(page, r, opts, nat, sole)
            if res:
                a = ctx.add_asset(*res)
                blk = Block("img", page=pno, asset=a, alt=f"Figura (página {pno + 1})",
                            width_pct=int(max(25, min(100, r.width / max(tw, 1) * 100))))
                col = -1 if (g is None or r.width > 0.55 * tw or (r.x0 < g < r.x1)) else (0 if r.x1 <= g + 3 else 1)
                items.append(("obj", r.y0, r.x0, col, blk))
        for r, rows, tab in table_items:
            blk = _table_block(page, r, rows, tab, pno, ctx, tw)
            if blk:
                col = -1 if (g is None or r.width > 0.55 * tw or (r.x0 < g < r.x1)) else (0 if r.x1 <= g + 3 else 1)
                items.append(("obj", r.y0, r.x0, col, blk))
        items.sort(key=lambda it: (it[1], it[2]))
        if g is not None:
            ordered, L, R = [], [], []
            for it in items:
                if it[3] == -1:
                    ordered += L + R + [it]
                    L, R = [], []
                elif it[3] == 0:
                    L.append(it)
                else:
                    R.append(it)
            items = ordered + L + R
        items = _title_first(items, ctx.body)

        # notas al pie: cola de líneas pequeñas en la zona baja
        foot: list[Line] = []
        main_items = items
        tail = []
        caps = _caption_lines(lines)      # un pie de figura al final de la página no es una nota
        for it in reversed(items):
            if (it[0] == "line" and it[4].size <= ctx.body * 0.9 and it[4].y0 > 0.55 * pr.height
                    and id(it[4]) not in caps):
                tail.append(it)
            else:
                break
        if tail and len(tail) < len(items):
            foot = [it[4] for it in reversed(tail)]
            main_items = items[: len(items) - len(tail)]

        for kind, _, _, _, obj in main_items:
            if kind == "line":
                flow.feed(obj)
            else:
                flow.add_object(obj)
        if foot:
            fblocks: list[Block] = []
            ff = Flow(ctx, fblocks, "fn")
            for l in foot:
                ff.feed(l)
            ff.close()
            for b in fblocks:
                flow.add_object(b)
            flow.after_obj = False
        if progress:
            progress("convirtiendo", pno + 1, n)
    flow.close()
    return blocks, ctx


def _title_first(items: list, body: float) -> list:
    """Página que abre capítulo con un recuadro ("En este capítulo") encima del título:
    el título va primero para que el recuadro quede dentro de su capítulo."""
    big = lambda it: it[0] == "line" and it[4].size >= 1.5 * body and len(it[4].text.strip()) > 1
    k = next((i for i, it in enumerate(items) if big(it) and it[4].size >= 2.2 * body), None)
    if not k or any(it[0] != "line" for it in items[:k]):
        return items
    if any(big(it) for it in items[:k]):
        return items                    # ya hay otro título antes: no es un recuadro previo
    end = k + 1
    while end < len(items) and big(items[end]):   # sin la letra capital, que va con su párrafo
        end += 1
    return items[k:end] + items[:k] + items[end:]


def rule_tables(page: pymupdf.Page, lines: list[Line], body: float):
    """Tablas sin rejilla (estilo booktabs): dos o más filetes horizontales de la misma anchura con
    texto en columnas entre ellos. find_tables no las ve porque busca celdas cerradas."""
    pr = page.rect
    try:
        drawings = page.get_drawings()
    except Exception:
        return []
    rules = sorted((pymupdf.Rect(d["rect"]) for d in drawings
                    if d["rect"].height < 1.5 and d["rect"].width > 0.3 * pr.width), key=lambda r: r.y0)
    spans: list[list[pymupdf.Rect]] = []
    for r in rules:                               # filetes con los mismos extremos
        for sp in spans:
            if abs(sp[0].x0 - r.x0) < 3 and abs(sp[0].x1 - r.x1) < 3:
                if r.y0 - sp[-1].y0 > 1:          # ignora dobles trazos
                    sp.append(r)
                break
        else:
            spans.append([r])
    out = []
    for sp in spans:
        runs: list[list[pymupdf.Rect]] = [[sp[0]]]
        for r in sp[1:]:
            if r.y0 - runs[-1][-1].y1 > 0.5 * pr.height:
                runs.append([r])
            else:
                runs[-1].append(r)
        for run in runs:
            if len(run) < 2:
                continue
            box = pymupdf.Rect(run[0].x0, run[0].y0, run[-1].x1, run[-1].y1)
            inside = [l for l in lines if box.y0 < l.cy < box.y1 and l.x0 >= box.x0 - 3 and l.x1 <= box.x1 + 3]
            if (not inside
                    or any(len(l.text.strip()) > 30 and l.x1 - l.x0 > 0.5 * box.width for l in inside)
                    or any(_mono_line(l) for l in inside)):
                continue          # frases o código entre los filetes (recuadros de listados): no es una tabla
            # filas: solo con el texto de tamaño normal; superíndices y subíndices (que PyMuPDF da
            # como líneas sueltas a otra altura) van a la fila más cercana
            big = max(l.size for l in inside)
            rows: list[list[Line]] = []
            for l in sorted((l for l in inside if l.size >= 0.85 * big), key=lambda l: l.base):
                if rows and abs(l.base - rows[-1][0].base) < 0.5 * l.size:
                    rows[-1].append(l)
                else:
                    rows.append([l])
            for l in inside:
                if l.size < 0.85 * big and rows:
                    min(rows, key=lambda row: abs(row[0].cy - l.cy)).append(l)
            multi = sum(1 for row in rows if len(row) >= 2)
            if len(rows) < 2 or multi < 0.6 * len(rows):
                continue
            # columnas: centros de las piezas agrupados en horizontal
            centers = sorted((l.x0 + l.x1) / 2 for l in inside)
            cols = [[centers[0]]]
            for c in centers[1:]:
                if c - cols[-1][-1] > 1.2 * body:
                    cols.append([c])
                else:
                    cols[-1].append(c)
            cx = [sum(c) / len(c) for c in cols]
            if len(cx) < 2:
                continue
            # cada columna debe tener contenido en la mayoría de las filas, como en una tabla de verdad
            used = [set() for _ in cx]
            for n, row in enumerate(rows):
                for l in row:
                    used[min(range(len(cx)), key=lambda k: abs(cx[k] - (l.x0 + l.x1) / 2))].add(n)
            if any(len(u) < 0.5 * len(rows) for u in used):
                continue
            matrix = []
            head_end = run[1].y0 if len(run) >= 3 else None   # el segundo filete cierra la cabecera
            for row in rows:
                cells = [""] * len(cx)
                for l in sorted(row, key=lambda l: l.x0):
                    if l.size < 0.85 * big:   # índice: a la columna cuya pieza tiene justo a la izquierda
                        k = min(range(len(cx)), key=lambda k: abs(cx[k] - l.x0))
                    else:
                        k = min(range(len(cx)), key=lambda k: abs(cx[k] - (l.x0 + l.x1) / 2))
                    cells[k] = (cells[k] + " " + l.text.strip()).strip()
                if head_end is not None and matrix and row[0].cy < head_end:
                    matrix[0] = [(a + " " + b).strip() for a, b in zip(matrix[0], cells)]   # cabecera en 2 líneas
                else:
                    matrix.append(cells)
            out.append((box + (0, -2, 0, 2), matrix))
    return out


def _table_block(page, r, rows, tab, pno, ctx, tw):
    if ctx.opts.tables == "html":
        out = ["<table>"]
        for i, row in enumerate(rows):
            head = tab is None or (getattr(tab, "header", None) and not tab.header.external)
            tag = "th" if i == 0 and head else "td"
            cells = "".join(f"<{tag}>{esc(clean(c or '').strip())}</{tag}>" for c in row)
            out.append(f"<tr>{cells}</tr>")
        out.append("</table>")
        return Block("table", html="".join(out), page=pno)
    res = images.render_clip(page, r, ctx.opts, None)
    if not res:
        return None
    a = ctx.add_asset(*res)
    return Block("img", page=pno, asset=a, alt=f"Tabla (página {pno + 1})", cls="table",
                 width_pct=int(max(40, min(100, r.width / max(tw, 1) * 100))))
