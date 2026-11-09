"""Similarity primitives and perceptual image hashing."""
from __future__ import annotations

import io
from collections import Counter

from . import text as T

EDIT_CAP = 400


def weighted_dice(tok_a, tok_b) -> float:
    """Weighted multiset overlap (weight = token length), same shape as the
    original tool's getSimilarList but computed over pre-tokenised lists."""
    if not tok_a or not tok_b:
        return 0.0
    ca = Counter(tok_a)
    cb = Counter(tok_b)
    total_a = sum(len(k) * v for k, v in ca.items())
    total_b = sum(len(k) * v for k, v in cb.items())
    if total_a == 0 or total_b == 0:
        return 0.0
    common = 0
    for k, v in ca.items():
        if k in cb:
            common += len(k) * min(v, cb[k])
    return (2.0 * common) / (total_a + total_b)


def edit_distance(a: str, b: str, cap: int = EDIT_CAP) -> int:
    if len(a) > cap:
        a = a[:cap]
    if len(b) > cap:
        b = b[:cap]
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def edit_similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    m = max(len(a), len(b))
    if m == 0:
        return 1.0
    return 1.0 - edit_distance(a, b) / m


def similarity(text_a: str, text_b: str, tok_a=None, tok_b=None) -> float:
    """0.4 * normalised edit distance + 0.6 * weighted token overlap."""
    if not text_a or not text_b:
        return 0.0
    if abs(len(text_a) - len(text_b)) > max(len(text_a), len(text_b)):
        return 0.0
    ta = tok_a if tok_a is not None else T.tokens(text_a)
    tb = tok_b if tok_b is not None else T.tokens(text_b)
    dice = weighted_dice(ta, tb)
    if dice < 0.2:
        return 0.0
    return 0.4 * edit_similarity(text_a, text_b) + 0.6 * dice


# ------------------------------------------------------------------- images

def dhash(data: bytes) -> int | None:
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        px = list(img.getdata())
        bits = 0
        for row in range(8):
            for col in range(8):
                left = px[row * 9 + col]
                right = px[row * 9 + col + 1]
                bits = (bits << 1) | (1 if left > right else 0)
        return bits
    except Exception:
        return None


def image_similar(h1: int, h2: int, threshold: int = 6) -> bool:
    return h1 is not None and h2 is not None and (h1 ^ h2).bit_count() <= threshold
