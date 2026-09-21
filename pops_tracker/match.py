"""Method B: match every enforcement action's property against the POPS master.

Hierarchy (first level that yields any candidate wins):  1 BBL  ->  2 BIN  ->  3 exact normalised address
->  4 address range overlap  ->  5 fuzzy address.  BBL/BIN come from (a) identifiers written in the bulletin text and
(b) the PAD-backed geocoder (geocode.py) applied to the bulletin's street address.

Fuzzy rule: same borough AND same house number (or overlapping range) AND identical numeric tokens in the street name
(so "EAST 57 STREET" can never fuzzy-match "EAST 5 STREET"), then rapidfuzz token_set_ratio on the remaining words.
"""
import re

import pandas as pd
from rapidfuzz import fuzz

from . import address as A
from . import config

CONF_ORDER = {"high": 3, "medium": 2, "low": 1, "none": 0}


class PopsIndex:
    def __init__(self, master: pd.DataFrame):
        m = master.copy()
        self.m = m
        self.by_bbl, self.by_bin, self.by_key, self.by_street = {}, {}, {}, {}
        for _, r in m.iterrows():
            if r["bbl"]:
                self.by_bbl.setdefault(r["bbl"], []).append(r["pops_id"])
            if r["bin"] and not r["bin_is_placeholder"] in (True, "True"):
                self.by_bin.setdefault(r["bin"], []).append(r["pops_id"])
            if r["address_key"]:
                self.by_key.setdefault(r["address_key"], []).append(r["pops_id"])
            if r["street_canonical"] and r["hn_low"] != "":
                self.by_street.setdefault((r["borough"], r["street_canonical"]), []).append(
                    (r["pops_id"], int(r["hn_low"]), int(r["hn_high"])))
        self.streets_by_borough = {}
        for (b, s) in self.by_street:
            self.streets_by_borough.setdefault(b, []).append(s)


def _digits(s: str) -> tuple:
    return tuple(sorted(re.findall(r"\d+", s)))


_DIRS = {"EAST", "WEST", "NORTH", "SOUTH"}
_GENERIC_NAMES = {"plaza", "tower", "towers", "building", "center", "centre", "house", "the", "park", "court", "place"}


def _dirs(s: str) -> tuple:
    return tuple(sorted(t for t in s.split() if t in _DIRS))


def _name_corroborated(building_name: str, text: str) -> bool:
    """Building name written in the bulletin ('Ascot Owners, Inc.' <-> POPS building 'Ascot'). Corroboration only."""
    n = (building_name or "").strip().lower()
    if len(n) < 5 or n in _GENERIC_NAMES:
        return False
    return re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", text.lower()) is not None


def _suffix_variant(a: str, b: str) -> bool:
    """'PARK AVENUE' vs 'PARK AVENUE SOUTH': identical except for one trailing compass word."""
    ta, tb = a.split(), b.split()
    short, long_ = (ta, tb) if len(ta) < len(tb) else (tb, ta)
    return len(long_) == len(short) + 1 and long_[:-1] == short and long_[-1] in _DIRS


def _explicit_ids(identifiers: dict, borough: str | None):
    """BBLs / BINs written in the bulletin text itself."""
    bbls, bins = [], []
    for v in identifiers.get("bbl", []):
        bbls.append(v)
    for blk, lot in identifiers.get("block_lot", []):
        if borough in A.BOROCODE:
            bbls.append(f"{A.BOROCODE[borough]}{int(blk):05d}{int(lot):04d}")
    for v in identifiers.get("bin", []):
        bins.append(v)
    return bbls, bins


def _candidates_from_addresses(action_addrs, idx: PopsIndex, cache: dict):
    """Evaluate each candidate address of an action; return list of evidence dicts."""
    ev = []
    for a in action_addrs:
        if a["borough"]:
            boroughs, inferred = [a["borough"]], False
        else:
            # Borough not stated anywhere: only try boroughs where this exact number+street exists in the POPS master.
            boroughs = [b for b in A.BOROCODE if A.address_key(b, a["number"], a["street"]) in idx.by_key]
            inferred = True
        for b in boroughs:
            key = A.address_key(b, a["number"], a["street"])
            if not key:
                continue
            g = cache.get(key) or {}
            ev.append({"query_key": key, "geo_bbl": g.get("bbl", "") if g.get("status") == "ok" else "",
                       "geo_bin": g.get("bin", "") if g.get("status") == "ok" else "",
                       "geo_status": g.get("status", "not_geocoded"), "borough": b, "number": a["number"],
                       "street": a["street"], "borough_inferred": inferred})
    return ev


