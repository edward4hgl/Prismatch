"use strict";
/* 主控：页签、文件夹导入（折叠树）、多选删除、提交、报告 */
const $ = (id) => document.getElementById(id);
const S = {
  mode: "group",
  groups: [], loose: [],
  tenderGroups: [], tenderLoose: [],
  selC: new Set(), selT: new Set(),
  job: null, result: null, reports: [], seq: 0,
};
const OK_EXT = /\.(docx?|pptx?|pdf|xlsx?|txt|md)$/i;
const MAX_MB = 200;

/* ---------------- theme（默认跟随系统，手动切换后固定） ---------------- */
const THEME_KEY = "tc-theme";
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

function systemTheme() {
  return darkQuery.matches ? "dark" : "light";
}

function applyTheme(name) {
  currentTheme = name === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = currentTheme;
  const btn = $("themeBtn");
  if (btn) {
    const manual = !!localStorage.getItem(THEME_KEY);
    btn.title = `主题：${currentTheme === "dark" ? "深色" : "浅色"}（${manual ? "手动" : "跟随系统"}，右键恢复跟随系统）`;
  }
}

let currentTheme = "dark";
const urlTheme = new URLSearchParams(location.search).get("theme");
applyTheme(urlTheme || localStorage.getItem(THEME_KEY) || systemTheme());

const onSystemThemeChange = (e) => {
  if (localStorage.getItem(THEME_KEY)) return;   // 手动模式下不跟随
  applyTheme(e.matches ? "dark" : "light");
};
if (darkQuery.addEventListener) darkQuery.addEventListener("change", onSystemThemeChange);
else if (darkQuery.addListener) darkQuery.addListener(onSystemThemeChange);

$("themeBtn").onclick = () => {
  const n = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem(THEME_KEY, n);
  applyTheme(n);
  toast(`已切换为${n === "dark" ? "深色" : "浅色"}主题（右键恢复跟随系统）`);
};

$("themeBtn").oncontextmenu = (e) => {
  e.preventDefault();
  localStorage.removeItem(THEME_KEY);
  applyTheme(systemTheme());
  toast("已恢复跟随系统主题");
};

/* ---------------- skin（默认液态玻璃） ---------------- */
const SKIN_KEY = "tc-skin";
const SKINS = { apple: "液态玻璃", geek: "极客终端", pixel: "可爱像素" };

function applySkin(name) {
  const skin = SKINS[name] ? name : "apple";
  document.documentElement.dataset.skin = skin;
  // 三套皮肤都支持浅色 / 深色，不再强制
  applyTheme(currentTheme);
  const menu = $("skinMenu");
  if (menu) {
    menu.querySelectorAll("button").forEach((b) =>
      b.classList.toggle("on", b.dataset.skin === skin));
  }
}

$("skinBtn").onclick = (e) => {
  e.stopPropagation();
  $("skinMenu").classList.remove("hidden");
};
$("skinMenu").querySelectorAll("button").forEach((b) => {
  b.onclick = () => {
    const skin = b.dataset.skin;
    localStorage.setItem(SKIN_KEY, skin);
    applySkin(skin);
    $("skinMenu").classList.add("hidden");
    toast(`皮肤已切换为「${SKINS[skin]}」`);
  };
});
document.addEventListener("click", (e) => {
  if (!e.target.closest(".skin-wrap")) $("skinMenu").classList.add("hidden");
});

const fromUrl = new URLSearchParams(location.search).get("skin");
applySkin(fromUrl || localStorage.getItem(SKIN_KEY) || "apple");
const PAGES = ["check", "reports", "report", "lib", "libreport", "libmanage"];
function go(page) {
  S.page = page;
  PAGES.forEach((p) => $("page-" + p).classList.toggle("hidden", p !== page));
  document.querySelectorAll("#mainTabs .tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.page === page ||
      (page === "report" && t.dataset.page === "reports")));
}
document.querySelectorAll("#mainTabs .tab").forEach((t) => {
  t.onclick = () => { if (t.dataset.page === "reports") renderReportList(); go(t.dataset.page); };
});
$("backReports").onclick = () => { renderReportList(); go("reports"); };

/* ---------------- mode ---------------- */
function applyMode() {
  document.querySelectorAll("#subTabs .sub").forEach((x) =>
    x.classList.toggle("active", x.dataset.mode === S.mode));
  $("btnFiles").classList.toggle("hidden", S.mode === "group");
  $("modeNote").textContent = S.mode === "normal"
    ? "普通查重：导入单个文件或散装文件时两两互比。来自同一文件夹的文件同样按文件夹成组，组内不互比。"
    : "分组查重：每个文件夹代表一家投标单位（内含多份响应文件）。软件只做跨文件夹比对，同一文件夹内的文件之间不互比。";
}

document.querySelectorAll("#subTabs .sub").forEach((b) => {
  b.onclick = () => {
    S.mode = b.dataset.mode;
    applyMode();
    renderTables();
  };
});
applyMode();

/* ---------------- overall progress ---------------- */
const STAGES = [
  { k: "upload", t: "上传", w: 8 },
  { k: "extract", t: "解析文档", w: 42 },
  { k: "compare", t: "内容比对", w: 35 },
  { k: "images", t: "图片查重", w: 5 },
  { k: "report", t: "生成报告", w: 10 },
];

function renderStepBar() {
  $("barSteps").innerHTML = STAGES.map((s) =>
    `<div class="step-item" style="flex:1">${s.t}</div>`
  ).join("");
}

function setStage(key, done, total) {
  // server reports one "finish" stage with 3 ticks; split into 图片查重 / 生成报告
  if (key === "finish") {
    if (done >= 2) { key = "report"; done = 1; total = 1; }
    else { key = "images"; total = 1; }
  }
  let idx = STAGES.findIndex((s) => s.k === key);
  if (idx < 0) idx = 0;
  const st = STAGES[idx];
  const band = 100 / STAGES.length;
  const frac = total > 0 ? Math.min(1, done / total) : 0;
  const overall = Math.min(100, idx * band + band * frac);

  overallPct = overall;
  recordRate(overall);

  $("barFill").style.width = overall + "%";
  const track = $("barTrack");
  if (track) track.style.setProperty("--p", overall);
  $("progPct").textContent = Math.round(overall) + "%";
  $("progTitle").textContent = st.t;
  document.querySelectorAll("#barSteps .step-item").forEach((el, i) => {
    el.classList.toggle("done", i < idx || (i === idx && frac >= 1));
    el.classList.toggle("active", i === idx && frac < 1);
  });
}

