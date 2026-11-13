"""Headless batch runner: compare folders on disk and write a report.

    python run_check.py --out DIR --tender DIR --group 单位A=DIR --group 单位B=DIR
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import engine  # noqa: E402
from app.report import render_report  # noqa: E402

EXTS = (".docx", ".doc", ".pptx", ".ppt", ".pdf", ".xlsx", ".xls", ".txt", ".md")


def collect(folder):
    out = []
    for root, _dirs, files in os.walk(folder):
        for fn in files:
            if fn.lower().endswith(EXTS):
                out.append(os.path.join(root, fn))
    out.sort()
    return out


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", action="append", default=[], metavar="NAME=DIR")
    ap.add_argument("--tender", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sentence-threshold", type=float, default=0.6)
    ap.add_argument("--group-threshold", type=float, default=0.5)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    files = []
    for spec in args.group:
        if "=" not in spec:
            raise SystemExit(f"bad --group: {spec}")
        name, folder = spec.split("=", 1)
        paths = collect(folder)
        log(f"组 {name}: {len(paths)} 份文件")
        for p in paths:
            files.append((os.path.basename(p), p, name))

    tender = []
    if args.tender:
        paths = collect(args.tender)
        log(f"招标文件: {len(paths)} 份")
        for p in paths:
            tender.append((os.path.basename(p), p))

    os.makedirs(args.out, exist_ok=True)
    log(f"开始检测：对比 {len(files)} 份，招标 {len(tender)} 份")

    t0 = time.time()
    last = {"t": 0}

    def progress(stage, done, total, eta=None):
        now = time.time()
        if now - last["t"] > 3 or done == total:
            last["t"] = now
            tail = "" if eta is None else f"  eta={eta:.0f}s"
            log(f"  {stage} {done}/{total}  ({now - t0:.0f}s){tail}")

    try:
        result = engine.analyze(
            files, tender,
            {
                "sentence_threshold": args.sentence_threshold,
                "group_threshold": args.group_threshold,
                "images": True,
                "workers": args.workers,
                "image_dir": os.path.join(args.out, "images"),
            },
            progress,
        )
    except Exception:
        traceback.print_exc()
        return 1

    elapsed = time.time() - t0
    html = render_report(result)
    with open(os.path.join(args.out, "查重报告.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    with open(os.path.join(args.out, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)

    st = result["stats"]
    summary = [
        f"检测时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"对比文档: {st['docs']} 份",
        f"招标文件: {len(tender)} 份（剔除 {st['filtered']} 段）",
        f"相似文件对: {st['pairs']}",
        f"最高重复率: {st['max_score'] * 100:.1f}%",
        f"最大相似句子: {st['max_sentences']}",
        f"最大相似段落: {st['max_paragraphs']}",
        f"最大相似图片: {st['max_images']}",
        f"用时: {elapsed:.1f}s",
    ]
    for g in result.get("groupPairs", []):
        summary.append(f"  {g['a']} ↔ {g['b']}: {g['score'] * 100:.1f}% "
                       f"(句子 {g['sentences']} / 段落 {g['paragraphs']} / 文件对 {g['fileCount']})")
    errs = result.get("errors", [])
    summary.append(f"解析失败: {len(errs)} 份")
    for e in errs:
        summary.append(f"  {e['name']}: {e['error']}")

    with open(os.path.join(args.out, "summary.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(summary) + "\n")

    log("完成")
    print("\n".join(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
