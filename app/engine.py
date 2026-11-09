"""Analysis engine v2: tender filtering, supplier groups, per-pair counts,
key-information and document-property comparison."""
from __future__ import annotations

import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import extract, rules, sim, text as T

MAX_BLOCK_TEXT = 6000
MAX_BLOCKS_PER_PAIR = 400
MAX_IMAGE_PAIRS = 4000
TENDER_THRESHOLD = 0.55


class Cancelled(Exception):
    """Raised when the caller stops a running analysis."""


@dataclass
class Seg:
    para: int
    start: int
    end: int
    text: str
    grams: set
    tokens: list


@dataclass
class Para:
    idx: int
    page: int
    ptype: int
    text: str
    filtered: bool = False


@dataclass
class Doc:
    id: int
    name: str
    chars: int
    paras: list
    segs: list
    index: dict = field(default_factory=dict)
    images: list = field(default_factory=list)
    image_bytes: list = field(default_factory=list)
    kind: str = "docx"
    group: object = None
    keyinfo: dict = field(default_factory=dict)
    props: dict = field(default_factory=dict)
    filtered_paras: int = 0
    error: str = ""
    path: str = ""
    html: str = ""
    raw: str = ""


def build_doc(idx, name, data, options, group=None, tender=None, path=""):
    try:
        return _build_doc(idx, name, data, options, group, tender, path)
    except Exception as exc:  # noqa: BLE001
        doc = Doc(id=idx, name=name, chars=0, paras=[], segs=[],
                  kind=extract.kind_of(name), group=group, path=path)
        doc.error = f"{type(exc).__name__}: {exc}"
        return doc


def _build_doc(idx, name, data, options, group=None, tender=None, path=""):
    if isinstance(data, str):          # path: load lazily, drop after parsing
        path = path or data
        with open(data, "rb") as fh:
            data = fh.read()
    kind, blocks = extract.extract(name, data)
    paras, segs = [], []
    for block in blocks:
        is_table = str(getattr(block, "kind", "para")) == "table"
        # 表格行没有"正文"的长度特征，强制纳入索引，否则数据表永远比不出来
        ptype = 0 if is_table else T.para_type(block.text)
        p = Para(len(paras), block.page, ptype, block.text)
        paras.append(p)
        if ptype != 0:
            continue
        if tender is not None and tender.matches(block.text, options):
            p.filtered = True
            continue
        if is_table:
            seg_text = block.text.strip()
            if seg_text:
                segs.append(Seg(p.idx, 0, len(block.text), seg_text,
                                T.gram_hashes(seg_text), T.tokens(seg_text)))
            continue
        for s, e in T.segments(block.text):
            seg_text = block.text[s:e]
            segs.append(Seg(p.idx, s, e, seg_text, T.gram_hashes(seg_text), T.tokens(seg_text)))

    index = defaultdict(list)
    for sid, seg in enumerate(segs):
        for g in seg.grams:
            index[g].append(sid)

    chars = sum(len(p.text) for p in paras if p.ptype == 0 and not p.filtered)
    doc = Doc(id=idx, name=name, chars=chars, paras=paras, segs=segs,
              index=dict(index), kind=kind, group=group, path=path)
    doc.filtered_paras = sum(1 for p in paras if p.filtered)
    if options.get("images", True):
        raw = extract.images_of(name, data)
        for b in raw:
            h = sim.dhash(b)
            if h is None:
                continue
            ext = "png" if b[:8] == b"\x89PNG\r\n\x1a\n" else ("jpg" if b[:2] == b"\xff\xd8" else "png")
            doc.image_bytes.append({"hash": h, "bytes": b, "ext": ext})
        doc.images = [x["hash"] for x in doc.image_bytes]
    doc.keyinfo = rules.extract_keyinfo("\n".join(p.text for p in paras))
    doc.props = rules.doc_properties(name, data)

    if kind == "docx" and options.get("html_dir"):
        try:
            html_name = f"d{idx}.html"
            with open(os.path.join(options["html_dir"], html_name), "w", encoding="utf-8") as fh:
                fh.write(extract.docx_to_html(data))
            doc.html = html_name
        except Exception:
            doc.html = ""

    if kind == "docx" and options.get("raw_dir"):
        try:
            raw_name = f"d{idx}.docx"
            with open(os.path.join(options["raw_dir"], raw_name), "wb") as fh:
                fh.write(data)
            doc.raw = raw_name
        except Exception:
            doc.raw = ""
    return doc


