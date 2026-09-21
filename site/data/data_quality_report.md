# Data-quality report — first deliverable (run of 2026-09-20)

What was found while investigating the sources, what it affects, and what the pipeline does about it.
"Handled" means an automated rule and a review-queue entry exist; "Open" means a human or a new source is needed.

## A. DOB bulletin index and PDFs

| # | Problem | Evidence | Effect | Status |
|---|---|---|---|---|
| A1 | **Mislabelled bulletin**: link labelled "January 2020" points to `0121_…pdf` | The PDF's header reads "JANUARY 2021"; a real Jan 2020 bulletin also exists (`0120`) | Would have created a duplicate 2020-01 and lost 2021-01 if the label were trusted | Handled: month from filename; `label_conflict` flagged (`index_label_conflict`) |
| A2 | **Three months absent** from the index: 2024-06, 2024-07, 2025-12 | Gaps inside the 2017-12 → 2026-07 span | Any month-level count is understated for those months; 2024-06/07 sit just before the last POPS-related bulletin (2024-08) | Handled: `missing_bulletin_month` (medium). Open: ask DOB whether they exist |
| A3 | **Duplicate anchors** on the index (e.g. `0426`, `0626` appear twice, one unlabelled) | 104 PDF anchors → 101 distinct PDFs | Would double-download | Handled: dedup by URL, labels merged |
| A4 | **Entries truncated in the source PDF**: `"$"`, `"$."`, `"DOB inspectors"` | 2022-11 (×2), 2023-10 | A parser cannot recover the text; the action is unknowable | Handled: kept verbatim, flagged `truncated_source_entry`; 2 stray empty bullets dropped and counted |
| A5 | **Entries re-published verbatim** in later bulletins (e.g. several 2021-11 entries again in 2022-05) | 11 `possible_duplicate_action` | Double counting if naive | Handled: flagged with the earlier ID; none of the 45 tier-A actions is affected |
| A6 | **Wording drift for penalties**: "in penalties", "in fines", "in *mitigated* penalties", "in *default* penalties", "in total *violations*" | 21 amounts were missed by the first version of the parser | Understated penalty totals | Handled (regex widened; the "violations" wording is marked `leading_amount_violations_wording`, 12 entries) |
| A7 | **Layout differs by era**: no borough headers before mid-2019; bullet glyph is U+F0B7 or • | 2017–early 2019 bulletins | Borough must come from text | Handled: `borough_source` records text / section / text_elsewhere |
| A8 | **Early bulletins are thin**: 2017-12 has 6 highlights, no borough structure | — | No pre-2018 baseline | Limitation |
| A9 | **PDF text artefacts**: "217 th St.", "$22, 500", "84- 06 159th St." | seen in several years | Broke address/penalty extraction | Handled in normalisers + tests |
| A10 | **No exact dates**: violations are described without dates | almost all entries | Only the bulletin month is known | Limitation (stated in every output) |
| A11 | **Bulletin content is selective by design** | DOB's own text: "highlights … represent a portion of DOB's overall work" | Zero count ≠ compliant | **Fundamental limitation**, stated in METHODOLOGY.md, README, and every export |

## B. NYC POPS dataset (DCP, `rvih-nhyn`)

| # | Problem | Count | Status |
|---|---|---|---|
| B1 | **No zoning-district / legal-basis field, no per-record source URL** (both requested) | — | Open: not in the dataset; would require DCP's APOPS legal files. `source_record_url` added as a link to the Socrata record |
| B2 | **Placeholder BINs** (`1000000`, `2000000`, `3000000`, `4000000`) | 8 rows | Handled: flagged `bin_placeholder_not_matchable`, never used to match |
| B3 | **Missing BBL and BIN** | 2 rows (M050077, M050100) | Handled: flagged; matched by address only |
| B4 | **Year completed = 0** | 2 rows | Handled: blank + flag; **38** further rows have no year |
| B5 | **Missing required hours / amenities** | 34 / 32 rows | Kept blank + flagged; "no listed amenities" ≠ "none required" |
| B6 | **`nta` column empty** for all rows | 392 | Ignored |
| B7 | **Under construction** | 7 rows | Flagged |
| B8 | **Snapshot age**: published 2025-10-14 (DCP says every 6 months) | — | Open: re-fetched every run; the weekly job will pick up a newer release automatically |
| B9 | **Street-name style mixes** ("FIFTH AVENUE", "39 AVENUE", "AVENUE OF THE AMERICAS") | throughout | Handled by canonicalisation |
| B10 | **A POPS named in a bulletin is absent from the dataset** (341 East 6th Street: "Privately Owned Public Space (POPS)") | 1 | Open, in review queue |