function recordRate(overall) {
  const now = Date.now();
  const dt = (now - sample.t) / 1000;
  const dp = overall - sample.p;
  if (dt >= 0.5 && dp > 0) {
    const inst = dp / dt;
    rate = rate > 0 ? rate * 0.7 + inst * 0.3 : inst;
    sample = { t: now, p: overall };
  } else if (dp >= 0) {
    sample = { t: now, p: overall };
  }
}

renderStepBar();

/* ---------------- clock + ETA ---------------- */
let runStart = 0;
let aborter = null;
let clockTimer = null;
let overallPct = 0;
let rate = 0;
let sample = { t: 0, p: 0 };
let etaState = { v: null, at: 0 };

function fmtSec(sec) {
  const s = Math.max(0, Math.round(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

function etaSeconds() {
  if (etaState.v != null) {
    return Math.max(0, etaState.v - (Date.now() - etaState.at) / 1000);
  }
  if (!runStart || overallPct <= 1) return null;
  const elapsed = (Date.now() - runStart) / 1000;
  const r = rate > 0 ? rate : overallPct / Math.max(elapsed, 1);
  if (!r || !isFinite(r)) return null;
  return (100 - overallPct) / r;
}

function paintClock() {
  if (!runStart) return;
  const elapsed = (Date.now() - runStart) / 1000;
  const eta = etaSeconds();
  const tail = eta == null
    ? "剩余 估算中"
    : (eta > 3600 ? "剩余 >1 小时" : "剩余 " + fmtSec(eta));
  $("progTime").textContent = `已用 ${fmtSec(elapsed)} · ${tail}`;
}

function startClock() {
  runStart = Date.now();
  overallPct = 0;
  rate = 0;
  sample = { t: runStart, p: 0 };
  etaState = { v: null, at: 0 };
  clearInterval(clockTimer);
  clockTimer = setInterval(paintClock, 500);
  paintClock();
}

function stopClock(finished) {
  clearInterval(clockTimer);
  clockTimer = null;
  if (!runStart) return;
  const elapsed = (Date.now() - runStart) / 1000;
  $("progTime").textContent = finished
    ? `已用 ${fmtSec(elapsed)} · 已完成`
    : `已用 ${fmtSec(elapsed)} · 已停止`;
}

/* ---------------- log drawer ---------------- */
let logTimer = null;
function openLogs() {
  $("logDrawer").classList.remove("hidden");
  loadLogs();
}
$("logBtn").onclick = () => {
  if ($("logDrawer").classList.contains("hidden")) openLogs();
  else { $("logDrawer").classList.add("hidden"); clearTimeout(logTimer); }
};
$("logClose").onclick = () => { $("logDrawer").classList.add("hidden"); clearTimeout(logTimer); };
$("logCopy").onclick = async () => {
  try { await navigator.clipboard.writeText($("logBody").innerText); toast("日志已复制"); }
  catch (_) { toast("复制失败，请手动选择"); }
};

async function loadLogs() {
  clearTimeout(logTimer);
  if (!S.job) {
    $("logBody").innerHTML = `<div class="log-line lv-info"><span>--:--:--</span>还没有任务，提交一次检测后再看。</div>`;
    return;
  }
  try {
    const j = await (await fetch("/api/logs/" + S.job)).json();
    if (j.error) throw new Error(j.error);
    const lines = j.lines || [];
    const body = $("logBody");
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
    body.innerHTML = lines.map((l) =>
      `<div class="log-line lv-${l.level || "info"}"><span>${esc(l.t)}</span>${esc(l.msg)}</div>`).join("")
      || `<div class="log-line lv-info"><span>--:--:--</span>等待日志…</div>`;
    $("logState").textContent = `${j.state} · ${lines.length} 行`;
    if (atBottom) body.scrollTop = body.scrollHeight;
    if (j.state === "running" || j.state === "queued") logTimer = setTimeout(loadLogs, 800);
  } catch (e) {
    $("logState").textContent = "读取失败：" + e.message;
  }
}

/* ---------------- intake ---------------- */
$("btnPath").onclick = () => importByPath("c");
$("btnTenderPath").onclick = () => importByPath("t");

// exe 启动参数里的文件夹（把文件夹拖到 exe 图标上）自动导入
async function loadStartup() {
  try {
    const j = await (await fetch("/api/startup")).json();
    for (const folder of j.folders || []) {
      const res = await fetch("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: folder }),
      });
      const s = await res.json();
      if (res.ok && s.files && s.files.length) {
        addFolder("c", s.folder, s.files);
        toast(`已从启动参数导入「${s.folder}」：${s.files.length} 个文件`);
      }
    }
  } catch (_) { /* ignore */ }
}
loadStartup();

$("btnFiles").onclick = () => $("fileInput").click();
$("btnTenderFiles").onclick = () => $("tenderInput").click();
$("fileInput").onchange = (e) => { addLoose([...e.target.files], "c"); e.target.value = ""; };
$("tenderInput").onchange = (e) => { addLoose([...e.target.files], "t"); e.target.value = ""; };

/* ---------------- drag & drop (folders + files) ---------------- */
async function readEntry(entry, parent) {
  if (entry.isFile) {
    const f = await new Promise((res, rej) => entry.file(res, rej));
    f.relPath = parent + entry.name;
    return [f];
  }
  const reader = entry.createReader();
  const out = [];
  let batch;
  do {
    batch = await new Promise((res, rej) => reader.readEntries(res, rej));
    for (const e of batch) {
      out.push(...(await readEntry(e, parent + entry.name + "/")));
    }
  } while (batch.length);
  return out;
}

function wireDrop(el, kind) {
  ["dragenter", "dragover"].forEach((ev) =>
    el.addEventListener(ev, (e) => {
      e.preventDefault();
      e.stopPropagation();
      el.classList.add("on");
    }));
  ["dragleave", "dragend"].forEach((ev) =>
    el.addEventListener(ev, () => el.classList.remove("on")));
  el.addEventListener("drop", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    el.classList.remove("on");

    // 窗口层刚处理过这次拖放（已按原路径导入），别再上传一遍
    if (window.__lastNativeDrop && Date.now() - window.__lastNativeDrop < 900) return;

    el.classList.add("busy");

    const items = [...(e.dataTransfer.items || [])];
    const entries = items
      .map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null))
      .filter(Boolean);

    try {
      if (!entries.length) {
        const files = [...(e.dataTransfer.files || [])];
        const ok = files.filter((f) => OK_EXT.test(f.name));
        ok.forEach((f) => (f.relPath = f.name));
        if (kind === "c") addLoose(ok, "c"); else addLoose(ok, "t");
        if (ok.length) toast(`已添加 ${ok.length} 个文件`);
        return;
      }
      for (const entry of entries) {
        const all = await readEntry(entry, "");
        const ok = all.filter((f) => OK_EXT.test(f.name));
        if (!ok.length) { toast("跳过：" + entry.name + "（没有支持的文件）"); continue; }

        const resolved = await tryResolveDrop(ok, entry.isDirectory ? entry.name : "");
        if (resolved) {
          if (entry.isDirectory) addFolder(kind, entry.name, resolved);
          else addLoose(resolved, kind);
          toast(`已按原路径导入「${entry.name}」：${ok.length} 个文件（未上传）`);
          continue;
        }
        if (window.__dropMiss) {
          toast(`未能定位原文件：${window.__dropMiss}，改为上传`);
          window.__dropMiss = "";
        }

        if (entry.isDirectory) {
          addFolder(kind, entry.name, ok);
          toast(`已添加文件夹「${entry.name}」到${kind === "c" ? "对比文件" : "招标文件"}：${ok.length} 个文件`);
          maybeHintPath();
        } else if (kind === "c") {
          addLoose(ok, "c");
          toast(`已添加文件：${entry.name}`);
        } else {
          addLoose(ok, "t");
          toast(`已添加文件：${entry.name}`);
        }
      }
    } catch (err) {
      toast("拖拽解析失败：" + (err.message || err));
    } finally {
      el.classList.remove("busy");
    }
  });
}

