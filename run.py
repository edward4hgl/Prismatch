#!/usr/bin/env python
"""Entry point: python run.py [--port 8765] [--host 127.0.0.1] [--no-browser] [文件夹...]"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.server import serve  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="棱镜 Prismatch 本地查重")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="0 表示随机端口")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("paths", nargs="*", help="开机即导入的文件夹（拖到 exe 图标上即可）")
    args = parser.parse_args()

    startup = []
    for raw in args.paths:
        p = raw.strip().strip('"')
        if p and os.path.isdir(p):
            startup.append(os.path.abspath(p))
    serve(args.host, args.port, not args.no_browser, startup)


if __name__ == "__main__":
    main()
