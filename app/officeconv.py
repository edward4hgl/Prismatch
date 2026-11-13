"""Legacy Office binaries -> modern XML packages through Office automation.

The three legacy containers each have a modern sibling that mammoth / python-pptx
/ openpyxl can already read, so the cheapest reliable route is to let Office
itself do the conversion:

    .doc / .rtf -> .docx   Word.Application      FileFormat=16
    .xls        -> .xlsx   Excel.Application     FileFormat=51
    .ppt        -> .pptx   PowerPoint.Application FileFormat=24

Word gives us the real layout (tables, headings, bold) that the hand-rolled
OLE/piece-table reader can never recover. Each converter keeps *one* Office
process alive for the whole batch (starting Word costs ~5 s, each extra
document only ~0.5-2 s) and results are cached by source digest, so re-running
the same bid folder costs nothing.

Everything degrades quietly: a file Office refuses to open maps to None and the
caller falls back to the legacy text reader or reports it as a parse failure.
"""
from __future__ import annotations

import hashlib
import os
import threading

_LOCK = threading.Lock()
_AVAILABLE = None

# kind -> (cache/产出后缀, 说明)
KIND_SUFFIX = {"doc": ".docx", "rtf": ".docx", "xls": ".xlsx", "ppt": ".pptx"}


def available() -> bool:
    """True when win32com is importable (Office itself is probed on first use)."""
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


def _cache_file(cache_dir: str, data: bytes, kind: str) -> str:
    return os.path.join(cache_dir, _digest(data) + KIND_SUFFIX.get(kind, ".docx"))


def _read_cache(cache_dir: str, data: bytes, kind: str):
    if not cache_dir:
        return None
    path = _cache_file(cache_dir, data, kind)
    try:
        if os.path.getsize(path) > 0:
            with open(path, "rb") as fh:
                return fh.read()
    except OSError:
        return None
    return None


def _write_cache(cache_dir: str, data: bytes, kind: str, blob: bytes) -> None:
    if not cache_dir:
        return
    try:
        os.makedirs(cache_dir, exist_ok=True)
        path = _cache_file(cache_dir, data, kind)
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(blob)
        os.replace(tmp, path)
    except OSError:
        pass


def _tick(progress, done, total):
    if progress is not None:
        try:
            progress(done, total)
        except Exception:
            pass


def _save(out, cache_dir, key, src_data, kind, dst, progress, done, total):
    """Read the produced file back into `out` (and the cache)."""
    try:
        with open(dst, "rb") as fh:
            blob = fh.read()
    except OSError:
        out[key] = None
    else:
        if blob.startswith(b"PK"):
            out[key] = blob
            _write_cache(cache_dir, src_data, kind, blob)
        else:
            out[key] = None
    _tick(progress, done, total)


