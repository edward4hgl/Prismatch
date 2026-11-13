"""Standalone HTML report (matches the in-app summary + detail views)."""
from __future__ import annotations

import html
import time


def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _dur(sec) -> str:
    s = max(0, int(round(float(sec or 0))))
    m, r = divmod(s, 60)
    return f"{r} 秒" if m == 0 else f"{m} 分 {r} 秒"


def _hl(text: str, spans) -> str:
    if not spans:
        return _e(text)
    out, pos = [], 0
    for s, e, sc in sorted(spans, key=lambda x: x[0]):
        s, e = max(0, int(s)), min(len(text), int(e))
        if s < pos or e <= s:
            continue
        out.append(_e(text[pos:s]))
        cls = "hit" if sc >= 0.8 else "warn"
        out.append(f'<mark class="{cls}" title="{sc:.0%}">{_e(text[s:e])}</mark>')
        pos = e
    out.append(_e(text[pos:]))
    return "".join(out)


CSS = """
:root{--bg:#0b1020;--panel:rgba(255,255,255,.05);--line:rgba(255,255,255,.1);--fg:#e8ecf8;--dim:#8b96b5;--bad:#ff5b7f;--warn:#ffbe50}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 800px at 15% -10%,#1c2150 0%,transparent 60%),#080b16;
 color:var(--fg);font:14px/1.75 "Inter","PingFang SC","Microsoft YaHei",system-ui,sans-serif;padding:34px 26px}
.wrap{max-width:1240px;margin:0 auto}
h1{font-size:26px;margin:0 0 4px}
h2{font-size:16px;margin:28px 0 10px;color:#cfd6ee}
.sub{color:var(--dim);margin:0 0 20px;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0 22px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:13px 15px}
.card .k{font-size:11.5px;color:var(--dim)}
.card .v{font-size:22px;font-weight:700;margin-top:2px}
table{width:100%;border-collapse:collapse;font-size:13px;border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 11px;text-align:left;border-bottom:1px solid rgba(255,255,255,.06)}
th{background:rgba(255,255,255,.04);color:var(--dim);font-weight:500;font-size:12px}
.tag{display:inline-block;font-size:12px;border:1px solid rgba(255,190,80,.3);background:rgba(255,190,80,.12);
 border-radius:7px;padding:2px 8px;margin:2px 5px 2px 0}
.pane{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:10px 0 22px}
.col{background:rgba(0,0,0,.25);border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:12px 14px;
 font-size:13px;line-height:1.95;white-space:pre-wrap;word-break:break-word}
:root{color-scheme:dark}
mark{background:transparent;border-radius:3px;padding:1px 0}
mark.hit{background:rgba(255,91,127,.3);box-shadow:inset 0 -2px 0 rgba(255,91,127,.8)}
mark.warn{background:rgba(255,190,80,.22);box-shadow:inset 0 -2px 0 rgba(255,190,80,.6)}
h3{font-size:13.5px;margin:18px 0 6px;color:#b9c2ff}
.imgrow{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:8px 0}
.imgbox{background:rgba(0,0,0,.25);border:1px solid rgba(255,255,255,.07);
 border-radius:10px;padding:6px;text-align:center}
.imgbox img{max-width:100%;max-height:220px;border-radius:6px}
.foot{margin-top:36px;color:#5f6a8a;font-size:11.5px;text-align:center}
@media print{body{background:#fff;color:#111}.card,.col{border-color:#ddd;background:#fff}
 h1,h2,h3{color:#111}.sub,.card .k,th{color:#555}mark.hit{background:#ffe0e6}mark.warn{background:#fff3d6}}
"""


