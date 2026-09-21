# NYC POPS Accountability Tracker

An open, reproducible, continuously updated dataset of **documented enforcement history at New York City's Privately Owned Public Spaces (POPS)**,
built from the DCP POPS dataset, DOB's Monthly Enforcement Action Bulletins, and the NYC Comptroller's 2017 POPS audit.

> **Enforcement records come from DOB's Monthly Enforcement Action Bulletins, which highlight selected enforcement activity.
> No enforcement record does not necessarily mean that a POPS is compliant.** See [METHODOLOGY.md](METHODOLOGY.md).

Status: **Phase 1 (pipeline) done · Phase 2 (analysis) preliminary · Phase 3 (interface) not started.**

## What's here
| Path | What |
|---|---|
| `data/raw/pops/` | DCP POPS snapshots (immutable, hashed, with `manifest.csv`) |
| `data/raw/dob_bulletins/YYYY/MM.pdf` | Every bulletin DOB currently lists (101, 2017-12 → 2026-07) |
| `data/raw/comptroller/SR16_102A.pdf` | 2017 audit |
| `data/registry/bulletin_registry.csv` | One row per bulletin: URL, discovery date, download/parse status, counts, errors |
| `data/interim/` | Extracted PDF text (per bulletin) and the geocoder cache |
| `data/processed/pops_master.csv/.json` | Normalised POPS list (all source columns kept + join keys + quality flags) |
| `data/processed/enforcement_actions_all.csv` | **All** 2,631 parsed enforcement actions with match results |
| `data/processed/pops_enforcement.csv/.json` | POPS-related enforcement records (the main dataset) |
| `data/processed/pops_accountability.csv/.json` | One row per POPS: requirements, 2017 audit result, enforcement counts |
| `data/processed/comptroller_2017_audit.csv` | The audit's 333 locations, linked to the master |
| `data/processed/pops_tracker.sqlite` | The history data model ([schema](data/schema/pops_history.sql)): agreement → requirements → audit → enforcement, with empty tables ready for inspections, 311, modifications, building records |
| `data/review/manual_review.csv` | Everything uncertain, for a human. `review_decisions.csv` holds reviewer decisions |
| `reports/analysis.md` | Phase 2 preliminary analysis · `reports/data_quality_report.md` · `reports/analysis/*.csv` |

## Use
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pops_tracker update     # everything, from the public sources (~1 min when up to date)
.venv/bin/python -m pops_tracker build      # re-derive outputs from what's on disk
.venv/bin/python -m pops_tracker analyze    # Phase 2 tables + reports/analysis.md
.venv/bin/python -m pops_tracker check      # non-zero exit if DOB's page/PDF structure changed
.venv/bin/python -m pytest                  # 46 tests
```
First run after a fresh clone downloads ~101 PDFs (69 MB, ~70 s) and geocodes ~2,000 addresses (a few minutes); later runs are incremental.

## Weekly automation
[`.github/workflows/update-data.yml`](.github/workflows/update-data.yml) runs Mondays: re-read the DOB index → diff against the registry → download new/replaced PDFs → extract → parse →
match against POPS → classify → apply saved review decisions → QC → regenerate CSV/JSON/SQLite → commit if changed → fail loudly on structural change.
It never assumes a publication date. Running twice with no new inputs changes nothing (verified byte-for-byte).

## Reading the main file (`pops_enforcement.csv`)
* **`pops_relation`** — `pops_text_and_property_match` (POPS wording *and* a matched POPS) · `pops_text_only` (wording, no database match) · `property_match_only` (a POPS building, but the paragraph doesn't mention POPS; often a building/construction violation).
* **`manual_review_status`** — `auto_confirmed` only for text+property at *high* confidence (BBL, BIN or exact address); everything else `needs_review` until a human decides.
* **`match_method` / `match_confidence`** — `bbl`, `bin`, `address_exact`, `address_range`, `address_fuzzy` × `high`/`medium`/`low`. Fuzzy is never high.
* **`violation_category`** is a multi-label heuristic; **`violation_description` and `enforcement_text` are DOB's own words** and are the source of truth.
* `owner` is the party the penalty was issued to (may be a contractor); `bulletin_month/year` is the publication month, not the date of the violation.

## Not done yet
Phase 3 (public site), DOB inspections / complaints / 311 loaders (schema is ready), and a human pass over the 92 open review items. Nothing here should be published as final until that pass is done.
