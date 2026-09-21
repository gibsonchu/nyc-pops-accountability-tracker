import pandas as pd
import pytest
from pops_tracker import bulletins as B, detect as D, classify as C, config

HTML = """<html><body>
<a href="/assets/buildings/pdf/0724_enforcement_action_bulletin.pdf">Enforcement Action Bulletin: July 2024</a>
<a href="/assets/buildings/pdf/0724_enforcement_action_bulletin.pdf"></a>
<a href="/assets/buildings/pdf/0121_enforcement_action_bulletin.pdf">Enforcement Action Bulletin: January 2020</a>
<a href="/assets/buildings/pdf/some_new_layout_enforcement.pdf">Enforcement Action Bulletin: August 2026</a>
<a href="/assets/buildings/pdf/unrelated.pdf">Annual report</a>
</body></html>"""


def test_index_parsing_dedupes_and_flags_label_conflict_and_new_filename_pattern():
    recs = {B.bulletin_id(r): r for r in B.parse_index(HTML)}
    assert set(recs) == {"2024-07", "2021-01", "2026-08"}            # unrelated.pdf ignored, duplicate anchor merged
    assert recs["2024-07"]["index_label"].startswith("Enforcement Action Bulletin")   # label survives the blank duplicate
    assert recs["2021-01"]["label_conflict"] is True                 # filename says 0121, label says January 2020
    assert recs["2026-08"]["filename_pattern_ok"] is False           # falls back to label, flagged as structure change


def test_discover_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REGISTRY_DIR", tmp_path)
    monkeypatch.setattr(config, "BULLETIN_REGISTRY", tmp_path / "reg.csv")
    r1 = B.discover(HTML)
    r2 = B.discover(HTML)
    assert len(r1) == len(r2) == 3 and r1["date_discovered"].tolist() == r2["date_discovered"].tolist()


@pytest.mark.parametrize("text,tier", [
    ("owner of the Privately-Owned Public Space (POPS) for blocking access", "strong"),
    ("where a public plaza at the location was closed to the public", "moderate"),
    ("violation of discretionary zoning", "moderate"),
    ("the site was found to be open to the public and the shed inadequate", ""),   # construction-site phrasing: no hit
    ("a scaffold at 5100 Kings Plaza, Brooklyn", ""),                              # 'plaza' only inside an address
    ("chairs pops up", ""),                                                        # lower-case 'pops' is not the acronym
])
def test_detect_tiers(text, tier):
    addrs = ["5100 Kings Plaza"] if "Kings Plaza" in text else []
    assert D.detect(text, addrs)["tier"] == tier


def test_classification_is_multilabel_and_falls_back_to_other():
    c = C.classify("missing required tables, chairs and trees; metal spikes obstructed seating; entrances padlocked")
    assert {"seating", "trees", "obstruction", "access / closure"} <= set(c["categories"])
    assert C.classify("failure to file a form")["categories"] == ["other"]
