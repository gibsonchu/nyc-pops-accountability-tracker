# Methodology

> ## ⚠ Critical limitation — read before using any number from this project
>
> **DOB's Monthly Enforcement Action Bulletins highlight *selected* enforcement activity. They are not a comprehensive
> record of all DOB inspections, violations, complaints, or POPS compliance.**
>
> Therefore **absence from the bulletins must never be interpreted as evidence that a POPS is compliant.**
> "No enforcement action was found in the Monthly Enforcement Bulletins" and "This POPS is compliant" are **not equivalent**.
> A POPS with zero records here may have unpublished violations, unresolved complaints, or no inspection at all.
> Every public display of this data must carry that statement.

*Pipeline version 0.1.0. Retrieval date of all sources below: 2026-09-20 (re-stamped automatically in the manifests on each run).*

---

## 1. Sources

| # | Source | Owner | Endpoint / URL | How retrieved | Stored at |
|---|---|---|---|---|---|
| 1 | **Privately Owned Public Spaces (POPS)** — dataset `rvih-nhyn` (392 rows; published 2025-10-14; DCP states a 6-month update cycle) | NYC Dept. of City Planning via NYC Open Data | landing: `https://data.cityofnewyork.us/City-Government/Privately-Owned-Public-Spaces-POPS-/rvih-nhyn` · data: `https://data.cityofnewyork.us/resource/rvih-nhyn.csv?$limit=50000&$order=pops_number` · metadata: `https://data.cityofnewyork.us/api/views/rvih-nhyn.json` | Socrata API, no key | `data/raw/pops/` (content-addressed CSV + metadata JSON + append-only `manifest.csv` with retrieval time and SHA-256) |
| 2 | **DOB Monthly Enforcement Action Bulletins** (101 PDFs, 2017-12 → 2026-07) | NYC Dept. of Buildings | index `https://www.nyc.gov/site/buildings/dob/enforcement-action-bulletins.page`; PDFs `https://www.nyc.gov/assets/buildings/pdf/MMYY_enforcement_action_bulletin.pdf` | HTML scrape of the index; PDFs discovered from links, never hard-coded | `data/raw/dob_bulletins/YYYY/MM.pdf`; registry `data/registry/bulletin_registry.csv` |
| 3 | **Audit Report on the City's Oversight over POPS**, SR16-102A, 18 Apr 2017 | NYC Comptroller | page `https://comptroller.nyc.gov/reports/audit-report-on-the-on-the-citys-oversight-over-privately-owned-public-spaces/`; PDF `https://comptroller.nyc.gov/wp-content/uploads/documents/SR16_102A.pdf` | Direct download | `data/raw/comptroller/SR16_102A.pdf` |
| 4 | **NYC Planning Labs Geosearch** (Pelias over the Property Address Directory) — used only to resolve a street address to BBL/BIN | NYC DCP / Planning Labs | `https://geosearch.planninglabs.nyc/v2/search` | Per-address query, cached | `data/interim/geocode_cache.csv` |

Sources referenced but **not yet ingested**: New Yorkers for Parks 2026 recommendations (context only); In Spaces, "The Hidden Value of Privately
Owned Public Spaces" (prior research).

**Gaps in the authoritative POPS dataset** (verified against its published schema): it has **no zoning-district or legal-basis field** and
**no per-record source URL**. We do not invent them; `source_record_url` in our master is a link to the Socrata record. The `nta` column is
empty for all 392 rows. Each POPS has one street address even where the space spans several.

## 2. Bulletin discovery (steps 2, 3, 10)

1. `pops_tracker.bulletins.parse_index` parses the index HTML and collects every `<a>` whose target is a `.pdf` and whose URL or label contains
   "enforcement". Duplicate anchors to the same URL are merged (the page repeats some links with empty labels).
2. **Month and year come from the filename** (`MMYY_enforcement_action_bulletin.pdf`), not the label, because DOB's labels contain errors:
   `0121_…pdf` is labelled "January 2020", but the PDF's own header reads "JANUARY 2021". Any disagreement sets `label_conflict` and raises a
   low-severity review item. If a link no longer follows the filename convention, the label is used as a fallback and `structure_change_filename`
   (high severity) is raised.
3. Each bulletin gets a stable ID `YYYY-MM`. The registry is keyed on it, so **re-running is idempotent**: existing rows are updated in place,
   `date_discovered` is never overwritten, new IDs are appended, and bulletins that vanish from the index are flagged `still_on_index=False`, never deleted.
4. Downloads are skipped when the file exists. With `--check-updates` (used by the weekly job) a HEAD request compares ETag/Last-Modified; if DOB
   silently replaced a PDF, the old copy is preserved as `MM.<sha8>.pdf`, the new one saved, and the bulletin re-parsed and flagged.
