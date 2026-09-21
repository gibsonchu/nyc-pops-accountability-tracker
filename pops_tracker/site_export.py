"""Build the static site's data files (site/data/*) from the processed dataset.

The site is plain static files so Vercel can serve it with no build step: this exporter runs in the weekly job, the
result is committed, and the push redeploys. Evidence tiers are exported explicitly so the page can never blur
"confirmed POPS violation" with "another DOB action at a POPS building".
"""
import json
import shutil

import pandas as pd

from . import analysis, config

SITE = config.ROOT / "site"
DATA = SITE / "data"
DOWNLOADS = ["pops_enforcement.csv", "pops_enforcement.json", "pops_master.csv", "pops_accountability.csv",
             "comptroller_2017_audit.csv", "enforcement_actions_all.csv"]
DISCLAIMER = ("Enforcement records shown here come from DOB's Monthly Enforcement Action Bulletins, which highlight selected "
              "enforcement activity. No enforcement record does not necessarily mean that a POPS is compliant.")


def _tier(r) -> str:
    if r["manual_review_status"] == "reviewed_rejected":
        return ""
    if r["pops_relation"] == "pops_text_and_property_match":
        return "confirmed" if r["manual_review_status"] in ("auto_confirmed", "reviewed_confirmed") else "pending"
    if r["pops_relation"] == "property_match_only":
        return "property_only"
    return ""


def build() -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "download").mkdir(exist_ok=True)
    master = pd.read_csv(config.POPS_MASTER, dtype=str, keep_default_na=False)
    acc = pd.read_csv(config.PROCESSED / "pops_accountability.csv", dtype=str, keep_default_na=False).set_index("pops_id")
    x = pd.read_csv(config.ENFORCEMENT_ALL, dtype=str, keep_default_na=False)
    x["tier"] = x.apply(_tier, axis=1)
    linked = x[(x["pops_id"] != "") & (x["tier"] != "")].sort_values(["bulletin_year", "bulletin_month"], ascending=False)

    by_pops = {}
    for _, r in linked.iterrows():
        by_pops.setdefault(r["pops_id"], []).append({
            "id": r["enforcement_id"], "tier": r["tier"], "y": int(r["bulletin_year"]), "m": int(r["bulletin_month"]),
            "cat": [c for c in r["violation_category"].split(";") if c], "pen": int(float(r["penalty_amount"])) if r["penalty_amount"] else None,
            "who": r["respondent"], "text": r["enforcement_text"], "pdf": r["pdf_url"], "page": int(r["source_page"]),
            "how": f"{r['match_method']} / {r['match_confidence']}", "dup": bool(r["possible_duplicate_of"]),
        })

    pops = []
    for _, m in master.iterrows():
        a = acc.loc[m["pops_id"]]
        ev = by_pops.get(m["pops_id"], [])
        pops.append({
            "id": m["pops_id"], "addr": m["building_address_with_zip"], "name": m["building_name"], "boro": m["borough"],
            "lat": float(m["latitude"]) if m["latitude"] else None, "lon": float(m["longitude"]) if m["longitude"] else None,
            "type": m["pops_type"], "year": m["year_established"], "dev": m["developer"], "bbl": m["bbl"], "bin": m["bin"],
            "hours": m["required_hours"], "size": m["required_size"], "amen": m["required_amenities"],
            "other": m["other_requirements"], "perm": m["permitted_amenities_text"], "access": m["physically_disabled"],
            "flags": [f for f in m["data_quality_flags"].split(";") if f],
            "audit": {"inspected": a["comptroller_2017_inspected"] == "True", "status": a["comptroller_2017_compliant"],
                      "findings": a["comptroller_2017_findings"]},
            "n_conf": sum(e["tier"] == "confirmed" for e in ev), "n_pend": sum(e["tier"] == "pending" for e in ev),
            "n_prop": sum(e["tier"] == "property_only" for e in ev),
            "pen": sum((e["pen"] or 0) for e in ev if e["tier"] == "confirmed"), "e": ev,
        })
    (DATA / "pops.json").write_text(json.dumps(pops, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    o = analysis.run()
    analysis.write_report(o)
    t = o["tables"]
    reg = pd.read_csv(config.BULLETIN_REGISTRY, dtype=str, keep_default_na=False)
    rv = pd.read_csv(config.MANUAL_REVIEW, dtype=str, keep_default_na=False)
    summary = {
        "disclaimer": DISCLAIMER, "res": o["res"], "generated": pd.Timestamp.utcnow().strftime("%Y-%m-%d"),
        "by_year": json.loads(t["by_year"].reset_index().rename(columns={"index": "year"}).to_json(orient="records")),
        "categories": json.loads(t["cat"].to_json(orient="records")),
        "audit": json.loads(t["audit"].to_json(orient="records")),
        "latest_bulletin": reg["bulletin_id"].max(), "n_open_review": int((rv["status"] == "open").sum()),
        "missing_months": rv[rv["issue_type"] == "missing_bulletin_month"]["bulletin_id"].tolist(),
    }
    (DATA / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    for f in DOWNLOADS:
        shutil.copy(config.PROCESSED / f, DATA / "download" / f)
    shutil.copy(config.ROOT / "METHODOLOGY.md", DATA / "METHODOLOGY.md")
    shutil.copy(config.REPORTS / "analysis.md", DATA / "analysis.md")
    shutil.copy(config.REPORTS / "data_quality_report.md", DATA / "data_quality_report.md")
    return {"pops": len(pops), "with_confirmed": sum(p["n_conf"] > 0 for p in pops)}
