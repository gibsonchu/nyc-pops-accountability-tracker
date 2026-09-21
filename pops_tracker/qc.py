"""Step 11: quality-control checks. Nothing uncertain is discarded; it is routed to data/review/manual_review.csv.

Record-level and bulletin-level issues share one file. Human decisions live separately in review_decisions.csv (keyed by
enforcement_id) so regenerating this file never loses reviewer work: a decided item simply shows status='resolved'.
"""
import datetime as dt
import hashlib
import json
import re

import pandas as pd
from rapidfuzz import fuzz

from . import address as A
from . import config
from .match import _name_corroborated

PROFESSIONAL_RE = re.compile(
    r"licen[sc]e|professional\s+certification|Directive\s+14|suspen|probation|revoke|revocation|disciplin|surrender|"
    r"Special\s+Enforcement\s+Team|SET\)|audit(?:ed)?\s+of|filing\s+(?:false|privileges)|Registered\s+Architect|"
    r"Professional\s+Engineer|OATH|stipulation|petition\s+for\s+padlock|summons", re.I)

REVIEW_COLUMNS = ["review_id", "issue_type", "severity", "status", "enforcement_id", "bulletin_id", "pops_id_candidate",
                  "detail", "suggested_candidates", "source_pdf", "source_page", "enforcement_text_excerpt", "detected_at"]

SEV = {"high": 0, "medium": 1, "low": 2}


def _rid(*parts) -> str:
    return "R-" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


def suggest_candidates(row, master: pd.DataFrame) -> str:
    """Name / house-number based hints for a text-only POPS mention. Suggestions are never applied automatically."""
    out = []
    text = row["enforcement_text"]
    for _, m in master.iterrows():
        if _name_corroborated(m["building_name"], text):
            out.append(f"{m['pops_id']} ({m['building_name']}, {m['address_normalized']}) [building name in text]")
    b = row.get("borough") or None
    if b and row.get("address_number"):
        hn = A.parse_house_number(row["address_number"], b)
        if hn:
            near = master[(master["borough"] == b) & (master["hn_low"] != "") & (master["hn_low"].astype(str) == str(hn["low"]))]
            want = A.canonical_street(row.get("address_street", ""))
            for _, m in near.iterrows():
                if want and fuzz.ratio(want, m["street_canonical"]) >= 70 and not any(m["pops_id"] in o for o in out):
                    out.append(f"{m['pops_id']} ({m['address_normalized']}) [same house number, similar street name]")
    return " | ".join(out[:4])


def record_issues(df: pd.DataFrame, master: pd.DataFrame) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    issues = []

    def add(r, issue, sev, detail, cand="", sugg=""):
        issues.append({"review_id": _rid(issue, r["enforcement_id"]), "issue_type": issue, "severity": sev,
                       "enforcement_id": r["enforcement_id"], "bulletin_id": r["bulletin_id"], "pops_id_candidate": cand,
                       "detail": detail, "suggested_candidates": sugg, "source_pdf": r["source_pdf"],
                       "source_page": r["source_page"], "enforcement_text_excerpt": r["enforcement_text"][:400],
                       "detected_at": now})

    for _, r in df.iterrows():
        rel = r["pops_relation"]
        if r["match_status"] == "ambiguous":
            add(r, "ambiguous_pops_match", "high", f"multiple POPS candidates: {r['match_candidates']}; {r['match_notes']}", r["match_candidates"])
        if r["match_status"] == "matched" and r["match_confidence"] in ("low", "medium"):
            add(r, "low_confidence_match", "high" if r["match_confidence"] == "low" else "medium",
                f"{r['match_method']} / {r['match_confidence']}: {r['match_notes']}", r["pops_id"])
        if rel == "pops_text_only":
            add(r, "pops_keyword_without_db_match", "high",
                f"POPS terminology ({r['pops_keyword_hits']}) but no POPS-database match. Address extracted: "
                f"'{r['address_raw']}' ({r['borough'] or 'borough unknown'}); geocode: {r['geocode_status']}. "
                "Possible causes: POPS missing from DCP data, DOB address error, or not a POPS.",
                "", suggest_candidates(r, master))
        elif rel == "weak_keyword_only":
            add(r, "weak_pops_keyword_no_match", "low", f"only weak terms ({r['pops_keyword_hits']}) and no match", "", "")
        elif rel == "property_match_only":
            add(r, "db_match_without_pops_terms", "medium",
                "Property is a POPS building but the paragraph does not mention POPS; the violation may concern the building, "
                f"not the public space. Match: {r['match_method']}/{r['match_confidence']}", r["pops_id"])
        if r["possible_duplicate_of"]:
            add(r, "possible_duplicate_action", "medium", f"{r['duplicate_basis']}: duplicates {r['possible_duplicate_of']}", r["pops_id"])
        if r["borough_conflict"] in (True, "True"):
            add(r, "borough_conflict", "medium", "borough in text differs from bulletin section header")
        prof = r["professional_section"] in (True, "True") or bool(PROFESSIONAL_RE.search(r["enforcement_text"]))
        if not r["address_raw"] and not prof:
            add(r, "address_not_parsed", "low", "no street address could be extracted from a property-type entry")
        pen = r["penalty_amount"]
        txt = r["enforcement_text"]
        if pen != "" and pen is not None:
            p = int(float(pen))
            if p < config.PENALTY_MIN_PLAUSIBLE or p > config.PENALTY_MAX_PLAUSIBLE:
                add(r, "suspicious_penalty", "high", f"penalty ${p:,} outside plausible range "
                    f"${config.PENALTY_MIN_PLAUSIBLE:,}-${config.PENALTY_MAX_PLAUSIBLE:,}")
        elif txt.startswith("$"):
            add(r, "suspicious_penalty", "medium", "entry starts with '$' but no penalty amount could be parsed")
        if len(txt) < 40 or (len(txt) < 120 and not txt.rstrip().endswith((".", "”", '"', ")"))):
            add(r, "truncated_source_entry", "low", "entry is very short / cut off in the source PDF; kept as published")
    return issues


