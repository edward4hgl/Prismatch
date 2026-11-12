"""Scanned-PDF text recovery: render pages with PyMuPDF, recognise with the
Windows built-in OCR engine (Windows.Media.Ocr, zh-Hans model).

No extra download, no bundled model: the engine ships with Windows 10/11 and
handles Chinese well on clean 300 dpi scans. A PowerShell child process drives
the WinRT API through System.Runtime.WindowsRuntime (Windows PowerShell 5.1 is
required - PowerShell 7 cannot project the WinRT types).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

CJK = "\u2e80-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef"
_RE_CJK_GAP = re.compile(r"(?<=[%s])[ \t]+(?=[%s])" % (CJK, CJK))
_RE_PUNCT_L = re.compile(r"(?<=[\u3000-\u303f\uff00-\uffef])[ \t]+")
_RE_PUNCT_R = re.compile(r"[ \t]+(?=[\u3000-\u303f\uff00-\uffef])")
_RE_MULTI = re.compile(r"[ \t]{2,}")
_RE_MIDDOT = re.compile(r"(?<=\d)[ \t]*[\u00b7\u30fb\u2022\uff65][ \t]*(?=\d)")
_SENT_END = "。！？；：!?;:…）)】」』\"' ”’"

_PS_CANDIDATES = [
    os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                 "WindowsPowerShell", "v1.0", "powershell.exe"),
    "powershell.exe",
]


def _script_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr_win.ps1")


def _powershell() -> str:
    for cand in _PS_CANDIDATES:
        if os.path.isabs(cand):
            if os.path.exists(cand):
                return cand
            continue
        found = shutil.which(cand)
        if found:
            return found
    return ""


def available() -> bool:
    if not sys.platform.startswith("win"):
        return False
    return bool(_powershell()) and os.path.exists(_script_path())


def _fitz():
    try:
        import pymupdf  # PyMuPDF >= 1.24
        return pymupdf
    except Exception:
        try:
            import fitz  # legacy name
            return fitz
        except Exception:
            return None


def page_count(data: bytes) -> int:
    mod = _fitz()
    if mod is None:
        return 0
    try:
        with mod.open(stream=data, filetype="pdf") as doc:
            return int(doc.page_count)
    except Exception:
        return 0


def tidy(text: str) -> str:
    """Undo the OCR habit of putting a space between every Chinese glyph."""
    s = text or ""
    if not s:
        return ""
    s = _RE_MIDDOT.sub(".", s)
    s = _RE_CJK_GAP.sub("", s)
    s = _RE_PUNCT_L.sub("", s)
    s = _RE_PUNCT_R.sub("", s)
    s = _RE_MULTI.sub(" ", s)
    return s.strip()


_NEW_ITEM = re.compile(r"^[（(]?\d{1,2}[）).、．]|^[\u2460-\u2473]|^第[一二三四五六七八九十]+[条章节]")
_CJK_TAIL = re.compile(r"[%s]$" % CJK)


def _should_join(prev: str, nxt: str) -> bool:
    if not prev or prev[-1] in _SENT_END:
        return False
    if len(prev) < 15:          # short line: heading, caption or bare number
        return False
    if _NEW_ITEM.match(nxt):    # numbered clause starts a new block
        return False
    return True


def _merge_lines(lines):
    """Glue wrapped lines back together; keep headings and numbered items apart."""
    out = []
    for raw in lines:
        s = tidy(raw)
        if not s:
            continue
        if out and _should_join(out[-1], s):
            prev = out[-1]
            joiner = "" if _CJK_TAIL.search(prev) else " "
            out[-1] = prev + joiner + s
        else:
            out.append(s)
    return out


def ocr_pdf(data: bytes, pages=None, max_pages: int = 0, dpi: int = 300,
            progress=None, cancel=None):
    """OCR the pages a PDF has no text layer for.

    pages: 1-based page numbers to recognise; None means every page.
    max_pages: 0 = no limit (only used as an emergency stop).
    Return (blocks, meta); blocks: [(page_no, text)], meta carries
    pages_total / pages_asked / pages_done / lang / truncated / error.
    Never raises: any failure yields ([], meta with error).
    """
    meta = {"pages_total": 0, "pages_asked": 0, "pages_done": 0,
            "lang": "", "truncated": False, "error": ""}
    mod = _fitz()
    if mod is None:
        meta["error"] = "no_pymupdf"
        return [], meta
    if not available():
        meta["error"] = "no_ocr_engine"
        return [], meta

    tmp = tempfile.mkdtemp(prefix="prismatch_ocr_")
    try:
        try:
            doc = mod.open(stream=data, filetype="pdf")
        except Exception as exc:
            meta["error"] = "open_failed: %s" % exc
            return [], meta
        try:
            total = int(doc.page_count)
            meta["pages_total"] = total
            if pages is None:
                want = list(range(1, total + 1))
            else:
                want = sorted({int(p) for p in pages if 1 <= int(p) <= total})
            meta["pages_asked"] = len(want)
            if max_pages > 0 and len(want) > max_pages:
                want = want[:max_pages]
                meta["truncated"] = True
            done = 0
            for page in want:
                if cancel is not None and cancel.is_set():
                    meta["error"] = "cancelled"
                    break
                try:
                    pix = doc[page - 1].get_pixmap(dpi=dpi)
                    pix.save(os.path.join(tmp, "p%05d.png" % page))
                except Exception:
                    continue
                done += 1
                if progress is not None:
                    try:
                        progress(done, len(want))
                    except Exception:
                        pass
            meta["pages_done"] = done
        finally:
            doc.close()

        pngs = sorted(f for f in os.listdir(tmp) if f.endswith(".png"))
        if not pngs:
            meta["error"] = meta["error"] or "render_failed"
            return [], meta

        out_json = os.path.join(tmp, "ocr.json")
        cmd = [
            _powershell(), "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", _script_path(),
            "-Dir", tmp, "-OutFile", out_json,
        ]
        try:
            subprocess.run(
                cmd, capture_output=True, timeout=max(120, 25 * len(pngs)),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            meta["error"] = "ocr_timeout"
            return [], meta
        except Exception as exc:
            meta["error"] = "ocr_failed: %s" % exc
            return [], meta

        if not os.path.exists(out_json):
            meta["error"] = "ocr_no_output"
            return [], meta
        try:
            with open(out_json, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception as exc:
            meta["error"] = "ocr_bad_json: %s" % exc
            return [], meta

        if not payload.get("ok"):
            meta["error"] = "ocr_engine: %s" % payload.get("error", "?")
            return [], meta
        meta["lang"] = payload.get("lang") or ""

        blocks = []
        for row in payload.get("pages") or []:
            name = row.get("file") or ""
            digits = re.sub(r"\D", "", name)
            page = int(digits) if digits else 0
            lines = row.get("lines") or []
            merged = _merge_lines(lines)
            if merged:
                blocks.append((page, "\n".join(merged)))
        if not blocks:
            meta["error"] = meta["error"] or "ocr_empty"
        return blocks, meta
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