def match_action(action: dict, addr_evidence: list, idx: PopsIndex) -> dict:
    """Return dict(pops_id, match_method, match_confidence, match_score, match_status, match_candidates, match_notes)."""
    out = {"pops_id": "", "match_method": "none", "match_confidence": "none", "match_score": 0.0,
           "match_status": "no_match", "match_candidates": "", "match_notes": "", "matched_address_key": "",
           "geocoded_bbl": "", "geocoded_bin": ""}
    notes = []
    text_bbls, text_bins = _explicit_ids(action["identifiers_mentioned"], action["borough"] or None)

    geo_bbls = [e["geo_bbl"] for e in addr_evidence if e["geo_bbl"]]
    geo_bins = [e["geo_bin"] for e in addr_evidence if e["geo_bin"]]
    out["geocoded_bbl"], out["geocoded_bin"] = ";".join(dict.fromkeys(geo_bbls)), ";".join(dict.fromkeys(geo_bins))

    def finish(level, pops_ids, conf, score, method):
        ids = list(dict.fromkeys(pops_ids))
        if len(ids) == 1:
            out.update(pops_id=ids[0], match_method=method, match_confidence=conf, match_score=round(score, 3),
                       match_status="matched")
        else:
            out.update(match_method=method, match_confidence="none", match_score=0.0, match_status="ambiguous",
                       match_candidates=";".join(ids))
            notes.append(f"{len(ids)} POPS candidates at level '{method}'")
        out["match_notes"] = "; ".join(notes)
        return out

    # ---- 1. BBL ----
    hits = [(p, "text") for b in text_bbls for p in idx.by_bbl.get(b, [])] + [(p, "geocode") for b in geo_bbls for p in idx.by_bbl.get(b, [])]
    if hits:
        ids = [p for p, _ in hits]
        src = sorted({s for _, s in hits})
        # corroboration: does an exact address key also point at the same POPS?
        corro = any(e["query_key"] in idx.by_key and set(idx.by_key[e["query_key"]]) & set(ids) for e in addr_evidence)
        notes.append(f"bbl via {'+'.join(src)}" + ("; address also agrees" if corro else ""))
        return finish("bbl", ids, "high", 1.0 if corro else 0.95, "bbl")

    # ---- 2. BIN ----
    hits = [p for b in text_bins + geo_bins for p in idx.by_bin.get(b, [])]
    if hits:
        notes.append("bin via " + ("text" if text_bins else "geocode"))
        return finish("bin", hits, "high", 0.9, "bin")

    # ---- 3. exact normalised address ----
    hits = [(p, e) for e in addr_evidence for p in idx.by_key.get(e["query_key"], [])]
    if hits:
        ids = [p for p, _ in hits]
        e0 = hits[0][1]
        conf, score = "high", 0.9
        if e0["geo_bbl"] and idx.m.loc[idx.m.pops_id == ids[0], "bbl"].iloc[0] not in ("", e0["geo_bbl"]):
            conf, score = "medium", 0.6
            notes.append("exact address match, but geocoded BBL differs from POPS BBL")
        elif e0["geo_status"] != "ok":
            notes.append(f"geocoder could not confirm ({e0['geo_status']})")
        if e0.get("borough_inferred"):
            conf, score = "medium", min(score, 0.7)
            notes.append("borough not stated in bulletin; inferred from the unique POPS address")
        out["matched_address_key"] = e0["query_key"]
        return finish("address_exact", ids, conf, score, "address_exact")

    # ---- 4. house-number range overlap on identical street ----
    rng = []
    for e in addr_evidence:
        hn = A.parse_house_number(e["number"], e["borough"])
        if not hn:
            continue
        for pid, lo, hi in idx.by_street.get((e["borough"], A.canonical_street(e["street"])), []):
            if (hn["low"] <= hi and hn["high"] >= lo) and (hn["kind"] == "range" or lo != hi):
                rng.append((pid, e))
    if rng:
        out["matched_address_key"] = rng[0][1]["query_key"]
        notes.append("house-number range overlap")
        return finish("address_range", [p for p, _ in rng], "medium", 0.75, "address_range")

    # ---- 5. fuzzy ----
    # Identity-bearing tokens (numbers, compass words) must be identical, so EAST 57 can never fuzzy-match WEST 57 or
    # EAST 5. A trailing-compass-word variant ("PARK AVENUE" ~ "PARK AVENUE SOUTH") is a separate, lower-confidence case.
    best = []
    for e in addr_evidence:
        hn = A.parse_house_number(e["number"], e["borough"])
        if not hn:
            continue
        street = A.canonical_street(e["street"])
        for cand_street in idx.streets_by_borough.get(e["borough"], []):
            if cand_street == street:
                continue
            variant = _suffix_variant(street, cand_street)
            if not variant and (_digits(cand_street) != _digits(street) or _dirs(cand_street) != _dirs(street)):
                continue
            score = 88.0 if variant else fuzz.ratio(street, cand_street)
            if score < config.FUZZY_REVIEW_FLOOR:
                continue
            for pid, lo, hi in idx.by_street[(e["borough"], cand_street)]:
                if lo <= hn["high"] and hi >= hn["low"]:
                    best.append((score, pid, e, cand_street, variant))
    if best:
        top = max(b[0] for b in best)
        winners = [b for b in best if b[0] == top]
        conf = "medium" if (top >= config.FUZZY_AUTO_ACCEPT and not winners[0][4]) else "low"
        kind = "street suffix variant" if winners[0][4] else f"fuzzy street score {top:.0f}"
        notes.append(f"{kind} ('{winners[0][2]['street']}' ~ '{winners[0][3]}')")
        if len({w[1] for w in winners}) == 1:
            bname = idx.m.loc[idx.m.pops_id == winners[0][1], "building_name"].iloc[0]
            if _name_corroborated(bname, action["enforcement_text"]):
                conf = "medium"
                notes.append(f"building name '{bname}' appears in the bulletin text")
        out["matched_address_key"] = winners[0][2]["query_key"]
        return finish("address_fuzzy", [w[1] for w in winners], conf, top / 100 * 0.8, "address_fuzzy")

    notes.append("no address evidence" if not addr_evidence else "no POPS at this address")
    out["match_notes"] = "; ".join(notes)
    return out
