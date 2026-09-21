"""NYC Planning Labs Geosearch (Pelias over the Property Address Directory) as the address -> BBL/BIN resolver.

Why: DOB writes "776 6th Ave" while DCP writes "AVENUE OF THE AMERICAS"; only a PAD-backed lookup reliably lands both
on the same tax lot. Results are cached on disk (data/interim/geocode_cache.csv) so runs are reproducible and cheap.

A response is only *accepted* if its echoed house number, street (after our canonicalisation) and county all agree with
the query. Pelias' fuzzy corrections are therefore never trusted blindly; disagreements are stored as 'mismatch'.
"""
import datetime as dt
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import pandas as pd

from . import address as A
from . import config
from .http import session

GEOSEARCH = "https://geosearch.planninglabs.nyc/v2/search"
CACHE = config.INTERIM / "geocode_cache.csv"
FIELDS = ["query_key", "status", "bbl", "bin", "label", "pelias_confidence", "match_type", "returned_number",
          "returned_street", "geocoded_at"]
COUNTY = {"New York County": "Manhattan", "Kings County": "Brooklyn", "Bronx County": "Bronx",
          "Queens County": "Queens", "Richmond County": "Staten Island"}
_lock = threading.Lock()


def query_key(borough, number, street) -> str | None:
    return A.address_key(borough, number, street)


def load_cache() -> dict:
    if not CACHE.exists():
        return {}
    df = pd.read_csv(CACHE, dtype=str, keep_default_na=False)
    return {r["query_key"]: r.to_dict() for _, r in df.iterrows()}


def save_cache(cache: dict):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(list(cache.values())).reindex(columns=FIELDS).sort_values("query_key").to_csv(CACHE, index=False)


def _lookup(borough, number, street) -> dict:
    key = query_key(borough, number, street)
    base = {"query_key": key, "status": "", "bbl": "", "bin": "", "label": "", "pelias_confidence": "", "match_type": "",
            "returned_number": "", "returned_street": "", "geocoded_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()}
    text = f"{number} {street}, {borough}"
    try:
        time.sleep(0.15)
        r = session().get(GEOSEARCH, params={"text": text, "size": 5}, timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
        feats = r.json().get("features", [])
    except Exception as e:
        return {**base, "status": f"error: {type(e).__name__}"}
    want_hn = A.parse_house_number(number, borough)
    want_street = A.canonical_street(street)
    for f in feats:
        p = f.get("properties", {})
        pad = (p.get("addendum") or {}).get("pad") or {}
        rhn = A.parse_house_number(p.get("housenumber"), borough)
        ok = (rhn and want_hn and rhn["text"] == want_hn["text"]
              and A.canonical_street(p.get("street", "")) == want_street
              and COUNTY.get(p.get("county")) == borough and pad.get("bbl"))
        if ok:
            return {**base, "status": "ok", "bbl": pad.get("bbl", ""), "bin": pad.get("bin", ""), "label": p.get("label", ""),
                    "pelias_confidence": str(p.get("confidence", "")), "match_type": p.get("match_type", ""),
                    "returned_number": p.get("housenumber", ""), "returned_street": p.get("street", "")}
    if feats:
        p = feats[0].get("properties", {})
        return {**base, "status": "mismatch", "label": p.get("label", ""), "returned_number": p.get("housenumber", ""),
                "returned_street": p.get("street", "")}
    return {**base, "status": "no_match"}


def geocode_many(addrs: list[tuple], workers: int = 4, retry_errors: bool = True) -> dict:
    """addrs: iterable of (borough, number, street). Returns {query_key: cache_row}. Only uncached keys hit the network."""
    cache = load_cache()
    todo = {}
    wanted = set()
    for b, n, s in addrs:
        k = query_key(b, n, s)
        if k:
            wanted.add(k)
        if k and (k not in cache or (retry_errors and cache[k]["status"].startswith("error"))):
            todo[k] = (b, n, s)
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for row in ex.map(lambda t: _lookup(*t), todo.values()):
                with _lock:
                    cache[row["query_key"]] = row
    # Prune keys no longer produced by the extractor (e.g. lookups made by an earlier, buggier version), so the cache
    # only describes the current dataset. Safe because every run re-derives addresses from ALL bulletins.
    stale = set(cache) - wanted
    if todo or stale:
        cache = {k: v for k, v in cache.items() if k in wanted}
        save_cache(cache)
    return cache
