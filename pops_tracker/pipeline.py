"""Orchestrates steps 5-7: parse -> geocode -> detect (A) -> match (B) -> classify -> review overlay -> outputs.

Outputs are a pure function of (raw PDFs, POPS master, geocode cache, review decisions). Re-running never duplicates
records: enforcement IDs are content-derived and the CSV/JSON files are rewritten wholesale.
"""
import datetime as dt
import json

import pandas as pd

from . import address as A
from . import bulletin_parser as P
from . import bulletins as B
from . import classify as C
from . import config
from . import detect as D
from . import extract as X
from . import geocode as G
from . import match as M

REVIEW_DECISIONS = config.REVIEW / "review_decisions.csv"
DECISION_FIELDS = ["enforcement_id", "decision", "pops_id", "reviewer", "note", "decided_at"]
PARSER_VERSION = "0.1.0"

POPS_RELATIONS = {"pops_text_and_property_match", "pops_text_only", "property_match_only"}


def load_decisions() -> dict:
    if not REVIEW_DECISIONS.exists():
        REVIEW_DECISIONS.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=DECISION_FIELDS).to_csv(REVIEW_DECISIONS, index=False)
        return {}
    df = pd.read_csv(REVIEW_DECISIONS, dtype=str, keep_default_na=False)
    return {r["enforcement_id"]: r.to_dict() for _, r in df.iterrows() if r["enforcement_id"]}


def relation(det_tier: str, matched: bool) -> str:
    strong = det_tier in ("strong", "moderate")
    if strong and matched:
        return "pops_text_and_property_match"
    if strong:
        return "pops_text_only"
    if matched:
        return "property_match_only"
    if det_tier == "weak":
        return "weak_keyword_only"
    return "none"


def parse_all(reg: pd.DataFrame):
    """Parse every extracted bulletin. Returns (actions, per-bulletin diagnostics)."""
    actions, diags = [], {}
    for _, r in reg.iterrows():
        tp = X.text_path(r["bulletin_id"])
        if not tp.exists() or r["bulletin_id"].startswith("unparsed:"):
            continue
        ex = json.loads(tp.read_text(encoding="utf-8"))
        if not ex.get("has_text_layer"):
            diags[r["bulletin_id"]] = {"needs_ocr": True, "n_entries": 0, "notes": ["no text layer"], "marker_found": False}
            continue
        acts, d = P.parse_bulletin(r.to_dict(), ex)
        d["extraction_method"] = ex["method"]
        d["n_pages"], d["n_chars"] = ex["n_pages"], ex["n_chars"]
        diags[r["bulletin_id"]] = d
        actions += acts
    return actions, diags


def enrich(actions: list[dict], master: pd.DataFrame, geocode: bool = True) -> pd.DataFrame:
    idx = M.PopsIndex(master)
    want = {(a_["borough"], a_["number"], a_["street"]) for a in actions for a_ in a["_addresses"] if a_["borough"]}
    cache = G.geocode_many(sorted(want)) if geocode else G.load_cache()
    mrec = master.set_index("pops_id")
    decisions = load_decisions()
    rows = []
    for a in actions:
        ev = M._candidates_from_addresses(a["_addresses"], idx, cache)
        m = M.match_action(a, ev, idx)
        det = D.detect(a["enforcement_text"], [x["raw"] for x in A.extract_addresses(a["enforcement_text"])], a["respondent"])
        cls = C.classify(a["enforcement_text"]) if (det["tier"] or m["match_status"] == "matched") else {"categories": [], "terms": {}}
        matched = m["match_status"] == "matched"
        rel = relation(det["tier"], matched)
        row = {k: v for k, v in a.items() if not k.startswith("_")}
        row.update(m)
        row.update(
            pops_keyword_tier=det["tier"], pops_keyword_hits=";".join(det["hits"]), pops_relation=rel,
            violation_category=";".join(cls["categories"]),
            violation_category_terms=json.dumps(cls["terms"], ensure_ascii=False) if cls["terms"] else "",
            geocode_status=";".join(dict.fromkeys(e["geo_status"] for e in ev)) if ev else "no_address",
        )
        # ---- review status: conservative; only text+property agreement at high confidence is auto-confirmed ----
        if rel == "pops_text_and_property_match" and m["match_confidence"] == "high":
            status = "auto_confirmed"
        elif rel in POPS_RELATIONS or rel == "weak_keyword_only" or m["match_status"] == "ambiguous":
            status = "needs_review"
        else:
            status = ""
        d = decisions.get(a["enforcement_id"])
        if d:
            dec = d["decision"].strip().lower()
            if dec in ("confirm", "confirmed", "reassign"):
                status = "reviewed_confirmed"
                if d["pops_id"]:
                    row["pops_id"] = d["pops_id"]
                    row["match_method"] = "manual"
                    row["match_confidence"] = "high"
                    row["match_status"] = "matched"
            elif dec in ("reject", "rejected"):
                status = "reviewed_rejected"
            row["review_note"] = d["note"]
        row["manual_review_status"] = status
        # ---- master fields for matched POPS ----
        pid = row["pops_id"]
        if pid and pid in mrec.index:
            r = mrec.loc[pid]
            row.update(pops_bbl=r["bbl"], pops_bin=r["bin"], pops_address_normalized=r["address_normalized"],
                       pops_borough=r["borough"], pops_latitude=r["latitude"], pops_longitude=r["longitude"],
                       pops_building_name=r["building_name"], pops_type=r["pops_type"],
                       pops_year_established=r["year_established"], pops_required_hours=r["required_hours"])
        rows.append(row)
    df = pd.DataFrame(rows)
    return _flag_duplicates(df)