class TenderFilter:
    """Drops paragraphs that are near-identical to the tender document."""

    def __init__(self, tender_files, options):
        self.index = defaultdict(list)
        self.segs = []
        for name, data in tender_files:
            try:
                if isinstance(data, str):
                    with open(data, "rb") as fh:
                        data = fh.read()
                _kind, blocks = extract.extract(name, data)
            except Exception:
                continue
            for block in blocks:
                try:
                    if T.para_type(block.text) != 0:
                        continue
                    for s, e in T.segments(block.text):
                        seg_text = block.text[s:e]
                        self.segs.append(seg_text)
                        for g in T.gram_hashes(seg_text):
                            self.index[g].append(len(self.segs) - 1)
                except Exception:  # noqa: BLE001
                    continue
        self.index = dict(self.index)

    def matches(self, text, options):
        try:
            return self._matches(text, options)
        except Exception:  # noqa: BLE001
            return False

    def _matches(self, text, options):
        thr = float(options.get("tender_threshold", TENDER_THRESHOLD))
        for s, e in T.segments(text):
            seg = text[s:e]
            grams = T.gram_hashes(seg)
            if len(grams) < 4:
                continue
            counts = defaultdict(int)
            for g in grams:
                for i in self.index.get(g, ()):
                    counts[i] += 1
            if not counts:
                continue
            need = max(3, int(len(grams) * 0.3))
            for i, c in sorted(counts.items(), key=lambda kv: -kv[1])[:5]:
                if c < need:
                    break
                if sim.similarity(seg, self.segs[i]) >= thr:
                    return True
        return False


def compare_pair(a, b, options):
    threshold = float(options.get("sentence_threshold", 0.6))
    min_ratio = float(options.get("min_shared_ratio", 0.25))
    topk = int(options.get("top_k", 12))

    matches = []
    for bi, sb in enumerate(b.segs):
        gb = sb.grams
        if len(gb) < 4:
            continue
        counts = defaultdict(int)
        for g in gb:
            ids = a.index.get(g)
            if ids:
                for ai in ids:
                    counts[ai] += 1
        if not counts:
            continue
        need = max(3, int(len(gb) * min_ratio))
        cand = [(c, ai) for ai, c in counts.items() if c >= need]
        if not cand:
            continue
        cand.sort(reverse=True)
        best = None
        for _c, ai in cand[:topk]:
            sa = a.segs[ai]
            s = sim.similarity(sb.text, sa.text, sb.tokens, sa.tokens)
            if s >= threshold and (best is None or s > best[2]):
                best = (ai, bi, s)
        if best:
            matches.append(best)

    if not matches:
        return None

    blocks, a_best, b_best = {}, {}, {}
    for ai, bi, s in matches:
        sa, sb = a.segs[ai], b.segs[bi]
        a_best[ai] = max(a_best.get(ai, 0.0), s)
        b_best[bi] = max(b_best.get(bi, 0.0), s)
        entry = blocks.setdefault((sa.para, sb.para), {"a": [], "b": [], "score": 0.0})
        entry["a"].append([sa.start, sa.end, round(s, 4)])
        entry["b"].append([sb.start, sb.end, round(s, 4)])
        entry["score"] = max(entry["score"], s)

    def merge(spans):
        spans.sort()
        out = []
        for s, e, sc in spans:
            if out and s <= out[-1][1]:
                out[-1][1] = max(out[-1][1], e)
                out[-1][2] = max(out[-1][2], sc)
            else:
                out.append([s, e, sc])
        return out

    rows = []
    for (ap, bp), e in sorted(blocks.items(), key=lambda kv: -kv[1]["score"]):
        pa, pb = a.paras[ap], b.paras[bp]
        rows.append({
            "a_para": ap, "a_page": pa.page, "a_text": pa.text[:MAX_BLOCK_TEXT],
            "a_spans": merge(e["a"]),
            "b_para": bp, "b_page": pb.page, "b_text": pb.text[:MAX_BLOCK_TEXT],
            "b_spans": merge(e["b"]),
            "score": round(e["score"], 4),
        })
        if len(rows) >= MAX_BLOCKS_PER_PAIR:
            break

    dup_a = sum(len(a.segs[i].text) * s for i, s in a_best.items())
    dup_b = sum(len(b.segs[i].text) * s for i, s in b_best.items())
    ratio_a = min(1.0, dup_a / a.chars) if a.chars else 0.0
    ratio_b = min(1.0, dup_b / b.chars) if b.chars else 0.0

    return {
        "a": a.id, "b": b.id,
        "ratio_a": round(ratio_a, 4),
        "ratio_b": round(ratio_b, 4),
        "sentences": len(matches),
        "paragraphs": len(rows),
        "score": round(max(ratio_a, ratio_b), 4),
        "blocks": rows,
        "_a_best": a_best,
        "_b_best": b_best,
    }


