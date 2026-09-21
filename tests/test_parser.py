from pops_tracker import bulletin_parser as P

BUL = ""
PAGE1 = f"""DOB ISSUES MONTHLY ENFORCEMENT BULLETIN
Below are individual enforcement highlights for
July 2024:
Construction and Design Professionals
{BUL} DOB revoked the license of Jane Doe, after she failed to
supervise.
Brooklyn
{BUL} $10,000 in penalties issued to 1809 Emmons Avenue Development LLC for
violations recorded at 1809 Emmons Ave. DOB inspectors issued violations to the
Privately Owned Public Space (POPS) after finding that 80% of plaza was taken
CONTACT: (212) 393-2126   dobcommunications@buildings.nyc.gov
build safe|live safe   JULY 2024"""
PAGE2 = f"""3
over by two restaurants.
{BUL}
Manhattan
{BUL} $22, 500 in mitigated penalties issued to Ascot Owners, Inc., the owners of 407 Park Avenue, Manhattan, for a
zoning violation.
{BUL} $
Queens
{BUL} $5,000 in total violations issued to Kreisel Co. Inc., the owner of 26-01 1st Street in Queens for x."""
BULLETIN = {"bulletin_id": "2024-07", "bulletin_month": "7", "bulletin_year": "2024", "pdf_url": "u", "local_filename": "f"}


def actions():
    acts, diag = P.parse_bulletin(BULLETIN, {"pages": [PAGE1, PAGE2]})
    return acts, diag


def test_wrapped_marker_and_boilerplate_are_skipped():
    acts, diag = actions()
    assert diag["marker_found"] and not [n for n in diag["notes"] if "orphan" in n]
    assert all("CONTACT" not in a["enforcement_text"] and "build safe" not in a["enforcement_text"] for a in acts)


def test_entry_spanning_a_page_break_is_one_entry():
    acts, _ = actions()
    e = [a for a in acts if "Emmons" in a["enforcement_text"]]
    assert len(e) == 1 and e[0]["source_page"] == 1 and e[0]["source_page_end"] == 2
    assert e[0]["enforcement_text"].endswith("two restaurants.")


def test_empty_bullet_dropped_and_counted_truncated_entry_kept():
    acts, diag = actions()
    assert diag["empty_bullets"] == 1
    assert any(a["enforcement_text"] == "$" for a in acts)      # DOB's own truncated entry is kept, not hidden


def test_penalty_respondent_and_section_borough():
    acts, _ = actions()
    e = next(a for a in acts if "Emmons" in a["enforcement_text"])
    assert (e["penalty_amount"], e["borough"], e["borough_source"]) == (10000, "Brooklyn", "section")
    a = next(a for a in acts if "Ascot" in a["enforcement_text"])
    assert (a["penalty_amount"], a["respondent"]) == (22500, "Ascot Owners, Inc.")   # 'Owners' must not truncate the name
    k = next(a for a in acts if "Kreisel" in a["enforcement_text"])
    assert (k["penalty_amount"], k["respondent"], k["borough"]) == (5000, "Kreisel Co. Inc.", "Queens")
    assert k["penalty_basis"] == "leading_amount_violations_wording"


def test_professional_entry_has_no_address_and_is_flagged_professional():
    acts, _ = actions()
    p = acts[0]
    assert p["professional_section"] and p["address_raw"] == ""


def test_enforcement_ids_are_stable_and_unique():
    a1, _ = actions()
    a2, _ = actions()
    assert [a["enforcement_id"] for a in a1] == [a["enforcement_id"] for a in a2]
    assert len({a["enforcement_id"] for a in a1}) == len(a1)