def bulletin_issues(reg: pd.DataFrame, diags: dict, df: pd.DataFrame) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    issues = []

    def add(bid, issue, sev, detail):
        issues.append({"review_id": _rid(issue, bid), "issue_type": issue, "severity": sev, "enforcement_id": "",
                       "bulletin_id": bid, "pops_id_candidate": "", "detail": detail, "suggested_candidates": "",
                       "source_pdf": "", "source_page": "", "enforcement_text_excerpt": "", "detected_at": now})

    ids = sorted(b for b in reg["bulletin_id"] if re.match(r"^\d{4}-\d{2}$", b))
    # missing months inside the covered span
    if ids:
        y, m = map(int, ids[0].split("-"))
        yl, ml = map(int, ids[-1].split("-"))
        have = set(ids)
        while (y, m) <= (yl, ml):
            k = f"{y}-{m:02d}"
            if k not in have:
                add(k, "missing_bulletin_month", "medium",
                    "no bulletin for this month appears on the DOB index. DOB may not have published one; absence of "
                    "enforcement data for this month must not be read as absence of enforcement.")
            m += 1
            if m > 12:
                y, m = y + 1, 1
    # duplicate bulletins
    for col, label in (("sha256", "identical PDF content"), ("pdf_url", "same PDF URL")):
        d = reg[reg[col] != ""].groupby(col)["bulletin_id"].apply(list)
        for val, lst in d.items():
            if len(lst) > 1:
                add(",".join(lst), "duplicate_bulletin", "high", f"{label} registered under {lst}")
    for _, r in reg.iterrows():
        bid = r["bulletin_id"]
        if bid.startswith("unparsed:"):
            add(bid, "bulletin_month_unparsed", "high", f"could not derive month/year for {r['pdf_url']}")
            continue
        if r["downloaded"] != "True":
            add(bid, "download_failed", "high", r["processing_errors"] or "PDF not downloaded")
        if r["label_conflict"] == "True":
            add(bid, "index_label_conflict", "low",
                f"index label '{r['index_label']}' disagrees with the filename month; filename used "
                "(confirm against the PDF's own header)")
        if r["filename_pattern_ok"] != "True":
            add(bid, "structure_change_filename", "high", f"PDF filename no longer follows MMYY_enforcement_action_bulletin.pdf: {r['pdf_url']}")
        if r["still_on_index"] == "False":
            add(bid, "bulletin_removed_from_index", "medium", "previously registered bulletin is no longer linked on the DOB index")
        if "pdf_replaced_upstream" in r["processing_errors"]:
            add(bid, "bulletin_replaced_upstream", "medium", "DOB replaced this PDF after we downloaded it; the earlier copy is archived")
    # extraction / structure
    counts = {b: d.get("n_entries", 0) for b, d in diags.items()}
    for bid, d in diags.items():
        if d.get("needs_ocr") or not d.get("has_text_layer", True):
            add(bid, "failed_extraction", "high", "no machine-readable text layer; OCR required and NOT attempted automatically")
            continue
        if d.get("n_entries", 0) == 0:
            add(bid, "failed_extraction", "high", "text extracted but zero enforcement entries were parsed")
        if not d.get("marker_found", True):
            add(bid, "structure_change_marker", "high", "phrase 'individual enforcement highlights' not found; parser fell back to heuristics")
        prev = [counts[k] for k in sorted(counts) if k < bid][-6:]
        if len(prev) >= 3 and d.get("n_entries", 0) > 0:
            med = sorted(prev)[len(prev) // 2]
            if med and (d["n_entries"] < 0.4 * med or d["n_entries"] > 2.5 * med):
                add(bid, "structure_change_entry_count", "medium",
                    f"{d['n_entries']} entries vs median {med} for the previous {len(prev)} bulletins")
        if d.get("empty_bullets"):
            add(bid, "empty_bullets_dropped", "low", f"{d['empty_bullets']} stray bullet glyph(s) with no text were dropped")
    return issues


def index_structure_issues(html_link_count: int, reg: pd.DataFrame) -> list[dict]:
    """Guard against DOB redesigning the index page: finding zero (or far fewer) bulletin links is a hard signal."""
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    known = int((reg["still_on_index"] == "True").sum()) if len(reg) else 0
    if html_link_count == 0 or (known and html_link_count < 0.8 * known):
        return [{"review_id": _rid("index", html_link_count), "issue_type": "structure_change_index", "severity": "high",
                 "enforcement_id": "", "bulletin_id": "", "pops_id_candidate": "",
                 "detail": f"index page yielded {html_link_count} bulletin links vs {known} known; the page layout may have changed",
                 "suggested_candidates": "", "source_pdf": "", "source_page": "", "enforcement_text_excerpt": "", "detected_at": now}]
    return []


def audit_issues(audit: pd.DataFrame) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    out = []
    for _, r in audit[(audit["match_status"] != "matched") | (audit["match_confidence"] != "high")].iterrows():
        out.append({"review_id": _rid("audit", r["audit_row"]), "issue_type": "comptroller_audit_link", "severity": "medium",
                    "enforcement_id": "", "bulletin_id": "", "pops_id_candidate": r["pops_id"] or r["match_candidates"],
                    "detail": f"audit row {r['audit_row']} '{r['audit_address']}' (status {r['audit_status_raw']}): "
                              f"{r['match_status']} via {r['match_method']}/{r['match_confidence']}",
                    "suggested_candidates": "", "source_pdf": "data/raw/comptroller/SR16_102A.pdf",
                    "source_page": r["audit_pdf_page"], "enforcement_text_excerpt": "", "detected_at": now})
    return out


def build_review(df, master, reg, diags, audit=None, index_link_count=None) -> pd.DataFrame:
    issues = record_issues(df, master) + bulletin_issues(reg, diags, df)
    if audit is not None:
        issues += audit_issues(audit)
    if index_link_count is not None:
        issues += index_structure_issues(index_link_count, reg)
    rv = pd.DataFrame(issues, columns=[c for c in REVIEW_COLUMNS if c != "status"] + [])
    from .pipeline import load_decisions
    decided = load_decisions()
    rv["status"] = ["resolved" if e and e in decided else "open" for e in rv["enforcement_id"]]
    rv = rv.reindex(columns=REVIEW_COLUMNS)
    rv["_s"] = rv["severity"].map(SEV)
    rv = rv.sort_values(["_s", "issue_type", "bulletin_id"]).drop(columns="_s")
    config.REVIEW.mkdir(parents=True, exist_ok=True)
    rv.to_csv(config.MANUAL_REVIEW, index=False)
    return rv


def summary(rv: pd.DataFrame) -> dict:
    s = rv.groupby(["issue_type", "severity"]).size().reset_index(name="n")
    return {"total_open_items": int((rv["status"] == "open").sum()),
            "by_issue": {f"{r.issue_type} [{r.severity}]": int(r.n) for r in s.itertuples()}}
