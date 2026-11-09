"""Text normalisation, paragraph/sentence segmentation, tokenisation and fingerprints."""
from __future__ import annotations

import hashlib
import re
import unicodedata

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
ASCII_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+\-'.]*")
SPACE_RE = re.compile(r"[\s\u3000\xa0]+")
REF_RE = re.compile(r"^\[\d{1,3}\].+")
END_CHARS = "。！？!?；;…"
CLOSERS = "”’\"')）】》」』"

# sentence chunking
MAX_SENT = 150
CHUNK = 100
OVERLAP = 20

CH_SEN_LOWER = 5
EN_SEN_LOWER = 3


def normalize(text: str) -> str:
    """NFKC, unify spaces/newlines, drop control chars and lone surrogates."""
    if not text:
        return ""
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in text):
        text = "".join(ch for ch in text if not (0xD800 <= ord(ch) <= 0xDFFF))
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return text


def cjk_count(text: str) -> int:
    return sum(1 for ch in text if CJK_RE.match(ch))


def cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    return cjk_count(text) / len(text)


def word_count(text: str) -> int:
    return len(ASCII_WORD_RE.findall(text))


def is_reference(text: str) -> bool:
    t = text.strip()
    if not REF_RE.match(t):
        return False
    if cjk_ratio(t) < 0.2:
        return word_count(t) <= 20
    return len(t) <= 40


def is_main_text(text: str) -> bool:
    t = SPACE_RE.sub("", text).strip()
    if not t:
        return False
    if cjk_ratio(t) < 0.2:
        return word_count(t) >= 4
    return len(t) >= 20


def para_type(text: str) -> int:
    """0 = main text, 1 = reference/footnote, 2 = other (ignored)."""
    if is_reference(text):
        return 1
    if is_main_text(text):
        return 0
    return 2


def split_sentences(text: str):
    """Return [(start, end)] spans of sentences, offsets into ``text``."""
    spans = []
    n = len(text)
    start = 0
    i = 0
    while i < n:
        ch = text[i]
        cut = False
        if ch in END_CHARS:
            cut = True
        elif ch == ".":
            nxt = text[i + 1] if i + 1 < n else ""
            prev = text[i - 1] if i > 0 else ""
            if nxt == "" or nxt.isspace() or CJK_RE.match(prev or " "):
                cut = True
        elif ch == "\n":
            cut = True
        if cut:
            j = i + 1
            while j < n and (text[j] in END_CHARS or text[j] in CLOSERS or text[j] == "\n"):
                j += 1
            if j > start:
                spans.append((start, j))
            start = j
            i = j
            continue
        i += 1
    if start < n:
        spans.append((start, n))
    return spans


def chunk_span(text: str, start: int, end: int):
    """Split a very long sentence into overlapping chunks (offsets preserved)."""
    if end - start <= MAX_SENT:
        return [(start, end)]
    out = []
    s = start
    while s < end:
        e = min(s + CHUNK, end)
        out.append((s, e))
        if e >= end:
            break
        s = e - OVERLAP
    return out


def segments(text: str):
    """Yield (start, end) indexable segments: sentences, then chunks."""
    for s, e in split_sentences(text):
        seg = text[s:e]
        stripped = seg.strip()
        if not stripped:
            continue
        if cjk_ratio(seg) < 0.2:
            if word_count(seg) < EN_SEN_LOWER:
                continue
        elif len(stripped) < CH_SEN_LOWER:
            continue
        for cs, ce in chunk_span(text, s, e):
            if text[cs:ce].strip():
                yield cs, ce


# ---------------------------------------------------------------- tokenisation

def tokens(text: str):
    """Token list. CJK: character bigrams (dictionary-free, robust).
    ASCII: words. Digits are grouped."""
    text = normalize(text)
    out = []
    cjk_run = []

    def flush():
        if not cjk_run:
            return
        run = "".join(cjk_run)
        if len(run) == 1:
            out.append(run)
        else:
            for k in range(len(run) - 1):
                out.append(run[k:k + 2])
        cjk_run.clear()

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if CJK_RE.match(ch):
            cjk_run.append(ch)
            i += 1
            continue
        flush()
        if ch.isalnum() and ord(ch) < 128:
            j = i
            while j < n and text[j].isalnum() and ord(text[j]) < 128:
                j += 1
            out.append(text[i:j].lower())
            i = j
            continue
        i += 1
    flush()
    return out


def gram_hashes(text: str, n: int = 3):
    """Set of 64-bit hashes of character n-grams over whitespace-stripped text."""
    t = SPACE_RE.sub("", normalize(text)).lower()
    if len(t) < n:
        return set()
    out = set()
    for i in range(len(t) - n + 1):
        g = t[i:i + n]
        if g.isdigit():
            continue
        out.add(int.from_bytes(hashlib.blake2b(g.encode("utf-8", "replace"), digest_size=8).digest(), "big"))
    return out


def simhash(gram_set) -> int:
    if not gram_set:
        return 0
    bits = [0] * 64
    for h in gram_set:
        for b in range(64):
            if (h >> b) & 1:
                bits[b] += 1
            else:
                bits[b] -= 1
    out = 0
    for b in range(64):
        if bits[b] > 0:
            out |= (1 << b)
    return out


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()