// 内嵌窗口：窗口层拖放拿到的真实路径（Python 侧注入，带落点坐标）
async function importPaths(paths, kind) {
  let dirs = 0, files = 0;
  for (const p of paths || []) {
    try {
      const res = await fetch("/api/paths-info", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths: [p] }),
      });
      const j = await res.json();
      const it = (j.items || [])[0];
      if (!it) continue;
      if (it.dir) {
        const sres = await fetch("/api/scan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: it.path }),
        });
        const s = await sres.json();
        if (sres.ok && s.files && s.files.length) {
          addFolder(kind, s.folder, s.files);
          dirs += 1;
        }
      } else if (OK_EXT.test(it.name)) {
        addLoose([{ name: it.name, path: it.path, size: it.size }], kind);
        files += 1;
      }
    } catch (_) { /* skip */ }
  }
  if (dirs || files) {
    const where = kind === "t" ? "招标文件" : "对比文件";
    toast(`已按原路径导入${where}：${dirs} 个文件夹、${files} 个文件（不上传）`);
  }
  return dirs + files;
}

window.__nativeDropAt = async (paths, devX, devY) => {
  window.__lastNativeDrop = Date.now();
  let kind = "c";
  let hit = null;
  try {
    const dpr = window.devicePixelRatio || 1;
    const x = devX >= 0 ? devX / dpr : -1;
    const y = devY >= 0 ? devY / dpr : -1;
    hit = x >= 0 ? document.elementFromPoint(x, y) : null;
  } catch (_) { /* ignore */ }

  if (!hit) {
    toast("请把文件夹拖到「导入对比文件」或「导入招标文件」的拖拽区");
    return;
  }
  const zone = hit.closest("#dropC, #dropT, .dropzone");
  if (zone) {
    kind = zone.id === "dropT" ? "t" : "c";
  } else {
    const card = hit.closest(".card");
    const step = card && card.querySelector(".step");
    if (step && step.textContent.includes("招标")) kind = "t";
  }
  await importPaths(paths, kind);
};

// 拖拽时先用「文件名+大小」找回本机原件，找到就不上传
async function tryResolveDrop(files, hint) {
  if (!files.length) return null;
  try {
    const items = files.map((f) => ({ name: f.name, size: f.size }));
    const rels = files.map((f) => f.relPath || f.name);
    const res = await fetch("/api/resolve-drop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items, rels, hint: hint || "" }),
    });
    if (!res.ok) return null;
    const j = await res.json();
    const list = j.resolved || [];
    if (list.length !== files.length) return null;
    const out = [];
    for (let i = 0; i < files.length; i++) {
      if (!list[i].path) { window.__dropMiss = `${list[i].name}`; return null; }
      out.push({ name: files[i].name, path: list[i].path, size: files[i].size });
    }
    return out;
  } catch (_) {
    return null;
  }
}

wireDrop($("dropC"), "c");
wireDrop($("dropT"), "t");

// 内嵌窗口下，若原生拖放没生效且本次走了上传，提示一次原因
function maybeHintPath() {
  if (!(window.pywebview && window.pywebview.api)) return;
  if (window.__nativeDropReady === true) return;
  if (localStorage.getItem("tc-hint-drag") === "1") return;
  localStorage.setItem("tc-hint-drag", "1");
}

window.addEventListener("nativedropready", () => {
  if (window.__nativeDropReady === true) {
    toast("原生拖放已启用：拖到拖拽区将直接读取原文件，不再上传");
  }
});
document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("drop", (e) => e.preventDefault());

