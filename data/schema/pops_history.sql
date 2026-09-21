-- POPS history data model (SQLite dialect, portable to Postgres).
-- One POPS' story:  original agreement -> requirements -> complaints -> inspections -> violations -> enforcement
--                   -> modifications -> current status
-- Every source table keeps its own rich columns AND emits rows into pops_event, so the timeline view is a simple union.
-- Phase 1 populates: source_document, pops_site, pops_requirement, enforcement_action, comptroller_audit, pops_event.
-- Tables marked FUTURE are created empty so later phases only need loaders, not schema changes.

CREATE TABLE IF NOT EXISTS source_document (
  source_id      TEXT PRIMARY KEY,           -- e.g. 'dcp_pops_2025-10-14', 'dob_bulletin_2024-08', 'comptroller_SR16-102A'
  source_type    TEXT NOT NULL,              -- dcp_pops | dob_bulletin | comptroller_audit | dob_inspection | 311 | dcp_modification | dob_filing
  title          TEXT, url TEXT, retrieved_at TEXT, sha256 TEXT, local_path TEXT
);

CREATE TABLE IF NOT EXISTS pops_site (         -- one row per POPS; current DCP attributes
  pops_id TEXT PRIMARY KEY, borough TEXT, address_normalized TEXT, bbl TEXT, bin TEXT, latitude REAL, longitude REAL,
  building_name TEXT, pops_type TEXT, year_established INTEGER, developer TEXT, current_status_note TEXT,
  source_id TEXT REFERENCES source_document(source_id)
);

CREATE TABLE IF NOT EXISTS pops_requirement (  -- what the owner promised; versioned so later amendments can supersede
  requirement_id INTEGER PRIMARY KEY AUTOINCREMENT,
  pops_id TEXT NOT NULL REFERENCES pops_site(pops_id),
  requirement_type TEXT NOT NULL,              -- required_hours | required_size | required_amenity | other_required | permitted_amenity
  value_text TEXT NOT NULL,                    -- verbatim from DCP
  valid_from TEXT, valid_to TEXT,              -- NULL = unknown/open; set when a modification changes it
  source_id TEXT REFERENCES source_document(source_id)
);

CREATE TABLE IF NOT EXISTS enforcement_action ( -- DOB Monthly Enforcement Action Bulletin entries linked to a POPS
  enforcement_id TEXT PRIMARY KEY, pops_id TEXT REFERENCES pops_site(pops_id),
  bulletin_year INTEGER, bulletin_month INTEGER, enforcement_date TEXT,
  respondent TEXT, penalty_amount INTEGER, violation_category TEXT, violation_description TEXT, enforcement_text TEXT,
  pops_relation TEXT,                            -- pops_text_and_property_match | property_match_only | pops_text_only
  match_method TEXT, match_confidence TEXT, manual_review_status TEXT,
  source_pdf TEXT, source_page INTEGER, pdf_url TEXT
);

CREATE TABLE IF NOT EXISTS comptroller_audit (
  audit_row INTEGER PRIMARY KEY, audit_id TEXT, audit_date TEXT, audit_address TEXT,
  full_compliance_as_printed TEXT,               -- Yes | No | Construction (never inferred)
  pops_id TEXT REFERENCES pops_site(pops_id), match_method TEXT, match_confidence TEXT, findings_text TEXT, audit_pdf_page INTEGER
);

-- FUTURE ------------------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dob_inspection (
  inspection_id TEXT PRIMARY KEY, pops_id TEXT REFERENCES pops_site(pops_id), inspection_date TEXT, inspection_result TEXT,
  corrective_action TEXT, compliance_status TEXT, source_id TEXT REFERENCES source_document(source_id)
);
CREATE TABLE IF NOT EXISTS complaint_311 (
  complaint_id TEXT PRIMARY KEY, pops_id TEXT REFERENCES pops_site(pops_id), complaint_date TEXT, complaint_category TEXT,
  resolution TEXT, status TEXT, source_id TEXT REFERENCES source_document(source_id)
);
CREATE TABLE IF NOT EXISTS pops_modification (
  modification_id TEXT PRIMARY KEY, pops_id TEXT REFERENCES pops_site(pops_id),
  modification_type TEXT,                        -- approved_modification | renovation | required_amenity_change | temporary_closure
  approved_date TEXT, effective_from TEXT, effective_to TEXT, description TEXT, source_id TEXT REFERENCES source_document(source_id)
);
CREATE TABLE IF NOT EXISTS building_record (
  record_id TEXT PRIMARY KEY, pops_id TEXT REFERENCES pops_site(pops_id), bin TEXT, bbl TEXT,
  record_type TEXT,                              -- dob_filing | permit | ownership_change
  record_date TEXT, description TEXT, source_id TEXT REFERENCES source_document(source_id)
);
-- ---------------------------------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS pops_event (          -- the unified history; one row per dated thing that happened to a POPS
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  pops_id TEXT NOT NULL REFERENCES pops_site(pops_id),
  event_type TEXT NOT NULL,                      -- agreement | requirements_snapshot | audit_inspection | complaint | inspection |
                                                 -- violation | enforcement | modification | closure | building_record
  event_date TEXT,                               -- ISO date or partial (YYYY / YYYY-MM)
  event_date_precision TEXT,                     -- day | month | year | unknown
  summary TEXT, source_table TEXT, source_key TEXT, source_id TEXT REFERENCES source_document(source_id),
  confidence TEXT                                -- high | medium | low | needs_review
);
CREATE INDEX IF NOT EXISTS ix_event_pops_date ON pops_event(pops_id, event_date);

CREATE VIEW IF NOT EXISTS pops_timeline AS
  SELECT pops_id, event_date, event_date_precision, event_type, summary, source_table, source_key, confidence
  FROM pops_event ORDER BY pops_id, event_date;
