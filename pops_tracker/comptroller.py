"""Step 8: extract the 333 POPS locations in the NYC Comptroller's audit (SR16-102A, 18 Apr 2017) and link them to
the current POPS master.

The report's Appendix ("Compliance Status for 333 POPS Locations Visited by Auditors") lists each address with
Yes / No / Construction under "Full Compliance". We store that status exactly as printed. We do NOT infer anything else:
the appendix gives no per-location violation detail, so `comptroller_2017_findings` is filled only with narrative passages
from the report body that explicitly name the address, and left blank otherwise.
"""
import re

import pandas as pd
import pdfplumber

from . import address as A
from . import config
from .http import get

AUDIT_ID = "SR16-102A"
AUDIT_DATE = "2017-04-18"
AUDIT_PDF_URL = "https://comptroller.nyc.gov/wp-content/uploads/documents/SR16_102A.pdf"
AUDIT_PDF = config.RAW_COMPTROLLER / "SR16_102A.pdf"
OUT = config.PROCESSED / "comptroller_2017_audit.csv"
ROW_RE = re.compile(r"^\s*(?P<n>\d{1,3})\s+(?P<addr>.+?)\s+(?P<status>Yes|No|Construction)\s*$")
STATUS_MAP = {"Yes": "yes", "No": "no", "Construction": "construction"}


def download():
    if not AUDIT_PDF.exists():
        config.RAW_COMPTROLLER.mkdir(parents=True, exist_ok=True)
        AUDIT_PDF.write_bytes(get(AUDIT_PDF_URL).content)
    return AUDIT_PDF


def _pages():
    with pdfplumber.open(download()) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages]


def parse_appendix(pages) -> pd.DataFrame:
    rows = []
    for pno, txt in enumerate(pages, 1):
        if "Compliance Status for 333 POPS" not in txt and "Full" not in txt:
            continue
        for ln in txt.split("\n"):
            m = ROW_RE.match(ln)
            if m and int(m["n"]) <= 400:
                rows.append({"audit_row": int(m["n"]), "audit_address": m["addr"].strip(),
                             "audit_status_raw": m["status"], "audit_pdf_page": pno})
    return pd.DataFrame(rows)


def _split_addr(addr: str):
    addr = re.sub(r"^One\b", "1", addr.strip())
    m = re.match(r"^(\d+(?:-\d+)?[A-Za-z]?)\s+(.+)$", addr)
    return (m.group(1), m.group(2)) if m else (None, addr)


def _segments(addr: str) -> list[str]:
    """'725 Fifth Avenue - Trump Tower' / '100 UN Plaza/871 UN Plaza' -> address-looking segments, in order."""
    segs = [x.strip() for x in re.split(r"\s+-\s+|/", addr) if x.strip()]
    good = [x for x in segs if re.match(r"^(?:One\s|\d)", x)]
    return good or [addr]


def link_to_master(audit: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    """Borough is not printed in the appendix, so match on (house number, canonical street) across all boroughs."""
    by_num_street, by_street_only = {}, {}
    for _, r in master.iterrows():
        if r["address_normalized"]:
            num, street = r["address_normalized"].split(" ", 1)
            by_num_street.setdefault((num, street), []).append(r["pops_id"])
            by_street_only.setdefault(street, []).append(r["pops_id"])
    out = []
    for _, r in audit.iterrows():
        cands, method, conf = [], "none", "none"
        segs = _segments(r["audit_address"])
        for seg in segs:
            num, street = _split_addr(seg)
            cs = A.canonical_street(street)
            hn = A.parse_house_number(num, "Queens" if num and "-" in num and len(num.split("-")[1]) == 2 else None) if num else None
            if hn:
                c = by_num_street.get((hn["text"], cs), [])
                if c:
                    cands += c
                    method, conf = "address_exact", "high" if len(segs) == 1 else "medium"
                elif hn["kind"] != "range":       # same street, house number inside a POPS range
                    for _, m in master[master.street_canonical == cs].iterrows():
                        if m["hn_low"] != "" and int(m["hn_low"]) <= hn["low"] <= int(m["hn_high"]):
                            cands.append(m["pops_id"]); method, conf = "address_range", "medium"
            elif cs in by_street_only:            # e.g. "MetroTech Center": no house number in the audit
                cands += by_street_only[cs]
                method, conf = "street_only", "low"
        cands = list(dict.fromkeys(cands))
        status = "matched" if len(set(cands)) == 1 else ("ambiguous" if cands else "no_match")
        if status == "ambiguous":
            conf = "none"
        out.append({**r.to_dict(), "pops_id": cands[0] if status == "matched" else "",
                    "match_candidates": ";".join(dict.fromkeys(cands)), "match_status": status,
                    "match_method": method if cands else "none", "match_confidence": conf,
                    "needs_manual_review": status != "matched" or conf != "high"})
    return pd.DataFrame(out)


def findings_from_body(pages, audit: pd.DataFrame) -> dict:
    """{audit_row: (text, page)} for appendix addresses explicitly named in the report body (pages before the appendix)."""
    body_pages = []
    for pno, t in enumerate(pages, 1):
        if "Compliance Status for 333 POPS" in t:
            break
        body_pages.append((pno, t))
    res = {}
    for _, r in audit.iterrows():
        num, street = _split_addr(r["audit_address"])
        if not num or len(street) < 5:
            continue
        rx = re.compile(rf"\b{re.escape(num)}\s+{re.escape(street).replace('Street', '(?:Street|St\\.?)')}", re.I)
        snippets = []
        for pno, t in body_pages:
            flat = re.sub(r"\s+", " ", t)
            for m in rx.finditer(flat):
                snippets.append((pno, flat[max(0, m.start() - 160):m.end() + 260].strip()))
        if snippets:
            res[int(r["audit_row"])] = snippets
    return res


def build(master: pd.DataFrame) -> pd.DataFrame:
    pages = _pages()
    audit = parse_appendix(pages)
    audit = audit.drop_duplicates("audit_row").sort_values("audit_row").reset_index(drop=True)
    linked = link_to_master(audit, master)
    body = findings_from_body(pages, audit)
    linked["comptroller_2017_inspected"] = True
    linked["comptroller_2017_compliant"] = linked["audit_status_raw"].map(STATUS_MAP)  # yes / no / construction (as printed)
    linked["comptroller_2017_findings"] = linked["audit_row"].map(
        lambda n: " || ".join(f"[p.{p}] {t}" for p, t in body.get(int(n), [])[:3]))
    linked["comptroller_2017_findings_source"] = f"{AUDIT_ID} ({AUDIT_DATE}), {AUDIT_PDF_URL}"
    return linked


def write(master: pd.DataFrame) -> pd.DataFrame:
    df = build(master)
    config.PROCESSED.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    return df