async function* walk(dir, prefix) {
  for await (const [name, h] of dir.entries()) {
    if (h.kind === "file") {
      const f = await h.getFile();
      f.relPath = prefix + name;
      yield f;
    } else if (h.kind === "directory") {
      yield* walk(h, prefix + name + "/");
    }
  }
}

async function pickFolder(kind) {
  if (!window.showDirectoryPicker) return fallbackFolder(kind);
  let dir;
  try { dir = await window.showDirectoryPicker({ mode: "read" }); } catch (e) { return; }
  const label = dir.name;
  const found = [];
  for await (const f of walk(dir, "")) if (OK_EXT.test(f.name)) found.push(f);
  if (!found.length) { toast(`文件夹「${label}」里没有支持的文件`); return; }
  addFolder(kind, label, found);
  toast(`已添加文件夹「${label}」：${found.length} 个文件（双击展开）`);
}

function fallbackFolder(kind) {
  const input = document.createElement("input");
  input.type = "file"; input.webkitdirectory = true; input.multiple = true;
  input.onchange = () => {
    const files = [...input.files];
    if (!files.length) return;
    const label = (files[0].webkitRelativePath || "").split("/")[0] || "文件夹";
    const ok = files.filter((f) => OK_EXT.test(f.name));
    if (!ok.length) { toast(`文件夹「${label}」里没有支持的文件`); return; }
    ok.forEach((f) => (f.relPath = f.webkitRelativePath || f.name));
    addFolder(kind, label, ok);
    toast(`已添加文件夹「${label}」：${ok.length} 个文件（双击展开）`);
  };
  input.click();
}

function bridgeReady(timeout = 1200) {
  return new Promise((resolve) => {
    const has = () => !!(window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder);
    if (has()) return resolve(true);
    let done = false;
    const onReady = () => { if (!done) { done = true; resolve(true); } };
    window.addEventListener("pywebviewready", onReady, { once: true });
    setTimeout(() => {
      if (done) return;
      done = true;
      window.removeEventListener("pywebviewready", onReady);
      resolve(has());
    }, timeout);
  });
}

/**
 * 选目录。返回值：
 *   { handled: true,  path }   —— 选择框正常弹出了；path 为空表示用户点了取消
 *   { handled: false, path:"" } —— 选择框不可用，才需要退到剪贴板/手填
 */
async function pickFolderDialog() {
  // 内嵌窗口：直接调 Python 的原生对话框
  try {
    if (await bridgeReady()) {
      const p = await window.pywebview.api.pick_folder();
      return { handled: true, path: p || "" };
    }
  } catch (_) { /* 继续走 HTTP 方案 */ }

  try {
    const res = await fetch("/api/pick-folder");
    const j = await res.json().catch(() => ({}));
    if (res.ok) return { handled: true, path: j.path || "" };
  } catch (_) { /* ignore */ }
  return { handled: false, path: "" };
}

async function clipPath() {
  try {
    const t = (await navigator.clipboard.readText()).trim().replace(/^"|"$/g, "");
    if (/^[A-Za-z]:[\\/]/.test(t) || t.startsWith("\\\\")) return t;
  } catch (_) { /* 无权限 */ }
  return "";
}

async function chooseFolder(hint) {
  const picked = await pickFolderDialog();
  // 选择框弹过了：选中有路径，取消就是取消，不再弹输入框
  if (picked.handled) return picked.path || "";

  // 只有选择框确实用不了，才退到剪贴板 / 手填
  const clip = await clipPath();
  if (clip) {
    toast("使用剪贴板路径：" + clip);
    return clip;
  }
  const typed = prompt(`${hint}（可先在资源管理器里选中文件夹按 Ctrl+C，再点确定）`);
  return typed ? typed.trim().replace(/^"|"$/g, "") : "";
}
async function importByPath(kind) {
  const folder = await chooseFolder("请输入文件夹完整路径");
  if (!folder) return;
  try {
    const res = await fetch("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: folder }),
    });
    const j = await res.json();
    if (!res.ok) throw new Error(j.error || ("HTTP " + res.status));
    if (!j.files || !j.files.length) { toast("该文件夹没有支持的文件"); return; }
    addFolder(kind, j.folder, j.files);
    toast(`已按原路径导入「${j.folder}」：${j.files.length} 个文件`);
  } catch (e) {
    toast("导入失败：" + (e.message || e));
  }
}

function addFolder(kind, label, files) {
  // accept both "c"/"t" and legacy "doc"/"tender" spellings
  const isCompare = kind === "c" || kind === "doc";
  const target = isCompare ? S.groups : S.tenderGroups;
  const items = [];
  for (const f of files) {
    const size = f.size || 0;
    if (size > MAX_MB * 1024 * 1024) { toast(`跳过超大文件（>${MAX_MB}MB）：${f.name}`); continue; }
    const isFileObj = typeof f.slice === "function";
    items.push({
      name: f.name,
      path: f.path || f.relPath || f.name,
      size,
      file: isFileObj ? f : (f.file || null),
    });
  }
  if (!items.length) return;
  const exist = target.find((g) => g.label === label);
  if (exist) {
    for (const it of items) {
      if (!exist.files.some((x) => x.name === it.name && x.size === it.size)) exist.files.push(it);
    }
  } else {
    target.push({ id: ++S.seq, label, files: items, open: false });
  }
  renderTables();
}

function addLoose(files, kind) {
  const isCompare = kind === "c" || kind === "doc";
  const target = isCompare ? S.loose : S.tenderLoose;
  for (const f of files) {
    if (!OK_EXT.test(f.name)) { toast("已跳过不支持的文件：" + f.name); continue; }
    if (f.size > MAX_MB * 1024 * 1024) { toast(`跳过超大文件（>${MAX_MB}MB）：${f.name}`); continue; }
    if (target.some((d) => d.name === f.name && d.size === f.size)) continue;
    const isFileObj = typeof f.slice === "function";
    target.push({
      name: f.name,
      path: f.path || f.webkitRelativePath || f.name,
      size: f.size,
      file: isFileObj ? f : null,
    });
  }
  renderTables();
}

