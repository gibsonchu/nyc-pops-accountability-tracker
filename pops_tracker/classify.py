"""Step 6: controlled violation taxonomy for POPS-related enforcement.

Rule-based and intentionally transparent: each category is a list of regexes over DOB's own wording. An action can
carry several categories. The classification NEVER replaces DOB's text: `violation_description` is kept verbatim and
`violation_category_terms` records exactly which phrases fired, so a human can audit every label.
"""
import re

CATEGORIES = [
    "access / closure", "seating", "landscaping", "trees", "signage", "fountain / water feature", "bicycle parking",
    "maintenance", "unauthorized private use", "unauthorized design modification", "obstruction", "hours", "other",
]

_RULES = {
    "access / closure": [r"padlock", r"\bchain(?:ed)?\b", r"locked", r"closed\s+to\s+the\s+public", r"\bclosed\b.*\bsign\b",
                         r"(?:deny|denied|denying|disallow\w*|restrict\w*|limit\w*|prevent\w*)\s+(?:the\s+)?(?:public\s+)?access",
                         r"access\s+(?:was\s+)?(?:denied|restricted|blocked|prevented)", r"blocking\s+the\s+public",
                         r"cordon\w*", r"\bgated?\b", r"entrances?\s+(?:were|was)\s+(?:closed|blocked|locked)",
                         r"not\s+(?:be\s+)?open\s+to\s+the\s+public", r"fenced\s+off"],
    "seating": [r"\bseating\b", r"\bchairs?\b", r"\btables?\b", r"\bbench(?:es)?\b", r"\bledges?\b"],
    "landscaping": [r"landscap\w*", r"plantings?", r"planters?", r"\bplants?\b", r"\bflowers?\b", r"\blawn\b", r"\bgardens?\b"],
    "trees": [r"\btrees?\b"],
    "signage": [r"\bsignage\b", r"\bsigns?\b", r"\bplaques?\b", r"\bmarquee\b"],
    "fountain / water feature": [r"fountains?", r"water\s+features?", r"waterfalls?", r"\bponds?\b", r"reflecting\s+pool"],
    "bicycle parking": [r"bicycle", r"bike\s+(?:rack|parking)"],
    "maintenance": [r"maintain\w*", r"maintenance", r"\bbroken\b", r"\bdamaged?\b", r"deteriorat\w*", r"\bdebris\b",
                    r"graffiti", r"not\s+(?:operational|functioning|working)", r"non-?function\w*", r"non-?operational",
                    r"\bdisrepair\b", r"electrical\s+wiring", r"\blamp\s*posts?\b", r"\blighting\b", r"\bcracked\b"],
    "unauthorized private use": [r"restaurants?", r"\bcaf[eé]s?\b", r"nurs(?:e)?ry\s+school", r"school", r"private\s+(?:use|event|party)",
                                 r"commercial\s+use", r"\bstorage\b", r"taken\s+over", r"outdoor\s+dining", r"\bkiosks?\b",
                                 r"\bvendors?\b", r"exclusive\s+use", r"without\s+.*certification", r"\bused\s+(?:by|for|as)\b"],
    "unauthorized design modification": [r"without\s+(?:prior\s+)?(?:approval|permit|authorization|DCP|(?:the\s+)?required\s+approval)",
                                         r"design\s+changes?", r"unapproved", r"\bmodif\w*", r"\balter\w*", r"installed\s+.*without",
                                         r"\bmarquee\b", r"\benclos\w*", r"\bconvert\w*", r"changes\s+to\s+(?:a|the)\s+(?:public\s+)?plaza"],
    "obstruction": [r"obstruct\w*", r"\bblock(?:ed|ing)\b", r"impeded?|impeding", r"\bspike", r"\bclutter\w*"],
    "hours": [r"\bhours\b", r"open\s+24", r"24[\s-]hour", r"closed\s+(?:at|during|after)\s+(?:night|hours)", r"after[\s-]hours",
              r"required\s+hours"],
}
_COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in _RULES.items()}


def classify(text: str) -> dict:
    cats, terms = [], {}
    for cat in CATEGORIES[:-1]:
        found = []
        for rx in _COMPILED[cat]:
            m = rx.search(text)
            if m:
                found.append(m.group(0))
        if found:
            cats.append(cat)
            terms[cat] = sorted(set(t.lower() for t in found))
    if not cats:
        cats = ["other"]
    return {"categories": cats, "terms": terms}