5. **Nothing assumes a publication date.** The weekly workflow simply re-reads the index and processes whatever is new. Gaps (currently
   2024-06, 2024-07, 2025-12) are reported, not filled: DOB may not have published, or may have removed them.

Registry fields include `bulletin_month/year`, `pdf_url`, `date_discovered`, `local_filename`, `downloaded`, `parsed`, `extraction_method`,
`n_enforcement_actions`, `n_potential_pops_matches`, `processing_errors`, plus `sha256`, page/char counts and label diagnostics.

## 3. PDF extraction

`pdfplumber` first, `pypdf` as fallback. A document is accepted when the average is ≥ 300 characters per page. **All 101 PDFs have a machine-readable
text layer; no OCR was used or needed.** A PDF that fails both libraries is stored as `needs_ocr`, raises `failed_extraction` (high), and is *not*
OCR'd automatically. Per-page text is cached in `data/interim/bulletin_text/YYYY-MM.json` so parsing can be re-run without re-reading PDFs.

## 4. Parsing individual enforcement actions

* **Scope.** Each bulletin opens with aggregate statistics ("$320,812 in penalties … on four separate occasions"). Those are *not* individual actions.
  Parsing starts after the sentence "Below are individual enforcement highlights …" (present in all 101 bulletins; its absence is a `structure_change_marker` alert).
* **Entry boundaries.** A bullet glyph (U+F0B7 or •) starts a new entry; borough headers (Bronx, Brooklyn, Manhattan, Queens, Staten Island) and
  "Construction and Design Professionals" set the section. Running headers/footers and page numbers are removed. Entries spanning a page break are
  joined; `source_page` is the first page. Bulletless entries are recognised by a new leading "$" after a completed sentence.
* **Fields.** Penalty = the leading `$` amount (`penalty_basis` records the wording; "in total violations" is marked separately). Respondent = the
  party the penalty was issued to (may be a contractor, not the owner; `respondent_role` keeps DOB's stated role). Address = every address-shaped span,
  anchored spans preferred; borough from the text next to the address, else the section header, else a single borough named elsewhere in the entry
  (`borough_source` says which). Identifiers (BIN, BBL, block/lot, job or ECB numbers) are extracted when present (rare).
* **Verbatim text is always kept** (`enforcement_text`, whitespace-normalised and line-end hyphenation repaired). `violation_description` is that text with the
  leading penalty/respondent clause removed. **Enforcement dates:** bulletins normally give none; `enforcement_date` is filled only when the text states a full
  date, otherwise blank. `bulletin_month/year` is the time grain, and it is the publication month of DOB's summary, not the violation date.
* **Known source defects are kept, not hidden:** entries truncated in the PDF itself (`"$"`, `"$."`, `"DOB inspectors"`) are retained and flagged; two stray empty bullets are dropped and counted.
* **IDs.** `EA-YYYYMM-<sha1 of normalised text>[-n]`: stable across re-runs.

## 5. Identifying POPS-related enforcement

### Method A — text detection (`detect.py`)
Tiers were set by reading every hit across all 101 bulletins, not from a pre-set list.

| Tier | Patterns | Rationale |
|---|---|---|
| strong | "Privately Owned Public Space" (hyphen variants), `POPS` (upper-case only) | explicit |
| moderate | "public plaza", "public space", "publicly accessible", "public access area", "discretionary zoning", ZR §37-…, "public pedestrian path" | DOB's other wording for POPS; can rarely mean something else |
| weak | "plaza", "open air café", "arcade", "through-block / covered pedestrian space" — tested **after blanking addresses and the respondent's name** | mostly addresses ("Kings Plaza") and company names |

Deliberately **not** used: "open to the public" (5 of 6 hits describe construction sites) and bare "public access" (excavations).
Variations discovered: `Privately-Owned`, `(POPS)`, "public plaza" without the acronym, "discretionary zoning" (one entry, 445 5th Avenue, uses only this and "public plaza").

### Method B — property matching (`match.py`), on *every* action
Each entry's addresses go through the hierarchy below; **the first level that yields a candidate wins**, and two different POPS at one level = `ambiguous`, never guessed.

| Level | Evidence | `match_method` | Confidence |
|---|---|---|---|
| 1 | **BBL** — written in the text (BBL, or borough+block+lot) **or** returned by the geocoder for the bulletin address | `bbl` | high |
| 2 | **BIN** — written in text or geocoded (placeholder BINs `x000000` are never used) | `bin` | high |
| 3 | **Exact normalised address** (borough + house number + canonical street) | `address_exact` | high; *medium* if the borough had to be inferred or the geocoded BBL disagrees |
| 4 | House-number **range overlap** on an identical street | `address_range` | medium |
| 5 | **Fuzzy** street (see thresholds) | `address_fuzzy` | medium / low |

**Geocoding.** The bulletin's street address is sent to Geosearch; the result is accepted only if its echoed house number, street (after our own
normalisation) and county all agree with the query. Otherwise it is stored as `mismatch` and ignored, so Pelias' fuzzy "corrections" are never trusted
blindly. Results are cached for reproducibility.

