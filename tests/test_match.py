import pandas as pd
import pytest
from pops_tracker import match as M


def master():
    rows = [
        ("M1", "Manhattan", "776", "6 AVENUE", "1008280001", "1015632", ""),
        ("M2", "Manhattan", "200", "EAST 24 STREET", "1009000001", "1012345", "Crystal House"),
        ("M3", "Manhattan", "407", "PARK AVENUE SOUTH", "1008840001", "1099999", "Ascot"),
        ("M4", "Manhattan", "114", "WEST 47 STREET", "1012700001", "1055555", ""),
        ("M5", "Manhattan", "322", "WEST 57 STREET", "1010000001", "1066666", "Sheffield"),
    ]
    df = pd.DataFrame(rows, columns=["pops_id", "borough", "num", "street_canonical", "bbl", "bin", "building_name"])
    df["hn_low"] = df["num"].astype(int); df["hn_high"] = df["num"].astype(int)
    df["address_key"] = df["borough"] + "|" + df["num"] + "|" + df["street_canonical"]
    df["bin_is_placeholder"] = False
    df["address_normalized"] = df["num"] + " " + df["street_canonical"]
    return df


def action(text="x", ids=None, borough="Manhattan"):
    return {"identifiers_mentioned": ids or {}, "borough": borough, "enforcement_text": text}


def ev(number, street, bbl="", bin_="", borough="Manhattan"):
    from pops_tracker import address as A
    return {"query_key": A.address_key(borough, number, street), "geo_bbl": bbl, "geo_bin": bin_, "geo_status": "ok" if bbl else "no_match",
            "borough": borough, "number": number, "street": street}


IDX = M.PopsIndex(master())


def test_bbl_beats_address_and_is_high_confidence():
    r = M.match_action(action(), [ev("774", "Sixth Avenue", bbl="1008280001")], IDX)
    assert (r["pops_id"], r["match_method"], r["match_confidence"]) == ("M1", "bbl", "high")


def test_exact_address_when_no_geocode():
    r = M.match_action(action(), [ev("776", "Avenue of the Americas")], IDX)
    assert (r["pops_id"], r["match_method"]) == ("M1", "address_exact")


def test_east_never_fuzzy_matches_west_and_numbers_are_identity_bearing():
    # regressions: '200 West 24th' -> EAST 24 and '322 East 57th' -> WEST 57 were false fuzzy matches
    assert M.match_action(action(), [ev("200", "West 24th Street")], IDX)["match_status"] == "no_match"
    assert M.match_action(action(), [ev("322", "East 57th Street")], IDX)["match_status"] == "no_match"


def test_short_range_does_not_overlap_unrelated_pops():
    # regression: '321-3 West 47th' must not match 114 West 47th
    assert M.match_action(action(), [ev("321-3", "West 47th Street")], IDX)["match_status"] == "no_match"


def test_suffix_variant_is_low_until_name_corroborates_and_never_high():
    r = M.match_action(action("Ascot Owners, Inc. owners of 407 Park Avenue"), [ev("407", "Park Avenue")], IDX)
    assert (r["pops_id"], r["match_confidence"]) == ("M3", "medium") and "Ascot" in r["match_notes"]
    r = M.match_action(action("some other owner of 407 Park Avenue"), [ev("407", "Park Avenue")], IDX)
    assert (r["pops_id"], r["match_confidence"]) == ("M3", "low")


def test_placeholder_bins_are_never_used():
    m = master(); m.loc[0, "bin"] = "1000000"; m.loc[0, "bin_is_placeholder"] = True
    idx = M.PopsIndex(m)
    assert idx.by_bin.get("1000000") is None
