"use strict";
/* 报告视图：汇总 / 相似句子 / 相似段落 / 相似图片 / 打印 */
(function () {
  const R = { res: null, view: "summary", pair: 0, block: 0, onlySim: true, meta: {}, gkey: 0,
              origin: null, focus: null };

  const esc = (s) => String(s == null ? "" : s)
    .replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function hl(text, spans) {
    if (!spans || !spans.length) return esc(text);
    let out = "", pos = 0;
    for (const [s, e, sc, idx] of spans.slice().sort((x, y) => x[0] - y[0])) {
      if (s < pos) continue;
      out += esc(text.slice(pos, s));
      const item = idx == null ? "" : ` data-item="${idx}"`;
      out += `<mark class="${sc >= 0.8 ? "hit" : "warn"}"${item}>${esc(text.slice(s, e))}</mark>`;
      pos = e;
    }
    return out + esc(text.slice(pos));
  }

  function pairOf(i, j) {
    return R.res.pairs.find((p) =>
      (p.a === i && p.b === j) || (p.a === j && p.b === i)) || null;
  }

  function open(result, meta) {
    R.res = result;
    R.meta = meta || {};
    R.view = "summary";
    R.pair = 0;
    R.block = 0;
    R.onlySim = true;
    paint();
  }

  function setView(v) {
    R.view = v;
    if (v === "sentence" || v === "para") R.item = 0;
    if (v === "print") { askPrint(); R.view = "summary"; return; }
    paint();
  }

  /* ---------------- print current pair ---------------- */
  function askPrint() {
    const r = R.res, p = r.pairs[R.pair];
    if (!p) return;
    const names = r.docs.map((d) => d.name);
    const box = document.createElement("div");
    box.className = "modal";
    const ga = r.docs[p.a].group || "未分组";
    const gb = r.docs[p.b].group || "未分组";
    box.innerHTML = `<div class="modal-card">
      <h3>打印当前对比组</h3>
      <p class="note small">${esc(names[p.a])}<br>↔ ${esc(names[p.b])}</p>
      <div class="opts">
        <button data-mode="sentence">相似句子报告（左右对照）</button>
        <button data-mode="para">相似段落报告（左右对照）</button>
      </div>
      <div class="opts row" style="margin-top:10px">
        <button data-mode="full-a">打印第 1 组（${esc(ga)}）全文</button>
        <button data-mode="full-b">打印第 2 组（${esc(gb)}）全文</button>
      </div>
      <div class="opts" style="margin-top:10px">
        <button data-mode="cancel" class="ghost">取消</button>
      </div>
    </div>`;
    box.addEventListener("click", (ev) => {
      if (ev.target === box) { box.remove(); return; }
      const btn = ev.target.closest("button");
      if (!btn) return;
      const mode = btn.dataset.mode;
      box.remove();
      if (mode === "sentence" || mode === "para") buildPrint(mode);
      else if (mode === "full-a") buildFullPrint("a");
      else if (mode === "full-b") buildFullPrint("b");
    });
    document.body.appendChild(box);
  }

  function buildPrint(mode) {
    const r = R.res, p = r.pairs[R.pair];
    if (!p) return;
    const A = r.docs[p.a], B = r.docs[p.b];
    const items = buildItems(p, mode);
    const blkA = {}, blkB = {};
    for (const blk of A.blocks) blkA[blk.i] = blk;
    for (const blk of B.blocks) blkB[blk.i] = blk;

    const headBlock = `<h1>${esc(A.name)} ↔ ${esc(B.name)}</h1>
      <div class="pr-first-head">
        <div class="ph-col">第 1 组（${esc(A.group || "未分组")}）</div>
        <div class="ph-col">第 2 组（${esc(B.group || "未分组")}）</div>
      </div>`;

    // thead 会被浏览器在每一页顶部重复绘制
    const out = [`<table class="pr-frame"><thead><tr><th>${headBlock}</th></tr></thead><tbody><tr><td>`,
      `<p>相似${mode === "sentence" ? "句子" : "段落"}报告 · 共 ${items.length} 处 · 生成于 ${new Date().toLocaleString("zh-CN")}</p>`];
    const pageA = buildPageMap(A), pageB = buildPageMap(B);
    const pageLabel = (m, para) => {
      const p = m[para];
      if (!p || !p.page) return "";
      return p.exact ? `第 ${p.page} 页` : `约第 ${p.page} 页`;
    };

    let count = 0;
    items.forEach((it, idx) => {
      if (count >= 2000) return;
      count += 1;
      const ba = blkA[it.a_para], bb = blkB[it.b_para];
      if (!ba || !bb) return;
      const score = Math.round((it.score || 0) * 100);
      let ta, tb;
      if (mode === "sentence") {
        ta = esc(ba.t.slice(it.a_start, it.a_end));
        tb = esc(bb.t.slice(it.b_start, it.b_end));
      } else {
        ta = renderPara(ba.t, [[it.a_start, it.a_end]]);
        tb = renderPara(bb.t, [[it.b_start, it.b_end]]);
      }
      out.push(`<div class="pr-item">
        <div class="pr-side">
          <div class="pr-head">第 1 组 · ${esc(A.name)} · ${pageLabel(pageA, it.a_para)} · <span class="pr-score">相似度 ${score}%</span></div>
          <div class="pr-text${mode === "sentence" ? " red" : ""}">${ta}</div>
        </div>
        <div class="pr-side">
          <div class="pr-head">第 2 组 · ${esc(B.name)} · ${pageLabel(pageB, it.b_para)} · <span class="pr-score">相似度 ${score}%</span></div>
          <div class="pr-text${mode === "sentence" ? " red" : ""}">${tb}</div>
        </div>
      </div>`);
    });
    out.push(`</td></tr></tbody></table>`);

    let area = document.getElementById("printArea");
    if (!area) {
      area = document.createElement("div");
      area.id = "printArea";
      document.body.appendChild(area);
    }
    area.innerHTML = out.join("");
    showPrintArea();
  }

  async function buildFullPrint(side) {
    const r = R.res, p = r.pairs[R.pair];
    if (!p) return;
    const docIdx = side === "a" ? p.a : p.b;
    const doc = r.docs[docIdx];

    // 先尝试用原文档渲染（保留表格/图片/版式），失败再退回纯文本
    const area = ensurePrintArea();
    area.innerHTML = `<h1>${esc(doc.name)}</h1>
      <p>${esc(doc.group || "未分组")} · 全文打印 · 相似部分红色标注并附相似度</p>
      <div class="rich pr-full-rich" id="prRender">正在加载原文…</div>`;
    const holder = document.getElementById("prRender");
    const ok = await renderDocInto(holder, doc, true);
    if (ok) {
      markFull(holder, side);
      showPrintArea();
      return;
    }
    area.innerHTML = "";
    buildFullPrintText(side);
  }

  async function renderDocInto(el, doc, forPrint) {
    try {
      if (doc.raw && window.docx && window.docx.renderAsync) {
        const resp = await fetch(`/api/raw/${R.meta.job}/${doc.raw}`);
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const buf = await resp.arrayBuffer();
        el.innerHTML = "";
        await window.docx.renderAsync(new Uint8Array(buf), el, null, {
          inWrapper: false,
          ignoreWidth: !forPrint,
          ignoreHeight: !forPrint,
          breakPages: !!forPrint,
          renderHeaders: false,
          renderFooters: false,
          useBase64URL: true,
        });
        return true;
      }
      if (doc.html) {
        const resp = await fetch(`/api/doc/${R.meta.job}/${doc.html}`);
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        el.innerHTML = await resp.text();
        return true;
      }
    } catch (_) {
      return false;
    }
    return false;
  }

  function markFull(root, side) {
    const p = R.res.pairs[R.pair];
    if (!p) return;
    const doc = side === "a" ? R.res.docs[p.a] : R.res.docs[p.b];
    const items = [];
    for (const b of p.blocks) {
      const para = side === "a" ? b.a_para : b.b_para;
      for (const sp of (side === "a" ? b.a_spans : b.b_spans)) {
        items.push({ para, s: sp[0], e: sp[1], score: sp[2] || 0 });
      }
    }
    const els = [...root.querySelectorAll("p,li,td,h1,h2,h3,h4,h5,h6")];
    const byText = new Map();
    for (const n of els) {
      const k = nrm(n.textContent);
      if (k && !byText.has(k)) byText.set(k, n);
    }
    const blkByPara = {}, elByPara = {};
    for (const blk of doc.blocks) {
      blkByPara[blk.i] = blk;
      const key = nrm(blk.t);
      let el = byText.get(key);
      if (!el && key.length >= 12) {
        el = els.find((n) => nrm(n.textContent).startsWith(key.slice(0, 40)));
      }
      if (el) { el.setAttribute("data-para", blk.i); elByPara[blk.i] = el; }
    }

    items.forEach((it, idx) => {
      const el = elByPara[it.para];
      const blk = blkByPara[it.para];
      if (!el || !blk) return;
      const sentence = blk.t.slice(it.s, it.e);
      if (!sentence || sentence.trim().length < 2) return;
      markSentence(el, sentence, "f" + idx);
    });

    items.forEach((it, idx) => {
      const el = elByPara[it.para];
      if (!el) return;
      const m = el.querySelector(`[data-item="f${idx}"]`);
      if (m) {
        const badge = document.createElement("span");
        badge.className = "pr-score";
        badge.textContent = Math.round((it.score || 0) * 100) + "%";
        m.parentNode.insertBefore(badge, m);
      }
    });
  }

  function ensurePrintArea() {
    let area = document.getElementById("printArea");
    if (!area) {
      area = document.createElement("div");
      area.id = "printArea";
      document.body.appendChild(area);
    }
    return area;
  }

  /* 打印前把"一屏高度 + 滚动容器"这两件事彻底去掉，否则 WebView2 只肯输出一页。
     用内联样式 + important，优先级压过 style.css 里 body{overflow-x:hidden} 的
     !important 规则（内联的 !important 永远最大）。 */
  const PRINT_SAVED = [];

  function lockScrollForPrint() {
    const set = (el, props) => {
      if (!el) return;
      for (const [k, v] of Object.entries(props)) {
        PRINT_SAVED.push([el, k, el.style.getPropertyValue(k), el.style.getPropertyPriority(k)]);
        el.style.setProperty(k, v, "important");
      }
    };
    set(document.documentElement, {
      height: "auto", "min-height": "0", overflow: "visible", "overflow-y": "visible",
    });
    set(document.body, {
      height: "auto", "min-height": "0", overflow: "visible", "overflow-y": "visible",
      position: "static", display: "block",
    });
    const area = document.getElementById("printArea");
    set(area, { display: "block", height: "auto", "max-height": "none", overflow: "visible" });
  }

  function unlockScrollForPrint() {
    while (PRINT_SAVED.length) {
      const [el, k, v, p] = PRINT_SAVED.pop();
      if (v) el.style.setProperty(k, v, p);
      else el.style.removeProperty(k);
    }
  }

  function showPrintArea() {
    document.body.classList.add("printing");
    lockScrollForPrint();
    window.scrollTo(0, 0);
    let cleaned = false;
    const done = () => {
      if (cleaned) return;
      cleaned = true;
      window.removeEventListener("afterprint", done);
      document.body.classList.remove("printing");
      unlockScrollForPrint();
      const area = document.getElementById("printArea");
      if (area) area.innerHTML = "";
    };
    // 打印对话框关闭后浏览器会派发 afterprint；某些宿主不派发，用长超时兜底。
    // 千万别用短超时：WebView2 里 window.print() 可能立即返回，
    // 提前恢复样式会让内容塌回一屏高度，结果只打出一页。
    window.addEventListener("afterprint", done);
    try {
      window.print();
    } finally {
      setTimeout(done, 120000);
    }
  }

  function buildFullPrintText(side) {
    const r = R.res, p = r.pairs[R.pair];
    if (!p) return;
    const doc = side === "a" ? r.docs[p.a] : r.docs[p.b];
    const spans = {};
    for (const b of p.blocks) {
      const para = side === "a" ? b.a_para : b.b_para;
      const list = side === "a" ? b.a_spans : b.b_spans;
      (spans[para] = spans[para] || []).push(...list);
    }
    const pages = buildPageMap(doc);
    const out = [
      `<h1>${esc(doc.name)}</h1>`,
      `<p>${esc(doc.group || "未分组")} · 全文打印 · 相似部分红色标注并附相似度</p>`,
    ];
    const body = doc.all || doc.blocks || [];
    for (const blk of body) {
      const sp = (spans[blk.i] || []).slice().sort((x, y) => x[0] - y[0]);
      let html = "", pos = 0;
      for (const [s, e, sc] of sp) {
        if (s < pos) continue;
        html += esc(blk.t.slice(pos, s));
        html += `<span class="pr-score">${Math.round((sc || 0) * 100)}%</span><span class="pr-hit">${esc(blk.t.slice(s, e))}</span>`;
        pos = e;
      }
      html += esc(blk.t.slice(pos));
      const pg = pages[blk.i];
      out.push(`<div class="pr-full">
        <div class="pr-head">${pg && pg.page ? (pg.exact ? `第 ${pg.page} 页` : `约第 ${pg.page} 页`) : ""}</div>
        <div class="pr-text">${html}</div>
      </div>`);
    }
    let area = document.getElementById("printArea");
    if (!area) {
      area = document.createElement("div");
      area.id = "printArea";
      document.body.appendChild(area);
    }
    area.innerHTML = out.join("");
    showPrintArea();
  }

  function buildPageMap(doc) {
    const map = {};
    let chars = 0;
    const list = doc.all || doc.blocks || [];
    for (const blk of list) {
      const pg = Number(blk.pg) || 0;
      if (pg > 0) {
        map[blk.i] = { page: pg, exact: true };
      } else {
        map[blk.i] = { page: Math.floor(chars / 1400) + 1, exact: false };
      }
      chars += (blk.t || "").length;
    }
    return map;
  }

  function renderPara(text, spans) {
    if (!spans || !spans.length) return esc(text);
    let out = "", pos = 0;
    for (const [s, e] of spans.slice().sort((x, y) => x[0] - y[0])) {
      if (s < pos) continue;
      out += esc(text.slice(pos, s));
      out += `<span class="pr-hit">${esc(text.slice(s, e))}</span>`;
      pos = e;
    }
    return out + esc(text.slice(pos));
  }

  function goPair(idx, block) {
    R.pair = idx;
    R.block = block || 0;
    R.view = "para";
    paint();
  }

  function paint() {
    const box = document.getElementById("view");
    const r = R.res;
    if (!r) { box.innerHTML = ""; return; }
    if (R.view === "summary") box.innerHTML = summary();
    else if (R.view === "sentence") box.innerHTML = detailView("sentence");
    else if (R.view === "para") box.innerHTML = detailView("para");
    else if (R.view === "pic") box.innerHTML = pictures();
    else if (R.view === "files") box.innerHTML = files();
    wire();
    if (R.view === "sentence" || R.view === "para") {
      if (document.querySelector("#view .rich")) hydrateRich2();
      else focusItem(R.item || 0, false);
    }
    if (R.view === "summary" && R.focus) scrollToOrigin();
  }

  function fmtDuration(sec) {
    const s = Math.max(0, Math.round(Number(sec) || 0));
    const m = Math.floor(s / 60);
    const r = s % 60;
    if (m <= 0) return `${r} 秒`;
    return `${m} 分 ${r} 秒`;
  }

  const fileLink = (docId, name) =>
    `<a href="#" class="filelink" data-doc="${docId}" title="用本机默认程序打开原文件">${esc(name)}</a>`;

  // 数字本身就是入口：蓝色可点，0 值置灰不可点，省掉一列按钮
  const numCell = (idx, tab, n, unit) => {
    const v = Number(n) || 0;
    if (idx < 0 || v <= 0) return `<td class="num zero">${v}</td>`;
    const label = tab === "sentence" ? "相似句子" : tab === "para" ? "相似段落" : "相似图片";
    return `<td class="num"><button type="button" class="numlink" data-pair="${idx}" data-tab="${tab}" title="查看${label}（${v} ${unit}）">${v}</button></td>`;
  };

  async function openFile(docId) {
    const doc = (R.res && R.res.docs) ? R.res.docs[docId] : null;
    const original = (doc && doc.path) || "";

    // 内嵌窗口：直接让 Python 用系统默认程序打开原文件，不走服务端
    try {
      if (original && window.pywebview && window.pywebview.api && window.pywebview.api.open_path) {
        const r = await window.pywebview.api.open_path(original);
        if (r && r.ok) return;
      }
    } catch (_) { /* 退回 HTTP */ }

    if (!R.meta.job) return;
    try {
      const res = await fetch("/api/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job: R.meta.job, doc: docId }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.error || ("HTTP " + res.status));
    } catch (e) {
      alert("打开文件失败：" + (e.message || e));
    }
  }

  // 右键文件名：在资源管理器里定位并选中（不是只打开文件夹）
  async function revealFile(docId) {
    const doc = (R.res && R.res.docs) ? R.res.docs[docId] : null;
    const original = (doc && doc.path) || "";

    try {
      if (original && window.pywebview && window.pywebview.api && window.pywebview.api.reveal_path) {
        const r = await window.pywebview.api.reveal_path(original);
        if (r && r.ok) return;
      }
    } catch (_) { /* 退回 HTTP */ }

    if (!R.meta.job) return;
    try {
      const res = await fetch("/api/reveal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job: R.meta.job, doc: docId }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.error || ("HTTP " + res.status));
    } catch (e) {
      alert("定位文件失败：" + (e.message || e));
    }
  }

  let ctxEl = null;
  function closeCtx() {
    if (ctxEl) { ctxEl.remove(); ctxEl = null; }
  }

  function openCtx(x, y, docId) {
    closeCtx();
    const el = document.createElement("div");
    el.className = "ctxmenu";
    el.innerHTML = `<button type="button" class="ctx-item" data-reveal="${docId}">在文件夹中显示</button>`;
    document.body.appendChild(el);

    const box = el.getBoundingClientRect();
    const left = Math.min(Math.max(8, x), window.innerWidth - box.width - 8);
    const top = Math.min(Math.max(8, y), window.innerHeight - box.height - 8);
    el.style.left = left + "px";
    el.style.top = top + "px";

    el.querySelector("[data-reveal]").onclick = () => {
      const id = Number(el.querySelector("[data-reveal]").dataset.reveal);
      closeCtx();
      revealFile(id);
    };
    ctxEl = el;
  }

  /* ---------------- summary ---------------- */
  function summary() {    const r = R.res, s = r.stats, names = r.docs.map((d) => d.name);
    const docsLine = names.map((n, i) => {
      const g = r.docs[i].group;
      return `<span class="tag"><b>${esc(n)}</b>${g ? " · " + esc(g) : ""}</span>`;
    }).join(" ");
    const tender = (r.tender && r.tender.length ? r.tender : (R.meta.tender || []));

    const groupCount = {};
    r.docs.forEach((d) => {
      const k = d.group || "未分组";
      groupCount[k] = (groupCount[k] || 0) + 1;
    });
    const docLine = Object.entries(groupCount)
      .map(([k, v]) => `${esc(k)} <b>${v}</b> 份`).join(" · ") || `<b>${s.docs}</b> 份`;
    const tenderLine = tender.length ? `<b>${tender.length}</b> 份` : `<span class="dim">未导入</span>`;

    const keyLine = r.keyinfo.length
      ? r.keyinfo.map((g) => `${esc(g.label)} <b>${g.items.length}</b> 处`).join(" · ")
      : `<span class="dim">无</span>`;
    const propKept = (r.properties || []).filter((p) => {
      const units = new Set((p.docs || []).map((id) => (r.docs[id] || {}).group || "未分组"));
      return units.size >= 2 || (units.size === 1 && units.has("未分组"));
    });
    const propLine = propKept.length
      ? `<b>${propKept.length}</b> 项跨单位重复（作者 / 公司 / 时间）`
      : `<span class="dim">无</span>`;

    const propRows = propKept.map((p, pi) => {
      const names = (p.docs || []).map((id) => r.docs[id]).filter(Boolean);
      const byUnit = new Map();
      for (const d of names) {
        const g = d.group || "未分组";
        if (!byUnit.has(g)) byUnit.set(g, []);
        byUnit.get(g).push(d);
      }
      const entries = [...byUnit.entries()];
      const band = pi % 2 ? "pb" : "pa";
      return entries.map(([unit, list], k) => {
        const shown = list.slice(0, 3).map((d) => esc(d.name)).join("、");
        const more = list.length > 3 ? ` 等 ${list.length} 份` : "";
        const head = k === 0
          ? `<td class="ctr" rowspan="${entries.length}">${esc(p.label)}</td>` +
            `<td class="ctr pval" rowspan="${entries.length}">${esc(p.value)}</td>` +
            `<td class="ctr num" rowspan="${entries.length}">${names.length}</td>`
          : "";
        return `<tr class="${band}${k ? " punit-row" : ""}">${head}<td class="punit">${esc(unit)}</td>` +
          `<td class="pfile">${shown}${more}</td></tr>`;
      }).join("");
    }).join("");
    const propBlock = propKept.length ? `
      <div class="card prop-card">
        <div class="prop-head" id="propHead"><span class="chev">▶</span> 文档属性重复（${propKept.length} 项）
          <span class="h3-tip">同一作者 / 公司 / 时间出现在多份文件里，点开看明细</span></div>
        <div class="prop-body hidden" id="propBody">
          <table class="tbl"><thead><tr><th>字段</th><th>值</th><th class="num">文件数</th><th>涉及单位</th><th>文件</th></tr></thead>
          <tbody>${propRows}</tbody></table>
        </div>
      </div>` : "";

    const gp = r.groupPairs || [];
    const gpBlocks = gp.map((g, gi) => {
      const fileRows = (g.files || []).map((f) => {
        const idx = r.pairs.findIndex((p) =>
          (p.a === f.a && p.b === f.b) || (p.a === f.b && p.b === f.a));
        return `<tr>
          <td>${fileLink(f.a, f.name_a)}</td><td>${fileLink(f.b, f.name_b)}</td>
          ${numCell(idx, "sentence", f.sentences, "句")}
          ${numCell(idx, "para", f.paragraphs, "段")}
          ${numCell(idx, "pic", f.images, "张")}
          <td><b>${(f.score * 100).toFixed(1)}%</b></td>
        </tr>`;
      }).join("");
      const cls = g.score >= 0.8 ? "hi" : g.score >= 0.5 ? "mid" : "lo";
      return `<div class="grp-block" data-gi="${gi}">
        <div class="grp-head">
          <span class="chev2">▶</span>
          <b>${esc(g.a)}</b><span class="arrow">↔</span><b>${esc(g.b)}</b>
          <span class="hint">句子 ${g.sentences} · 段落 ${g.paragraphs} · 图片 ${g.images} · ${(g.files || []).length} 对文件</span>
          <span class="score ${cls}">${(g.score * 100).toFixed(1)}%</span>
        </div>
        <div class="grp-body">
          ${fileRows
            ? `<table class="tbl"><thead><tr><th>${esc(g.a)}</th><th>${esc(g.b)}</th><th class="num">句子</th><th class="num">段落</th><th class="num">图片</th><th class="num">重复率</th></tr></thead><tbody>${fileRows}</tbody></table>`
            : `<p class="note small">这两家之间没有检出相似内容</p>`}
        </div>
      </div>`;
    }).join("") || `<p class="note small">散装文件模式（无文件夹分组），没有公司级对比</p>`;

    const rows = r.pairs.map((p, i) => `
      <tr>
        <td>${i + 1}</td>
        <td>${fileLink(p.a, names[p.a])}</td>
        <td>${fileLink(p.b, names[p.b])}</td>
        ${numCell(i, "sentence", p.sentences, "句")}
        ${numCell(i, "para", p.paragraphs, "段")}
        ${numCell(i, "pic", p.images || 0, "张")}
        <td><b>${(p.score * 100).toFixed(1)}%</b></td>
      </tr>`).join("") || `<tr class="empty"><td colspan="6">没有超过阈值的相似内容</td></tr>`;

    const errs = r.errors || [];
    const errBlock = errs.length ? `<div class="card" style="border-color:rgba(255,91,127,.35)">
      <h3 class="h3">解析失败的文档（已跳过，未参与比对）</h3>
      ${errs.map((e) => `<div class="note small">✕ ${esc(e.name)}：${esc(e.error)}</div>`).join("")}
    </div>` : "";

    return `
    ${errBlock}
    <div class="sumgrid">
      <div class="sumcard"><div class="k">送检文档</div><div class="v">${s.docs} 份</div></div>
      <div class="sumcard"><div class="k">最大相似句子</div><div class="v hot">${s.max_sentences}</div></div>
      <div class="sumcard"><div class="k">最大相似段落</div><div class="v hot">${s.max_paragraphs}</div></div>
      <div class="sumcard"><div class="k">最大相似图片</div><div class="v hot">${s.max_images}</div></div>
    </div>
    <div class="card">
      <div class="kv">
        <div class="k">提交时间</div><div>${esc(R.meta.time || "")}</div>
        <div class="k">总耗时</div><div><b>${fmtDuration(s.elapsed)}</b> <span class="dim">（${Number(s.elapsed || 0).toFixed(1)} 秒）</span></div>
        <div class="k">对比文档</div><div>${docLine}</div>
        <div class="k">招标文件</div><div>${tenderLine}</div>
        <div class="k">过滤剔除</div><div>${s.filtered} 段</div>
        <div class="k">关键信息</div><div>${keyLine}</div>
        <div class="k">文档属性</div><div>${propLine}</div>
      </div>
      ${propBlock}
      ${gp.length
        ? `<h3 class="h3">公司级对比（共 ${gp.length} 组 · 点击展开）<span class="h3-tip">左键单击文件名打开文件，右键单击文件名在文件夹显示</span></h3>${gpBlocks}
           <p class="note small">跨公司按内容比对：任一文件与对方任一文件交叉比较，与文件名无关；招标文件夹的内容已先行剔除。</p>`
        : `<h3 class="h3">文件级明细</h3>
           <table class="tbl">
             <thead><tr><th>序号</th><th>文件1</th><th>文件2</th><th>相似句子</th><th>相似段落</th><th>相似图片</th><th>重复率</th></tr></thead>
             <tbody>${rows}</tbody>
           </table>
           <p class="note small">点击绿色数字可打开对应明细。</p>`}
    </div>`;
  }

  /* ---------------- sentences ---------------- */
  function sentences() {
    const r = R.res, p = r.pairs[R.pair];
    if (!p) return `<div class="card">没有可展示的相似句子。</div>`;
    const names = r.docs.map((d) => d.name);
    const rows = [];
    for (const b of p.blocks) {
      const n = Math.max(b.a_spans.length, b.b_spans.length);
      for (let k = 0; k < n; k++) {
        const sa = b.a_spans[k], sb = b.b_spans[k];
        const ta = sa ? b.a_text.slice(sa[0], sa[1]) : "";
        const tb = sb ? b.b_text.slice(sb[0], sb[1]) : "";
        rows.push(`<div class="sent-row">
          <div class="cell"><span class="n">A · 第${b.a_para + 1}段</span>${esc(ta)}</div>
          <div class="cell"><span class="n">B · 第${b.b_para + 1}段</span>${esc(tb)}</div>
        </div>`);
        if (rows.length >= 300) break;
      }
      if (rows.length >= 300) break;
    }
    return `
    <div class="detailbar">
      <b>${esc(names[p.a])} ↔ ${esc(names[p.b])}</b>
      <span class="hint">共 ${p.sentences} 句相似 · 重复率 ${(p.score * 100).toFixed(1)}%</span>
    </div>
    <div id="sentList">${rows.join("") || `<div class="card">无相似句子</div>`}</div>`;
  }

  /* ---------------- paragraphs ---------------- */
  function paragraphs() {
    const r = R.res, p = r.pairs[R.pair];
    if (!p) return `<div class="card">没有可展示的相似段落。</div>`;
    const names = r.docs.map((d) => d.name);
    const A = r.docs[p.a], B = r.docs[p.b];

    const spansA = {}, spansB = {};
    for (const b of p.blocks) {
      (spansA[b.a_para] = spansA[b.a_para] || []).push(...b.a_spans);
      (spansB[b.b_para] = spansB[b.b_para] || []).push(...b.b_spans);
    }

    function render(doc, spans, side) {
      if (R.onlySim) {
        const idxs = Object.keys(spans).map(Number).sort((x, y) => x - y);
        return idxs.map((i) => {
          const blk = doc.blocks.find((x) => x.i === i);
          if (!blk) return "";
          return `<div data-para="${i}">${hl(blk.t, spans[i])}</div>`;
        }).join("<br>") || `<span class="dim">无相似段落</span>`;
      }
      return doc.blocks.map((blk) =>
        `<div data-para="${blk.i}">${hl(blk.t, spans[blk.i])}</div>`).join("");
    }

    return `
    <div class="detailbar">
      <button class="mini" id="paneToggle">${R.onlySim ? "查看全文内容" : "仅查看相似内容"}</button>
      <button class="mini" id="prevPara">上一段</button>
      <button class="mini" id="nextPara">下一段</button>
      <span class="hint">相似段落 ${p.paragraphs} 段 · 点击标红处可定位</span>
    </div>
    <div class="two-pane">
      <div class="pane">
        <div class="pane-head"><span class="nm">${esc(names[p.a])}</span>
          <span class="stat">相似段落：${p.paragraphs} 段</span>
          <span class="stat">全文相似度：${(p.ratio_a * 100).toFixed(2)}%</span></div>
        <div class="pane-body" id="paneA">${render(A, spansA)}</div>
      </div>
      <div class="pane">
        <div class="pane-head"><span class="nm">${esc(names[p.b])}</span>
          <span class="stat">相似段落：${p.paragraphs} 段</span>
          <span class="stat">全文相似度：${(p.ratio_b * 100).toFixed(2)}%</span></div>
        <div class="pane-body" id="paneB">${render(B, spansB)}</div>
      </div>
    </div>`;
  }

  /* ---------------- pictures ---------------- */
  function pictures() {
    const r = R.res, p = r.pairs[R.pair];
    const vt = (cur) => {
      const n = (v) => (v === "sentence" ? p.sentences : v === "para" ? p.paragraphs : (p.images || 0));
      return [["sentence", "相似句子"], ["para", "相似段落"], ["pic", "相似图片"]]
        .map(([v, label]) => `<button class="mini vtab${cur === v ? " on" : ""}" data-vtab="${v}"${n(v) ? "" : " disabled"}>${label}</button>`)
        .join("");
    };
    const back = (title, extra) => `<div class="detailbar stack">
        <div class="db-row">
          <button class="mini" id="picBack">← 返回汇总</button>
          <span class="vtabs">${p ? vt("pic") : ""}</span>
          <button class="mini" id="printBtn">打印报告</button>
        </div>
        ${title || extra ? `<div class="db-row db-title">${title ? `<b>${esc(title)}</b>` : ""}<span class="hint">${extra || ""}</span></div>` : ""}
      </div>`;
    if (!p) return `${back("", "")}<div class="card">没有可展示的相似图片。</div>`;
    const names = r.docs.map((d) => d.name);
    const title = `${names[p.a]} ↔ ${names[p.b]}`;
    const list = (r.imagePairs || []).filter((x) =>
      (x.a === p.a && x.b === p.b) || (x.a === p.b && x.b === p.a));
    if (!list.length) {
      return `${back(title, "相似图片 0 张")}
        <div class="card"><p class="note small">这对文档未检出高度相似图片。</p></div>`;
    }
    const job = R.meta.job || "";
    const rows = list.slice(0, 200).map((x) => {
      const left = p.a === x.a ? x.a_img : x.b_img;
      const right = p.a === x.a ? x.b_img : x.a_img;
      const leftName = p.a === x.a ? names[x.a] : names[x.b];
      const rightName = p.a === x.a ? names[x.b] : names[x.a];
      const url = (n) => (n ? `/api/img/${job}/${n}` : "");
      return `<div class="imgrow">
        <div class="imgbox"><img loading="lazy" src="${url(left)}" alt="">
          <div class="cap">${esc(leftName)} · 图 ${left ? left.replace(/.*_/, "").replace(/\.\w+$/, "") : "?"}</div></div>
        <div class="imgbox"><img loading="lazy" src="${url(right)}" alt="">
          <div class="cap">${esc(rightName)} · 汉明距离 ${x.dist}</div></div>
      </div>`;
    }).join("");
    return `<div class="detailbar">
        <button class="mini" id="picBack">← 返回汇总</button>
        <b>${esc(names[p.a])} ↔ ${esc(names[p.b])}</b>
        <span class="hint">共 ${list.length} 组相似图片</span>
      </div>${rows}`;
  }

  /* ---------------- group drill-down ---------------- */
  function blockHtml(b) {
    return `<div class="cols" style="margin-bottom:10px">
      <div class="col"><div class="t">A · 第 ${b.a_para + 1} 段 · ${(b.score * 100).toFixed(0)}%</div>${hl(b.a_text, b.a_spans)}</div>
      <div class="col"><div class="t">B · 第 ${b.b_para + 1} 段</div>${hl(b.b_text, b.b_spans)}</div>
    </div>`;
  }

  function files() {
    const r = R.res, g = (r.groupPairs || [])[R.gkey];
    if (!g) return `<div class="card">没有公司级对比数据。</div>`;
    const cards = g.files.map((f) => {
      const pair = r.pairs.find((p) =>
        (p.a === f.a && p.b === f.b) || (p.a === f.b && p.b === f.a));
      const cls = f.score >= 0.8 ? "hi" : f.score >= 0.5 ? "mid" : "lo";
      const blocks = pair ? pair.blocks.slice(0, 20).map(blockHtml).join("") : "";
      return `<div class="pair">
        <div class="pair-head">
          <span class="nm">${esc(f.name_a)}</span><span class="arrow">↔</span>
          <span class="nm">${esc(f.name_b)}</span>
          <span class="hint" style="margin-left:12px">${f.sentences} 句 / ${f.paragraphs} 段</span>
          <span class="score ${cls}">${(f.score * 100).toFixed(1)}%</span>
        </div>
        <div class="pair-body">${blocks}</div>
      </div>`;
    }).join("");
    return `<div class="detailbar">
        <button class="mini" id="gpBack">← 返回汇总</button>
        <b>${esc(g.a)} ↔ ${esc(g.b)}</b>
        <span class="hint">A 方向 ${(g.ratio_a * 100).toFixed(1)}% · B 方向 ${(g.ratio_b * 100).toFixed(1)}% · 共 ${g.fileCount} 对文件</span>
      </div>
      <p class="note small">点开任意一对可查看具体相似的句子/段落。</p>
      ${cards || '<div class="card">无相似文件对</div>'}`;
  }

  /* ---------------- detail: full-text columns ---------------- */
  function buildItems(p, mode) {
    const items = [];
    for (const b of p.blocks) {
      if (mode === "para") {
        items.push({
          a_para: b.a_para, a_start: 0, a_end: (b.a_text || "").length,
          b_para: b.b_para, b_start: 0, b_end: (b.b_text || "").length,
          score: b.score,
        });
      } else {
        const n = Math.max(b.a_spans.length, b.b_spans.length);
        for (let k = 0; k < n; k++) {
          const sa = b.a_spans[k], sb = b.b_spans[k];
          items.push({
            a_para: b.a_para, a_start: sa ? sa[0] : 0, a_end: sa ? sa[1] : 0,
            b_para: b.b_para, b_start: sb ? sb[0] : 0, b_end: sb ? sb[1] : 0,
            score: sa ? sa[2] : (sb ? sb[2] : b.score),
          });
        }
      }
    }
    return items;
  }

  function detailView(mode) {
    const r = R.res, p = r.pairs[R.pair];
    if (!p) return `<div class="card">没有可展示的相似内容。</div>`;
    const A = r.docs[p.a], B = r.docs[p.b];
    const items = buildItems(p, mode);

    const spans = (side) => {
      const map = {};
      items.forEach((it, k) => {
        const para = side === "a" ? it.a_para : it.b_para;
        const s = side === "a" ? it.a_start : it.b_start;
        const e = side === "a" ? it.a_end : it.b_end;
        if (e > s) (map[para] = map[para] || []).push([s, e, 1, k]);
      });
      return map;
    };
    const spA = spans("a"), spB = spans("b");
    const label = mode === "sentence" ? "句子" : "段落";

    const pane = (doc, sp, side) => {
      const list = doc.blocks.filter((b) => !R.onlySim || sp[b.i]);
      const plain = list.length
        ? list.map((b) => `<div class="para" data-para="${b.i}">${hl(b.t, sp[b.i])}</div>`).join("")
        : `<span class="dim">没有相似内容</span>`;
      const body = (doc.raw || doc.html)
        ? `<div class="rich" data-side="${side}" data-raw="${esc(doc.raw || "")}" data-html="${esc(doc.html || "")}">正在加载原文…</div><div class="plain-fallback hidden">${plain}</div>`
        : `<div class="rich-note">该文档没有原样排版数据（${
            doc.kind === "docx" ? "旧记录" : doc.kind.toUpperCase()
          }），以下为文字版</div>${plain}`;
      const count = mode === "sentence" ? p.sentences : p.paragraphs;
      const ratio = side === "a" ? p.ratio_a : p.ratio_b;
      return `<div class="pane">
        <div class="pane-head"><span class="nm">${side === "a" ? "第1组：" : "第2组："}${esc(doc.name)}</span></div>
        <div class="pane-meta">相似${label}：${count} ${mode === "sentence" ? "句" : "段"}　全文相似度：${(ratio * 100).toFixed(2)}%</div>
        <div class="pane-tools">
          <button class="mini act-only">仅查看相似内容</button>
          <button class="mini act-full">查看全文内容</button>
          <button class="mini act-prev">上一${label}</button>
          <button class="mini act-next">下一${label}</button>
        </div>
        <div class="pane-body" id="pane${side.toUpperCase()}">${body}</div>
      </div>`;
    };

    const unit = mode === "sentence" ? "句" : "段";
    const lbl = mode === "sentence" ? "句子" : "段落";
    const total = mode === "sentence" ? p.sentences : p.paragraphs;
    const headTxt = total === items.length
      ? `共 ${items.length} 处相似`
      : `相似${lbl} ${total} ${unit} · 分 ${items.length} 处`;
    const vtabs = [["sentence", "相似句子", p.sentences], ["para", "相似段落", p.paragraphs], ["pic", "相似图片", p.images || 0]]
      .map(([v, label, n]) => `<button class="mini vtab${mode === v ? " on" : ""}" data-vtab="${v}"${n ? "" : " disabled"}>${label}</button>`)
      .join("");
    return `<div class="detailbar stack">
        <div class="db-row">
          <button class="mini" id="backSummary">← 返回汇总</button>
          <span class="vtabs">${vtabs}</span>
          <button class="mini" id="printBtn">打印报告</button>
          <button class="mini paper-btn" id="paperBtn" type="button" title="正文：纸面 / 深色"><span class="half"></span></button>
        </div>
        <div class="db-row db-title"><b>${esc(A.name)}</b><span class="arrow">↔</span><b>${esc(B.name)}</b><span class="hint">${headTxt} · 点击标红处可定位</span></div>
      </div>
      <div class="two-pane">${pane(A, spA, "a")}${pane(B, spB, "b")}</div>`;
  }

  function scrollToOrigin() {
    const f = R.focus;
    if (!f) return;
    R.focus = null;
    let el = null;
    if (f.kind === "gp") {
      el = document.querySelector(`#view [data-gp="${f.idx}"]`);
    } else {
      el = document.querySelector(`#view [data-pair="${f.idx}"]`);
      const block = el && el.closest(".grp-block");
      if (block) block.classList.add("open");
    }
    if (!el) return;
    const row = el.closest("tr") || el.closest(".pair") || el;
    document.querySelectorAll("#view .pinned").forEach((n) => n.classList.remove("pinned"));
    row.classList.add("pinned");
    row.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  function itemsNow() {
    const p = R.res && R.res.pairs[R.pair];
    if (!p) return [];
    return buildItems(p, R.view === "sentence" ? "sentence" : "para");
  }

  function scrollInPane(paneEl, target) {
    const body = (paneEl.classList && paneEl.classList.contains("pane-body"))
      ? paneEl
      : paneEl.querySelector(".pane-body");
    if (!body) return;
    const br = body.getBoundingClientRect();
    const tr = target.getBoundingClientRect();
    body.scrollTo({
      top: body.scrollTop + (tr.top - br.top) - body.clientHeight / 2 + tr.height / 2,
      behavior: "smooth",
    });
  }

  function focusItem(index, silent) {
    const items = itemsNow();
    if (!items.length) return;
    index = Math.max(0, Math.min(items.length - 1, index));
    R.item = index;
    const it = items[index];
    document.querySelectorAll("#view .current").forEach((el) => el.classList.remove("current"));
    for (const [paneId, para] of [["paneA", it.a_para], ["paneB", it.b_para]]) {
      const pane = document.getElementById(paneId);
      if (!pane) continue;
      const marks = [...pane.querySelectorAll(`[data-item="${index}"]`)];
      let el = marks[0] || null;
      if (!el) el = pane.querySelector(`[data-para="${para}"]`);
      if (!el) {
        const all = [...pane.querySelectorAll("[data-para]")];
        if (!all.length) continue;
        el = all.filter((n) => Number(n.dataset.para) <= para).pop() || all[0];
      }
      marks.forEach((m) => m.classList.add("current"));
      el.classList.add("current");
      if (!silent) scrollInPane(pane, el);
    }
  }

  function moveItem(delta) {
    focusItem((R.item || 0) + delta);
  }

  /* ---------------- rich (docx HTML) rendering ---------------- */
  function missingNote(e) {
    const msg = String((e && e.message) || e || "");
    if (/\b404\b/.test(msg)) {
      return "该文档的排版快照已被清理（重新检测会自动重建），这里只显示文字对照。";
    }
    return "原文加载失败：" + msg;
  }

  function fallbackToPlain(el, e) {
    const fb = el.nextElementSibling;
    if (!fb || !fb.classList.contains("plain-fallback")) return false;
    el.classList.add("hidden");
    fb.classList.remove("hidden");
    fb.insertAdjacentHTML("afterbegin", `<div class="rich-note">${esc(missingNote(e))}</div>`);
    return true;
  }

  async function hydrateRich() {
    const nodes = document.querySelectorAll("#view .rich");
    for (const el of nodes) {
      const name = el.dataset.html;
      const side = el.dataset.side;
      if (!name || !R.meta.job) { el.textContent = "原文不可用"; continue; }
      try {
        const resp = await fetch(`/api/doc/${R.meta.job}/${name}`);
        if (!resp.ok) throw new Error(String(resp.status));
        el.innerHTML = await resp.text();
      } catch (e) {
        if (!fallbackToPlain(el, e)) el.textContent = missingNote(e);
        continue;
      }
      markRich(el, side);
      if (R.onlySim) {
        [...el.children].forEach((child) => {
          if (!child.querySelector("mark") && child.tagName !== "TABLE") child.style.display = "none";
        });
      }
    }
    focusItem(R.item || 0, false);
  }

  function markRich(root, side) {
    const r = R.res, p = r.pairs[R.pair];
    if (!p) return;
    const mode = R.view === "sentence" ? "sentence" : "para";
    const items = buildItems(p, mode);
    const doc = side === "a" ? r.docs[p.a] : r.docs[p.b];

    const els = [...root.querySelectorAll("p,li,td,h1,h2,h3,h4,h5,h6")];
    const exact = new Map();
    for (const n of els) {
      const k = nrm(n.textContent);
      if (k && !exact.has(k)) exact.set(k, n);
    }

    const elByPara = {};
    for (const blk of doc.blocks) {
      const key = nrm(blk.t);
      if (!key) continue;
      let el = exact.get(key);
      if (!el && key.length > 20) {
        el = els.find((n) => nrm(n.textContent).includes(key.slice(0, 40)));
      }
      if (!el) continue;
      el.setAttribute("data-para", blk.i);
      elByPara[blk.i] = el;
    }

    items.forEach((it, idx) => {
      const para = side === "a" ? it.a_para : it.b_para;
      const s = side === "a" ? it.a_start : it.b_start;
      const e = side === "a" ? it.a_end : it.b_end;
      const el = elByPara[para];
      if (!el || e <= s) return;
      applyMark(el, s, e, idx);
    });
  }

  function applyMark(el, s, e, idx) {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let pos = 0, node;
    while ((node = walker.nextNode())) {
      const start = pos;
      const end = pos + node.nodeValue.length;
      pos = end;
      if (end <= s || start >= e) continue;
      const from = Math.max(s, start) - start;
      const to = Math.min(e, end) - start;
      if (to <= from) continue;
      const range = document.createRange();
      range.setStart(node, from);
      range.setEnd(node, to);
      const mark = document.createElement("mark");
      mark.className = "hit";
      mark.dataset.item = String(idx);
      try { range.surroundContents(mark); } catch (_) { /* 跨节点 */ }
      return;
    }
  }

  function applyMarks(el, spans) {
    const list = spans.map((s) => [s[0], s[1]]).sort((a, b) => b[0] - a[0]);
    for (const [s, e] of list) {
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      let pos = 0, node;
      while ((node = walker.nextNode())) {
        const start = pos;
        const end = pos + node.nodeValue.length;
        pos = end;
        if (end <= s || start >= e) continue;
        const from = Math.max(s, start) - start;
        const to = Math.min(e, end) - start;
        if (to <= from) continue;
        const range = document.createRange();
        range.setStart(node, from);
        range.setEnd(node, to);
        const mark = document.createElement("mark");
        mark.className = "hit";
        try { range.surroundContents(mark); } catch (_) { /* span crosses nodes */ }
        break;
      }
    }
  }

  const nrm = (s) => String(s || "").replace(/\s+/g, " ").trim();

  // 富文本里的句子是异步插入的，用事件委托；点段落内任意位置都能联动
  document.addEventListener("click", (ev) => {
    const t = ev.target;
    if (!t || !t.closest) return;
    const view = document.getElementById("view");
    if (!view || !view.contains(t)) return;
    if (!t.closest(".pane")) return;

    const mk = t.closest("[data-item]");
    if (mk) {
      ev.stopPropagation();
      focusItem(Number(mk.getAttribute("data-item")));
      return;
    }

    const holder = t.closest("[data-para]") || t.closest("p,li,td");
    if (!holder) return;
    const items = itemsNow();
    if (!items.length) return;

    let idx = -1;
    const attr = holder.getAttribute("data-para");
    if (attr !== null && attr !== "") {
      const para = Number(attr);
      idx = items.findIndex((it) => it.a_para === para || it.b_para === para);
    }
    if (idx < 0) {
      const p = R.res.pairs[R.pair];
      const txt = nrm(holder.textContent);
      if (p && txt) {
        const blk = p.blocks.find((b) => nrm(b.a_text) === txt || nrm(b.b_text) === txt);
        if (blk) idx = items.findIndex((it) => it.a_para === blk.a_para || it.b_para === blk.b_para);
      }
    }
    if (idx < 0) return;
    ev.stopPropagation();
    focusItem(idx);
  });

  /* ---------------- rich v2: docx-preview + sentence-text marking ---------------- */
  async function hydrateRich2() {
    const nodes = document.querySelectorAll("#view .rich");
    for (const el of nodes) {
      const side = el.dataset.side;
      try {
        if (el.dataset.raw && window.docx && window.docx.renderAsync) {
          const resp = await fetch(`/api/raw/${R.meta.job}/${el.dataset.raw}`);
          if (!resp.ok) throw new Error("HTTP " + resp.status);
          const buf = await resp.arrayBuffer();
          el.innerHTML = "";
          await window.docx.renderAsync(new Uint8Array(buf), el, null, {
            inWrapper: false, ignoreWidth: true, ignoreHeight: true,
            breakPages: false, renderHeaders: false, renderFooters: false,
            useBase64URL: true,
          });
        } else if (el.dataset.html) {
          const resp = await fetch(`/api/doc/${R.meta.job}/${el.dataset.html}`);
          if (!resp.ok) throw new Error("HTTP " + resp.status);
          el.innerHTML = await resp.text();
        } else {
          el.textContent = "原文不可用";
          continue;
        }
      } catch (e) {
        if (!fallbackToPlain(el, e)) el.textContent = missingNote(e);
        continue;
      }
      markRich2(el, side);
      const marked = el.querySelectorAll("mark, .hit-row").length;
      if (!marked) {
        el.insertAdjacentHTML("afterbegin",
          `<div class="rich-note">未能在此文档中定位到相似片段（排版文本与解析文本不一致），已显示全文</div>`);
      } else if (R.onlySim) {
        // 只保留包含相似片段的段落/表格行，容器本身不动
        el.querySelectorAll("tr").forEach((tr) => {
          const keep = tr.classList.contains("hit-row")
            || tr.querySelector("mark")
            || tr.querySelector("th");
          if (!keep) tr.style.display = "none";
        });
        el.querySelectorAll("p,li").forEach((node) => {
          const tr = node.closest("tr");
          const keep = node.querySelector("mark")
            || (tr && tr.classList.contains("hit-row"))
            || (tr && tr.querySelector("th"))
            || (node.parentElement && node.parentElement.classList.contains("hit-row"));
          if (!keep) node.style.display = "none";
        });
        el.querySelectorAll("table").forEach((tbl) => {
          const rows = [...tbl.querySelectorAll("tr")];
          const visible = rows.filter((r) => r.style.display !== "none");
          if (rows.length && !visible.length) tbl.style.display = "none";
        });
      }
    }
    focusItem(R.item || 0, false);
  }

  function markRich2(root, side) {
    const r = R.res, p = r.pairs[R.pair];
    if (!p) return;
    const mode = R.view === "sentence" ? "sentence" : "para";
    const items = buildItems(p, mode);
    const doc = side === "a" ? r.docs[p.a] : r.docs[p.b];

    const els = [...root.querySelectorAll("p,li,td,h1,h2,h3,h4,h5,h6")];
    const byText = new Map();
    const normEls = [];
    for (const n of els) {
      const k = nrm(n.textContent);
      if (!k) continue;
      normEls.push({ el: n, key: k });
      if (!byText.has(k)) byText.set(k, n);
    }
    const blkByPara = {}, elByPara = {};
    for (const blk of doc.blocks) {
      blkByPara[blk.i] = blk;
      const key = nrm(blk.t);
      if (!key) continue;
      let el = byText.get(key);
      if (!el && key.length >= 12) {
        const probe = key.slice(0, 40);
        const cand = normEls.find((x) => x.key.startsWith(probe) || x.key.includes(probe));
        if (cand) el = cand.el;
      }
      if (el) {
        el.setAttribute("data-para", blk.i);
        elByPara[blk.i] = el;
      }
    }

    // 表格行：用单元格文本以 " | " 连接去匹配 <tr>
    const tableMap = new Map();
    for (const tr of root.querySelectorAll("tr")) {
      const cells = [...tr.children].map((c) => nrm(c.textContent));
      if (!cells.length) continue;
      const k = cells.join(" | ");
      if (!tableMap.has(k)) tableMap.set(k, tr);
    }

    items.forEach((it, idx) => {
      const para = side === "a" ? it.a_para : it.b_para;
      const blk = blkByPara[para];
      if (!blk) return;
      const key = nrm(blk.t);

      if (key.includes(" | ")) {
        const tr = tableMap.get(key);
        if (tr && !tr.hasAttribute("data-item")) {
          tr.setAttribute("data-para", para);
          tr.setAttribute("data-item", String(idx));
          tr.classList.add("hit-row");
        }
        return;
      }

      const el = elByPara[para];
      if (!el) return;
      const s = side === "a" ? it.a_start : it.b_start;
      const e = side === "a" ? it.a_end : it.b_end;
      const sentence = blk.t.slice(s, e);
      if (!sentence || sentence.trim().length < 2) return;
      markSentence(el, sentence, idx);
    });
  }

  function markSentence(el, sentence, idx) {
    const raw = el.textContent || "";
    let needleText = sentence;
    let start = raw.indexOf(needleText);
    let len = needleText.length;
    if (start < 0) {
      // 自动编号（（1）、1.、（一）等）不在 docx-preview 的文本里，去掉再找
      const stripped = sentence.replace(/^\s*(?:[（(]\s*\d{1,3}\s*[）)]|\d{1,3}\s*[.、）)]|[（(]\s*[一二三四五六七八九十]{1,3}\s*[）)])\s*/, "");
      if (stripped && stripped !== sentence) {
        needleText = stripped;
        start = raw.indexOf(needleText);
        len = needleText.length;
      }
    }
    if (start < 0) {
      const needle = nrm(needleText);
      const cm = collapseMap(raw);
      const pos = cm.text.indexOf(needle);
      if (pos < 0) return;
      start = cm.map[pos];
      len = cm.map[Math.min(pos + needle.length - 1, cm.map.length - 1)] + 1 - start;
    }
    markRange(el, start, start + len, idx);
  }

  function collapseMap(raw) {
    const chars = [], map = [];
    let prevSpace = false;
    for (let i = 0; i < raw.length; i++) {
      const ch = raw[i];
      if (/\s/.test(ch)) {
        if (!prevSpace && chars.length) { chars.push(" "); map.push(i); prevSpace = true; }
      } else {
        chars.push(ch);
        map.push(i);
        prevSpace = false;
      }
    }
    return { text: chars.join(""), map };
  }

  function markRange(el, s, e, idx) {
    // 一句话可能跨越多个文本节点（编号、加粗、不同 run），逐段标注
    const parts = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let pos = 0, node;
    while ((node = walker.nextNode())) {
      const start = pos;
      const end = pos + node.nodeValue.length;
      pos = end;
      if (end <= s || start >= e) continue;
      const from = Math.max(s, start) - start;
      const to = Math.min(e, end) - start;
      if (to > from) parts.push([node, from, to]);
    }
    for (let i = parts.length - 1; i >= 0; i--) {
      const [n, from, to] = parts[i];
      const range = document.createRange();
      range.setStart(n, from);
      range.setEnd(n, to);
      const mark = document.createElement("mark");
      mark.className = "hit";
      mark.dataset.item = String(idx);
      try { range.surroundContents(mark); } catch (_) { /* 极端嵌套 */ }
    }
  }

  // 图片点击放大，滚轴缩放，点空白关闭
  document.addEventListener("click", (ev) => {
    const img = ev.target.closest ? ev.target.closest(".imgbox img") : null;
    if (!img) return;
    const view = document.getElementById("view");
    if (!view || !view.contains(img)) return;
    const box = document.createElement("div");
    box.className = "lightbox";
    const big = document.createElement("img");
    big.src = img.src;
    box.appendChild(big);
    box.onclick = () => box.remove();
    document.body.appendChild(box);

    let scale = 1;
    let baseW = 0;
    const apply = () => {
      if (!baseW) return;
      big.style.width = Math.round(baseW * scale) + "px";
    };
    big.onload = () => {
      baseW = Math.min(big.naturalWidth || 1200, Math.round(window.innerWidth * 0.94));
      apply();
    };
    box.addEventListener("wheel", (e) => {
      e.preventDefault();
      scale = Math.min(8, Math.max(0.3, scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
      apply();
    }, { passive: false });
    big.onclick = (e) => e.stopPropagation();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") document.querySelectorAll(".lightbox").forEach((n) => n.remove());
  });

  // 点击文件名用本机默认程序打开
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest ? ev.target.closest("a.filelink") : null;
    if (!a) return;
    ev.preventDefault();
    ev.stopPropagation();
    openFile(Number(a.dataset.doc));
  });

  // 右键文件名：在文件夹中显示并选中
  document.addEventListener("contextmenu", (ev) => {
    const a = ev.target.closest ? ev.target.closest("a.filelink") : null;
    if (!a) return;
    ev.preventDefault();
    ev.stopPropagation();
    openCtx(ev.clientX, ev.clientY, Number(a.dataset.doc));
  });
  document.addEventListener("click", (ev) => {
    if (ctxEl && !ctxEl.contains(ev.target)) closeCtx();
  }, true);
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") closeCtx();
  });
  window.addEventListener("resize", closeCtx);
  window.addEventListener("blur", closeCtx);

  /* ---------------- wiring ---------------- */
  function wire() {
    const box = document.getElementById("view");
    const paperBtn = document.getElementById("paperBtn");
    if (paperBtn) {
      paperBtn.onclick = () => {
        const on = document.documentElement.dataset.paper === "1";
        if (on) {
          delete document.documentElement.dataset.paper;
          localStorage.setItem("tc-paper", "0");
        } else {
          document.documentElement.dataset.paper = "1";
          localStorage.setItem("tc-paper", "1");
        }
      };
    }
    box.querySelectorAll(".grp-head").forEach((h) => {
      h.onclick = (ev) => {
        if (ev.target.closest("button")) return;
        const blk = h.parentElement;
        const willOpen = !blk.classList.contains("open");
        // 手风琴：同一时刻只展开一组，避免页面被撑得很长
        box.querySelectorAll(".grp-block.open").forEach((o) => {
          if (o !== blk) o.classList.remove("open");
        });
        blk.classList.toggle("open", willOpen);
      };
    });
    box.querySelectorAll("[data-pair]").forEach((el) => {
      el.onclick = () => {
        R.pair = Number(el.dataset.pair);
        R.block = 0;
        R.origin = { kind: "pair", idx: R.pair };
        setView(el.dataset.tab);
      };
    });
    box.querySelectorAll("[data-gp]").forEach((el) => {
      el.onclick = () => {
        R.gkey = Number(el.dataset.gp);
        R.origin = { kind: "gp", idx: R.gkey };
        setView("files");
      };
    });
    box.querySelectorAll(".pair-head").forEach((h) => {
      h.onclick = () => h.parentElement.classList.toggle("open");
    });
    const gpBack = document.getElementById("gpBack");
    if (gpBack) {
      gpBack.onclick = () => {
        R.focus = R.origin || { kind: "gp", idx: R.gkey };
        setView("summary");
      };
    }
    const picBack = document.getElementById("picBack");
    if (picBack) {
      picBack.onclick = () => {
        R.focus = R.origin;
        setView("summary");
      };
    }
    const backSummary = document.getElementById("backSummary");    if (backSummary) {
      backSummary.onclick = () => {
        R.focus = R.origin;      // 回到刚才点的那一行
        setView("summary");
      };
    }
    box.querySelectorAll("[data-vtab]").forEach((b) => {
      b.onclick = () => {
        if (b.disabled) return;
        const v = b.dataset.vtab;
        if (v === R.view) return;
        setView(v);
      };
    });
    const printBtn = document.getElementById("printBtn");
    if (printBtn) printBtn.onclick = () => setView("print");
    const propHead = document.getElementById("propHead");
    if (propHead) {
      propHead.onclick = () => {
        const body = document.getElementById("propBody");
        if (!body) return;
        const open = body.classList.toggle("hidden") === false;
        propHead.classList.toggle("open", open);
      };
    }
    box.querySelectorAll(".act-only").forEach((b) => {
      b.onclick = () => { R.onlySim = true; paint(); };
    });
    box.querySelectorAll(".act-full").forEach((b) => {
      b.onclick = () => { R.onlySim = false; paint(); };
    });
    box.querySelectorAll(".act-prev").forEach((b) => {
      b.onclick = () => moveItem(-1);
    });
    box.querySelectorAll(".act-next").forEach((b) => {
      b.onclick = () => moveItem(1);
    });
    const t = document.getElementById("paneToggle");
    if (t) t.onclick = () => { R.onlySim = !R.onlySim; paint(); };
    const prev = document.getElementById("prevPara");
    const next = document.getElementById("nextPara");
    if (prev) prev.onclick = () => move(-1);
    if (next) next.onclick = () => move(1);
  }

  function move(d) {
    const r = R.res, p = r.pairs[R.pair];
    if (!p) return;
    R.block = Math.max(0, Math.min(p.blocks.length - 1, R.block + d));
    const b = p.blocks[R.block];
    ["paneA", "paneB"].forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      const idx = id === "paneA" ? b.a_para : b.b_para;
      const target = el.querySelector(`[data-para="${idx}"]`);
      if (target) target.scrollIntoView({ block: "center", behavior: "smooth" });
    });
  }

  window.Report = { open, setView, goPair, state: R };
})();