def _flag_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-bulletin repeats: identical normalised text, or same address+penalty+respondent in different months."""
    df = df.sort_values(["bulletin_year", "bulletin_month", "source_page"]).reset_index(drop=True)
    df["possible_duplicate_of"] = ""
    df["duplicate_basis"] = ""
    first_text, first_sig = {}, {}
    norm = df["enforcement_text"].str.lower().str.replace(r"[^a-z0-9$]+", " ", regex=True).str.strip()
    for i, r in df.iterrows():
        t = norm[i]
        sig = None
        if r["address_raw"] and r["penalty_amount"] != "" and r["respondent"]:
            sig = (A.canonical_street(r["address_street"]), r["address_number"], str(r["penalty_amount"]), r["respondent"].lower())
        if t in first_text and first_text[t][1] != r["bulletin_id"]:
            df.at[i, "possible_duplicate_of"], df.at[i, "duplicate_basis"] = first_text[t][0], "identical_text"
        elif sig and sig in first_sig and first_sig[sig][1] != r["bulletin_id"]:
            df.at[i, "possible_duplicate_of"], df.at[i, "duplicate_basis"] = first_sig[sig][0], "same_address_penalty_respondent"
        first_text.setdefault(t, (r["enforcement_id"], r["bulletin_id"]))
        if sig:
            first_sig.setdefault(sig, (r["enforcement_id"], r["bulletin_id"]))
    return df


def update_registry(reg: pd.DataFrame, actions_df: pd.DataFrame, diags: dict) -> pd.DataFrame:
    reg = reg.set_index("bulletin_id", drop=False)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    for bid, d in diags.items():
        sub = actions_df[actions_df.bulletin_id == bid] if len(actions_df) else actions_df
        was_parsed = reg.at[bid, "parsed"] == "True" and bool(reg.at[bid, "parsed_at"])
        reg.at[bid, "parsed"] = "False" if d.get("needs_ocr") else "True"
        if not was_parsed:   # first-parse time; keeps weekly diffs quiet
            reg.at[bid, "parsed_at"] = now
        reg.at[bid, "extraction_method"] = d.get("extraction_method", "needs_ocr")
        reg.at[bid, "page_count"] = str(d.get("n_pages", ""))
        reg.at[bid, "text_chars"] = str(d.get("n_chars", ""))
        reg.at[bid, "has_text_layer"] = str(not d.get("needs_ocr", False))
        reg.at[bid, "n_enforcement_actions"] = str(len(sub))
        reg.at[bid, "n_potential_pops_matches"] = str(int(sub["pops_relation"].isin(POPS_RELATIONS).sum())) if len(sub) else "0"
        errs = [n for n in d.get("notes", []) if not n.startswith("orphan line")]
        if not d.get("marker_found", True):
            errs.append("structure_marker_missing")
        base = [e for e in reg.at[bid, "processing_errors"].split("; ") if e and e.split(":")[0] in ("download_failed", "pdf_replaced_upstream") or e.startswith("url_changed")]
        reg.at[bid, "processing_errors"] = "; ".join(base + errs)
    reg = reg.reset_index(drop=True)
    B.save_registry(reg)
    return reg


OUTPUT_COLUMNS = [
    "enforcement_id", "pops_id", "pops_bbl", "pops_bin", "pops_address_normalized", "pops_borough", "pops_latitude",
    "pops_longitude", "pops_building_name", "pops_type", "pops_year_established", "pops_required_hours",
    "respondent", "respondent_role", "bulletin_month", "bulletin_year", "enforcement_date", "violation_category",
    "violation_description", "penalty_amount", "enforcement_text", "pdf_url", "source_pdf", "source_page",
    "match_method", "match_confidence", "match_score", "match_status", "match_notes", "pops_relation",
    "pops_keyword_tier", "pops_keyword_hits", "manual_review_status", "review_note", "possible_duplicate_of",
    "duplicate_basis", "violation_category_terms", "bulletin_id", "address_raw", "borough", "geocoded_bbl", "geocoded_bin",
]


def export(actions_df: pd.DataFrame):
    config.PROCESSED.mkdir(parents=True, exist_ok=True)
    actions_df.to_csv(config.ENFORCEMENT_ALL, index=False)
    pops = actions_df[actions_df["pops_relation"].isin(POPS_RELATIONS) & (actions_df["manual_review_status"] != "reviewed_rejected")].copy()
    for c in OUTPUT_COLUMNS:
        if c not in pops.columns:
            pops[c] = ""
    pops = pops[OUTPUT_COLUMNS].rename(columns={"respondent": "owner", "respondent_role": "owner_role_as_stated",
                                                "pops_bbl": "bbl", "pops_bin": "bin", "pops_address_normalized": "normalized_address",
                                                "pops_borough": "pops_borough_master", "pops_latitude": "latitude",
                                                "pops_longitude": "longitude", "pops_building_name": "building_name"})
    pops.to_csv(config.ENFORCEMENT_POPS, index=False)
    records = json.loads(pops.fillna("").to_json(orient="records"))
    (config.PROCESSED / "pops_enforcement.json").write_text(json.dumps(records, indent=1, ensure_ascii=False), encoding="utf-8")
    return pops