/* ---------------- table rendering ---------------- */
function groupRow(g, ck, prefix, name) {
  const n = g.files.length;
  return `<tr class="grow" data-g="${g.id}">
    <td><input type="checkbox" class="ck" data-ck="${prefix}g:${g.id}" ${ck ? "checked" : ""}>
      <span class="chev ${g.open ? "open" : ""}">▶</span>
      <span class="folder-name">📁 ${esc(g.label)}</span>
      <span class="fcount">${n} 个文件</span></td>
    <td class="path" title="${esc(g.label)}">${esc(g.label)}/</td>
    <td class="act"><button class="linkbtn" data-tg="${g.id}">${g.open ? "收起" : "展开"}</button>
      <button class="linkbtn del" data-dg="${g.id}">删除</button></td>
  </tr>`;
}

function childRow(g, f, i, ck, prefix) {
  return `<tr class="child">
    <td><input type="checkbox" class="ck" data-ck="${prefix}g:${g.id}:${i}" ${ck ? "checked" : ""}>${esc(f.name)}</td>
    <td class="path" title="${esc(f.path)}">${esc(f.path)}</td>
    <td class="act"><button class="linkbtn del" data-dc="${prefix}:${g.id}:${i}">删除</button></td>
  </tr>`;
}

function looseRow(f, i, ck, prefix) {
  return `<tr class="child">
    <td><input type="checkbox" class="ck" data-ck="${prefix}l:${i}" ${ck ? "checked" : ""}>${esc(f.name)}</td>
    <td class="path" title="${esc(f.path)}">${esc(f.path)}</td>
    <td class="act"><button class="linkbtn del" data-dc="${prefix}:l:${i}">删除</button></td>
  </tr>`;
}

function renderTables() {
  paint("c", S.groups, S.loose, S.selC, $("tblCompare"));
  paint("t", S.tenderGroups, S.tenderLoose, S.selT, $("tblTender"));

  const total = countOf(S.groups) + S.loose.length;
  $("docCount").textContent = total;
  $("runBtn").disabled = total < 2;
  $("runHint").textContent = total < 2 ? "至少需要 2 份文档" : "";
}

function countOf(groups) {
  return groups.reduce((a, g) => a + g.files.length, 0);
}

function paint(prefix, groups, loose, sel, tbody) {
  const rows = [];
  for (const g of groups) {
    rows.push(groupRow(g, sel.has(`${prefix}g:${g.id}`), prefix, `${g.label}/`));
    if (g.open) g.files.forEach((f, i) =>
      rows.push(childRow(g, f, i, sel.has(`${prefix}g:${g.id}:${i}`), prefix)));
  }
  loose.forEach((f, i) => rows.push(looseRow(f, i, sel.has(`${prefix}l:${i}`), prefix)));
  tbody.innerHTML = rows.length ? rows.join("")
    : `<tr class="empty"><td colspan="3">表中无内容</td></tr>`;

  tbody.querySelectorAll("[data-ck]").forEach((el) => {
    el.onclick = (ev) => {
      ev.stopPropagation();
      const k = el.dataset.ck;
      if (el.checked) sel.add(k); else sel.delete(k);
    };
  });

  tbody.querySelectorAll("tr.grow").forEach((tr) => {
    tr.ondblclick = (ev) => {
      if (ev.target.closest("button,input")) return;
      toggleGroup(prefix, tr.dataset.g);
    };
  });

  tbody.querySelectorAll("[data-tg]").forEach((b) => {
    b.onclick = (ev) => { ev.stopPropagation(); toggleGroup(prefix, b.dataset.tg); };
  });
  tbody.querySelectorAll("[data-dg]").forEach((b) => {
    b.onclick = (ev) => { ev.stopPropagation(); removeGroup(prefix, b.dataset.dg); };
  });
  tbody.querySelectorAll("[data-dc]").forEach((b) => {
    b.onclick = (ev) => { ev.stopPropagation(); removeChild(prefix, b.dataset.dc); };
  });
}

function toggleGroup(prefix, gid) {
  const arr = prefix === "c" ? S.groups : S.tenderGroups;
  const g = arr.find((x) => String(x.id) === String(gid));
  if (g) { g.open = !g.open; renderTables(); }
}

function removeGroup(prefix, gid) {
  const arr = prefix === "c" ? S.groups : S.tenderGroups;
  const i = arr.findIndex((x) => String(x.id) === String(gid));
  if (i >= 0) { arr.splice(i, 1); renderTables(); }
}

function removeChild(prefix, key) {
  const parts = key.split(":");
  const gid = parts[1];
  const idx = Number(parts[2]);
  const arr = prefix === "c" ? S.groups : S.tenderGroups;
  if (gid === "l") {
    const loose = prefix === "c" ? S.loose : S.tenderLoose;
    loose.splice(idx, 1);
  } else {
    const g = arr.find((x) => String(x.id) === gid);
    if (g) g.files.splice(idx, 1);
    if (g && !g.files.length) arr.splice(arr.indexOf(g), 1);
  }
  renderTables();
}

/* ---------------- selection bulk ops ---------------- */
function allKeys(prefix, groups, loose) {
  const keys = [];
  for (const g of groups) {
    keys.push(`${prefix}g:${g.id}`);
    g.files.forEach((_, i) => keys.push(`${prefix}g:${g.id}:${i}`));
  }
  loose.forEach((_, i) => keys.push(`${prefix}l:${i}`));
  return keys;
}

$("selAllC").onclick = () => {
  const keys = allKeys("c", S.groups, S.loose);
  if (S.selC.size === keys.length) S.selC.clear();
  else keys.forEach((k) => S.selC.add(k));
  renderTables();
};
$("selAllT").onclick = () => {
  const keys = allKeys("t", S.tenderGroups, S.tenderLoose);
  if (S.selT.size === keys.length) S.selT.clear();
  else keys.forEach((k) => S.selT.add(k));
  renderTables();
};