### Combining the methods (`pops_relation`)
| Value | Meaning | Default handling |
|---|---|---|
| `pops_text_and_property_match` | POPS wording **and** matched property | **auto-confirmed only if match confidence is high** |
| `pops_text_only` | POPS wording, no database match | manual review (possible gap in DCP data, DOB address error, or not a POPS) |
| `property_match_only` | matched POPS building, **no** POPS wording | manual review; often a building- or construction-level violation, **not** a public-space violation |
| `weak_keyword_only` | only weak terms | logged in review, excluded from the POPS file |

## 6. Address normalisation (`address.py`)
Follows DCP/Geosupport/PAD conventions: upper-case; street types spelled out (ST→STREET, AVE→AVENUE, …); compass prefixes spelled out; **numbered streets/avenues
as bare numbers** ("5th", "Fifth", "5" → `5`); "Avenue of the Americas"/"Sixth Avenue" → `6 AVENUE`; PDF spacing artefacts repaired ("217 th St" → 217th). House numbers:
Queens `NN-NN` is a compound number; elsewhere `321-3` is DOB shorthand for the range 321–323 (completed from the first number; an incoherent range keeps its low end only).
"Park" is not treated as a street type (it would truncate "3 Park Avenue"); avenue letters ("Avenue N"), "Central/Prospect Park West", saints ("St. Nicholas Avenue") and
lowercase ordinal words ("third Ave") are handled explicitly. Every extraction rule has a regression test in `tests/`.

## 7. Fuzzy-matching thresholds
* Metric: `rapidfuzz.fuzz.ratio` on canonical street names (not `token_set_ratio`, which scores "PARK AVENUE" vs "PARK AVENUE SOUTH" as 100).
* **Preconditions (all required):** same borough; same house number, or overlapping range; **identical numeric tokens** and **identical compass words** in the street name
  (EAST 57 can never match WEST 57 or EAST 5).
* Score ≥ **96** → `medium`; ≥ **88** and < 96 → `low`; < 88 → no match. A fuzzy match is **never `high`**.
* "Suffix variant" (street identical except one trailing compass word, e.g. *Park Avenue* vs *Park Avenue South*) → `low`, raised to `medium` only if the POPS's
  building name appears in the bulletin text ("Ascot Owners, Inc." ↔ POPS "Ascot").
* Anything below `high`, or ambiguous, is in `manual_review.csv`.

**Validation.** An independent recall check searched every POPS address (house number + distinctive street tokens) in the raw entry text:
71 hits, 67 agreed with the matcher. The other 4 were: a company name ("316 Kent Construction LLC"), a different street ("50 West 69th"), East/West confusion
in the check itself ("322 East 57th"), and one genuine miss — "200 *West* 24th Street", where the respondent is "Crystal House Owners Inc." and the POPS "Crystal House" is at 200 *East* 24th (probable DOB typo). That
one is `pops_text_only` in the review queue with the building-name suggestion; it is **not** auto-corrected.

## 8. Violation classification (`classify.py`)
Rule-based, multi-label, transparent. Taxonomy: access / closure · seating · landscaping · trees · signage · fountain / water feature · bicycle parking ·
maintenance · unauthorized private use · unauthorized design modification · obstruction · hours · other (fallback when nothing fires). Each category is a list of
regexes over DOB's own wording; `violation_category` holds the labels and `violation_category_terms` records exactly which phrases fired. **DOB's original text is never replaced**
(`violation_description`, `enforcement_text`). Labels are a finding aid, not a legal determination. Known weaknesses: "maintenance" is broad; "unauthorized private use" fires on
"restaurant" and "school"; classification is not attempted for actions with neither POPS wording nor a POPS match.

## 9. Counting rules
Analysis uses three evidence tiers and never merges them silently: **A** confirmed POPS violation (`pops_text_and_property_match` + `auto_confirmed`/`reviewed_confirmed`);
**B** POPS wording, match medium/low or absent; **C** `property_match_only`. `possible_duplicate_of` flags entries that repeat across bulletins (identical text, or same
address+penalty+respondent in another month); duplicates are kept and flagged, not removed. Penalty totals sum each entry once.

