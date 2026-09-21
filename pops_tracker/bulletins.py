"""Steps 2-3: discover Monthly Enforcement Action Bulletins from the DOB index page, keep a registry, download PDFs.

Nothing here hard-codes a PDF URL. Discovery is driven by whatever links the index page currently exposes.
The bulletin's month/year is taken from the filename convention (MMYY) when it matches, and cross-checked
against the human-readable link label. Disagreements are recorded (label_conflict) rather than silently resolved,
because DOB's own labels contain typos (e.g. ``0121_...pdf`` labelled "January 2020").
"""
import datetime as dt
import re
from urllib.parse import urljoin, urlparse

import pandas as pd
from bs4 import BeautifulSoup

from . import config
from .http import get, head, sha256_bytes

REGISTRY_FIELDS = [
    "bulletin_id", "bulletin_month", "bulletin_year", "pdf_url", "date_discovered", "last_seen_on_index",
    "local_filename", "downloaded", "downloaded_at", "sha256", "size_bytes", "http_etag", "http_last_modified",
    "page_count", "text_chars", "has_text_layer", "parsed", "parsed_at", "extraction_method",
    "n_enforcement_actions", "n_potential_pops_matches", "index_label", "label_month", "label_year", "label_conflict",
    "filename_pattern_ok", "still_on_index", "processing_errors",
]

# DOB's current convention: /assets/buildings/pdf/MMYY_enforcement_action_bulletin.pdf
FILENAME_RE = re.compile(r"(?P<mm>\d{2})(?P<yy>\d{2})_enforcement_action_bulletin\.pdf$", re.I)
LABEL_RE = re.compile(r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)"
                      r"\s+(?P<year>\d{4})", re.I)
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


def is_bulletin_link(href: str, text: str) -> bool:
    """A link counts as a bulletin candidate if it is a PDF and either the URL or the label says 'enforcement'."""
    path = urlparse(href).path.lower()
    return path.endswith(".pdf") and ("enforcement" in path or "enforcement" in (text or "").lower())


def parse_index(html: str, base_url: str = config.DOB_INDEX_URL) -> list[dict]:
    """Return one record per distinct PDF URL found on the index page (labels merged across duplicate anchors)."""
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, dict] = {}
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())
        if not is_bulletin_link(a["href"], text):
            continue
        url = urljoin(base_url, a["href"]).split("#")[0]
        rec = found.setdefault(url, {"pdf_url": url, "index_label": ""})
        if text and (not rec["index_label"] or "bulletin" in text.lower()):
            rec["index_label"] = text
    out = []
    for rec in found.values():
        fm = FILENAME_RE.search(urlparse(rec["pdf_url"]).path)
        lm = LABEL_RE.search(rec["index_label"])
        rec["filename_pattern_ok"] = bool(fm)
        if fm:
            rec["bulletin_month"], rec["bulletin_year"] = int(fm["mm"]), 2000 + int(fm["yy"])
        elif lm:  # unknown filename convention: fall back on the label and flag it for review
            rec["bulletin_month"], rec["bulletin_year"] = MONTHS[lm["month"].lower()], int(lm["year"])
        else:
            rec["bulletin_month"] = rec["bulletin_year"] = None
        rec["label_month"], rec["label_year"] = (MONTHS[lm["month"].lower()], int(lm["year"])) if lm else (None, None)
        rec["label_conflict"] = bool(
            lm and rec["bulletin_month"] and (rec["label_month"], rec["label_year"]) != (rec["bulletin_month"], rec["bulletin_year"]))
        out.append(rec)
    return out


def bulletin_id(rec) -> str | None:
    if rec.get("bulletin_year") and rec.get("bulletin_month"):
        return f"{int(rec['bulletin_year']):04d}-{int(rec['bulletin_month']):02d}"
    return None


def local_path(bid: str):
    y, m = bid.split("-")
    return config.RAW_BULLETINS / y / f"{m}.pdf"


def load_registry() -> pd.DataFrame:
    if config.BULLETIN_REGISTRY.exists():
        return pd.read_csv(config.BULLETIN_REGISTRY, dtype=str, keep_default_na=False)
    return pd.DataFrame(columns=REGISTRY_FIELDS)


def save_registry(df: pd.DataFrame):
    config.REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    df = df.reindex(columns=REGISTRY_FIELDS).sort_values("bulletin_id")
    df.to_csv(config.BULLETIN_REGISTRY, index=False)


