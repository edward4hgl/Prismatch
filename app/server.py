"""Zero-dependency local web server: static UI + JSON API + background jobs."""
from __future__ import annotations

import base64
import gzip
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import engine

if getattr(sys, "frozen", False):
    # PyInstaller: resources live in _MEIPASS, writable data next to the exe
    _MEI = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    ROOT = os.path.join(_MEI, "app")
    APP_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))
    APP_ROOT = os.path.dirname(ROOT)

STATIC = os.path.join(ROOT, "static")
APP_VERSION = "1.1.11"
LOG_DIR = os.path.join(APP_ROOT, "logs")
IMG_DIR = os.path.join(APP_ROOT, "data", "images")
REPORT_DIR = os.path.join(APP_ROOT, "data", "reports")
DOC_DIR = os.path.join(APP_ROOT, "data", "docs")
try:
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(IMG_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    os.makedirs(DOC_DIR, exist_ok=True)
except Exception:
    LOG_DIR = ROOT


def _doc_target(job_id, doc_id):
    """把「报告里的文档编号」解析成磁盘路径：优先原始路径，退回落盘副本。"""
    target, source = None, ""
    meta_path = os.path.join(REPORT_DIR, job_id + ".meta.json")
    try:
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        docs = meta.get("docs") or []
        if isinstance(doc_id, int) and 0 <= doc_id < len(docs):
            p = docs[doc_id].get("path") or ""
            if p and os.path.isfile(p):
                target, source = p, "original"
    except Exception:
        pass
    if target is None:
        raw = os.path.join(DOC_DIR, job_id, f"d{doc_id}.docx")
        if os.path.isfile(raw):
            target, source = raw, "cached"
    return target, source


def _reveal_in_explorer(path):
    """在资源管理器里打开所在文件夹并选中该文件（不是只打开文件夹）。"""
    if os.name != "nt":
        return False, "仅 Windows 支持"
    try:
        subprocess.Popen(
            'explorer /select,"%s"' % path,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _save_report(job_id, result, files):
    """Persist a finished run: gzip result + meta + human-readable txt."""
    meta = {
        "id": job_id,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stats": result["stats"],
        "tender": result.get("tender", []),
        "docs": [
            {
                "name": d["name"],
                "path": d.get("path") or "",
                "group": d.get("group"),
                "chars": d["chars"],
                "error": d.get("error") or "",
            }
            for d in result["docs"]
        ],
    }
    try:
        with open(os.path.join(REPORT_DIR, job_id + ".meta.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=1)
        with gzip.open(os.path.join(REPORT_DIR, job_id + ".json.gz"), "wt", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False)
        st = result["stats"]
        lines = [
            f"查重记录 {meta['time']}",
            f"报告 ID: {job_id}",
            f"对比文档 {st['docs']} 份 / 相似文件对 {st['pairs']} / 最高重复率 {st['max_score'] * 100:.1f}%",
            f"总耗时 {st['elapsed']} 秒 / 招标文件剔除 {st['filtered']} 段",
            "",
            "文档清单（路径为提交时的原始路径）：",
        ]
        for d in result["docs"]:
            tag = "解析失败" if d.get("error") else "正常"
            lines.append(f"  [{tag}] {d['name']}  <{d.get('path') or '-'}>")
        for e in result.get("errors", []):
            lines.append(f"  解析失败：{e['name']} -> {e['error']}")
        lines.append("")
        lines.append("公司级对比：")
        for g in result.get("groupPairs", []):
            lines.append(f"  {g['a']} ↔ {g['b']}: {g['score'] * 100:.1f}% "
                         f"(句子 {g['sentences']} / 段落 {g['paragraphs']})")
        with open(os.path.join(REPORT_DIR, job_id + ".txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception:
        pass


DOC_EXTS = (".docx", ".doc", ".pptx", ".ppt", ".pdf", ".xlsx", ".xls", ".txt", ".md")


def _remember_root(folder):
    try:
        data = []
        if os.path.isfile(ROOTS_FILE):
            with open(ROOTS_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        folder = os.path.abspath(folder)
        if folder not in data:
            data.append(folder)
            data = data[-40:]
            with open(ROOTS_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _common_roots():
    roots = []
    try:
        if os.path.isfile(ROOTS_FILE):
            with open(ROOTS_FILE, encoding="utf-8") as fh:
                roots = [p for p in json.load(fh) if os.path.isdir(p)]
    except Exception:
        roots = []
    for name in ("Desktop", "Documents", "Downloads"):
        p = os.path.join(os.path.expanduser("~"), name)
        if os.path.isdir(p):
            roots.append(p)
    return list(dict.fromkeys(roots))


def _find_dirs_named(name, max_depth=6, budget=8.0):
    """在常用根目录里找指定名字的文件夹（用于把拖拽文件还原成原路径）。"""
    import time

    target = name.lower()
    hits = []
    started = time.time()
    for root in _common_roots():
        base_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirs, _files in os.walk(root):
            if time.time() - started > budget or len(hits) >= 8:
                return hits
            if dirpath.count(os.sep) - base_depth >= max_depth:
                dirs[:] = []
                continue
            keep = []
            for d in dirs:
                if d.lower() == target:
                    hits.append(os.path.join(dirpath, d))
                elif not d.startswith(".") and d not in ("node_modules", "$RECYCLE.BIN",
                                                         "System Volume Information"):
                    keep.append(d)
            dirs[:] = keep
    return hits


def _drop_index():
    """名字+大小 -> 原路径，供网页拖拽时找回本机原件。"""
    import time

    with _DROP_LOCK:
        if time.time() - _DROP_INDEX["at"] < 30 and _DROP_INDEX["map"]:
            return _DROP_INDEX["map"]

        roots = []
        try:
            if os.path.isfile(ROOTS_FILE):
                with open(ROOTS_FILE, encoding="utf-8") as fh:
                    roots = json.load(fh)
        except Exception:
            roots = []
        for name in ("Desktop", "Documents", "Downloads"):
            p = os.path.join(os.path.expanduser("~"), name)
            if os.path.isdir(p):
                roots.append(p)

        index = {}
        started = time.time()
        for root in list(dict.fromkeys(roots)):
            if not os.path.isdir(root):
                continue
            base_depth = root.rstrip(os.sep).count(os.sep)
            for dirpath, dirs, files in os.walk(root):
                if time.time() - started > 12:
                    break
                if dirpath.count(os.sep) - base_depth > 7:
                    dirs[:] = []
                    continue
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in
                           ("node_modules", "$RECYCLE.BIN", "System Volume Information")]
                for fn in files:
                    if not fn.lower().endswith(DOC_EXTS):
                        continue
                    full = os.path.join(dirpath, fn)
                    try:
                        size = os.path.getsize(full)
                    except Exception:
                        continue
                    index.setdefault((fn.lower(), size), []).append(full)
        _DROP_INDEX["map"] = index
        _DROP_INDEX["at"] = time.time()
        return index


def _clamp_scores(result):
    """Old runs may store >100% ratios; clamp on read."""
    st = result.get("stats") or {}
    if st.get("max_score", 0) > 1:
        st["max_score"] = 1.0
    for p in result.get("pairs") or []:
        p["score"] = min(1.0, p.get("score") or 0)
        p["ratio_a"] = min(1.0, p.get("ratio_a") or 0)
        p["ratio_b"] = min(1.0, p.get("ratio_b") or 0)
    for g in result.get("groupPairs") or []:
        g["score"] = min(1.0, g.get("score") or 0)
        g["ratio_a"] = min(1.0, g.get("ratio_a") or 0)
        g["ratio_b"] = min(1.0, g.get("ratio_b") or 0)
    return result


def _list_reports():
    out = []
    try:
        names = [n for n in os.listdir(REPORT_DIR) if n.endswith(".meta.json")]
    except Exception:
        return out
    for n in names:
        try:
            with open(os.path.join(REPORT_DIR, n), encoding="utf-8") as fh:
                meta = json.load(fh)
            _clamp_scores({"stats": (meta.get("stats") or {})})
            out.append(meta)
        except Exception:
            continue
    out.sort(key=lambda m: str(m.get("time", "")), reverse=True)
    return out


def _load_report(job_id):
    path = os.path.join(REPORT_DIR, job_id + ".json.gz")
    if not os.path.isfile(path):
        return None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return _clamp_scores(json.load(fh))


def _log(job, msg, level="info"):
    now = time.time()
    line = {
        "t": time.strftime("%H:%M:%S", time.localtime(now)) + f".{int(now * 1000) % 1000:03d}",
        "level": level,
        "msg": msg,
    }
    job.setdefault("log", []).append(line)
    if len(job["log"]) > 3000:
        del job["log"][:-3000]
    try:
        with open(os.path.join(LOG_DIR, job.get("id", "job") + ".log"), "a", encoding="utf-8") as fh:
            fh.write(f'{line["t"]} [{level}] {msg}\n')
    except Exception:
        pass

JOBS = {}
UPLOADS = {}
STARTUP = []
ROOTS_FILE = os.path.join(os.path.dirname(REPORT_DIR), "roots.json")
_DROP_INDEX = {"at": 0.0, "map": {}}
_DROP_LOCK = threading.Lock()
JOBS_LOCK = threading.Lock()
UPLOAD_LOCK = threading.Lock()
MAX_UPLOAD = 400 * 1024 * 1024
MAX_FILE = 200 * 1024 * 1024
UPLOAD_TTL = 3600


def _reap_uploads():
    now = time.time()
    with UPLOAD_LOCK:
        for uid in list(UPLOADS):
            name, data, kind, ts = UPLOADS[uid]
            if now - ts > UPLOAD_TTL:
                UPLOADS.pop(uid, None)


# ---------------- 缓存清理 ----------------

CONV_DIR = os.path.join(APP_ROOT, "data", "conv")


def _dir_size(path):
    total = 0
    count = 0
    if not os.path.isdir(path):
        return 0, 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
                count += 1
            except OSError:
                pass
    return total, count


def _report_ids():
    ids = set()
    try:
        for fn in os.listdir(REPORT_DIR):
            if fn.endswith(".meta.json"):
                ids.add(fn[: -len(".meta.json")])
    except OSError:
        pass
    return ids


def _orphan_dirs(base, keep):
    out = []
    try:
        for name in os.listdir(base):
            full = os.path.join(base, name)
            if os.path.isdir(full) and name not in keep:
                out.append((name, full))
    except OSError:
        pass
    return out


def _report_bytes(rid):
    total = 0
    for suffix in (".meta.json", ".json.gz", ".txt"):
        try:
            total += os.path.getsize(os.path.join(REPORT_DIR, rid + suffix))
        except OSError:
            pass
    for base in (DOC_DIR, IMG_DIR):
        total += _dir_size(os.path.join(base, rid))[0]
    return total


def _cache_stats(days=30):
    keep = _report_ids()
    docs_bytes, docs_files = _dir_size(DOC_DIR)
    img_bytes, img_files = _dir_size(IMG_DIR)
    conv_bytes, conv_files = _dir_size(CONV_DIR)
    rep_bytes, rep_files = _dir_size(REPORT_DIR)
    docs_dirs = len(_orphan_dirs(DOC_DIR, set())) if os.path.isdir(DOC_DIR) else 0
    img_dirs = len(_orphan_dirs(IMG_DIR, set())) if os.path.isdir(IMG_DIR) else 0

    cutoff = time.time() - days * 86400
    old_ids = []
    for rid in keep:
        try:
            if os.path.getmtime(os.path.join(REPORT_DIR, rid + ".meta.json")) < cutoff:
                old_ids.append(rid)
        except OSError:
            pass
    old_bytes = sum(_report_bytes(rid) for rid in old_ids)

    return {
        "ok": True,
        "items": [
            {"key": "docs", "label": "排版快照", "bytes": docs_bytes, "files": docs_files,
             "dirs": docs_dirs, "note": "报告里的原样排版，删了仍能打开"},
            {"key": "images", "label": "图片缩略图", "bytes": img_bytes, "files": img_files,
             "dirs": img_dirs, "note": "报告里的相似图片预览"},
            {"key": "conv", "label": "Word 转换缓存", "bytes": conv_bytes, "files": conv_files,
             "dirs": 0, "note": "旧版 .doc 转 docx 的中间结果"},
            {"key": "reports", "label": "历史报告", "bytes": rep_bytes, "files": rep_files,
             "dirs": 0, "note": "报告本身就保留着，只清 30 天前的"},
        ],
        "old_reports": {"days": days, "count": len(old_ids), "bytes": old_bytes},
        "total": docs_bytes + img_bytes + conv_bytes + rep_bytes,
    }


def _clear_dir(base):
    """删掉目录下的所有内容，保留目录本身。返回释放字节数。"""
    import shutil

    freed = 0
    if not os.path.isdir(base):
        return 0
    for name in os.listdir(base):
        full = os.path.join(base, name)
        try:
            if os.path.isdir(full):
                freed += _dir_size(full)[0]
                shutil.rmtree(full, ignore_errors=True)
            else:
                freed += os.path.getsize(full)
                os.remove(full)
        except OSError:
            pass
    return freed


def _cache_clear(keys=None, days=30):
    if any(j.get("state") == "running" for j in JOBS.values()):
        return {"ok": False, "error": "有检测任务正在运行，请先等它结束"}
    keys = set(keys or [])
    freed = 0
    if "docs" in keys:
        freed += _clear_dir(DOC_DIR)
    if "images" in keys:
        freed += _clear_dir(IMG_DIR)
    if "conv" in keys:
        freed += _clear_dir(CONV_DIR)
    if "reports" in keys:
        cutoff = time.time() - days * 86400
        for rid in list(_report_ids()):
            meta = os.path.join(REPORT_DIR, rid + ".meta.json")
            try:
                if os.path.getmtime(meta) >= cutoff:
                    continue
            except OSError:
                continue
            freed += _report_bytes(rid)
            for suffix in (".meta.json", ".json.gz", ".txt"):
                try:
                    os.remove(os.path.join(REPORT_DIR, rid + suffix))
                except OSError:
                    pass
            import shutil

            for base in (DOC_DIR, IMG_DIR):
                shutil.rmtree(os.path.join(base, rid), ignore_errors=True)
    return {"ok": True, "freed": freed}

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
}


def _dec(b64: str) -> bytes:
    if "," in b64[:200] and b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    return base64.b64decode(b64)


def run_job(job_id, files, tender, options):
    job = JOBS[job_id]
    job["id"] = job_id
    last = {"stage": None, "decile": -1}

    def progress(stage, done, total, eta=None, sub=None):
        job["stage"] = stage
        job["done"] = done
        job["total"] = total
        job["eta"] = eta
        job["sub"] = sub
        job["percent"] = int(done * 100 / total) if total else 0
        if stage != last["stage"]:
            last["stage"] = stage
            last["decile"] = -1
            _log(job, f"阶段开始：{stage}，共 {total} 项")
        dec = int(done * 10 / total) if total else 0
        if dec != last["decile"]:
            last["decile"] = dec
            _log(job, f"{stage} 进度 {done}/{total}")

    try:
        job["state"] = "running"
        _log(job, f"任务开始：对比文件 {len(files)} 份，招标文件 {len(tender)} 份")
        for i, item in enumerate(files, 1):
            name, data = item[0], item[1]
            group = item[2] if len(item) > 2 else None
            _log(job, f"  对比文件 {i}: {name} ({len(data) / 1024:.0f} KB) 组={group}")
        for i, item in enumerate(tender, 1):
            name, data = item[0], item[1]
            _log(job, f"  招标文件 {i}: {name} ({len(data) / 1024:.0f} KB)")
        _log(job, f"参数：{options}")

        opts = dict(options)
        opts["image_dir"] = os.path.join(IMG_DIR, job_id)
        opts["html_dir"] = os.path.join(DOC_DIR, job_id)
        opts["raw_dir"] = opts["html_dir"]
        opts.setdefault("conv_dir", os.path.join(APP_ROOT, "data", "conv"))
        try:
            os.makedirs(opts["html_dir"], exist_ok=True)
        except Exception:
            pass
        result = engine.analyze(files, tender, opts, progress, job.get("cancel"))
        job["result"] = result
        job["state"] = "done"
        job["percent"] = 100
        _save_report(job_id, result, files)

        st = result["stats"]
        for d in result["docs"]:
            if d.get("note"):
                _log(job, f"  {d['name']}：{d['note']}")
        _log(job, f"完成：文档 {st['docs']} 份，字数 {st['chars']}，相似文件对 {st['pairs']}，"
                  f"最高 {st['max_score'] * 100:.1f}%，剔除 {st['filtered']} 段，用时 {st['elapsed']}s")
        for e in result.get("errors", []):
            _log(job, f"解析失败：{e['name']} -> {e['error']}", "warn")
        _log(job, "任务结束", "ok")
    except engine.Cancelled:
        job["state"] = "cancelled"
        job["error"] = "已手动停止"
        _log(job, "已手动停止", "warn")
    except Exception as exc:  # noqa: BLE001
        job["state"] = "error"
        job["error"] = str(exc)
        job["trace"] = traceback.format_exc()
        _log(job, f"失败：{exc}", "error")
        for line in job["trace"].splitlines()[-12:]:
            _log(job, "  " + line, "error")
    finally:
        job["finished"] = time.time()


class Handler(BaseHTTPRequestHandler):
    server_version = "Prismatch/1.0"

    def log_message(self, fmt, *args):  # quieter logs
        if os.environ.get("TCHECK_VERBOSE"):
            super().log_message(fmt, *args)

    # ---------------------------------------------------------------- helpers
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _static(self, rel):
        path = os.path.normpath(os.path.join(STATIC, rel.lstrip("/")))
        if not path.startswith(STATIC) or not os.path.isfile(path):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as fh:
            body = fh.read()
        self._send(200, body, MIME.get(ext, "application/octet-stream"))

    # ------------------------------------------------------------------ verbs
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p in ("/", "/index.html"):
            self._static("index.html")
            return
        if p.startswith("/static/"):
            self._static(p[len("/static/"):])
            return
        if p == "/api/reports":
            self._json({"reports": _list_reports()})
            return
        if p.startswith("/api/reports/"):
            rest = p[len("/api/reports/"):]
            parts = [x for x in rest.split("/") if x]
            rid = parts[0] if parts else ""
            if len(parts) > 1 and parts[1] == "export":
                result = _load_report(rid)
                if not result:
                    self._json({"error": "report not found"}, 404)
                    return
                from .report import render_report
                html = render_report(result).encode("utf-8")
                self._send(200, html, "text/html; charset=utf-8",
                           {"Content-Disposition": f'attachment; filename="tocheck-{rid}.html"'})
                return
            result = _load_report(rid)
            if not result:
                self._json({"error": "report not found"}, 404)
                return
            self._json({"id": rid, "result": result})
            return
        if p.startswith("/api/job/"):
            job_id = p.rsplit("/", 1)[-1]
            job = JOBS.get(job_id)
            if not job:
                self._json({"error": "job not found"}, 404)
                return
            payload = {
                "state": job["state"],
                "stage": job.get("stage"),
                "done": job.get("done", 0),
                "total": job.get("total", 0),
                "percent": job.get("percent", 0),
                "eta": job.get("eta"),
                "sub": job.get("sub"),
                "error": job.get("error"),
            }
            if job["state"] == "done":
                payload["result"] = job["result"]
            self._json(payload)
            return
        if p.startswith("/api/export/"):
            job_id = p.rsplit("/", 1)[-1]
            from .report import render_report
            job = JOBS.get(job_id)
            if job and job.get("state") == "done" and job.get("result"):
                html = render_report(job["result"]).encode("utf-8")
            else:
                result = _load_report(job_id)
                if not result:
                    self._json({"error": "job not ready"}, 404)
                    return
                html = render_report(result).encode("utf-8")
            self._send(200, html, "text/html; charset=utf-8",
                       {"Content-Disposition": 'attachment; filename="tocheck-report.html"'})
            return
        if p.startswith("/api/raw/"):
            parts = [x for x in p.split("/") if x]
            if len(parts) < 4:
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            job_id, fname = parts[2], parts[3]
            base = os.path.join(DOC_DIR, job_id)
            target = os.path.normpath(os.path.join(base, fname))
            if not target.startswith(base) or not os.path.isfile(target):
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            with open(target, "rb") as fh:
                body = fh.read()
            self._send(200, body, "application/octet-stream")
            return
        if p.startswith("/api/doc/"):
            parts = [x for x in p.split("/") if x]
            if len(parts) < 4:
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            job_id, fname = parts[2], parts[3]
            base = os.path.join(DOC_DIR, job_id)
            target = os.path.normpath(os.path.join(base, fname))
            if not target.startswith(base) or not os.path.isfile(target):
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            with open(target, "rb") as fh:
                body = fh.read()
            self._send(200, body, "text/html; charset=utf-8")
            return
        if p.startswith("/api/img/"):
            parts = p.split("/")
            if len(parts) < 5:
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            job_id, fname = parts[3], parts[4]
            base = os.path.join(IMG_DIR, job_id)
            target = os.path.normpath(os.path.join(base, fname))
            if not target.startswith(base) or not os.path.isfile(target):
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            ext = os.path.splitext(target)[1].lower()
            ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                     ".gif": "image/gif", ".webp": "image/webp"}.get(ext, "application/octet-stream")
            with open(target, "rb") as fh:
                body = fh.read()
            self._send(200, body, ctype)
            return
        if p.startswith("/api/logs/"):
            job_id = p.rsplit("/", 1)[-1]
            job = JOBS.get(job_id)
            if not job:
                self._json({"error": "job not found"}, 404)
                return
            self._json({"state": job.get("state"), "lines": job.get("log", [])})
            return
        if p == "/api/pick-folder":
            tmp_ps1 = None
            try:
                import subprocess
                import tempfile
                script = (
                    "Add-Type -AssemblyName System.Windows.Forms;"
                    "$owner=New-Object System.Windows.Forms.Form;"
                    "$owner.TopMost=$true;$owner.ShowInTaskbar=$false;"
                    "$owner.WindowState='Minimized';$owner.Show();"
                    "$d=New-Object System.Windows.Forms.FolderBrowserDialog;"
                    "$d.Description='Select folder';"
                    "$d.ShowNewFolderButton=$true;"
                    "$r=$d.ShowDialog($owner);"
                    "$owner.Close();"
                    "if($r -eq [System.Windows.Forms.DialogResult]::OK){Write-Output $d.SelectedPath}"
                )
                fd, tmp_ps1 = tempfile.mkstemp(suffix=".ps1")
                with os.fdopen(fd, "w", encoding="utf-8-sig") as fh:
                    fh.write(script)
                try:
                    out = subprocess.run(
                        ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
                         "-File", tmp_ps1],
                        capture_output=True, timeout=300,
                    )
                except subprocess.TimeoutExpired:
                    self._json({"path": "", "timeout": True})
                    return
                raw = out.stdout or b""
                text = ""
                for enc in ("utf-8-sig", "gbk", "latin-1"):
                    try:
                        text = raw.decode(enc)
                        break
                    except Exception:
                        continue
                chosen = ""
                for line in text.splitlines():
                    line = line.strip()
                    if line and os.path.isdir(line):
                        chosen = line
                err = (out.stderr or b"").decode("utf-8", "replace").strip()
                self._json({"path": chosen, "stderr": err[:400]})
            except Exception as exc:  # noqa: BLE001
                self._json({"error": f"打开选择框失败: {exc}"}, 500)
            finally:
                if tmp_ps1 and os.path.exists(tmp_ps1):
                    try:
                        os.remove(tmp_ps1)
                    except Exception:
                        pass
            return
        if p == "/api/startup":
            self._json({"folders": list(STARTUP)})
            STARTUP.clear()
            return
        if p == "/api/health":
            self._json({"ok": True, "jobs": len(JOBS), "version": APP_VERSION})
            return
        if p == "/api/cache":
            self._json(_cache_stats())
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_DELETE(self):
        u = urlparse(self.path)
        if u.path.startswith("/api/reports/"):
            rid = u.path.rsplit("/", 1)[-1]
            if not rid or "/" in rid:
                self._json({"error": "bad id"}, 400)
                return
            for suffix in (".meta.json", ".json.gz", ".txt"):
                try:
                    os.remove(os.path.join(REPORT_DIR, rid + suffix))
                except FileNotFoundError:
                    pass
                except Exception:
                    pass
            img_dir = os.path.join(IMG_DIR, rid)
            if os.path.isdir(img_dir):
                try:
                    import shutil
                    shutil.rmtree(img_dir, ignore_errors=True)
                except Exception:
                    pass
            doc_dir = os.path.join(DOC_DIR, rid)
            if os.path.isdir(doc_dir):
                try:
                    import shutil
                    shutil.rmtree(doc_dir, ignore_errors=True)
                except Exception:
                    pass
            self._json({"ok": True})
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path.startswith("/api/cancel/"):
            job_id = u.path.rsplit("/", 1)[-1]
            job = JOBS.get(job_id)
            if not job:
                self._json({"error": "job not found"}, 404)
                return
            ev = job.get("cancel")
            if ev is not None:
                ev.set()
            _log(job, "收到停止请求", "warn")
            self._json({"ok": True})
            return
        if u.path == "/api/cache/clear":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8-sig")) if length else {}
            except Exception:
                payload = {}
            keys = payload.get("keys")
            if not isinstance(keys, list):
                keys = ["docs", "images", "conv"]
            res = _cache_clear(keys=[str(k) for k in keys], days=int(payload.get("days") or 30))
            self._json(res, 200 if res.get("ok") else 409)
            return
        if u.path == "/api/open":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8-sig")) if length else {}
            except Exception:
                payload = {}
            job_id = str(payload.get("job") or "")
            doc_id = payload.get("doc")
            target, source = _doc_target(job_id, doc_id)
            if not target:
                self._json({"error": "找不到该文件（原始路径已变更，且没有缓存副本）"}, 404)
                return
            try:
                if os.name == "nt":
                    os.startfile(target)  # noqa: S606
                else:
                    subprocess.Popen(["xdg-open", target])
            except Exception as exc:  # noqa: BLE001
                self._json({"error": f"打开失败: {exc}"}, 500)
                return
            self._json({"ok": True, "source": source, "path": target})
            return
        if u.path == "/api/reveal":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8-sig")) if length else {}
            except Exception:
                payload = {}
            job_id = str(payload.get("job") or "")
            doc_id = payload.get("doc")
            target, source = _doc_target(job_id, doc_id)
            if not target:
                self._json({"error": "找不到该文件（原始路径已变更，且没有缓存副本）"}, 404)
                return
            ok, err = _reveal_in_explorer(target)
            if not ok:
                self._json({"error": f"定位失败: {err}"}, 500)
                return
            self._json({"ok": True, "path": target, "source": source})
            return
        if u.path == "/api/paths-info":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8-sig")) if length else {}
            except Exception:
                payload = {}
            items = []
            for raw in payload.get("paths") or []:
                p = str(raw)
                try:
                    if os.path.isdir(p):
                        items.append({"path": os.path.abspath(p),
                                      "name": os.path.basename(os.path.normpath(p)),
                                      "dir": True, "size": 0})
                    elif os.path.isfile(p):
                        items.append({"path": os.path.abspath(p),
                                      "name": os.path.basename(p),
                                      "dir": False, "size": os.path.getsize(p)})
                except Exception:
                    continue
            self._json({"items": items})
            return
        if u.path == "/api/resolve-paths":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8-sig")) if length else {}
            except Exception:
                payload = {}
            base = str(payload.get("base") or "").strip()
            rels = payload.get("rels") or []
            if not base or not os.path.isdir(base):
                self._json({"error": f"基准目录不存在：{base}"}, 400)
                return
            base_norm = os.path.normpath(base)
            out = []
            for rel in rels:
                r = str(rel).replace("\\", os.sep).replace("/", os.sep)
                full = os.path.normpath(os.path.join(base_norm, r))
                if not full.startswith(base_norm):
                    continue
                if os.path.isfile(full):
                    try:
                        out.append({"rel": str(rel), "path": full, "size": os.path.getsize(full)})
                    except Exception:
                        continue
            self._json({"resolved": out, "base": base_norm})
            return
        if u.path == "/api/scan":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8-sig")) if length else {}
            except Exception:
                payload = {}
            folder = str(payload.get("path") or "").strip()
            if not folder or not os.path.isdir(folder):
                self._json({"error": f"文件夹不存在：{folder}"}, 400)
                return
            exts = (".docx", ".doc", ".pptx", ".ppt", ".pdf", ".xlsx", ".xls", ".txt", ".md")
            found = []
            for root, _dirs, names in os.walk(folder):
                for fn in names:
                    if fn.lower().endswith(exts):
                        full = os.path.join(root, fn)
                        try:
                            found.append({"name": fn, "path": full, "size": os.path.getsize(full)})
                        except Exception:
                            continue
            found.sort(key=lambda x: x["path"])
            _remember_root(folder)
            self._json({"folder": os.path.basename(os.path.normpath(folder)),
                        "files": found})
            return
        if u.path == "/api/resolve-drop":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8-sig")) if length else {}
            except Exception:
                payload = {}
            hint = str(payload.get("hint") or "").strip()
            items = payload.get("items") or []
            rels = payload.get("rels") or []

            # 1) 先用「拖进来的文件夹名」在常用根目录里精确匹配
            if hint and any(rels):
                bases = _find_dirs_named(hint)
                good = []
                for base in bases:
                    ok = True
                    for idx, it in enumerate(items):
                        rel = str(rels[idx] if idx < len(rels) else it.get("name") or "")
                        rel = rel.replace("\\", os.sep).replace("/", os.sep)
                        parts = rel.split(os.sep)
                        if parts and parts[0].lower() == hint.lower():
                            rel = os.sep.join(parts[1:])
                        full = os.path.join(base, rel)
                        if not os.path.isfile(full):
                            ok = False
                            break
                        try:
                            if int(it.get("size") or 0) and os.path.getsize(full) != int(it.get("size")):
                                ok = False
                                break
                        except Exception:
                            ok = False
                            break
                    if ok:
                        good.append(base)
                if len(good) == 1:
                    out = []
                    for idx, it in enumerate(items):
                        rel = str(rels[idx] if idx < len(rels) else it.get("name") or "")
                        rel = rel.replace("\\", os.sep).replace("/", os.sep)
                        parts = rel.split(os.sep)
                        if parts and parts[0].lower() == hint.lower():
                            rel = os.sep.join(parts[1:])
                        out.append({"name": it.get("name"), "path": os.path.join(good[0], rel),
                                    "hits": 1})
                    self._json({"resolved": out, "mode": "folder"})
                    return

            # 2) 退回全局索引（名字+大小）
            index = _drop_index()
            hint_l = hint.lower()
            out = []
            for it in items:
                key = (str(it.get("name") or "").lower(), int(it.get("size") or 0))
                hits = list(dict.fromkeys(index.get(key) or []))
                pick = ""
                if hint_l:
                    same = [h for h in hits
                            if os.path.basename(os.path.dirname(h)).lower() == hint_l]
                    if len(same) == 1:
                        pick = same[0]
                if not pick and len(hits) == 1:
                    pick = hits[0]
                out.append({"name": it.get("name"), "path": pick, "hits": len(hits)})
            self._json({"resolved": out, "mode": "index"})
            return
        if u.path == "/api/diag":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8-sig")) if length else {}
            except Exception:
                payload = {}
            try:
                with open(os.path.join(LOG_DIR, "client.log"), "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
            except Exception:
                pass
            self._json({"ok": True})
            return
        if u.path == "/api/upload":
            self._upload(u)
            return
        if u.path != "/api/analyze":
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_UPLOAD:
            self._json({"error": "请求过大或为空"}, 413)
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except Exception:
            self._json({"error": "无效的 JSON"}, 400)
            return

        items = payload.get("files") or []
        if not items:
            self._json({"error": "没有文件"}, 400)
            return

        files = []
        tender = []
        try:
            for item in items:
                name, data = self._resolve(item)
                files.append((name, data, item.get("group"), item.get("path") or ""))
            for item in (payload.get("tender") or []):
                name, data = self._resolve(item)
                tender.append((name, data))
        except Exception as exc:  # noqa: BLE001
            self._json({"error": f"文件读取失败: {exc}"}, 400)
            return

        options = payload.get("options") or {}
        job_id = uuid.uuid4().hex
        with JOBS_LOCK:
            JOBS[job_id] = {"state": "queued", "created": time.time(), "percent": 0,
                            "log": [], "cancel": threading.Event()}
        threading.Thread(target=run_job, args=(job_id, files, tender, options), daemon=True).start()
        self._json({"job": job_id})

    def _upload(self, u):
        from urllib.parse import parse_qs
        q = parse_qs(u.query)
        name = (q.get("name") or ["file"])[0]
        kind = (q.get("kind") or ["c"])[0]
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._json({"error": "空文件"}, 400)
            return
        if length > MAX_FILE:
            self._json({"error": f"文件过大（{length / 1048576:.0f}MB），上限 {MAX_FILE // 1048576}MB"}, 413)
            return
        data = self.rfile.read(length)
        uid = uuid.uuid4().hex
        _reap_uploads()
        with UPLOAD_LOCK:
            UPLOADS[uid] = (name, data, kind, time.time())
        self._json({"id": uid, "size": len(data)})

    def _resolve(self, item):
        uid = item.get("id")
        if uid:
            with UPLOAD_LOCK:
                entry = UPLOADS.pop(uid, None)
            if entry is None:
                raise ValueError("上传已过期，请重新提交")
            name, data, _kind, _ts = entry
            return item.get("name") or name, data
        p = item.get("path")
        if p and os.path.isfile(p):
            return item.get("name") or os.path.basename(p), p
        name = str(item.get("name") or "unnamed.docx")
        return name, _dec(item.get("data") or "")


def start_server(host="127.0.0.1", port=0, startup=None):
    """Start the HTTP server in a background thread and return (httpd, url)."""
    STARTUP[:] = list(startup or [])
    httpd = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://{host}:{httpd.server_address[1]}"


def serve(host="127.0.0.1", port=0, open_browser=True, startup=None):
    STARTUP[:] = list(startup or [])
    httpd = ThreadingHTTPServer((host, port), Handler)
    actual = httpd.server_address[1]
    url = f"http://{host}:{actual}"
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    print(f"棱镜 Prismatch 已启动: {url}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