## 10. The 2017 Comptroller audit (`comptroller.py`)
The report's Appendix lists 333 addresses with a "Full Compliance" column of **Yes / No / Construction**. We parse all 333 rows (validated: rows 1–333 are contiguous; the 182 "No" rows equal the
report's stated 182 non-compliant locations). Status is stored **as printed**; "Construction" is **not** treated as compliant. (The report's methodology text says 16 of 349 addresses were
excluded as under construction, while the appendix marks 41 of the 333 as "Construction"; we do not reconcile this.) The appendix has no BBL and no borough, so rows are matched to the
current master on (house number, canonical street) across boroughs: 332 of 333 link automatically (330 high, 1 medium, 1 low); one ("774 Sixth Avenue", close to POPS 776 6 Avenue) does not and is **not** inferred.
`comptroller_2017_findings` is filled only where the report body names the address (9 locations); the appendix itself gives no per-location detail. `comptroller_2017_compliant` is blank, never guessed, for POPS not in the audit.
`post_2017_dob_enforcement_count` counts confirmed actions from bulletins dated ≥ 2017-04; since DOB's first bulletin is 2017-12, that is every bulletin.

## 11. Quality control (`qc.py`) and manual review
`data/review/manual_review.csv` is regenerated every run. Checks: duplicate enforcement actions · duplicate bulletins (same hash/URL) · missing bulletin months · failed PDF extraction ·
addresses not parsed · ambiguous matches · suspicious penalties (outside $100–$2,000,000, or a "$" lead with no parseable amount) · POPS keyword hits with no match · matches without POPS wording ·
low/medium-confidence matches · borough conflicts · truncated source entries · structure changes (index yields far fewer links, filename convention changed, marker phrase missing, entry count outside 0.4×–2.5× the recent median) · Comptroller-link uncertainty.
`python -m pops_tracker check` (run in CI) exits non-zero on structural problems.

**Procedure.** Open the review file; for each open item read `enforcement_text_excerpt` and the source PDF page; record the outcome as a row in `data/review/review_decisions.csv`
(`enforcement_id, decision ∈ {confirm, reject, reassign}, pops_id, reviewer, note, decided_at`) and re-run `python -m pops_tracker build`. Decisions are keyed to content-derived IDs so they survive re-runs;
`confirm`/`reassign` → `reviewed_confirmed` (and the POPS ID is set), `reject` → `reviewed_rejected` (kept in `enforcement_actions_all.csv`, excluded from the POPS file and analysis). Nothing is ever deleted.

## 12. Known limitations
1. **Selectivity of the bulletins** (top of this document). After 2024-08 no bulletin contains any POPS wording; we cannot tell whether enforcement stopped or only its publication.
2. **The POPS dataset is a snapshot** (published 2025-10-14, ~11 months before retrieval) and may lack newer POPS. Entries such as 341 East 6th Street (explicitly a "POPS") are not in it.
3. **Bulletin months are not violation dates.** Entries can describe conduct that preceded publication by months.
4. **Respondent ≠ owner** in general; names are inconsistent across bulletins ("Claridge"/"Clairidge"), so entity counts are lower bounds.
5. **Parsing coverage:** an address was extracted for 84.3% of entries (2,219 / 2,631); 314 sit in the "Construction and Design Professionals" section and are legitimately address-less. Of the 103 address-less entries outside that section, most are still licence/stipulation/summons text; 29 that look like property enforcement are queued for review (`address_not_parsed`, low). Penalty: 1,887 entries (the rest, mostly professional discipline and stipulations, carry no leading amount).
6. **Geocoder:** 181 of 2,080 lookups (8.7%) were rejected as mismatches (mostly malformed or non-existent source addresses, e.g. "Miranda Street" resolving to Kirby Street); such entries can still match by exact address.
7. **Keyword rules** are English-phrase based and tuned on this corpus; new DOB wording will be missed by Method A (Method B still works). Classification labels are heuristic.
8. **Small numbers.** Tier A is 45 actions at 41 POPS; comparisons between groups are descriptive.
9. Bulletins from before 2018-01 barely exist (one, December 2017, with 6 highlights); no earlier enforcement can be studied from this source.

## 13. Reproducibility
`python -m pops_tracker update` reproduces everything from the public sources. Processed outputs are a pure function of raw PDFs + POPS snapshot + geocode cache + review decisions:
re-running with no new inputs leaves every output file byte-identical (verified), and simulating a newly published bulletin (deleting one month and re-running) restores identical outputs. Tests: `python -m pytest`.
