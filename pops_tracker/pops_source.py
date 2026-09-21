"""Step 1a: download the authoritative POPS dataset (NYC Open Data / DCP) into data/raw/pops/.

Raw files are immutable and content-addressed: a new retrieval is only written when the bytes differ from
every earlier retrieval. `manifest.csv` is append-only and records every retrieval, including no-change checks.
"""
import csv
import datetime as dt
import json

from . import config
from .http import get, sha256_bytes

MANIFEST = config.RAW_POPS / "manifest.csv"
MANIFEST_FIELDS = ["retrieved_at_utc", "dataset_id", "source_rows_updated_at", "sha256", "bytes", "row_count",
                   "csv_file", "metadata_file", "source_url", "status"]


def _read_manifest():
    if not MANIFEST.exists():
        return []
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _append_manifest(row):
    config.RAW_POPS.mkdir(parents=True, exist_ok=True)
    new = not MANIFEST.exists()
    with open(MANIFEST, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def download_raw() -> dict:
    """Fetch the CSV and the dataset metadata. Returns the manifest row describing what happened."""
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    meta = get(config.POPS_META_URL).json()
    updated = dt.datetime.fromtimestamp(meta["rowsUpdatedAt"], dt.timezone.utc).date().isoformat()
    body = get(config.POPS_CSV_URL).content
    digest = sha256_bytes(body)
    rows = max(body.count(b"\n") - 1, 0)  # approximate; exact count is verified by the processor

    for prev in _read_manifest():
        if prev["sha256"] == digest and prev["status"] in ("downloaded", "unchanged"):
            row = dict(prev, retrieved_at_utc=now.isoformat(), status="unchanged")
            _append_manifest(row)
            return row

    stem = f"{config.POPS_DATASET_ID}_{updated}_{digest[:8]}"
    config.RAW_POPS.mkdir(parents=True, exist_ok=True)
    csv_path = config.RAW_POPS / f"{stem}.csv"
    meta_path = config.RAW_POPS / f"{stem}.metadata.json"
    csv_path.write_bytes(body)
    meta_path.write_text(json.dumps(meta, indent=1, sort_keys=True), encoding="utf-8")
    row = {"retrieved_at_utc": now.isoformat(), "dataset_id": config.POPS_DATASET_ID, "source_rows_updated_at": updated,
           "sha256": digest, "bytes": len(body), "row_count": rows, "csv_file": csv_path.name,
           "metadata_file": meta_path.name, "source_url": config.POPS_CSV_URL, "status": "downloaded"}
    _append_manifest(row)
    return row


def latest_raw_csv():
    """Path of the most recently retrieved raw CSV (by manifest order)."""
    rows = _read_manifest()
    if not rows:
        raise FileNotFoundError("No raw POPS retrieval yet; run `python -m pops_tracker fetch-pops`.")
    return config.RAW_POPS / rows[-1]["csv_file"], rows[-1]
