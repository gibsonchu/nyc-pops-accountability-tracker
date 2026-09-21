import pytest
from pops_tracker import address as A


@pytest.mark.parametrize("raw,want", [
    ("E. 57th St.", "EAST 57 STREET"), ("East Fifty-Seventh Street", "EAST 57 STREET"), ("Fifth Avenue", "5 AVENUE"),
    ("5th Ave", "5 AVENUE"), ("Avenue of the Americas", "6 AVENUE"), ("6th Ave.", "6 AVENUE"),
    ("East 217 th St.", "EAST 217 STREET"), ("Tenth Avenue", "10 AVENUE"), ("Park Avenue South", "PARK AVENUE SOUTH"),
])
def test_canonical_street(raw, want):
    assert A.canonical_street(raw) == want


def test_house_number_short_range_is_completed_not_sorted():
    # regression: "321-3" was parsed as 3..321 and matched a POPS at 114 West 47th
    assert A.parse_house_number("321-3", "Manhattan")["high"] == 323
    assert A.parse_house_number("348-58", "Manhattan")["high"] == 358


def test_queens_hyphen_is_compound_number_not_range():
    assert A.parse_house_number("26-01", "Queens")["kind"] == "queens"


@pytest.mark.parametrize("text,number,street", [
    ("owner of 3 Park Avenue, Manhattan, for", "3", "Park Avenue"),          # 'Park' is not a street type
    ("at 1 Metrotech Center, Brooklyn", "1", "Metrotech Center"),
    ("at 1345 Avenue of the Americas. DOB", "1345", "Avenue of the Americas"),
    ("at 2210 Avenue N, Brooklyn", "2210", "Avenue N"),
    ("at 57 St. Nicholas Avenue, Brooklyn", "57", "St. Nicholas Avenue"),
    ("at 3336 third Ave", "3336", "third Ave"),
    ("at 825 8 th Avenue. DOB", "825", "8th Avenue"),
])
def test_extract_addresses(text, number, street):
    a = A.extract_addresses(text)[0]
    assert (a["number"], a["street"]) == (number, street)


def test_quantities_are_not_addresses():
    assert A.extract_addresses("for having 45 tables and 180 chairs in the Plaza") == []


def test_multiple_addresses_in_one_entry():
    t = "properties in Manhattan, including 1801 2nd Avenue, 154 West 71st Street, and 75 West End Avenue, concerning"
    assert [a["number"] for a in A.extract_addresses(t)] == ["1801", "154", "75"]


@pytest.mark.parametrize("raw,want", [
    ("West 47 St", "WEST 47 STREET"),            # regression: 'St' after a bare number is STREET, not an ordinal suffix
    ("East 21 St.", "EAST 21 STREET"),
    ("East 217 th St", "EAST 217 STREET"),
    ("1 st Avenue", "1 AVENUE"),
    ("West 47th St.", "WEST 47 STREET"),
])
def test_bare_number_st_is_street_not_ordinal(raw, want):
    assert A.canonical_street(raw) == want