def _save_img(image_dir, doc_id, idx, item, cache):
    key = (doc_id, idx)
    if key in cache:
        return cache[key]
    name = f"d{doc_id}_{idx}.{item['ext']}"
    try:
        with open(os.path.join(image_dir, name), "wb") as fh:
            fh.write(item["bytes"])
    except Exception:
        name = ""
    cache[key] = name
    return name


def analyze(files, tender_files=None, options=None, progress=None, cancel=None):
    options = options or {}
    t0 = time.time()
    docs = []

    def report(stage, done, total, eta=None):
        if progress:
            try:
                progress(stage, done, total, eta)
            except TypeError:
                progress(stage, done, total)

    tender = TenderFilter(tender_files, options) if tender_files else None

    FINISH_OVERHEAD = 2.0

    # ---- extract: per-file-type throughput model ----
    sizes = []
    for item in files:
        name, data = item[0], item[1]
        if isinstance(data, str):
            try:
                sz = os.path.getsize(data)
            except Exception:
                sz = 2048
        else:
            sz = len(data)
        sizes.append((extract.kind_of(name), max(sz, 2048)))

    total_bytes = sum(s for _k, s in sizes) or 1
    remaining = defaultdict(lambda: [0, 0])   # kind -> [count, bytes]
    for kind, sz in sizes:
        remaining[kind][0] += 1
        remaining[kind][1] += sz

    obs = []                                  # (bytes, seconds)
    eta_hist = {"v": None}

    def fit_cost():
        """Least squares t = a + b*size over completed files."""
        n = len(obs)
        if n < 5:
            return None
        sx = sum(s for s, _t in obs)
        sy = sum(t for _s, t in obs)
        sxx = sum(s * s for s, _t in obs)
        sxy = sum(s * t for s, t in obs)
        den = n * sxx - sx * sx
        if den <= 0:
            return None
        b = (n * sxy - sx * sy) / den
        a = (sy - b * sx) / n
        return max(a, 0.0), max(b, 0.0)

    def smooth(value):
        if value is None:
            return None
        prev = eta_hist["v"]
        if prev is None:
            eta_hist["v"] = value
            return value
        value = min(value, prev * 1.5 + 5)
        merged = prev * 0.55 + value * 0.45
        eta_hist["v"] = merged
        return merged

    def extract_eta():
        f = fit_cost()
        if f is None:
            return None
        a, b = f
        rem = 0.0
        for _kind, (cnt, nbytes) in remaining.items():
            if cnt <= 0:
                continue
            rem += cnt * a + nbytes * b
        return rem

    report("extract", 0, len(files), None)
    for i, item in enumerate(files):
        name, data, group = item[0], item[1], item[2]
        src = item[3] if len(item) > 3 else ""
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        t_file = time.time()
        docs.append(build_doc(i, name, data, options, group, tender, src))
        dt = time.time() - t_file
        kind, sz = sizes[i]
        obs.append((sz, dt))
        remaining[kind][0] -= 1
        remaining[kind][1] -= sz
        left = extract_eta()
        report("extract", i + 1, len(files),
               None if left is None else smooth(left + FINISH_OVERHEAD))

    n = len(docs)
    jobs, k = [], 0
    for i in range(n):
        for j in range(i + 1, n):
            if docs[i].group is not None and docs[i].group == docs[j].group:
                continue
            jobs.append((k, i, j))
            k += 1

    # ---- compare: cost weighted by segment volume, measured wall-clock rate ----
    weights = [max(1, len(docs[i].segs) + len(docs[j].segs)) for _kk, i, j in jobs]
    total_weight = sum(weights) or 1
    done_weight = 0
    pairs = [None] * len(jobs)
    done = 0

    def work(job):
        kk, i, j = job
        if cancel is not None and cancel.is_set():
            return kk, None
        return kk, compare_pair(docs[i], docs[j], options)

    t_cmp = time.time()
    rate_w = None
    report("compare", 0, len(jobs), FINISH_OVERHEAD + 0.0)
    workers = int(options.get("workers", 0)) or min(8, max(1, len(jobs)))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for kk, res in pool.map(work, jobs):
            pairs[kk] = res
            done += 1
            done_weight += weights[kk]
            elapsed = max(1e-3, time.time() - t_cmp)
            cum = elapsed / max(done_weight, 1)
            rate_w = cum if rate_w is None else 0.8 * rate_w + 0.2 * cum
            rem_cmp = max(0.0, (total_weight - done_weight) * rate_w)
            report("compare", done, len(jobs), smooth(rem_cmp + FINISH_OVERHEAD))

    if cancel is not None and cancel.is_set():
        raise Cancelled()

    report("finish", 0, 2, 1.5)

    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        matrix[i][i] = 1.0

    pair_rows = []
    for res in pairs:
        if res:
            matrix[res["a"]][res["b"]] = matrix[res["b"]][res["a"]] = res["score"]
            pair_rows.append(res)

    # image duplicates (perceptual hash); optionally materialise thumbnails
    image_pairs = []
    if options.get("images", True):
        image_dir = options.get("image_dir")
        if image_dir:
            try:
                os.makedirs(image_dir, exist_ok=True)
            except Exception:
                image_dir = None
        saved = {}
        stop = False
        for i in range(n):
            if stop:
                break
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            for j in range(i + 1, n):
                if docs[i].group is not None and str(docs[i].group) == str(docs[j].group):
                    continue
                for ia, imga in enumerate(docs[i].image_bytes):
                    for ib, imgb in enumerate(docs[j].image_bytes):
                        if len(image_pairs) >= MAX_IMAGE_PAIRS:
                            stop = True
                            break
                        dist = (imga["hash"] ^ imgb["hash"]).bit_count()
                        if dist > 6:
                            continue
                        ent = {"a": i, "ai": ia, "b": j, "bi": ib, "dist": dist}
                        if image_dir:
                            ent["a_img"] = _save_img(image_dir, i, ia, imga, saved)
                            ent["b_img"] = _save_img(image_dir, j, ib, imgb, saved)
                        image_pairs.append(ent)
                    if stop:
                        break
                if stop:
                    break

    counts = defaultdict(int)
    for x in image_pairs:
        counts[(x["a"], x["b"])] += 1
    for res in pair_rows:
        res["images"] = counts.get((res["a"], res["b"]), 0)

    report("finish", 1, 2, 0.8)

    pair_rows.sort(key=lambda r: -r["score"])

    group_pairs = build_group_pairs(docs, pair_rows)
    for res in pair_rows:
        res.pop("_a_best", None)
        res.pop("_b_best", None)

    keyinfo = build_keyinfo_rows(docs)
    props = build_property_rows(docs)
    groups = build_groups(n, pair_rows, float(options.get("group_threshold", 0.5)))

    report("finish", 2, 2, 0.0)
    elapsed = round(time.time() - t0, 2)
    errors = [{"name": d.name, "error": d.error} for d in docs if d.error]
    return {
        "docs": [
            {"id": d.id, "name": d.name, "chars": d.chars, "paras": len(d.paras),
             "indexed": len(d.segs), "images": len(d.images), "kind": d.kind,
             "group": d.group, "filtered": d.filtered_paras, "error": d.error,
             "path": d.path, "html": d.html, "raw": d.raw,
             "blocks": [{"i": p.idx, "pg": p.page, "t": p.text[:MAX_BLOCK_TEXT]}
                        for p in d.paras if p.ptype == 0 and not p.filtered],
             "all": [{"i": p.idx, "pg": p.page, "t": p.text[:MAX_BLOCK_TEXT],
                      "f": 1 if p.filtered else 0}
                     for p in d.paras if p.text.strip()]}
            for d in docs
        ],
        "matrix": matrix,
        "pairs": pair_rows,
        "groupPairs": group_pairs,
        "groups": groups,
        "keyinfo": keyinfo,
        "properties": props,
        "errors": errors,
        "tender": [n for n, _d in (tender_files or [])],
        "imagePairs": image_pairs,
        "stats": {
            "docs": n,
            "chars": sum(d.chars for d in docs),
            "pairs": len(pair_rows),
            "max_score": pair_rows[0]["score"] if pair_rows else 0.0,
            "max_sentences": max((p["sentences"] for p in pair_rows), default=0),
            "max_paragraphs": max((p["paragraphs"] for p in pair_rows), default=0),
            "max_images": max((p.get("images", 0) for p in pair_rows), default=0),
            "filtered": sum(d.filtered_paras for d in docs),
            "elapsed": elapsed,
            "thresholds": {
                "sentence": options.get("sentence_threshold", 0.6),
                "group": options.get("group_threshold", 0.5),
            },
        },
    }


