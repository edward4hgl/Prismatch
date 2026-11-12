"""Document extraction: docx / pptx / pdf / xlsx / txt -> list of (page, kind, text)."""
from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass

TEXT_EXT = {".txt", ".md", ".csv"}
DOCX_EXT = {".docx", ".docm"}
PPTX_EXT = {".pptx", ".pptm"}
PDF_EXT = {".pdf"}
XLSX_EXT = {".xlsx", ".xlsm"}


@dataclass
class Block:
    page: int
    text: str
    kind: str = "para"  # para | table | slide | cell


def _docx(data: bytes):
    from docx import Document

    doc = Document(io.BytesIO(data))
    out = []
    for p in doc.paragraphs:
        t = p.text
        if t and t.strip():
            out.append(Block(0, t))
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                out.append(Block(0, " | ".join(cells), "table"))
    return out


def _pptx(data: bytes):
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    out = []
    for idx, slide in enumerate(prs.slides, start=1):
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            for para in shape.text_frame.paragraphs:
                t = "".join(r.text for r in para.runs)
                if t.strip():
                    out.append(Block(idx, t, "slide"))
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        out.append(Block(idx, " | ".join(cells), "table"))
    return out


def _pdf(data: bytes):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    out = []
    for idx, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        for line in text.split("\n"):
            if line.strip():
                out.append(Block(idx, line))
    return out


def _xlsx(data: bytes):
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                out.append(Block(0, " | ".join(cells), "cell"))
    wb.close()
    return out