function deleteSelected(prefix) {
  const sel = prefix === "c" ? S.selC : S.selT;
  const groups = prefix === "c" ? S.groups : S.tenderGroups;
  const loose = prefix === "c" ? S.loose : S.tenderLoose;
  if (!sel.size) { toast("请先勾选要删除的文件夹或文件"); return; }

  for (let gi = groups.length - 1; gi >= 0; gi--) {
    const g = groups[gi];
    if (sel.has(`${prefix}g:${g.id}`)) { groups.splice(gi, 1); continue; }
    for (let i = g.files.length - 1; i >= 0; i--) {
      if (sel.has(`${prefix}g:${g.id}:${i}`)) g.files.splice(i, 1);
    }
    if (!g.files.length) groups.splice(gi, 1);
  }
  for (let i = loose.length - 1; i >= 0; i--) {
    if (sel.has(`${prefix}l:${i}`)) loose.splice(i, 1);
  }
  sel.clear();
  renderTables();
  toast("已删除选中项");
}
$("delSelC").onclick = () => deleteSelected("c");
$("delSelT").onclick = () => deleteSelected("t");

/* ---------------- submit ---------------- */
$("runBtn").onclick = async () => {
  const docs = [];
  for (const g of S.groups) for (const f of g.files)
    docs.push({ name: f.name, group: g.label, file: f.file, path: f.path });
  for (const f of S.loose) docs.push({ name: f.name, group: null, file: f.file, path: f.path });

  const tender = [];
  for (const g of S.tenderGroups) for (const f of g.files) tender.push({ name: f.name, file: f.file, path: f.path });
  for (const f of S.tenderLoose) tender.push({ name: f.name, file: f.file, path: f.path });

  if (docs.length < 2) { toast("至少需要 2 份文档"); return; }

  $("progress").classList.remove("hidden");
  $("runBtn").disabled = true;
  $("runBtn").classList.add("hidden"); $("stopBtn").classList.remove("hidden"); document.querySelector(".submitbar").classList.add("running");
  $("stopBtn").disabled = false;
  $("stopBtn").textContent = "停止检测";
  setProgressReset();
  startClock();
  $("logBody").innerHTML = "";
  aborter = new AbortController();
  S.job = null;

  try {
    const total = docs.length + tender.length;
    let done = 0;
    const upload = async (file, name, kind, group) => {
      const qs = new URLSearchParams({ name, kind });
      const res = await fetch("/api/upload?" + qs, { method: "POST", body: file, signal: aborter.signal });
      let j = {};
      try { j = await res.json(); } catch (_) { /* ignore */ }
      if (!res.ok) throw new Error(j.error || `上传失败（${res.status}）：${name}`);
      done += 1;
      setStage("upload", done, total);
      $("progSub").textContent = `${done}/${total} · ${name} · ${(file.size / 1048576).toFixed(1)}MB`;
      return { id: j.id, name, group };
    };

    const payloadFiles = [];
    for (const d of docs) {
      if (d.file) {
        const up = await upload(d.file, d.name, "c", d.group);
        payloadFiles.push({ ...up, path: d.path || "" });
      } else {
        payloadFiles.push({ name: d.name, group: d.group, path: d.path });
        done += 1;
        setStage("upload", done, total);
        $("progSub").textContent = `${done}/${total} · ${d.name} · 原始路径`;
      }
    }
    const payloadTender = [];
    for (const t of tender) {
      if (t.file) {
        payloadTender.push(await upload(t.file, t.name, "t", null));
      } else {
        payloadTender.push({ name: t.name, path: t.path });
      }
    }

    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: aborter.signal,
      body: JSON.stringify({
        files: payloadFiles,
        tender: payloadTender,
        options: {
          sentence_threshold: 0.6, group_threshold: 0.5,
          images: true, workers: Math.min(8, docs.length),
        },
      }),
    });
    const j = await res.json();
    if (j.error) throw new Error(j.error);
    S.job = j.job;
    $("stopBtn").disabled = false;
    $("stopBtn").textContent = "停止检测";
    poll();
  } catch (e) {
    if (e && e.name === "AbortError") { resetRun(); toast("已取消提交"); return; }
    fail(e.message || String(e));
  }
};

function toB64(file) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result).split(",", 2)[1] || "");
    r.onerror = () => rej(new Error("读取失败：" + file.name));
    r.readAsDataURL(file);
  });
}

$("stopBtn").onclick = async () => {
  const btn = $("stopBtn");
  btn.disabled = true;
  btn.textContent = "停止中…";

  if (!S.job) {
    // 还在上传/提交阶段：直接中断请求
    if (aborter) { aborter.abort(); aborter = null; }
    resetRun();
    toast("已取消提交");
    return;
  }
  try { await fetch("/api/cancel/" + S.job, { method: "POST" }); } catch (_) { /* ignore */ }
  setTimeout(() => {
    if (!S.job) return;
    btn.disabled = false;
    btn.textContent = "再点一次停止";
    toast("仍在收尾当前文件，可再点一次或稍候");
  }, 10000);
};

function resetRun() {
  stopClock(false);
  $("stopBtn").classList.add("hidden"); $("runBtn").classList.remove("hidden"); document.querySelector(".submitbar").classList.remove("running");
  $("progress").classList.add("hidden");
  $("runBtn").disabled = false;
}

function notify(text, rec) {
  let n = document.getElementById("notifyBox");
  if (!n) {
    n = document.createElement("div");
    n.id = "notifyBox";
    n.className = "notify";
    document.body.appendChild(n);
  }
  n.innerHTML = `<div class="n-title">检测完成</div>
    <div class="n-body">${text}<br>报告已保存，可随时查看。</div>
    <div class="n-acts"><button id="nGo">查看报告</button><button id="nClose">关闭</button></div>`;
  n.classList.add("on");
  document.getElementById("nGo").onclick = () => {
    n.classList.remove("on");
    if (rec) openReport(rec);
    else { renderReportList(); go("reports"); }
  };
  document.getElementById("nClose").onclick = () => n.classList.remove("on");
  clearTimeout(n._t);
  n._t = setTimeout(() => n.classList.remove("on"), 20000);
}