def render_report(result) -> str:
    docs = result["docs"]
    stats = result["stats"]
    names = [d["name"] for d in docs]
    group_count = {}
    for d in docs:
        key = d.get("group") or "未分组"
        group_count[key] = group_count.get(key, 0) + 1
    docs_line = " · ".join(f"{_e(k)} <b>{v}</b> 份" for k, v in group_count.items())
    tender_count = len(result.get("tender") or [])
    key_line = " · ".join(
        f"{_e(g['label'])} <b>{len(g['items'])}</b> 处" for g in result["keyinfo"]
    ) or "无"
    prop_line = (f"<b>{len(result['properties'])}</b> 项重复（作者 / 公司 / 时间）"
                 if result["properties"] else "无")

    rows = "".join(
        f"<tr><td>{i+1}</td><td>{_e(names[p['a']])}</td><td>{_e(names[p['b']])}</td>"
        f"<td>{p['sentences']}</td><td>{p['paragraphs']}</td><td>{p.get('images',0)}</td>"
        f"<td><b>{p['score']*100:.1f}%</b></td></tr>"
        for i, p in enumerate(result["pairs"])
    ) or '<tr><td colspan="7">无</td></tr>'

    key = "".join(
        f'<span class="tag"><b>{_e(g["label"])}</b> ' +
        "、".join(_e(x["value"]) for x in g["items"][:4]) + "</span>"
        for g in result["keyinfo"]
    ) or '<span style="color:#8b96b5">未发现相同身份证号 / 手机号 / 公司名称</span>'

    props = "".join(
        f'<span class="tag"><b>{_e(p["label"])}</b> {_e(p["value"])}</span>'
        for p in result["properties"]
    ) or '<span style="color:#8b96b5">无异常</span>'

    errs = result.get("errors") or []
    err_html = ""
    if errs:
        err_html = ("<h2>解析失败的文档（已跳过）</h2>" + "".join(
            f'<div class="sub">✕ {_e(e["name"])}：{_e(e["error"])}</div>' for e in errs))

    gp = result.get("groupPairs") or []
    gp_html = ""
    if gp:
        gp_rows = "".join(
            f"<tr><td>{i+1}</td><td>{_e(g['a'])}</td><td>{_e(g['b'])}</td>"
            f"<td>{g['sentences']}</td><td>{g['paragraphs']}</td><td>{g['images']}</td>"
            f"<td><b>{g['score']*100:.1f}%</b></td></tr>"
            for i, g in enumerate(gp))
        gp_html = (
            "<h2>公司（文件夹）级对比</h2>"
            "<table><thead><tr><th>序号</th><th>公司 A</th><th>公司 B</th>"
            "<th>相似句子</th><th>相似段落</th><th>相似图片</th><th>重复率</th></tr></thead>"
            f"<tbody>{gp_rows}</tbody></table>"
            '<p class="sub">跨公司按内容比对：A 的任意文件与 B 的任意文件交叉比较，与文件名无关；'
            '招标文件夹的内容已先行剔除。</p>'
        )

    img_by_pair = {}
    for x in result.get("imagePairs", []):
        img_by_pair.setdefault((x["a"], x["b"]), []).append(x)

    details = []
    for p in result["pairs"][:40]:
        imgs = img_by_pair.get((p["a"], p["b"])) or img_by_pair.get((p["b"], p["a"])) or []
        img_html = ""
        if imgs and imgs[0].get("a_img"):
            rows_i = []
            for x in imgs[:24]:
                if p["a"] == x["a"]:
                    left, right = x.get("a_img"), x.get("b_img")
                else:
                    left, right = x.get("b_img"), x.get("a_img")
                rows_i.append(
                    f'<div class="imgrow"><div class="imgbox"><img src="images/{_e(left)}" alt=""></div>'
                    f'<div class="imgbox"><img src="images/{_e(right)}" alt=""></div></div>')
            img_html = "<h3>相似图片</h3>" + "".join(rows_i)
        pa = "".join(
            f'<h3>第 {b["a_para"]+1} 段 · 相似度 {b["score"]:.0%}</h3>'
            f'<div class="pane"><div class="col">{_hl(b["a_text"], b["a_spans"])}</div>'
            f'<div class="col">{_hl(b["b_text"], b["b_spans"])}</div></div>'
            for b in p["blocks"][:20]
        )
        details.append(
            f'<h2>{_e(names[p["a"]])} ↔ {_e(names[p["b"]])} · 重复率 {p["score"]*100:.1f}%</h2>'
            f'<p class="sub">相似句子 {p["sentences"]} · 相似段落 {p["paragraphs"]} · '
            f'相似图片 {p.get("images",0)} · A 方向 {p["ratio_a"]*100:.1f}% / B 方向 {p["ratio_b"]*100:.1f}%</p>'
            + pa + img_html
        )

    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>棱镜 Prismatch · 查重报告</title><style>{CSS}</style></head><body><div class="wrap">
<h1>棱镜 Prismatch · 查重报告</h1>
<p class="sub">生成时间 {time.strftime("%Y-%m-%d %H:%M:%S")} · 总耗时 <b>{_dur(stats["elapsed"])}</b>（{stats["elapsed"]} 秒） · 阈值 {stats["thresholds"]["sentence"]}</p>
<div class="grid">
<div class="card"><div class="k">送检文档</div><div class="v">{stats["docs"]} 份</div></div>
<div class="card"><div class="k">最大相似句子</div><div class="v">{stats["max_sentences"]}</div></div>
<div class="card"><div class="k">最大相似段落</div><div class="v">{stats["max_paragraphs"]}</div></div>
<div class="card"><div class="k">最大相似图片</div><div class="v">{stats["max_images"]}</div></div>
</div>
<p class="sub">对比文档：{docs_line}　|　招标文件：<b>{tender_count}</b> 份　|　剔除 {stats["filtered"]} 段</p>
<p class="sub">关键信息：{key_line}　|　文档属性：{prop_line}</p>
{err_html}
{gp_html}
<h2>文件级明细</h2>
<table><thead><tr><th>序号</th><th>文件1</th><th>文件2</th><th>相似句子</th><th>相似段落</th><th>相似图片</th><th>重复率</th></tr></thead>
<tbody>{rows}</tbody></table>
{''.join(details)}
<p class="foot">由 棱镜 Prismatch 本地生成 · 全部计算在本机完成</p>
</div></body></html>"""
