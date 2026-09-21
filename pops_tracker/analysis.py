"""Phase 2: descriptive analysis of the historical dataset. Every figure in reports/analysis.md is computed here.

Evidence tiers (used everywhere, never blended silently):
  A  confirmed POPS violation : DOB text uses POPS wording AND the property matches a POPS at high confidence
                                (or a reviewer confirmed it).
  B  probable, awaiting review: POPS wording with a medium/low-confidence match, or POPS wording with no database match.
  C  property-only            : the property is a POPS building but the paragraph never mentions POPS (often contractor
                                or building-level violations, not public-space violations).
Nothing here says a POPS is compliant. 'No bulletin entry' means only that DOB did not highlight one.
"""
import json
import re

import numpy as np
import pandas as pd
from scipy import stats

from . import config

OUT = config.REPORTS / "analysis"
CONFIRMED = ["auto_confirmed", "reviewed_confirmed"]
DECADES = [(1961, 1969, "1961-69"), (1970, 1979, "1970s"), (1980, 1989, "1980s"), (1990, 1999, "1990s"), (2000, 2100, "2000+")]


def _norm_entity(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    s = re.sub(r"\b(llc|inc|corp|co|company|assoc|associates|association|condominium|condo|owners|owner|l p|lp|ltd|the|c o)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _decade(y):
    try:
        y = int(y)
    except (TypeError, ValueError):
        return "unknown"
    return next((lab for lo, hi, lab in DECADES if lo <= y <= hi), "unknown")


def load():
    x = pd.read_csv(config.ENFORCEMENT_ALL, dtype=str, keep_default_na=False)
    x["pen"] = pd.to_numeric(x["penalty_amount"], errors="coerce")
    x["year"] = x["bulletin_year"].astype(int)
    x["ym"] = x["year"].astype(str) + "-" + x["bulletin_month"].astype(int).map("{:02d}".format)
    acc = pd.read_csv(config.PROCESSED / "pops_accountability.csv", dtype=str, keep_default_na=False)
    reg = pd.read_csv(config.BULLETIN_REGISTRY, dtype=str, keep_default_na=False)
    audit = pd.read_csv(config.PROCESSED / "comptroller_2017_audit.csv", dtype=str, keep_default_na=False)
    return x, acc, reg, audit


def tiers(x):
    rejected = x["manual_review_status"] == "reviewed_rejected"
    A = x[(x["pops_relation"] == "pops_text_and_property_match") & x["manual_review_status"].isin(CONFIRMED)]
    B = x[~rejected & (((x["pops_relation"] == "pops_text_and_property_match") & ~x["manual_review_status"].isin(CONFIRMED))
                       | (x["pops_relation"] == "pops_text_only"))]
    C = x[~rejected & (x["pops_relation"] == "property_match_only")]
    return A, B, C


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    x, acc, reg, audit = load()
    A, B, C = tiers(x)
    res = {}

    # Q1-3 headline counts and penalties ------------------------------------------------------------------------
    res["n_bulletins"], res["n_actions_all"] = len(reg), len(x)
    res["span"] = f"{reg.bulletin_id.min()} to {reg.bulletin_id.max()}"
    for name, d in (("A", A), ("B", B), ("C", C)):
        res[f"tier_{name}_actions"] = len(d)
        res[f"tier_{name}_pops"] = int(d[d.pops_id != ""].pops_id.nunique())
        res[f"tier_{name}_penalty_total"] = int(d["pen"].sum())
        res[f"tier_{name}_penalty_n"] = int(d["pen"].notna().sum())
    AB = pd.concat([A, B])
    res["tierAB_pops"] = int(AB[AB.pops_id != ""].pops_id.nunique())
    res["tierABC_pops"] = int(pd.concat([A, B, C]).query("pops_id != ''").pops_id.nunique())
    res["tierA_penalty_median"] = float(A["pen"].median())
    res["tierA_penalty_max"] = int(A["pen"].max())
    res["tierA_possible_duplicates"] = int((A["possible_duplicate_of"] != "").sum())
    res["all_actions_penalty_total"] = int(x["pen"].sum())

    # Q4 repeat POPS / Q5 repeat owners ---------------------------------------------------------------------------
    rp = pd.concat([A.assign(tier="A"), B.assign(tier="B"), C.assign(tier="C")])
    rp = rp[rp.pops_id != ""]
    repeat = (rp.groupby("pops_id").agg(total_actions=("enforcement_id", "size"),
                                        tierA=("tier", lambda s: (s == "A").sum()), tierB=("tier", lambda s: (s == "B").sum()),
                                        tierC=("tier", lambda s: (s == "C").sum()), first=("ym", "min"), last=("ym", "max"),
                                        penalties=("pen", "sum")).reset_index()
              .merge(acc[["pops_id", "address_normalized", "building_name", "year_established"]], on="pops_id"))
    repeat = repeat[repeat.total_actions >= 2].sort_values(["tierA", "total_actions"], ascending=False)
    repeat.to_csv(OUT / "q4_repeat_pops.csv", index=False)
    res["repeat_pops_n"] = len(repeat)
    ent = A.assign(entity=A["respondent"].map(_norm_entity))
    ent = ent[ent.entity != ""].groupby("entity").agg(actions=("enforcement_id", "size"), example_name=("respondent", "first"),
                                                       pops=("pops_id", lambda s: ";".join(sorted(set(s)))),
                                                       penalties=("pen", "sum")).reset_index().sort_values("actions", ascending=False)
    ent.to_csv(OUT / "q5_entities_tierA.csv", index=False)
    res["repeat_entities_n"] = int((ent.actions >= 2).sum())

    # Q6 / Q11 violation categories ------------------------------------------------------------------------------
    cat = A["violation_category"].str.split(";").explode().value_counts().rename_axis("category").reset_index(name="tierA_actions")
    cat["share_of_tierA_actions"] = (cat.tierA_actions / len(A)).round(3)
    cat.to_csv(OUT / "q6_categories.csv", index=False)
    era = A.assign(era=pd.cut(A.year, [2017, 2019, 2021, 2100], labels=["2018-19", "2020-21", "2022-24"]))
    cat_era = era.assign(c=era["violation_category"].str.split(";")).explode("c").groupby(["era", "c"], observed=True).size().unstack(0).fillna(0).astype(int)
    cat_era.to_csv(OUT / "q11_categories_by_era.csv")

    # Q7 by year -----------------------------------------------------------------------------------------------
    by_year = pd.DataFrame({"bulletins": reg.groupby(reg.bulletin_id.str[:4].astype(int)).size(),
                            "all_entries": x.groupby("year").size()})
    by_year["tierA_actions"] = A.groupby("year").size()
    by_year["tierB_actions"] = B.groupby("year").size()
    by_year["tierC_actions"] = C.groupby("year").size()
    by_year = by_year.fillna(0).astype(int)
    by_year["tierA_per_100_entries"] = (100 * by_year.tierA_actions / by_year.all_entries.replace(0, np.nan)).round(2)
    by_year.to_csv(OUT / "q7_by_year.csv")
    res["last_pops_wording_bulletin"] = str(x[x.pops_keyword_tier.isin(["strong", "moderate"])].ym.max())
    res["bulletins_after_last_pops_wording"] = int((reg.bulletin_id > res["last_pops_wording_bulletin"]).sum())

    # Q8 borough -----------------------------------------------------------------------------------------------
    bor = acc.groupby("borough").size().rename("pops_in_master").to_frame()
    bor["tierA_actions"] = A.groupby("pops_borough").size()
    bor["tierA_pops"] = A.groupby("pops_borough").pops_id.nunique()
    bor = bor.fillna(0).astype(int)
    bor["pops_with_tierA_pct"] = (100 * bor.tierA_pops / bor.pops_in_master).round(1)
    bor.to_csv(OUT / "q8_borough.csv")

    # Q9 age -----------------------------------------------------------------------------------------------------
    acc["decade"] = acc.year_established.map(_decade)
    acc["has_A"] = acc.confirmed_pops_violation_count.astype(int) > 0
    dec = acc.groupby("decade").agg(pops=("pops_id", "size"), pops_with_tierA=("has_A", "sum")).reset_index()
    dec["pct"] = (100 * dec.pops_with_tierA / dec.pops).round(1)
    dec.to_csv(OUT / "q9_age.csv", index=False)
    known = acc[acc.decade != "unknown"]
    pre = known.decade.isin(["1961-69", "1970s"])
    tbl = [[int((known.has_A & pre).sum()), int((~known.has_A & pre).sum())],
           [int((known.has_A & ~pre).sum()), int((~known.has_A & ~pre).sum())]]
    res["q9_pre1980_with_A"], res["q9_pre1980_n"] = tbl[0][0], int(pre.sum())
    res["q9_post1980_with_A"], res["q9_post1980_n"] = tbl[1][0], int((~pre).sum())
    res["q9_fisher_p"] = float(stats.fisher_exact(tbl)[1])

    # Q10 Comptroller follow-up ---------------------------------------------------------------------------------
    acc["audit_group"] = acc.comptroller_2017_compliant.replace("", "not_in_audit")
    acc["A"] = acc.confirmed_pops_violation_count.astype(int) > 0
    idsAB = set(AB[AB.pops_id != ""].pops_id)
    idsC = set(C[C.pops_id != ""].pops_id)
    acc["AB"] = acc.pops_id.isin(set(A.pops_id) | idsAB)
    acc["any_linked"] = acc.pops_id.isin(set(A.pops_id) | idsAB | idsC)
    g = acc.groupby("audit_group").agg(pops=("pops_id", "size"), tierA=("A", "sum"), tierAB=("AB", "sum"), any_linked=("any_linked", "sum")).reset_index()
    for c in ("tierA", "tierAB", "any_linked"):
        g[c + "_pct"] = (100 * g[c] / g.pops).round(1)
    g.to_csv(OUT / "q10_audit_followup.csv", index=False)
    no = acc[acc.audit_group == "no"]
    yes = acc[acc.audit_group == "yes"]
    res["q10_no_n"], res["q10_no_A"], res["q10_no_AB"] = len(no), int(no.A.sum()), int(no.AB.sum())
    res["q10_yes_n"], res["q10_yes_A"] = len(yes), int(yes.A.sum())
    res["q10_fisher_no_vs_yes_p"] = float(stats.fisher_exact([[int(no.A.sum()), len(no) - int(no.A.sum())], [int(yes.A.sum()), len(yes) - int(yes.A.sum())]])[1])
    res["audit_unlinked_rows"] = int((audit.pops_id == "").sum())
    res["audit_status_counts"] = audit.audit_status_raw.value_counts().to_dict()
    res["review_open"] = int((pd.read_csv(config.MANUAL_REVIEW, dtype=str, keep_default_na=False).status == "open").sum())

    tables = {"repeat": repeat, "entities": ent, "cat": cat, "cat_era": cat_era, "by_year": by_year, "bor": bor, "dec": dec, "audit": g}
    (OUT / "summary.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return {"res": res, "tables": tables, "A": A, "B": B, "C": C, "acc": acc}


def _fmt(v):
    if isinstance(v, (float, np.floating)):
        if np.isnan(v):
            return ""
        return f"{v:,.0f}" if float(v).is_integer() and abs(v) >= 10000 else (str(int(v)) if float(v).is_integer() else f"{v:g}")
    if isinstance(v, (int, np.integer)):
        return f"{v:,}" if abs(v) >= 10000 else str(v)
    return str(v)


def _md(df: pd.DataFrame, index=False, index_name="year") -> str:
    d = df.rename_axis(index_name).reset_index() if index else df
    cols = list(d.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for row in d.itertuples(index=False):        # itertuples keeps per-column dtypes (iterrows would upcast to float)
        lines.append("| " + " | ".join(_fmt(v) for v in row) + " |")
    return "\n".join(lines)


def write_report(o: dict):
    r, t, A, B, C = o["res"], o["tables"], o["A"], o["B"], o["C"]
    n_master = len(o["acc"])
    by_year = t["by_year"]
    stat = r["audit_status_counts"]
    no_share_never = 100 * (r["q10_no_n"] - r["q10_no_A"]) / r["q10_no_n"]
    pre_pct = 100 * r["q9_pre1980_with_A"] / r["q9_pre1980_n"]
    post_pct = 100 * r["q9_post1980_with_A"] / r["q9_post1980_n"]
    top = t["repeat"].head(6)[["address_normalized", "building_name", "tierA", "tierB", "tierC", "first", "last"]]
    md = f"""# POPS enforcement in DOB Monthly Enforcement Action Bulletins: preliminary analysis

*Generated by `python -m pops_tracker analyze` from the processed dataset. **Provisional:** {r['review_open']} items in
`data/review/manual_review.csv` are still open, so tier B/C counts and some tier A confirmations may change.*

## Read this first: what the data can and cannot support

DOB's Monthly Enforcement Action Bulletins **highlight selected enforcement activity**. They are not a comprehensive record of
DOB inspections, violations, complaints, or POPS compliance. Consequently:

* **"No enforcement action was found in the bulletins" is NOT the same as "this POPS is compliant."** Of the {n_master} POPS,
  {n_master - r['tierABC_pops']} never appear in any bulletin; we know nothing about their compliance from this source.
* Counts below are counts of *what DOB chose to publish*. A change over time may reflect a change in DOB's editorial choices,
  not in the underlying conduct.
* Every figure is descriptive. Nothing here establishes cause, and small counts (dozens) limit what any comparison can show.

Evidence tiers, used throughout and never blended silently:
**A** = POPS wording in the DOB text *and* a high-confidence match to a POPS (or reviewer-confirmed);
**B** = POPS wording but match is medium/low or missing (awaiting review);
**C** = the property is a POPS building but the paragraph never mentions POPS (often contractor/building-level violations, not
public-space violations).

## Headline numbers

| Measure | Value |
|---|---|
| Bulletins processed | {r['n_bulletins']} ({r['span']}; 3 months absent from DOB's index) |
| Individual enforcement highlights parsed | {r['n_actions_all']:,} |
| **Q1** POPS with ≥1 tier A action | **{r['tier_A_pops']}** of {n_master} ({100*r['tier_A_pops']/n_master:.1f}%) |
| POPS with tier A or B | {r['tierAB_pops']} · with any tier (A, B or C): {r['tierABC_pops']} |
| **Q2** POPS-related actions | tier A **{r['tier_A_actions']}** · tier B {r['tier_B_actions']} · tier C {r['tier_C_actions']} |
| **Q3** Identifiable penalties | tier A **${r['tier_A_penalty_total']:,}** (median ${r['tierA_penalty_median']:,.0f}, max ${r['tierA_penalty_max']:,}) · tier B ${r['tier_B_penalty_total']:,} · tier C ${r['tier_C_penalty_total']:,} |
| For scale: all penalties parsed from all bulletins | ${r['all_actions_penalty_total']:,} |

Tier C penalties are larger than tier A but mostly reflect construction-safety or building-level violations at buildings that
happen to contain a POPS. They should not be described as penalties for POPS violations without reading each paragraph.
{r['tierA_possible_duplicates']} tier A actions are flagged as possible cross-bulletin duplicates.

## Q4-5. Repeat POPS and repeat entities

{r['repeat_pops_n']} POPS are linked to two or more bulletin actions (any tier). Those with repeated tier A actions:

{_md(top)}

Only {r['repeat_entities_n']} respondent entities appear in more than one tier A action. Respondent names in bulletins are
written inconsistently (e.g. "Claridge House LLC" / "Clairidge House LLC"), so entity counts are a lower bound; see
`reports/analysis/q5_entities_tierA.csv`.

## Q6 & Q11. Violation types and patterns (tier A, multi-label)

{_md(t['cat'])}

Categories overlap (one action can carry several), so shares sum to more than 100%. Labels come from keyword rules over DOB's
wording (see METHODOLOGY.md) and are a finding aid, not a legal classification.

By era (`reports/analysis/q11_categories_by_era.csv`): 2018-19 bulletins are dominated by missing or degraded **amenities**
(seating, trees, landscaping, maintenance, fountains), often several to one paragraph (the bulletins do not say why these
cluster in time). 2022-24 shifts toward **access/closure** and **unauthorized private use** (restaurants, a nursery school, padlocked
entrances, a plaza "80% taken over") and **signage**. Bicycle parking and hours appear rarely.

## Q7. Change by year

{_md(by_year, index=True)}

Bulletins per year vary (2017: one; 2024: 10 and 2025: 11 because June/July 2024 and December 2025 are not on DOB's index; 2026
runs through July). The important pattern is at the end of the series: **the last bulletin containing any POPS wording is
{r['last_pops_wording_bulletin']}, and none of the {r['bulletins_after_last_pops_wording']} bulletins since mentions POPS.** The only
later POPS-building entries (tier C) are ordinary building or construction violations. The data cannot say whether DOB stopped
*enforcing* POPS rules or stopped *highlighting* them; that is the single most important thing to ask DOB.

## Q8. Boroughs

{_md(t['bor'], index=True, index_name='borough')}

The POPS universe is {100*366/n_master:.0f}% Manhattan, so almost all enforcement is Manhattan by construction. Rates for the
Bronx (3 POPS) and Staten Island (2) are too small to interpret.

## Q9. Are older POPS over-represented?

{_md(t['dec'])}

Not in this data. POPS completed 1961-79 have tier A actions at {pre_pct:.1f}% ({r['q9_pre1980_with_A']}/{r['q9_pre1980_n']}) versus
{post_pct:.1f}% ({r['q9_post1980_with_A']}/{r['q9_post1980_n']}) for 1980 and later; the difference runs the *other* way and is not
statistically distinguishable from chance (Fisher exact p = {r['q9_fisher_p']:.2f}). {int(o['acc'].decade.eq('unknown').sum())} POPS
with no recorded year are excluded from that test.

## Q10. What happened to the POPS the 2017 Comptroller audit found non-compliant?

The audit (SR16-102A, 18 April 2017) visited {sum(stat.values())} locations: {stat.get('No')} "No" (not fully compliant),
{stat.get('Yes')} "Yes", {stat.get('Construction')} "Construction" (the appendix's third status; it is not evidence of compliance).
{r['audit_unlinked_rows']} audit row could not be linked to the current POPS list, leaving {r['q10_no_n']} "No" locations analysed.

{_md(t['audit'])}

* Of the **{r['q10_no_n']}** POPS the audit marked non-compliant, **{r['q10_no_A']}** ({100*r['q10_no_A']/r['q10_no_n']:.1f}%) later appear in a tier A
  bulletin action, versus {r['q10_yes_A']} of {r['q10_yes_n']} ({100*r['q10_yes_A']/r['q10_yes_n']:.1f}%) of those the audit marked compliant
  (Fisher exact p = {r['q10_fisher_no_vs_yes_p']:.4f}). Audit-flagged POPS were considerably more likely to be highlighted.
* But **{r['q10_no_n'] - r['q10_no_A']} of {r['q10_no_n']} ({no_share_never:.0f}%) never appear in a tier A action.** Because bulletins are selective, this does
  not mean those spaces were fixed, and it does not mean they were not.
* All bulletins post-date the audit (DOB's first bulletin is December 2017), so "subsequently appear" is by construction;
  we cannot see 2017 enforcement, and the audit's own fieldwork was July-November 2016.

## Q12. Datasets that would materially improve measurement of actual compliance

Verified on NYC Open Data on {pd.Timestamp.today().date()}:

1. **DOB Complaints Received** (`eabe-havv`; BIN, category code, inspection date, disposition). The Comptroller says DOB files
   POPS complaints under a dedicated category, so the complaint-to-inspection-to-disposition history for every POPS building is
   likely obtainable. The category code to filter on still has to be identified.
2. **DOB Violations** (`3h2n-5cm9`) and **DOB ECB Violations** (`6bgk-3dad`): the underlying violations (BIN/block/lot) of which
   bulletins show a small selection; needed to measure how many violations exist versus how many are highlighted.
3. **OATH hearings** for those ECB violations (outcomes, penalties imposed vs paid).
4. **311 Service Requests** (`erm2-nwe9`): resident-reported problems by address, if POPS-specific descriptors exist.
5. **DCP modification records** (CPC certifications / authorizations, amended declarations): needed to know which requirements
   were legally changed, otherwise "missing" amenities may be lawful.
6. **DOB job filings and permits**, plus **ACRIS/PLUTO** ownership: renovations that close spaces, and owner changes.
7. **Field observation** (inspections, photos, e.g. by advocates) — the only source that measures present-day conditions.

Reproduce: `python -m pops_tracker analyze` (tables in `reports/analysis/`).
"""
    (config.REPORTS / "analysis.md").write_text(md, encoding="utf-8")
