"""Limpieza de texto extraído del PDF (caracteres raros, ligaduras, etc.)."""
from __future__ import annotations

import re
import unicodedata

LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
    "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st", "Ĳ": "IJ", "ĳ": "ij",
}
_CID = re.compile(r"\(cid:\d+\)")
_PUA = re.compile("[-]")
# Caracteres ilegales en XML 1.0 + controles C1 + zero-width + FFFD
_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f�￾￿​‌‍⁠﻿]")
_SPACES = re.compile("[   -   　\t]")
# Acento suelto antes de la letra (PDFs de LaTeX con fuentes antiguas): "´a" -> "á"
_ACCENT = re.compile("([´¨˜])([aeiouAEIOUnNuU])")
_ACC_MAP = {"´": "́", "¨": "̈", "˜": "̃"}


def garble_count(raw: str) -> int:
    """Cuenta caracteres que delatan una extracción fallida."""
    return len(_PUA.findall(raw)) + raw.count("�") + 5 * len(_CID.findall(raw))


def clean(text: str) -> str:
    if not text:
        return ""
    text = _CID.sub("", text)
    text = _PUA.sub("", text)
    for k, v in LIGATURES.items():
        if k in text:
            text = text.replace(k, v)
    text = _SPACES.sub(" ", text)
    text = _BAD.sub("", text)
    if "´" in text or "¨" in text or "˜" in text:
        text = _ACCENT.sub(lambda m: m.group(2) + _ACC_MAP[m.group(1)], text)
    return unicodedata.normalize("NFC", text)   # NFC (no NFKC): respeta ª º ² etc.
