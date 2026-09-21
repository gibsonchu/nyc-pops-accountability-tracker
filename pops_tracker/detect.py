"""Method A: POPS terminology detection in enforcement text.

Three tiers, chosen from a review of every hit across all bulletins (see METHODOLOGY.md, "Keyword discovery"):
  strong   - explicit POPS wording; almost certainly a POPS.
  moderate - phrasing DOB uses for POPS-type spaces that can, rarely, mean something else ("public space").
  weak     - words that mostly appear in addresses or unrelated contexts ("plaza"); never sufficient on their own.
Phrases such as "open to the public" were deliberately excluded: in 5/6 hits they describe construction sites.
"""
import re

# (label, compiled regex). POPS acronym is case-sensitive so "pops up" never matches.
STRONG = [
    ("privately owned public space", re.compile(r"privately[\s-]+owned\s+public\s+spaces?", re.I)),
    ("POPS", re.compile(r"\bPOPS\b")),
]
MODERATE = [
    ("public plaza", re.compile(r"public\s+plazas?", re.I)),
    ("public space", re.compile(r"public\s+spaces?", re.I)),
    ("publicly accessible", re.compile(r"publicly[\s-]+accessible", re.I)),
    ("public access area", re.compile(r"public\s+access\s+(?:area|space)s?", re.I)),
    ("discretionary zoning", re.compile(r"discretionary\s+zoning", re.I)),
    ("zoning resolution ch.37", re.compile(r"\b(?:ZR|Zoning\s+Resolution)\s*(?:§|Section)?\s*37-\d", re.I)),
    ("public pedestrian path", re.compile(r"public\s+pedestrian(?:/bike)?\s+path", re.I)),
]
WEAK = [
    ("plaza", re.compile(r"\bplazas?\b", re.I)),
    ("open air cafe", re.compile(r"open[\s-]+air\s+caf[eé]", re.I)),
    ("arcade", re.compile(r"\barcades?\b", re.I)),
    ("through-block / covered pedestrian space", re.compile(r"through[\s-]+block|covered\s+pedestrian", re.I)),
]


def detect(text: str, address_strings=(), respondent: str = "") -> dict:
    """Returns dict(tier, hits). Weak terms are tested on text with addresses / respondent name blanked out."""
    hits, tier = [], ""
    for label, rx in STRONG:
        if rx.search(text):
            hits.append(label)
            tier = "strong"
    for label, rx in MODERATE:
        if rx.search(text):
            hits.append(label)
            tier = tier or "moderate"
    scrub = text
    for s in list(address_strings) + ([respondent] if respondent else []):
        if s:
            scrub = scrub.replace(s, " ")
    for label, rx in WEAK:
        if rx.search(scrub):
            hits.append(label)
            tier = tier or "weak"
    return {"tier": tier, "hits": hits}