function poll() {
  setTimeout(async () => {
    try {
      const j = await (await fetch("/api/job/" + S.job)).json();
      if (j.error) throw new Error(j.error);
      if (j.state === "cancelled") {
        stopClock(false);
        S.job = null;
        aborter = null;
        resetRun();
        toast("已停止检测");
        return;
      }
      if (j.state === "done") {
        stopClock(true);
        const jobId = S.job;
        S.job = null;
        aborter = null;
        $("stopBtn").classList.add("hidden"); $("runBtn").classList.remove("hidden"); document.querySelector(".submitbar").classList.remove("running");
        setStage("finish", 2, 2);
        $("progSub").textContent = "正在生成报告";
        const rec = { id: jobId, time: new Date().toLocaleString("zh-CN"), result: j.result, tender: [] };
        loadReports().then(() => {
          if (S.page === "reports") renderReportList();
        });
        if (j.result.errors && j.result.errors.length) {
          toast(`有 ${j.result.errors.length} 份文件解析失败，已跳过并记入报告`);
        }
        setTimeout(() => {
          $("progress").classList.add("hidden");
          $("runBtn").disabled = false;
          if (S.page === "check") {
            openReport(rec);
          } else {
            const n = (j.result.pairs || []).length;
            notify(`已完成 ${n} 组相似对比`, rec);
          }
        }, 400);
        return;
      }
      if (j.state === "error") throw new Error(j.error || "分析失败");
      const sub = j.sub || (j.stage === "extract" ? `已解析 ${j.done}/${j.total} 份` : `已完成 ${j.done}/${j.total} 对`);
      if (j.eta != null) {
        const raw = Number(j.eta);
        const prev = etaState.v == null
          ? null
          : Math.max(0, etaState.v - (Date.now() - etaState.at) / 1000);
        let next = prev == null ? raw : prev * 0.55 + raw * 0.45;
        if (prev != null) next = Math.min(next, prev * 1.5 + 5); // 防止剩余时间往上跳
        etaState = { v: next, at: Date.now() };
      }
      setStage(j.stage || "extract", j.done, j.total);
      $("progSub").textContent = sub;
      poll();
    } catch (e) { fail(e.message || String(e)); }
  }, 400);
}

function setProgressReset() {
  setStage("upload", 0, 1);
  $("progSub").textContent = "准备中";
}

function fail(msg) {
  stopClock(false);
  $("stopBtn").classList.add("hidden"); $("runBtn").classList.remove("hidden"); document.querySelector(".submitbar").classList.remove("running");
  $("progress").classList.add("hidden");
  $("runBtn").disabled = false;
  toast("检测失败：" + msg);
  openLogs();
}

function fmtDur(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m <= 0 ? `${r} 秒` : `${m} 分 ${r} 秒`;
}

/* ---------------- reports (persisted) ---------------- */
async function loadReports() {
  try {
    const j = await (await fetch("/api/reports")).json();
    S.reports = j.reports || [];
  } catch (_) {
    S.reports = [];
  }
  S.reports.sort((a, b) =>
    ((b.stats && b.stats.max_score) || 0) - ((a.stats && a.stats.max_score) || 0));
  return S.reports;
}

function renderReportList() {
  const box = $("reportList");
  if (!S.reports.length) {
    box.innerHTML = `<div class="card empty-page"><p class="note">还没有历史记录，先到「标书查重」提交一次检测。</p></div>`;
    return;
  }
  box.innerHTML = S.reports.map((m, i) => {
    const s = m.stats || {};
    return `<div class="rep-item" data-rep="${i}">
      <div><div class="when">${esc(m.time)}　${s.docs || 0} 份文档</div>
      <div class="sub2">最高重复率 ${((s.max_score || 0) * 100).toFixed(1)}% · ${s.pairs || 0} 对相似 · 用时 ${fmtDur(s.elapsed)}</div></div>
      <div class="sp">相似句子 ${s.max_sentences || 0} · 段落 ${s.max_paragraphs || 0} · 图片 ${s.max_images || 0}</div>
      <button class="linkbtn del" data-del="${i}" title="删除记录">删除</button>
    </div>`;
  }).join("");
  box.querySelectorAll("[data-rep]").forEach((el) => {
    el.onclick = (ev) => {
      if (ev.target.closest("[data-del]")) return;
      openSavedReport(S.reports[+el.dataset.rep]);
    };
  });
  box.querySelectorAll("[data-del]").forEach((b) => {
    b.onclick = async (ev) => {
      ev.stopPropagation();
      const m = S.reports[+b.dataset.del];
      if (!confirm(`删除这条记录？\n${m.time}`)) return;
      await fetch("/api/reports/" + m.id, { method: "DELETE" });
      await loadReports();
      renderReportList();
    };
  });
}

async function openSavedReport(meta) {
  try {
    const j = await (await fetch("/api/reports/" + meta.id)).json();
    if (j.error) throw new Error(j.error);
    openReport({ id: meta.id, time: meta.time, result: j.result });
  } catch (e) {
    toast("打开记录失败：" + (e.message || e));
  }
}

function openReport(rec) {
  go("report");
  Report.open(rec.result, { time: rec.time, tender: rec.tender, job: rec.id });
  document.querySelectorAll("#specTabs .tab2").forEach((b) =>
    b.onclick = () => Report.setView(b.dataset.view));
  $("expBtn").onclick = () => window.open("/api/reports/" + rec.id + "/export", "_blank");
}

/* ---------------- misc ---------------- */
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
let toastTimer = null;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("on"), 2800);
}

renderTables();
loadReports();