def discover(html: str | None = None) -> pd.DataFrame:
    """Fetch (or accept) the index, merge into the registry and return the registry. Idempotent by bulletin_id."""
    if html is None:
        html = get(config.DOB_INDEX_URL).text
    today = dt.date.today().isoformat()
    reg = load_registry().astype(object).set_index("bulletin_id", drop=False)
    seen_ids = set()
    for rec in parse_index(html):
        bid = bulletin_id(rec) or f"unparsed:{rec['pdf_url']}"
        seen_ids.add(bid)
        row = {
            "bulletin_id": bid, "bulletin_month": rec["bulletin_month"] or "", "bulletin_year": rec["bulletin_year"] or "",
            "pdf_url": rec["pdf_url"], "last_seen_on_index": today, "index_label": rec["index_label"],
            "label_month": rec["label_month"] or "", "label_year": rec["label_year"] or "",
            "label_conflict": str(rec["label_conflict"]), "filename_pattern_ok": str(rec["filename_pattern_ok"]),
            "still_on_index": "True",
        }
        row = {k: ("" if v is None else str(v)) for k, v in row.items()}   # registry is all-string (CSV round-trip safe)
        if bid in reg.index:
            old_url = reg.at[bid, "pdf_url"]
            for k, v in row.items():
                reg.at[bid, k] = v
            if old_url and old_url != rec["pdf_url"]:
                reg.at[bid, "processing_errors"] = (reg.at[bid, "processing_errors"] + f"; url_changed_from={old_url}").strip("; ")
        else:
            row.update({"date_discovered": today, "local_filename": "", "downloaded": "False", "parsed": "False",
                        "processing_errors": ""})
            reg = pd.concat([reg, pd.DataFrame([row]).set_index("bulletin_id", drop=False)])
    # Bulletins that used to be on the index but disappeared are flagged, never deleted.
    for bid in reg.index:
        if bid not in seen_ids:
            reg.at[bid, "still_on_index"] = "False"
    reg = reg.fillna("")
    save_registry(reg.reset_index(drop=True))
    return load_registry()


def download_missing(check_updates: bool = False, limit: int | None = None) -> list[str]:
    """Download PDFs not yet on disk. With check_updates, HEAD every known PDF and re-download when DOB replaced it.

    Replaced files: the previous copy is preserved as MM.<sha8>.pdf and the bulletin is marked unparsed.
    """
    reg = load_registry().set_index("bulletin_id", drop=False)
    changed = []
    n = 0
    for bid, row in reg.iterrows():
        if bid.startswith("unparsed:"):
            continue
        path = local_path(bid)
        need = row["downloaded"] != "True" or not path.exists()
        if not need and check_updates:
            h = head(row["pdf_url"])
            etag, lm = h.headers.get("ETag", ""), h.headers.get("Last-Modified", "")
            if h.ok and ((etag and row["http_etag"] and etag != row["http_etag"]) or
                         (lm and row["http_last_modified"] and lm != row["http_last_modified"])):
                need = True
        if not need:
            continue
        if limit is not None and n >= limit:
            break
        n += 1
        try:
            r = get(row["pdf_url"])
            body = r.content
            if not body.startswith(b"%PDF"):
                raise ValueError(f"response is not a PDF (content-type={r.headers.get('Content-Type')})")
            digest = sha256_bytes(body)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and row["sha256"] and row["sha256"] != digest:
                path.rename(path.with_name(f"{path.stem}.{row['sha256'][:8]}.pdf"))  # keep the superseded original
                reg.at[bid, "processing_errors"] = (reg.at[bid, "processing_errors"] + "; pdf_replaced_upstream").strip("; ")
                reg.at[bid, "parsed"] = "False"
            if not path.exists() or row["sha256"] != digest:
                path.write_bytes(body)
            reg.at[bid, "local_filename"] = str(path.relative_to(config.ROOT))
            reg.at[bid, "downloaded"] = "True"
            reg.at[bid, "downloaded_at"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
            reg.at[bid, "sha256"] = digest
            reg.at[bid, "size_bytes"] = str(len(body))
            reg.at[bid, "http_etag"] = r.headers.get("ETag", "")
            reg.at[bid, "http_last_modified"] = r.headers.get("Last-Modified", "")
            changed.append(bid)
        except Exception as e:  # never abort the run for one bad PDF
            reg.at[bid, "downloaded"] = "False"
            reg.at[bid, "processing_errors"] = (reg.at[bid, "processing_errors"] + f"; download_failed: {e}").strip("; ")
    save_registry(reg.reset_index(drop=True))
    return changed
