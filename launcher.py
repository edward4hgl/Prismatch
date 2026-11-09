#!/usr/bin/env python
"""棱镜 Prismatch 桌面启动器（pywebview 内嵌窗口）.

双击 Prismatch.exe：启动本地服务 → 内嵌 WebView2 窗口打开界面。
把文件夹拖到 exe 图标上启动时，作为启动参数直接导入。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):
    sys.path.insert(0, getattr(sys, "_MEIPASS", ROOT))
else:
    sys.path.insert(0, ROOT)

from app.server import start_server  # noqa: E402

TITLE = "棱镜 Prismatch"


class Api:
    """暴露给页面的原生能力：window.pywebview.api.xxx()"""

    def ping(self):
        return {"ok": True, "mode": "pywebview"}

    def pick_folder(self):
        try:
            import webview

            win = webview.active_window() or (webview.windows[0] if webview.windows else None)
            if win is None:
                return ""
            dialog = getattr(webview, "FOLDER_DIALOG", None)
            if dialog is None:
                return ""
            res = win.create_file_dialog(dialog)
            if not res:
                return ""
            if isinstance(res, (list, tuple)):
                return str(res[0]) if res else ""
            return str(res)
        except Exception:
            return ""

    def open_path(self, path: str):
        """用系统默认程序打开文件（报告里点文件名时优先走这里）"""
        try:
            if not path or not os.path.exists(path):
                return {"ok": False, "error": "文件不存在"}
            os.startfile(path)  # noqa: S606
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}


def window_geometry():
    """按主屏工作区算出居中、能完整显示界面的窗口尺寸。"""
    try:
        import clr

        clr.AddReference("System.Windows.Forms")
        from System.Windows.Forms import Screen

        wa = Screen.PrimaryScreen.WorkingArea
        sw, sh = int(wa.Width), int(wa.Height)
        sx, sy = int(wa.X), int(wa.Y)
    except Exception:
        return 1320, 880, 80, 60

    # 界面在 1180px 宽时是双栏最优布局；高度按内容需要给足
    w = min(1320, max(1040, int(sw * 0.92)))
    h = min(960, max(700, int(sh * 0.94)))
    x = sx + max(0, (sw - w) // 2)
    y = sy + max(0, (sh - h) // 2)
    return w, h, x, y


def find_edge():
    for base in (
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("LOCALAPPDATA", ""),
    ):
        if not base:
            continue
        p = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
        if os.path.isfile(p):
            return p
    return ""


def fallback_window(url: str):
    edge = find_edge()
    if edge:
        try:
            subprocess.run([edge, f"--app={url}", "--window-size=1320,880"], check=False)
            return
        except Exception:
            pass
    webbrowser.open(url)


DROPS = []  # 保持委托引用，避免被 GC


def _log_line(text: str):
    try:
        base = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else ROOT
        d = os.path.join(base, "logs")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "launcher.log"), "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except Exception:
        pass


def hook_native_drop(window):
    """把窗口层的文件拖放接管过来：Windows 给的是 FileDrop 绝对路径。"""
    try:
        import json

        import clr

        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        from System.Windows.Forms import DataFormats, DragDropEffects

        native = getattr(window, "native", None)
        if native is None:
            _log_line("hook: native is None")
            return False

        def on_enter(sender, e):
            try:
                if e.Data.GetDataPresent(DataFormats.FileDrop):
                    e.Effect = DragDropEffects.Copy | DragDropEffects.Link
                else:
                    e.Effect = getattr(DragDropEffects, "None")
            except Exception:
                pass

        def on_drop(sender, e):
            try:
                data = e.Data.GetData(DataFormats.FileDrop)
                paths = [str(x) for x in (data or [])]
            except Exception:
                return
            if not paths:
                return

            # 把落点换算成 WebView2 客户区坐标，页面据此判断落在哪个拖拽区
            x = y = -1
            try:
                from System.Drawing import Point

                inner = getattr(native, "webview", None)
                if inner is not None and sender is not inner:
                    screen = sender.PointToScreen(Point(int(e.X), int(e.Y)))
                    pt = inner.PointToClient(screen)
                    x, y = int(pt.X), int(pt.Y)
                else:
                    x, y = int(e.X), int(e.Y)
            except Exception:
                x = y = -1

            js = (
                "window.__nativeDropAt && window.__nativeDropAt("
                + json.dumps(paths, ensure_ascii=False)
                + f", {x}, {y});"
            )
            _log_line(f"drop: {len(paths)} paths at {x},{y} via {type(sender).__name__}")
            try:
                window.evaluate_js(js)
            except Exception as exc:  # noqa: BLE001
                _log_line(f"evaluate_js failed: {exc}")

        targets = [native]
        inner = getattr(native, "webview", None)
        if inner is not None:
            targets.append(inner)

        # 遍历控件树，关掉所有 WebView2 的内建拖放
        def _walk(ctrl, depth=0):
            yield ctrl
            if depth > 4:
                return
            try:
                children = list(ctrl.Controls)
            except Exception:
                return
            for c in children:
                yield from _walk(c, depth + 1)

        seen = set()
        for ctrl in _walk(native):
            try:
                key = int(ctrl.Handle)
            except Exception:
                key = id(ctrl)
            if key in seen:
                continue
            seen.add(key)
            try:
                _log_line(f"ctrl: {type(ctrl)}")
            except Exception:
                pass
            try:
                if hasattr(ctrl, "AllowExternalDrop") and os.environ.get("TC_FORCE_NO_AED") == "1":
                    ctrl.AllowExternalDrop = False
                    _log_line(f"  AllowExternalDrop -> {getattr(ctrl, 'AllowExternalDrop', '?')}")
            except Exception as exc:  # noqa: BLE001
                _log_line(f"  AllowExternalDrop failed: {exc}")
            if ctrl is native:
                pass
            elif not any(ctrl is t for t in targets):
                targets.append(ctrl)

        for t in targets:
            try:
                t.AllowDrop = True
                t.DragEnter += on_enter
                t.DragOver += on_enter
                t.DragDrop += on_drop
            except Exception:
                continue
        DROPS.extend([on_enter, on_drop])
        return True
    except Exception as exc:  # noqa: BLE001
        _log_line(f"hook error: {exc}")
        return False


def main():
    ap = argparse.ArgumentParser(description=TITLE)
    ap.add_argument("--port", type=int, default=0, help="0 表示随机端口")
    ap.add_argument("--headless", action="store_true", help="只启动服务，不开窗口（调试用）")
    ap.add_argument("--no-drop-hook", action="store_true", help="不接管窗口拖放（排查用）")
    ap.add_argument("paths", nargs="*", help="开机即导入的文件夹")
    args = ap.parse_args()

    folders = []
    for raw in args.paths:
        p = raw.strip().strip('"')
        if p and os.path.isdir(p):
            folders.append(os.path.abspath(p))

    httpd, url = start_server("127.0.0.1", args.port, folders)
    if os.environ.get("TC_MEASURE") == "1":
        url += "/?measure=1"
    try:
        print(f"{TITLE} 已启动: {url}", flush=True)
    except Exception:
        pass

    if args.headless:
        try:
            import time

            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            httpd.shutdown()
        return

    try:
        import webview  # type: ignore

        w, h, px, py = window_geometry()
        _log_line(f"window geometry: {w}x{h} at {px},{py}")
        webview.create_window(
            TITLE, url, js_api=Api(),
            width=w, height=h, x=px, y=py,
            min_size=(1040, 640),
        )

        _installed = {"done": False}

        def _install(win):
            if _installed["done"]:
                return
            _installed["done"] = True

            native = getattr(win, "native", None)
            if native is None:
                _log_line("install: native is None")
                return

            def work():
                ok = False
                try:
                    ok = hook_native_drop(win)
                except Exception as exc:  # noqa: BLE001
                    _log_line(f"install error: {exc}")
                _log_line(f"native drop hook: {ok}")
                # 关掉窗体自动滚动、把 WebView2 铺满窗体，避免出现原生滚动条
                try:
                    native.AutoScroll = False
                except Exception:
                    pass
                try:
                    from System.Windows.Forms import DockStyle

                    inner = getattr(native, "webview", None)
                    if inner is not None:
                        inner.Dock = DockStyle.Fill
                except Exception as exc:  # noqa: BLE001
                    _log_line(f"dock failed: {exc}")

            # WinForms 控件只能在 UI 线程操作，否则 WebView2 会白屏
            try:
                from System import Action

                native.BeginInvoke(Action(work))
            except Exception as exc:  # noqa: BLE001
                _log_line(f"BeginInvoke failed: {exc}")

        def _boot():
            if args.no_drop_hook:
                _log_line("drop hook skipped by flag")
                return
            try:
                win = webview.windows[0]
            except Exception as exc:  # noqa: BLE001
                _log_line(f"no window: {exc}")
                return

            try:
                win.events.loaded += lambda *a, **k: _install(win)
            except Exception:
                pass

            import threading
            import time

            def _wait():
                for _ in range(80):
                    if getattr(win, "native", None) is not None:
                        break
                    time.sleep(0.1)
                _install(win)

            threading.Thread(target=_wait, daemon=True).start()

        webview.start(_boot)
    except Exception:
        fallback_window(url)
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
