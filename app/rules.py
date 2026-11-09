"""Key-information extraction and document-property inspection."""
from __future__ import annotations

import io
import re

ID18 = re.compile(r"(?<![0-9A-Za-z])(\d{17}[\dXx])(?![0-9A-Za-z])")
ID15 = re.compile(r"(?<![0-9A-Za-z])(\d{15})(?![0-9A-Za-z])")
PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
TEL = re.compile(r"(?<!\d)(0\d{2,3}-?\d{7,8})(?!\d)")
CREDIT = re.compile(r"(?<![0-9A-Z])([0-9A-HJ-NPQRTUWXY]{18})(?![0-9A-Z])")
EMAIL = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
BANK = re.compile(r"(?<!\d)(\d{16,19})(?!\d)")
COMPANY = re.compile(
    r"[\u4e00-\u9fa5（）()]{2,20}?(?:股份有限公司|有限责任公司|有限公司|集团公司|集团|公司)"
)

ID_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
ID_CHECK = "10X98765432"


def valid_id(s: str) -> bool:
    if len(s) != 18:
        return False
    total = sum(int(s[i]) * ID_WEIGHTS[i] for i in range(17))
    return ID_CHECK[total % 11] == s[17].upper()


def extract_keyinfo(text: str, limit: int = 60):
    """Return {kind: [values]} with order preserved and deduplicated."""
    out = {"id_card": [], "phone": [], "credit_code": [], "email": [],
           "company": [], "bank_account": [], "landline": []}

    def push(kind, val):
        if val and val not in out[kind] and len(out[kind]) < limit:
            out[kind].append(val)

    for m in ID18.finditer(text):
        if valid_id(m.group(1)):
            push("id_card", m.group(1).upper())
    for m in ID15.finditer(text):
        push("id_card", m.group(1))
    for m in PHONE.finditer(text):
        push("phone", m.group(1))
    for m in TEL.finditer(text):
        push("landline", m.group(1))
    for m in CREDIT.finditer(text):
        v = m.group(1)
        if sum(c.isdigit() for c in v) >= 10 and not v.isdigit():
            push("credit_code", v)
    for m in EMAIL.finditer(text):
        push("email", m.group(1))
    for m in COMPANY.finditer(text):
        v = m.group(0).strip()
        if 4 <= len(v) <= 30:
            push("company", v)
    for m in BANK.finditer(text):
        push("bank_account", m.group(1))
    return {k: v for k, v in out.items() if v}


KIND_LABEL = {
    "id_card": "身份证号",
    "phone": "手机号",
    "landline": "固定电话",
    "credit_code": "统一社会信用代码",
    "email": "邮箱",
    "company": "公司名称",
    "bank_account": "银行账号",
}


def doc_properties(filename: str, data: bytes):
    """Best-effort document metadata: author, last editor, company, timestamps."""
    props = {}
    low = filename.lower()
    try:
        if low.endswith((".docx", ".docm")) and data.startswith(b"PK"):
            from docx import Document
            d = Document(io.BytesIO(data))
            cp = d.core_properties
            props = {
                "author": cp.author or "",
                "last_modified_by": cp.last_modified_by or "",
                "created": str(cp.created or ""),
                "modified": str(cp.modified or ""),
                "title": cp.title or "",
                "revision": str(cp.revision or ""),
            }
        elif low.endswith((".pptx", ".pptm")) and data.startswith(b"PK"):
            from pptx import Presentation
            prs = Presentation(io.BytesIO(data))
            cp = prs.core_properties
            props = {
                "author": cp.author or "",
                "last_modified_by": cp.last_modified_by or "",
                "created": str(cp.created or ""),
                "modified": str(cp.modified or ""),
                "title": cp.title or "",
                "revision": str(cp.revision or ""),
            }
        elif low.endswith(".pdf") and data.startswith(b"%PDF"):
            import sys
            from pypdf import PdfReader
            r = PdfReader(io.BytesIO(data))
            meta = r.metadata or {}
            props = {
                "author": str(meta.get("/Author") or ""),
                "last_modified_by": str(meta.get("/Producer") or ""),
                "created": str(meta.get("/CreationDate") or ""),
                "modified": str(meta.get("/ModDate") or ""),
                "title": str(meta.get("/Title") or ""),
                "revision": "",
            }
    except Exception:
        props = {}
    finally:
        pass
    # OOXML app.xml carries Company / Manager
    if data.startswith(b"PK") and low.endswith((".docx", ".docm", ".pptx", ".pptm")):
        try:
            import zipfile
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "docProps/app.xml" in z.namelist():
                    xml = z.read("docProps/app.xml").decode("utf-8", "ignore")
                    for tag, key in (("Company", "company"), ("Manager", "manager"),
                                     ("Application", "application"), ("AppVersion", "app_version")):
                        m = re.search(rf"<{tag}>(.*?)</{tag}>", xml)
                        if m and m.group(1).strip():
                            props[key] = m.group(1).strip()
        except Exception:
            pass
    return {k: v for k, v in props.items() if v}