def build_group_pairs(docs, pair_rows):
    """Aggregate file-level results into folder/supplier-level rows.

    Every distinct pair of groups is emitted, even when nothing matched,
    so an N-supplier run always shows C(N,2) rows.
    """
    groups = {}
    labels, seen = [], set()
    for d in docs:
        if d.group is None:
            continue
        g = str(d.group)
        if g not in seen:
            seen.add(g)
            labels.append(g)

    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            a, b = sorted((labels[i], labels[j]))
            groups[(a, b)] = {
                "a": a, "b": b, "files": [], "score": 0.0,
                "sentences": 0, "paragraphs": 0, "images": 0, "dup": {},
            }

    for res in pair_rows:
        ga, gb = docs[res["a"]].group, docs[res["b"]].group
        if ga is None or gb is None or ga == gb:
            continue
        key = tuple(sorted((str(ga), str(gb))))
        ent = groups.setdefault(key, {
            "a": key[0], "b": key[1], "files": [], "score": 0.0,
            "sentences": 0, "paragraphs": 0, "images": 0, "dup": {},
        })
        ent["files"].append({
            "a": res["a"], "b": res["b"],
            "name_a": docs[res["a"]].name, "name_b": docs[res["b"]].name,
            "sentences": res["sentences"], "paragraphs": res["paragraphs"],
            "images": res.get("images", 0), "score": res["score"],
        })
        ent["score"] = max(ent["score"], res["score"])
        ent["sentences"] += res["sentences"]
        ent["paragraphs"] += res["paragraphs"]
        ent["images"] += res.get("images", 0)
        for si, s in res.get("_a_best", {}).items():
            k = (res["a"], si)
            if s > ent["dup"].get(k, 0):
                ent["dup"][k] = s
        for si, s in res.get("_b_best", {}).items():
            k = (res["b"], si)
            if s > ent["dup"].get(k, 0):
                ent["dup"][k] = s

    chars = defaultdict(int)
    for d in docs:
        if d.group is not None:
            chars[str(d.group)] += d.chars

    out = []
    for ent in groups.values():
        dup = ent.pop("dup", {})
        side_a = sum(len(docs[di].segs[si].text) * s
                     for (di, si), s in dup.items() if str(docs[di].group) == ent["a"])
        side_b = sum(len(docs[di].segs[si].text) * s
                     for (di, si), s in dup.items() if str(docs[di].group) == ent["b"])
        ent["ratio_a"] = round(side_a / chars[ent["a"]], 4) if chars[ent["a"]] else 0.0
        ent["ratio_b"] = round(side_b / chars[ent["b"]], 4) if chars[ent["b"]] else 0.0
        ent["score"] = round(max(ent["ratio_a"], ent["ratio_b"]), 4)
        ent["files"].sort(key=lambda f: -f["score"])
        ent["fileCount"] = len(ent["files"])
        out.append(ent)
    out.sort(key=lambda g: -g["score"])
    return out