/* ---------------- 版本号 + 清理缓存 ---------------- */
function fmtSize(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(n < 10240 ? 1 : 0) + " KB";
  if (n < 1073741824) return (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + " MB";
  return (n / 1073741824).toFixed(2) + " GB";
}

fetch("/api/health").then((r) => r.json()).then((j) => {
  if (j && j.version) $("verTag").textContent = "v" + j.version;
}).catch(() => {});

(function mountCleanBtn() {
  const slot = $("cleanSlotTop");
  if (!slot) return;
  const btn = document.createElement("button");
  btn.className = "clean-btn";
  btn.id = "cleanBtn";
  btn.textContent = "清理缓存";
  btn.title = "清理本机的排版快照、图片缩略图等中间文件";
  btn.onclick = openCleanDlg;
  slot.appendChild(btn);
})();

let cacheState = null;
const DEFAULT_KEYS = ["docs", "images", "conv"];

function cacheRow(item) {
  const key = item.key;
  const disabled = key === "reports" && !(cacheState.old_reports || {}).count;
  const checked = !disabled && DEFAULT_KEYS.indexOf(key) >= 0 ? " checked" : "";
  const zero = !item.bytes ? " zero" : "";
  let meta = `${item.files} 个文件`;
  if (key === "reports") {
    const old = cacheState.old_reports || { count: 0, days: 30 };
    meta = old.count ? `30 天前的 ${old.count} 份报告` : "没有 30 天前的报告";
  }
  return `<label class="cache-row${zero}${disabled ? " disabled" : ""}">
    <input type="checkbox" class="cache-chk" data-key="${key}"${checked}${disabled ? " disabled" : ""}>
    <span class="cbox"><span class="cname">${esc(item.label)}</span><i class="cnote">${esc(item.note || "")}</i></span>
    <span class="cmeta">${meta}</span>
    <span class="csize">${fmtSize(item.bytes)}</span>
  </label>`;
}

function checkedKeys() {
  return [...document.querySelectorAll(".cache-chk")]
    .filter((el) => el.checked && !el.disabled)
    .map((el) => el.dataset.key);
}

function paintCache(j) {
  cacheState = j;
  $("cacheList").innerHTML = (j.items || []).map(cacheRow).join("");
  document.querySelectorAll(".cache-chk").forEach((el) => {
    el.onchange = paintFree;
  });
  paintFree();
}

function paintFree() {
  if (!cacheState) return;
  const keys = checkedKeys();
  let free = 0;
  (cacheState.items || []).forEach((it) => {
    if (keys.indexOf(it.key) < 0) return;
    if (it.key === "reports") free += (cacheState.old_reports || {}).bytes || 0;
    else free += it.bytes || 0;
  });
  $("cacheFree").textContent = fmtSize(free);
  $("cleanGo").textContent = free ? `清理 ${fmtSize(free)}` : "无需清理";
  $("cleanGo").disabled = !free;
}

function openCleanDlg() {
  $("cleanDlg").classList.remove("hidden");
  $("cacheList").innerHTML = '<div class="cache-loading">正在统计…</div>';
  $("cacheFree").textContent = "—";
  fetch("/api/cache").then((r) => r.json()).then(paintCache).catch(() => {
    $("cacheList").innerHTML = '<div class="cache-loading">统计失败，请稍后再试</div>';
  });
}

$("cleanCancel").onclick = () => $("cleanDlg").classList.add("hidden");
$("cleanDlg").onclick = (e) => {
  if (e.target === $("cleanDlg")) $("cleanDlg").classList.add("hidden");
};
$("cleanGo").onclick = async () => {
  const keys = checkedKeys();
  if (!keys.length) return;
  const btn = $("cleanGo");
  btn.disabled = true;
  btn.textContent = "清理中…";
  try {
    const r = await fetch("/api/cache/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keys, days: 30 }),
    });
    const j = await r.json();
    if (!j.ok) {
      toast(j.error || "清理失败");
      btn.disabled = false;
      paintFree();
      return;
    }
    $("cleanDlg").classList.add("hidden");
    toast(j.freed ? `已清理，释放 ${fmtSize(j.freed)}` : "没有可清理的内容");
    fetch("/api/cache").then((x) => x.json()).then(paintCache).catch(() => {});
  } catch (e) {
    toast("清理失败：" + (e.message || e));
    btn.disabled = false;
    paintFree();
  }
};

// 自检：?selftest=1 时模拟点击皮肤菜单，结果写入 document.title
if (new URLSearchParams(location.search).get("selftest") === "1") {
  setTimeout(() => {
    try {
      document.getElementById("skinBtn").click();
      const open = !document.getElementById("skinMenu").classList.contains("hidden");
      const btn = document.querySelector('#skinMenu button[data-skin="geek"]');
      if (btn) btn.click();
      document.title = "selftest open=" + open + " skin=" + document.documentElement.dataset.skin;
    } catch (e) {
      document.title = "selftest error " + e.message;
    }
  }, 300);
}

// 调试：?skinmenu=1 直接展开皮肤菜单
if (new URLSearchParams(location.search).get("skinmenu") === "1") {
  setTimeout(() => $("skinMenu").classList.remove("hidden"), 200);
}

// 调试：?demo=progress 直接展示"检测中"状态（停止按钮 + 比熊犬）
if (new URLSearchParams(location.search).get("demo") === "progress") {
  setTimeout(() => {
    try {
      $("progress").classList.remove("hidden");
      $("runBtn").classList.add("hidden");
      $("stopBtn").classList.remove("hidden");
      $("stopBtn").textContent = "停止检测";
      document.querySelector(".submitbar").classList.add("running");
      setProgressReset();
      setStage("compare", 4, 10);
    } catch (e) {}
  }, 250);
}

// 调试：?measure=1 把视口/内容宽度写进标题
if (new URLSearchParams(location.search).get("measure") === "1") {
  setTimeout(() => {
    const d = document.documentElement, b = document.body;
    const wide = [...document.querySelectorAll("*")]
      .filter((el) => el.getBoundingClientRect().right > d.clientWidth + 1)
      .slice(0, 5)
      .map((el) => el.tagName + "." + (el.className || "") + ":" + Math.round(el.getBoundingClientRect().right));
    document.title = `sw=${d.scrollWidth} cw=${d.clientWidth}`;
    fetch("/api/diag", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sw: d.scrollWidth, cw: d.clientWidth, bw: b.scrollWidth,
        iw: window.innerWidth, ih: window.innerHeight, dpr: window.devicePixelRatio, wide,
        bottom: [...Array(5)].map((_, k) => {
          const y = window.innerHeight - 8 - k * 12;
          const el = document.elementFromPoint(window.innerWidth / 2, y);
          return el ? `${el.tagName}.${el.className}` : "none";
        }) }) });
  }, 500);
}
