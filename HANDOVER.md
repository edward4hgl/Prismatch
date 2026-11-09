# 棱镜 Prismatch — 交接说明（迁移到 macOS）

> 本文件给「在新 Mac 上接手开发」的会话看。读完这一份，加上源码，就能继续。

## 1. 这是什么

本地标书查重工具。Python 标准库 HTTP 服务 + 浏览器界面，pywebview 包成桌面窗口。
Windows 版已可用（159MB 便携包，免安装）。现在要做 macOS 版。

主要能力：
- 文件夹＝投标单位，只做跨文件夹比对（组内不比），N 家自动生成 C(N,2) 组
- 招标文件夹作为白名单，命中段落先剔除
- 解析 docx（mammoth→HTML 保留排版/表格/图片）、.doc（OLE + FIB 分片表）、pdf、pptx、xlsx、txt
- 相似判定：0.4×归一化编辑距离 + 0.6×长度加权 token Dice；中文按字 bigram；3-gram 倒排索引
- 报告：句子/段落/图片三种视图、双栏对照、点击跳转高亮、相似度百分比、按页输出、打印（句子/段落/全文三种）、导出 HTML
- 三套皮肤（液态玻璃 / 极客终端 / 可爱像素）× 浅色深色；跟随系统主题
- 报告历史持久化；招标白名单；取消/进度/ETA；拖拽或路径导入

## 2. 目录结构

```
tocheck-next/
├── app/
│   ├── text.py        归一化、分句、token、gram 哈希、simhash
│   ├── extract.py     docx/doc/pdf/pptx/xlsx → 段落块
│   ├── engine.py      Doc 构建、compare_pair、analyze 主循环、分组聚合
│   ├── report.py      独立 HTML 报告导出
│   ├── server.py      HTTP 服务 + API + 任务管理
│   └── static/        界面（index.html / app.js / report.js / style.css）
├── vendor/            mammoth、olefile、pypdf（其余依赖装在环境里）
├── launcher.py        桌面启动器（pywebview 窗口 + Windows 专属钩子）
├── run.py             纯服务入口（开发调试用）
├── run_check.py       命令行批量查重
└── docs/, tools/
```

## 3. 现在必须改的 Windows 专属部分

`launcher.py`：

| 位置 | 现状 | macOS 需要 |
|---|---|---|
| `hook_native_drop()` | System.Windows.Forms + clr，接管窗口拖放拿真实路径 | 删除或改 NSView 实现；先降级「拖拽=上传」 |
| `window_geometry()` | Screen.PrimaryScreen.WorkingArea | 改用 `webview.screens[0]` 或 AppKit NSScreen |
| `find_edge()` / `fallback_window()` | 找 msedge.exe 启动应用窗口 | macOS 用 `open -na "Google Chrome" --args --app=` 或直接只保留 pywebview |
| `Api.open_path()` | `os.startfile(path)` | `subprocess.run(["open", path])` |
| `Api.pick_folder()` | `create_file_dialog(FOLDER_DIALOG)` | 这个 API 跨平台，保留 |

`app/server.py`：

| 位置 | 现状 | macOS 需要 |
|---|---|---|
| `/api/pick-folder` | 起 PowerShell 弹 FolderBrowserDialog | macOS 上直接返回 501，让前端走 pywebview 的 bridge |
| `/api/open` | `os.startfile` | `open` 命令 |
| 路径判断 | 有 `^[A-Za-z]:[\\/]` 这类 Windows 正则、`\` 拼接 | 改成 `os.sep` / `pathlib`，POSIX 路径 |

`app/static/app.js`：

| 位置 | 现状 | macOS 需要 |
|---|---|---|
| `clipPath()` | 正则只认 `C:\` 或 `\\` | 增加 `/Users/...`、`~/...` 判断 |
| `tryResolveDrop()` | 依赖服务器按文件名找回路径 | macOS 上 drop 拿不到路径，直接跳过 |

## 4. macOS 上跑起来

```bash
# 环境（建议 3.12）
python3 -m venv .venv && source .venv/bin/activate
pip install python-docx python-pptx openpyxl pillow pypdf olefile mammoth pywebview pyobjc-framework-WebKit pyinstaller

# 开发调试（浏览器打开）
python run.py --port 8765

# 桌面窗口（改完 launcher 后）
python launcher.py
```

打包 `.app`：

```bash
pyinstaller --noconfirm --windowed --name "棱镜 Prismatch" \
  --icon icon.icns \
  --add-data "app:app" --add-data "vendor:vendor" \
  launcher.py
```
注意 `--add-data` 在 macOS 用 `:` 分隔（Windows 是 `;`）。

未签名分发：对方右键 → 打开；或 `xattr -dr com.apple.quarantine "/Applications/棱镜 Prismatch.app"`。

正式分发需 Apple Developer 账号 + `codesign` + `notarytool`。

## 5. 数据与状态

- 运行时数据写在**程序同目录**的 `data/`（reports、docs、images）和 `logs/`
- 报告格式：`data/reports/<job>.meta.json` + `<id>.json.gz` + `<id>.txt`
- 源码里已判断 `sys.frozen`，打包后 `_MEIPASS` 放资源、exe 同目录放数据，macOS 版沿用即可（注意 .app 内不可写，数据目录要改到 `~/Library/Application Support/Prismatch` 或 app 同级）

## 6. 已知问题 / 待办

1. WebView2 / WKWebView 下窗口底部偶尔出现一条灰色横条（页面自身无横向溢出，疑似 overlay 滚动条），可尝试 Chromium/WK 启动参数或忽略
2. `.doc` 老格式尾部偶有乱码，已用 FIB 分片表缓解
3. 扫描件 PDF 无文字层 → 目前报解析失败，未来可接 OCR
4. 自建库（第二套库）模块只有界面骨架，逻辑未接
5. 报告「打印全文」依赖原始 docx 缓存，旧报告没有

## 7. 建议的第一步

1. 先把 `launcher.py` 里 Windows 钩子全部条件化（`if sys.platform == "win32":`），保证能 import
2. 用 `python run.py` 在浏览器里跑通一次完整检测，确认引擎无平台问题
3. 再接 pywebview 窗口，最后做 `.app` 打包
