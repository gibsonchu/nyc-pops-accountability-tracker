"""One row per POPS: requirements + 2017 audit outcome + DOB-bulletin enforcement counts.

Counting rules (also in METHODOLOGY.md):
  confirmed_pops_violation_count : bulletin actions that both use POPS wording AND match this POPS, status auto_confirmed or
                                   reviewed_confirmed (or manually reassigned/confirmed).
  property_only_action_count     : bulletin actions at this property that do not mention POPS (building-level, unreviewed).
  needs_review_count             : actions linked to this POPS that still await human review.
Absence of any count is NOT evidence of compliance.
"""
import json

import pandas as pd

from . import config

OUT = config.PROCESSED / "pops_accountability.csv"


def build(master: pd.DataFrame, enforcement_all: pd.DataFrame, audit: pd.DataFrame) -> pd.DataFrame:
    e = enforcement_all[(enforcement_all["pops_id"] != "") & (enforcement_all["manual_review_status"] != "reviewed_rejected")].copy()
    e["penalty_num"] = pd.to_numeric(e["penalty_amount"], errors="coerce")
    e["ym"] = e["bulletin_year"].astype(int).astype(str) + "-" + e["bulletin_month"].astype(int).map("{:02d}".format)
    confirmed_mask = e["manual_review_status"].isin(["auto_confirmed", "reviewed_confirmed"]) & (e["pops_relation"] == "pops_text_and_property_match")
    # post-audit window: audit released 2017-04-18; DOB's first bulletin is 2017-12, so every bulletin is post-audit.
    post = e["ym"] >= "2017-04"

    g_conf = e[confirmed_mask].groupby("pops_id")
    g_prop = e[e["pops_relation"] == "property_match_only"].groupby("pops_id")
    g_rev = e[e["manual_review_status"] == "needs_review"].groupby("pops_id")
    g_post = e[confirmed_mask & post].groupby("pops_id")
    g_any = e.groupby("pops_id")

    acc = master[["pops_id", "borough", "address_normalized", "building_name", "bbl", "bin", "latitude", "longitude", "pops_type",
                  "year_established", "required_hours", "required_size", "required_amenities", "other_requirements"]].copy()
    m = lambda s: acc["pops_id"].map(s)
    acc["confirmed_pops_violation_count"] = m(g_conf.size()).fillna(0).astype(int)
    acc["post_2017_dob_enforcement_count"] = m(g_post.size()).fillna(0).astype(int)
    acc["property_only_action_count"] = m(g_prop.size()).fillna(0).astype(int)
    acc["needs_review_count"] = m(g_rev.size()).fillna(0).astype(int)
    acc["any_linked_bulletin_action_count"] = m(g_any.size()).fillna(0).astype(int)
    acc["confirmed_penalties_total"] = m(g_conf["penalty_num"].sum()).fillna(0).astype(int)
    acc["latest_enforcement_date"] = m(g_conf["ym"].max()).fillna("")            # bulletin month; DOB gives no exact date
    acc["latest_enforcement_date_precision"] = acc["latest_enforcement_date"].map(lambda v: "bulletin_month" if v else "")
    acc["enforcement_ids_confirmed"] = m(g_conf["enforcement_id"].apply(";".join)).fillna("")

    a = audit[audit["pops_id"] != ""].drop_duplicates("pops_id").set_index("pops_id")
    acc["comptroller_2017_inspected"] = acc["pops_id"].isin(a.index)
    acc["comptroller_2017_compliant"] = acc["pops_id"].map(a["comptroller_2017_compliant"]).fillna("")   # yes|no|construction|'' (not listed)
    acc["comptroller_2017_findings"] = acc["pops_id"].map(a["comptroller_2017_findings"]).fillna("")
    acc["comptroller_2017_audit_row"] = acc["pops_id"].map(a["audit_row"]).fillna("")
    acc["comptroller_2017_match_confidence"] = acc["pops_id"].map(a["match_confidence"]).fillna("")
    acc["evidence_note"] = ("Bulletins highlight selected enforcement only; a zero count is not evidence of compliance.")
    acc.to_csv(OUT, index=False)
    (config.PROCESSED / "pops_accountability.json").write_text(
        json.dumps(json.loads(acc.fillna("").to_json(orient="records")), indent=1, ensure_ascii=False), encoding="utf-8")
    return acc