def _txt(data: bytes):
    for enc in ("utf-8-sig", "utf-8", "gb18030", "utf-16", "big5"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", "ignore")
    return [Block(0, line) for line in text.split("\n") if line.strip()]


def _doc_piece_text(data: bytes) -> str:
    """Parse a Word 97-2003 binary document through its piece table (FIB/Clx)."""
    try:
        import re
        import struct
        import olefile

        with io.BytesIO(data) as fh:
            if not olefile.isOleFile(fh):
                return ""
            fh.seek(0)
            ole = olefile.OleFileIO(fh)
            try:
                if not ole.exists("WordDocument"):
                    return ""
                wd = ole.openstream("WordDocument").read()
                if len(wd) < 0x200 or struct.unpack_from("<H", wd, 0)[0] != 0xA5EC:
                    return ""
                flags = struct.unpack_from("<H", wd, 0x000A)[0]
                table_name = "1Table" if (flags & 0x0200) else "0Table"
                if not ole.exists(table_name):
                    return ""
                table = ole.openstream(table_name).read()
            finally:
                ole.close()

        fc_clx, lcb_clx = struct.unpack_from("<II", wd, 0x01A2)
        if not lcb_clx or fc_clx + lcb_clx > len(table):
            return ""
        clx = table[fc_clx:fc_clx + lcb_clx]

        i, pcdt = 0, None
        while i < len(clx):
            tag = clx[i]
            if tag == 0x01:
                if i + 3 > len(clx):
                    return ""
                cb = struct.unpack_from("<H", clx, i + 1)[0]
                i += 3 + cb
            elif tag == 0x02:
                lcb = struct.unpack_from("<I", clx, i + 1)[0]
                pcdt = clx[i + 5:i + 5 + lcb]
                break
            else:
                return ""
        if not pcdt or len(pcdt) < 16:
            return ""

        n = (len(pcdt) - 4) // 12
        if n <= 0:
            return ""
        cps = [struct.unpack_from("<I", pcdt, 4 * k)[0] for k in range(n + 1)]
        base = 4 * (n + 1)

        parts = []
        for k in range(n):
            cp_start, cp_end = cps[k], cps[k + 1]
            length = cp_end - cp_start
            if length <= 0:
                continue
            fc_raw = struct.unpack_from("<I", pcdt, base + 8 * k + 2)[0]
            compressed = bool(fc_raw & 0x40000000)
            fc = fc_raw & 0x3FFFFFFF
            if compressed:
                start = fc // 2
                chunk = wd[start:start + length]
                parts.append(chunk.decode("cp1252", "replace"))
            else:
                chunk = wd[fc:fc + length * 2]
                parts.append(chunk.decode("utf-16-le", "replace"))

        text = "".join(parts)
        # Word fields: \x13 instruction \x14 result \x15 -> keep only the result
        while "\x13" in text:
            new = re.sub(r"\x13[^\x13\x14\x15]*\x14", "", text)
            if new == text:
                break
            text = new
        text = text.replace("\x13", "").replace("\x14", "").replace("\x15", "")
        for src, dst in (("\r", "\n"), ("\x07", "\n"), ("\x0b", "\n"), ("\x0c", "\n"), ("\x1e", "-")):
            text = text.replace(src, dst)
        text = "".join(ch for ch in text if ch >= " " or ch in "\n\t")
        return text
    except Exception:
        return ""


def _doc_legacy(data: bytes):
    """Legacy .doc: piece-table parse first, heuristic UTF-16 scrape as fallback."""
    text = _doc_piece_text(data)
    if text.strip():
        return [Block(0, line) for line in text.split("\n") if line.strip()]

    import re

    best = ""
    for enc in ("utf-16-le", "gb18030"):
        try:
            decoded = data.decode(enc, "ignore")
        except Exception:
            continue
        runs = re.findall(r"[\u4e00-\u9fffA-Za-z0-9，。、；：！？（）\"'《》\-]{8,}", decoded)
        candidate = "\n".join(runs)
        if len(candidate) > len(best):
            best = candidate
    return [Block(0, line) for line in best.split("\n") if line.strip()]


def _ppt_legacy(data: bytes):
    raise ValueError("旧版 .ppt 暂不支持，请另存为 .pptx")


def _xls_legacy(data: bytes):
    raise ValueError("旧版 .xls 暂不支持，请另存为 .xlsx")


EXTRACTORS = {
    "docx": _docx,
    "doc": _doc_legacy,
    "pptx": _pptx,
    "ppt": _ppt_legacy,
    "pdf": _pdf,
    "xlsx": _xlsx,
    "xls": _xls_legacy,
    "txt": _txt,
}

EXT_KIND = {
    ".docx": "docx", ".docm": "docx",
    ".doc": "doc",
    ".pptx": "pptx", ".pptm": "pptx",
    ".ppt": "ppt",
    ".pdf": "pdf",
    ".xlsx": "xlsx", ".xlsm": "xlsx",
    ".xls": "xls",
    ".txt": "txt", ".md": "txt", ".csv": "txt",
}


def kind_of(filename: str) -> str:
    return EXT_KIND.get(os.path.splitext(filename)[1].lower(), "txt")


def _clean(s: str) -> str:
    """Drop lone UTF-16 surrogates that PDF/office extractors sometimes emit."""
    if not s:
        return ""
    if not any(0xD800 <= ord(ch) <= 0xDFFF for ch in s):
        return s
    return "".join(ch for ch in s if not (0xD800 <= ord(ch) <= 0xDFFF))


def docx_to_html(data: bytes) -> str:
    """Word -> HTML (keeps tables, headings, lists, bold/italic)."""
    import mammoth

    def _skip_image(_image):
        return {"src": ""}

    with io.BytesIO(data) as fh:
        result = mammoth.convert_to_html(
            fh, convert_image=mammoth.images.img_element(_skip_image)
        )
    return result.value


def pdf_needs_ocr(data: bytes, blocks):
    """A PDF whose extracted text is far too thin for its page count is a scan."""
    pages = 0
    try:
        from pypdf import PdfReader

        pages = len(PdfReader(io.BytesIO(data)).pages)
    except Exception:
        pages = blocks[-1].page if blocks else 0
    total = sum(len(b.text.strip()) for b in blocks)
    if pages <= 0:
        return False, 0
    return total < max(120, pages * 24), pages


def extract(filename: str, data: bytes, force_kind=None, min_chars: int = 20,
            allow_empty: bool = False):
    kind = force_kind or kind_of(filename)
    renamed = False

    # sniff real container type instead of trusting the extension
    if kind in ("docx", "pptx", "xlsx") and not data.startswith(b"PK"):
        if kind == "docx":
            kind = "doc"          # legacy .doc, possibly renamed to .docx
            renamed = True
        else:
            raise ValueError("扩展名与实际格式不符（疑似旧版二进制格式）")
    if kind == "pdf" and not data.startswith(b"%PDF"):
        raise ValueError("不是有效的 PDF 文件")

    fn = EXTRACTORS.get(kind)
    if fn is None:
        raise ValueError(f"不支持的文件类型：{kind}")

    try:
        blocks = fn(data)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"解析失败：{exc}") from exc

    cleaned = []
    for b in blocks:
        text = _clean(b.text)
        if text.strip():
            b.text = text
            cleaned.append(b)
    blocks = cleaned

    if not blocks:
        if allow_empty:
            return kind, []
        if kind == "doc":
            if renamed:
                raise ValueError("文件不是有效的 .docx（可能是旧版 .doc 或已损坏），请另存为 .docx 后重试")
            raise ValueError("旧版 .doc 无法解析，请另存为 .docx 后重试")
        raise ValueError("没有提取到文本（可能是扫描件或加密文件）")
    if sum(len(b.text.strip()) for b in blocks) < min_chars:
        raise ValueError("提取到的文本过少（可能是扫描件）")
    return kind, blocks


def images_of(filename: str, data: bytes):
    """Extract embedded raster images (docx/pptx are zip containers)."""
    out = []
    if not (filename.lower().endswith((".docx", ".pptx", ".docm", ".pptm")) or data.startswith(b"PK")):
        return out
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                if "/media/" not in name:
                    continue
                if not name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")):
                    continue
                try:
                    out.append(z.read(name))
                except Exception:
                    continue
    except Exception:
        return out
    return out
