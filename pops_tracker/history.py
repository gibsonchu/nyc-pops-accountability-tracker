"""Step 9: build a SQLite database realising the schema in data/schema/pops_history.sql from the Phase 1 outputs.

The point is to prove the model can hold one POPS' full history now (agreement -> requirements -> audit -> enforcement)
with the FUTURE tables (inspections, 311, modifications, building records) present and empty, ready for loaders.
"""
import sqlite3

import pandas as pd

from . import config
from .comptroller import AUDIT_DATE, AUDIT_ID, AUDIT_PDF_URL

DDL = config.DATA / "schema" / "pops_history.sql"
DB = config.PROCESSED / "pops_tracker.sqlite"


def build(master: pd.DataFrame, enforcement: pd.DataFrame, audit: pd.DataFrame):
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(DDL.read_text(encoding="utf-8"))
    src = [("dcp_pops", "dcp_pops", "DCP POPS dataset (NYC Open Data rvih-nhyn)", master["source_dataset_url"].iloc[0],
            master["source_retrieved_at"].iloc[0], master["source_sha256"].iloc[0], "data/raw/pops/"),
           (AUDIT_ID, "comptroller_audit", "Comptroller audit of POPS oversight", AUDIT_PDF_URL, "", "", "data/raw/comptroller/SR16_102A.pdf")]
    for bid in sorted(set(enforcement["bulletin_id"])):
        src.append((f"dob_bulletin_{bid}", "dob_bulletin", f"DOB Monthly Enforcement Action Bulletin {bid}",
                    enforcement.loc[enforcement.bulletin_id == bid, "pdf_url"].iloc[0], "", "", enforcement.loc[enforcement.bulletin_id == bid, "source_pdf"].iloc[0]))
    con.executemany("INSERT INTO source_document VALUES (?,?,?,?,?,?,?)", src)

    site_cols = ["pops_id", "borough", "address_normalized", "bbl", "bin", "latitude", "longitude", "building_name", "pops_type",
                 "year_established", "developer"]
    s = master[site_cols].copy()
    s["year_established"] = pd.to_numeric(s["year_established"], errors="coerce")
    for c in ("latitude", "longitude"):
        s[c] = pd.to_numeric(s[c], errors="coerce")
    s["current_status_note"] = ""
    s["source_id"] = "dcp_pops"
    s.astype(object).where(s.notna(), None).to_sql("pops_site", con, if_exists="append", index=False)

    reqs = []
    for _, r in master.iterrows():
        for typ, col in (("required_hours", "required_hours"), ("required_size", "required_size"),
                         ("required_amenity", "required_amenities"), ("other_required", "other_requirements"),
                         ("permitted_amenity", "permitted_amenities_text")):
            if r[col].strip():
                reqs.append((r["pops_id"], typ, r[col].strip(), None, None, "dcp_pops"))
    con.executemany("INSERT INTO pops_requirement(pops_id,requirement_type,value_text,valid_from,valid_to,source_id) VALUES (?,?,?,?,?,?)", reqs)

    e = enforcement[enforcement["pops_id"] != ""]
    for _, r in e.iterrows():
        con.execute("INSERT INTO enforcement_action VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            r["enforcement_id"], r["pops_id"], int(r["bulletin_year"]), int(r["bulletin_month"]), r["enforcement_date"] or None,
            r["owner"], int(float(r["penalty_amount"])) if r["penalty_amount"] != "" else None, r["violation_category"],
            r["violation_description"], r["enforcement_text"], r["pops_relation"], r["match_method"], r["match_confidence"],
            r["manual_review_status"], r["source_pdf"], int(r["source_page"]), r["pdf_url"]))
    a = audit
    for _, r in a.iterrows():
        con.execute("INSERT INTO comptroller_audit VALUES (?,?,?,?,?,?,?,?,?,?)", (
            int(r["audit_row"]), AUDIT_ID, AUDIT_DATE, r["audit_address"], r["audit_status_raw"], r["pops_id"] or None,
            r["match_method"], r["match_confidence"], r["comptroller_2017_findings"] or None, int(r["audit_pdf_page"])))

    ev = []
    for _, r in master[master["year_established"] != ""].iterrows():
        ev.append((r["pops_id"], "agreement", r["year_established"], "year",
                   f"Building completed {r['year_established']}; POPS type: {r['pops_type']}. (DCP records completion year, not the agreement date.)",
                   "pops_site", r["pops_id"], "dcp_pops", "high"))
    for _, r in a[a["pops_id"] != ""].iterrows():
        ev.append((r["pops_id"], "audit_inspection", "2016", "year",
                   f"Comptroller audit {AUDIT_ID}: full compliance as printed = {r['audit_status_raw']}", "comptroller_audit",
                   str(r["audit_row"]), AUDIT_ID, r["match_confidence"]))
    for _, r in e.iterrows():
        conf = "high" if r["manual_review_status"] in ("auto_confirmed", "reviewed_confirmed") else "needs_review"
        ev.append((r["pops_id"], "enforcement", f"{int(r['bulletin_year'])}-{int(r['bulletin_month']):02d}", "month",
                   f"[{r['pops_relation']}] {r['violation_category'] or 'uncategorised'}; ${r['penalty_amount'] or '?'}; {r['enforcement_text'][:140]}",
                   "enforcement_action", r["enforcement_id"], f"dob_bulletin_{r['bulletin_id']}", conf))
    con.executemany("INSERT INTO pops_event(pops_id,event_type,event_date,event_date_precision,summary,source_table,source_key,source_id,confidence) VALUES (?,?,?,?,?,?,?,?,?)", ev)
    con.commit()
    n = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
         ("pops_site", "pops_requirement", "enforcement_action", "comptroller_audit", "pops_event", "dob_inspection", "complaint_311", "pops_modification", "building_record")}
    con.close()
    return n
