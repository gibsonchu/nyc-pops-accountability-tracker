"""Step 1b: normalise the raw POPS dataset into data/processed/pops_master.{csv,json}.

Every source column is preserved verbatim (raw column names). Derived columns are prefixed nowhere but are listed in
DERIVED_COLUMNS so they can never be confused with source data. Nothing is imputed: a blank in the source stays blank
and is described in `data_quality_flags`.
"""
import json

import pandas as pd

from . import address as A
from . import config
from .pops_source import latest_raw_csv

# BINs ending in 000000 are DCP/DOF "building not yet assigned" placeholders (one per borough), not real buildings.
DERIVED_COLUMNS = [
    "pops_id", "borough", "bbl", "bin", "bin_is_placeholder", "address_normalized", "street_canonical", "hn_low",
    "hn_high", "address_key", "year_established", "pops_type", "required_hours", "required_size", "required_amenities",
    "other_requirements", "permitted_amenities_text", "under_construction", "data_quality_flags",
    "source_dataset_url", "source_record_url", "source_rows_updated_at", "source_retrieved_at", "source_sha256",
]


def _clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def build() -> pd.DataFrame:
    raw_path, manifest = latest_raw_csv()
    raw = pd.read_csv(raw_path, dtype=str, keep_default_na=False)
    out = raw.copy()
    flags = [[] for _ in range(len(out))]

    out["pops_id"] = raw["pops_number"].str.strip()
    out["borough"] = raw["borough_name"].map(lambda b: A.canonical_borough(b) or _clean(b))
    out["bbl"] = raw["bbl"].map(lambda v: _clean(v).split(".")[0].zfill(10) if _clean(v) else "")
    out["bin"] = raw["bin"].map(lambda v: _clean(v).split(".")[0].zfill(7) if _clean(v) else "")
    out["bin_is_placeholder"] = out["bin"].map(lambda v: bool(v) and v.endswith("000000"))

    canon_street = raw["street_name"].map(lambda s: A.canonical_street(s) if _clean(s) else "")
    out["street_canonical"] = canon_street
    hn = [A.parse_house_number(n, b) for n, b in zip(raw["address_number"], out["borough"])]
    out["hn_low"] = [h["low"] if h else "" for h in hn]
    out["hn_high"] = [h["high"] if h else "" for h in hn]
    out["address_normalized"] = [f"{h['text']} {s}".strip() if h and s else "" for h, s in zip(hn, canon_street)]
    out["address_key"] = [A.address_key(b, n, s) or "" for b, n, s in zip(out["borough"], raw["address_number"], raw["street_name"])]

    out["year_established"] = raw["year_completed"].map(lambda y: "" if _clean(y) in ("", "0") else _clean(y))
    out["pops_type"] = raw["public_space_type"]
    out["required_hours"] = raw["hour_of_access_required"]
    out["required_size"] = raw["size_required"]
    out["required_amenities"] = raw["amenities_required"]
    out["other_requirements"] = raw["other_required"]
    out["permitted_amenities_text"] = raw["permitted_amenities"]
    out["under_construction"] = raw["building_constructed"].str.contains("Under Construction", case=False, na=False)

    for i, r in out.iterrows():
        f = flags[i]
        if not r["bbl"]:
            f.append("missing_bbl")
        if not r["bin"]:
            f.append("missing_bin")
        if r["bin_is_placeholder"]:
            f.append("bin_placeholder_not_matchable")
        if raw.at[i, "year_completed"].strip() == "0":
            f.append("year_completed_is_0_in_source")
        elif not r["year_established"]:
            f.append("missing_year")
        if r["under_construction"]:
            f.append("under_construction")
        if not r["address_key"]:
            f.append("address_not_normalizable")
        if not _clean(raw.at[i, "hour_of_access_required"]):
            f.append("missing_required_hours")
        if not _clean(raw.at[i, "amenities_required"]):
            f.append("missing_required_amenities")
    out["data_quality_flags"] = [";".join(f) for f in flags]

    out["source_dataset_url"] = config.POPS_LANDING_URL
    out["source_record_url"] = out["pops_id"].map(lambda i: f"{config.POPS_PORTAL}/resource/{config.POPS_DATASET_ID}.json?pops_number={i}")
    out["source_rows_updated_at"] = manifest["source_rows_updated_at"]
    out["source_retrieved_at"] = manifest["retrieved_at_utc"]
    out["source_sha256"] = manifest["sha256"]

    # column order: derived identity columns first, then every untouched source column
    lead = ["pops_id", "borough", "address_normalized", "building_name", "bbl", "bin", "latitude", "longitude"]
    ordered = lead + [c for c in out.columns if c not in lead]
    return out[ordered]


def write(df: pd.DataFrame | None = None) -> pd.DataFrame:
    df = build() if df is None else df
    config.PROCESSED.mkdir(parents=True, exist_ok=True)
    df.to_csv(config.POPS_MASTER, index=False)
    (config.PROCESSED / "pops_master.json").write_text(
        json.dumps(df.replace({pd.NA: None}).to_dict(orient="records"), indent=1, default=str), encoding="utf-8")
    return df
