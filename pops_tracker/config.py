"""Paths, source URLs and tunable thresholds. Everything that a methodology reader needs to know lives here."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
RAW_POPS = RAW / "pops"
RAW_BULLETINS = RAW / "dob_bulletins"
RAW_COMPTROLLER = RAW / "comptroller"
INTERIM = DATA / "interim"
BULLETIN_TEXT = INTERIM / "bulletin_text"
PROCESSED = DATA / "processed"
REGISTRY_DIR = DATA / "registry"
REVIEW = DATA / "review"
REPORTS = ROOT / "reports"

BULLETIN_REGISTRY = REGISTRY_DIR / "bulletin_registry.csv"
POPS_MASTER = PROCESSED / "pops_master.csv"
ENFORCEMENT_ALL = PROCESSED / "enforcement_actions_all.csv"
ENFORCEMENT_POPS = PROCESSED / "pops_enforcement.csv"
MANUAL_REVIEW = REVIEW / "manual_review.csv"

USER_AGENT = "nyc-pops-accountability-tracker/0.1 (public-interest research)"  # nyc.gov's firewall 403s UAs containing a URL/repo name; keep it plain
HTTP_TIMEOUT = 60
REQUEST_DELAY_SECONDS = 0.5  # be polite to nyc.gov

# ---- Sources -------------------------------------------------------------------------------
DOB_INDEX_URL = "https://www.nyc.gov/site/buildings/dob/enforcement-action-bulletins.page"
DOB_ORIGIN = "https://www.nyc.gov"

POPS_DATASET_ID = "rvih-nhyn"
POPS_PORTAL = "https://data.cityofnewyork.us"
POPS_LANDING_URL = f"{POPS_PORTAL}/City-Government/Privately-Owned-Public-Spaces-POPS-/{POPS_DATASET_ID}"
POPS_CSV_URL = f"{POPS_PORTAL}/resource/{POPS_DATASET_ID}.csv?$limit=50000&$order=pops_number"
POPS_META_URL = f"{POPS_PORTAL}/api/views/{POPS_DATASET_ID}.json"

COMPTROLLER_AUDIT_PAGE = (
    "https://comptroller.nyc.gov/reports/audit-report-on-the-on-the-citys-oversight-over-privately-owned-public-spaces/"
)

# ---- Matching thresholds (documented in METHODOLOGY.md) ------------------------------------
FUZZY_AUTO_ACCEPT = 96   # token-set score at/above which a fuzzy address match is 'medium' confidence
FUZZY_REVIEW_FLOOR = 88  # between floor and auto-accept: 'low' confidence, always manual review
# Penalty sanity bounds: DOB civil penalties in bulletins; outside this range gets a QC flag.
PENALTY_MIN_PLAUSIBLE = 100
PENALTY_MAX_PLAUSIBLE = 2_000_000