def build_keyinfo_rows(docs):
    owners = defaultdict(set)
    label = {}
    for d in docs:
        for kind, values in d.keyinfo.items():
            for v in values:
                owners[(kind, v)].add(d.id)
                label[kind] = rules.KIND_LABEL.get(kind, kind)
    rows = defaultdict(list)
    for (kind, value), ids in owners.items():
        if len(ids) >= 2:
            rows[kind].append({"value": value, "docs": sorted(ids)})
    return [
        {"kind": k, "label": label.get(k, k),
         "items": sorted(v, key=lambda x: -len(x["docs"]))}
        for k, v in rows.items()
    ]


def build_property_rows(docs):
    fields = [("author", "作者"), ("last_modified_by", "最后保存者"),
              ("company", "公司"), ("created", "创建时间"), ("modified", "修改时间")]
    rows = []
    for key, name in fields:
        buckets = defaultdict(list)
        for d in docs:
            v = (d.props or {}).get(key)
            if v:
                buckets[str(v)].append(d.id)
        for value, ids in buckets.items():
            if len(ids) >= 2:
                rows.append({"field": key, "label": name, "value": value, "docs": sorted(ids)})
    return rows


def build_groups(n, pair_rows, threshold):
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for row in pair_rows:
        if row["score"] >= threshold:
            ra, rb = find(row["a"]), find(row["b"])
            if ra != rb:
                parent[rb] = ra

    buckets = defaultdict(list)
    for i in range(n):
        buckets[find(i)].append(i)

    groups = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        best = max((r["score"] for r in pair_rows
                    if r["a"] in members and r["b"] in members), default=0.0)
        groups.append({"docs": sorted(members), "score": round(best, 4), "size": len(members)})
    groups.sort(key=lambda g: (-g["size"], -g["score"]))
    return groups