## C. Matching and geocoding

| # | Problem | Evidence | Status |
|---|---|---|---|
| C1 | **String similarity alone is unsafe** (and so is over-eager cleanup: an ordinal-repair rule deleted "Street" from "47 St"): `token_set_ratio` scored "PARK AVENUE" vs "PARK AVENUE SOUTH" = 100; fuzzy matching linked "200 *West* 24th" to *East* 24th and "322 East 57th" to *West* 57th; the range "321-3" (=321–323) parsed as 3–321 and matched an unrelated POPS | found during sample testing | Fixed; each has a regression test |
| C2 | **Geocoder rejects 181 of 2,080 addresses** (8.7%) | mostly malformed or non-existent source addresses ("Miranda Street" resolves to Kirby Street); the cache is pruned each run so it only reflects the current extractor | Mismatches are never used; entries can still match by exact address |
| C3 | **DOB address typos affect real POPS**: "407 Park Avenue" for the POPS at 407 Park Avenue *South* (respondent "Ascot Owners" ↔ building "Ascot"); "200 *West* 24th" for Crystal House at 200 *East* 24th | 2 | Ascot: matched `low→medium` through name corroboration, in review. Crystal House: text-only, name suggestion in review. Neither is auto-corrected |
| C4 | **One entry lists several properties** ("including 1801 2nd Avenue, 154 West 71st Street, …, and 75 West End Avenue") | 2018-04 | Handled: all addresses are matched; one POPS building found |
| C5 | **Independent recall audit**: text search for every POPS address vs the matcher | 71 hits; 67 agreed; the other 4 explained (3 false alarms in the check, 1 true miss = Crystal House, now in review) | Kept as the validation procedure |
| C6 | **POPS wording but doubtful POPS**: 25-40 Shore Blvd, Queens ("public pedestrian/bike path … maintained for public access") is likely a waterfront access area | 1 | Never auto-confirmed; review |
| C7 | **Building-level violations at POPS buildings** (contractor safety, signage) have no POPS wording | 30 actions at 26 POPS | Separate tier C; never counted as POPS violations |

## D. Comptroller 2017 audit

| # | Problem | Status |
|---|---|---|
| D1 | The appendix has no BBL/BIN and no borough | Matched on house number + street across boroughs: 332/333 automatic (330 high). One unlinked ("774 Sixth Avenue" — near, but not the same number as, POPS 776 6 AVENUE; **not inferred**) |
| D2 | **Report text vs appendix**: text says 16 of 349 addresses under construction were excluded; the appendix marks 41 of 333 "Construction" | Stored as printed; not reconciled |
| D3 | The appendix gives Yes/No only — **no per-location violation detail** | `comptroller_2017_findings` filled for only the 9 locations the body names; others blank |
| D4 | Headline check | 182 "No" rows = the report's "182 of the 333" ✔ |
| D5 | The 2016 DCP list had 349 addresses; today's has 392 | 60 current POPS are not in the audit; flagged `comptroller_2017_inspected=False`, compliance blank |

## E. Suggested first review pass (highest value first)
1. `pops_keyword_without_db_match` (3): 341 East 6th St., Crystal House, 25-40 Shore Blvd.
2. `low_confidence_match` (2): 407 Park Avenue / Ascot; 525 East 72nd Street.
3. `comptroller_audit_link` (3).
4. `db_match_without_pops_terms` (30): decide which are public-space violations.
5. `possible_duplicate_action` (11), `missing_bulletin_month` (3), the rest.