def _run_word(jobs, out, cache_dir, work_dir, progress, cancel):
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    app = None
    try:
        app = win32com.client.DispatchEx("Word.Application")
        for attr, val in (("Visible", False), ("DisplayAlerts", 0), ("AutomationSecurity", 3)):
            try:
                setattr(app, attr, val)
            except Exception:
                pass

        for done, (key, src, data, kind) in enumerate(jobs, start=1):
            if cancel is not None and cancel.is_set():
                break
            dst = os.path.join(work_dir, "out_%s.docx" % key)
            doc = None
            try:
                doc = app.Documents.Open(
                    src,
                    ConfirmConversions=False,
                    ReadOnly=True,
                    AddToRecentFiles=False,
                )
                doc.SaveAs2(dst, FileFormat=16)  # wdFormatDocumentDefault (.docx)
            except Exception:
                out[key] = None
                _tick(progress, done, len(jobs))
                continue
            finally:
                if doc is not None:
                    try:
                        doc.Close(False)
                    except Exception:
                        pass
            _save(out, cache_dir, key, data, kind, dst, progress, done, len(jobs))
            try:
                if os.path.exists(dst):
                    os.remove(dst)
            except OSError:
                pass
    finally:
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _run_excel(jobs, out, cache_dir, work_dir, progress, cancel):
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    app = None
    try:
        app = win32com.client.DispatchEx("Excel.Application")
        for attr, val in (("Visible", False), ("DisplayAlerts", False), ("ScreenUpdating", False)):
            try:
                setattr(app, attr, val)
            except Exception:
                pass
        try:
            app.AskToUpdateLinks = False
        except Exception:
            pass

        for done, (key, src, data, kind) in enumerate(jobs, start=1):
            if cancel is not None and cancel.is_set():
                break
            dst = os.path.join(work_dir, "out_%s.xlsx" % key)
            wb = None
            try:
                wb = app.Workbooks.Open(src, ReadOnly=True, UpdateLinks=0)
                wb.SaveAs(dst, FileFormat=51)  # xlOpenXMLWorkbook (.xlsx)
            except Exception:
                out[key] = None
                _tick(progress, done, len(jobs))
                continue
            finally:
                if wb is not None:
                    try:
                        wb.Close(SaveChanges=False)
                    except Exception:
                        pass
            _save(out, cache_dir, key, data, kind, dst, progress, done, len(jobs))
            try:
                if os.path.exists(dst):
                    os.remove(dst)
            except OSError:
                pass
    finally:
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _run_ppt(jobs, out, cache_dir, work_dir, progress, cancel):
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    app = None
    try:
        app = win32com.client.DispatchEx("PowerPoint.Application")
        # PowerPoint has no hidden window mode; WithWindow=False on Open keeps it quiet.
        for done, (key, src, data, kind) in enumerate(jobs, start=1):
            if cancel is not None and cancel.is_set():
                break
            dst = os.path.join(work_dir, "out_%s.pptx" % key)
            pres = None
            try:
                pres = app.Presentations.Open(src, ReadOnly=True, WithWindow=False)
                pres.SaveAs(dst, 24)  # ppSaveAsOpenXMLPresentation (.pptx)
            except Exception:
                out[key] = None
                _tick(progress, done, len(jobs))
                continue
            finally:
                if pres is not None:
                    try:
                        pres.Close()
                    except Exception:
                        pass
            _save(out, cache_dir, key, data, kind, dst, progress, done, len(jobs))
            try:
                if os.path.exists(dst):
                    os.remove(dst)
            except OSError:
                pass
    finally:
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


_RUNNERS = {"word": _run_word, "excel": _run_excel, "ppt": _run_ppt}
_GROUP = {"doc": "word", "rtf": "word", "xls": "excel", "ppt": "ppt"}
_SRC_EXT = {"doc": ".doc", "rtf": ".rtf", "xls": ".xls", "ppt": ".ppt"}


def convert_batch(pairs, cache_dir="", progress=None, cancel=None):
    """pairs: [(key, payload, kind)] with kind in {doc, rtf, xls, ppt}.

    payload is bytes or a path. Returns {key: modern-bytes | None}.
    Never raises: a document Office cannot open simply maps to None.
    """
    out = {}
    if not available() or not pairs:
        return out

    todo = []
    work_dir = None
    try:
        with _LOCK:
            for item in pairs:
                try:
                    key, payload, kind = item[0], item[1], item[2]
                except (TypeError, IndexError):
                    continue
                if kind not in _SRC_EXT:
                    out[key] = None
                    continue
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
                cached = _read_cache(cache_dir, data, kind)
                if cached:
                    out[key] = cached
                    continue
                todo.append((key, data, kind))

            if todo:
                import tempfile

                work_dir = tempfile.mkdtemp(prefix="prismatch_office_")
                buckets = {"word": [], "excel": [], "ppt": []}
                for key, data, kind in todo:
                    src = os.path.join(work_dir, "in_%s%s" % (key, _SRC_EXT[kind]))
                    try:
                        with open(src, "wb") as fh:
                            fh.write(data)
                    except OSError:
                        out[key] = None
                        continue
                    buckets[_GROUP[kind]].append((key, src, data, kind))

                total = sum(len(v) for v in buckets.values())
                done = 0

                def bump(d, _t):
                    _tick(progress, done + d, total)

                for name in ("word", "excel", "ppt"):
                    batch = buckets[name]
                    if not batch:
                        continue
                    if cancel is not None and cancel.is_set():
                        break
                    runner = _RUNNERS[name]
                    try:
                        runner(batch, out, cache_dir, work_dir, bump, cancel)
                    except Exception:
                        for key, _src, _data, _kind in batch:
                            out.setdefault(key, None)
                    done += len(batch)
                    _tick(progress, done, total)
    finally:
        if work_dir:
            try:
                import shutil

                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass
    return out
