"""Old binary .doc -> .docx through Microsoft Word automation.

Word gives us the real layout (tables, headings, bold) which the hand-rolled
OLE/piece-table reader can never recover; the produced .docx then flows through
the normal docx path (mammoth HTML + python-docx text).

The transfer is done inside a *single* Word instance: starting Word costs ~5 s,
each extra document only ~0.5-2 s. Results are cached by source digest so a
re-run of the same bid folder costs nothing.
"""
from __future__ import annotations

import hashlib
import os
import threading

_LOCK = threading.Lock()
_AVAILABLE = None


def available() -> bool:
    """True when win32com is importable (Word itself is probed on first use)."""
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            import win32com.client  # noqa: F401
            _AVAILABLE = True
        except Exception:
            _AVAILABLE = False
    return bool(_AVAILABLE)


def _digest(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _cache_file(cache_dir: str, data: bytes) -> str:
    return os.path.join(cache_dir, _digest(data) + ".docx")


def _read_cache(cache_dir: str, data: bytes):
    if not cache_dir:
        return None
    path = _cache_file(cache_dir, data)
    try:
        if os.path.getsize(path) > 0:
            with open(path, "rb") as fh:
                return fh.read()
    except OSError:
        return None
    return None


def _write_cache(cache_dir: str, data: bytes, docx: bytes) -> None:
    if not cache_dir:
        return
    try:
        os.makedirs(cache_dir, exist_ok=True)
        path = _cache_file(cache_dir, data)
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(docx)
        os.replace(tmp, path)
    except OSError:
        pass


def _run_word(jobs, out, cache_dir, work_dir, progress, cancel):
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        try:
            word.Visible = False
            word.DisplayAlerts = 0
        except Exception:
            pass
        try:  # disable macros from untrusted documents
            word.AutomationSecurity = 3
        except Exception:
            pass

        for done, (key, src, data) in enumerate(jobs, start=1):
            if cancel is not None and cancel.is_set():
                break
            dst = os.path.join(work_dir, "out_%s.docx" % key)
            doc = None
            try:
                doc = word.Documents.Open(
                    src,
                    ConfirmConversions=False,
                    ReadOnly=True,
                    AddToRecentFiles=False,
                )
                doc.SaveAs2(dst, FileFormat=16)  # wdFormatXMLDocument
                with open(dst, "rb") as fh:
                    blob = fh.read()
                if blob.startswith(b"PK"):
                    out[key] = blob
                    _write_cache(cache_dir, data, blob)
                else:
                    out[key] = None
            except Exception:
                out[key] = None
            finally:
                if doc is not None:
                    try:
                        doc.Close(False)
                    except Exception:
                        pass
                try:
                    if os.path.exists(dst):
                        os.remove(dst)
                except OSError:
                    pass
            if progress is not None:
                try:
                    progress(done, len(jobs))
                except Exception:
                    pass
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def convert_batch(pairs, cache_dir="", progress=None, cancel=None):
    """pairs: [(key, bytes | path)]. Returns {key: docx bytes | None}.

    Never raises: a document Word cannot open simply maps to None and the
    caller falls back to the legacy text reader.
    """
    out = {}
    if not available() or not pairs:
        return out

    todo = []
    work_dir = None
    try:
        with _LOCK:
            for key, payload in pairs:
                try:
                    if isinstance(payload, bytes):
                        data = payload
                    elif isinstance(payload, str) and os.path.exists(payload):
                        with open(payload, "rb") as fh:
                            data = fh.read()
                    else:
                        out[key] = None
                        continue
                except OSError:
                    out[key] = None
                    continue
                if not data:
                    out[key] = None
                    continue
                cached = _read_cache(cache_dir, data)
                if cached:
                    out[key] = cached
                    continue
                todo.append((key, data))

            if todo:
                import tempfile

                work_dir = tempfile.mkdtemp(prefix="prismatch_word_")
                jobs = []
                for key, data in todo:
                    src = os.path.join(work_dir, "in_%s.doc" % key)
                    try:
                        with open(src, "wb") as fh:
                            fh.write(data)
                    except OSError:
                        out[key] = None
                        continue
                    jobs.append((key, src, data))
                if jobs:
                    try:
                        _run_word(jobs, out, cache_dir, work_dir, progress, cancel)
                    except Exception:
                        pass
    finally:
        if work_dir:
            try:
                import shutil

                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass
    return out
