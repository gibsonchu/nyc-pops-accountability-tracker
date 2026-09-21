"""Address normalization following NYC (DCP/Geosupport/PAD) conventions.

Canonical form mirrors how DCP and PAD write street names: upper-case, spelled-out street types, numbered streets
and avenues as bare numbers without ordinal suffix ("WEST 57 STREET", "6 AVENUE", "5 AVENUE"), directions spelled
out. Both the POPS master and every address pulled from a bulletin pass through `canonical_street` so that
"E. 57th St.", "East Fifty-Seventh Street" and "EAST 57 STREET" collapse to one key.
"""
import re

BOROUGHS = {
    "MANHATTAN": "Manhattan", "NEW YORK": "Manhattan", "MN": "Manhattan", "1": "Manhattan",
    "BRONX": "Bronx", "THE BRONX": "Bronx", "BX": "Bronx", "2": "Bronx",
    "BROOKLYN": "Brooklyn", "BK": "Brooklyn", "3": "Brooklyn",
    "QUEENS": "Queens", "QN": "Queens", "4": "Queens",
    "STATEN ISLAND": "Staten Island", "SI": "Staten Island", "5": "Staten Island",
}
BOROCODE = {"Manhattan": 1, "Bronx": 2, "Brooklyn": 3, "Queens": 4, "Staten Island": 5}

_UNITS = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4, "FIFTH": 5, "SIXTH": 6, "SEVENTH": 7, "EIGHTH": 8,
          "NINTH": 9, "TENTH": 10, "ELEVENTH": 11, "TWELFTH": 12, "THIRTEENTH": 13, "FOURTEENTH": 14,
          "FIFTEENTH": 15, "SIXTEENTH": 16, "SEVENTEENTH": 17, "EIGHTEENTH": 18, "NINETEENTH": 19}
_TENS_ORD = {"TWENTIETH": 20, "THIRTIETH": 30, "FORTIETH": 40, "FIFTIETH": 50, "SIXTIETH": 60, "SEVENTIETH": 70,
             "EIGHTIETH": 80, "NINETIETH": 90}
_TENS = {"TWENTY": 20, "THIRTY": 30, "FORTY": 40, "FIFTY": 50, "SIXTY": 60, "SEVENTY": 70, "EIGHTY": 80, "NINETY": 90}
_WORD_ORD = {**_UNITS, **_TENS_ORD}
for _t, _n in _TENS.items():
    for _u, _v in list(_UNITS.items())[:9]:
        _WORD_ORD[f"{_t}-{_u}"] = _n + _v
        _WORD_ORD[f"{_t} {_u}"] = _n + _v

SUFFIX = {
    "ST": "STREET", "STR": "STREET", "AVE": "AVENUE", "AV": "AVENUE", "BLVD": "BOULEVARD", "BL": "BOULEVARD",
    "RD": "ROAD", "PL": "PLACE", "DR": "DRIVE", "PKWY": "PARKWAY", "PKY": "PARKWAY", "SQ": "SQUARE", "LN": "LANE",
    "CT": "COURT", "HWY": "HIGHWAY", "TER": "TERRACE", "TERR": "TERRACE", "EXPY": "EXPRESSWAY", "PLZ": "PLAZA",
    "CIR": "CIRCLE", "CONC": "CONCOURSE", "BWAY": "BROADWAY", "PROM": "PROMENADE", "TPKE": "TURNPIKE",
}
DIRECTION = {"E": "EAST", "W": "WEST", "N": "NORTH", "S": "SOUTH"}
STREET_TYPES = ("STREET", "AVENUE", "BOULEVARD", "ROAD", "PLACE", "DRIVE", "PARKWAY", "SQUARE", "LANE", "COURT",
                "HIGHWAY", "TERRACE", "EXPRESSWAY", "PLAZA", "CIRCLE", "CONCOURSE", "PROMENADE", "TURNPIKE", "WAY",
                "WALK", "SLIP", "ROW", "ALLEY", "PATH", "OVAL", "LOOP", "BROADWAY", "BOWERY", "PARK")

# Known one-off aliases in the POPS universe (Manhattan unless noted). Keys are post-canonicalisation strings.
ALIASES = {
    "AVENUE OF THE AMERICAS": "6 AVENUE",
    "AVENUE OF AMERICAS": "6 AVENUE",
    "SIXTH AVENUE": "6 AVENUE",
    "CENTRAL PARK W": "CENTRAL PARK WEST",
    "CPW": "CENTRAL PARK WEST",
    "PARK AVENUE S": "PARK AVENUE SOUTH",
    "FDR DRIVE": "FRANKLIN D ROOSEVELT DRIVE",
    "F D R DRIVE": "FRANKLIN D ROOSEVELT DRIVE",
    "FRANKLIN DELANO ROOSEVELT DRIVE": "FRANKLIN D ROOSEVELT DRIVE",
    "WEST STREET": "WEST STREET",
}


def canonical_borough(value) -> str | None:
    if value is None:
        return None
    v = re.sub(r"[^A-Za-z0-9 ]", "", str(value)).strip().upper()
    v = re.sub(r"\bTHE\b\s*", "", v) if v.startswith("THE BRONX") else v
    return BOROUGHS.get(v)


def _ordinal_words_to_numbers(s: str) -> str:
    # longest keys first so "TWENTY-FIRST" wins over "FIRST"
    for word in sorted(_WORD_ORD, key=len, reverse=True):
        s = re.sub(rf"\b{word}\b", str(_WORD_ORD[word]), s)
    return s


_STREET_TYPE_WORD = r"(?:AVENUE|AVE|STREET|STR|PLACE|PL|ROAD|RD|BOULEVARD|BLVD|DRIVE|DR|PARKWAY|LANE|COURT|TERRACE|PLAZA)"


def _collapse_spaced_ordinals(s: str, flags=0) -> str:
    """Repair '217 th St' -> '217th St' WITHOUT destroying '47 St' (= 47 Street).
    ND/RD/TH after a digit are unambiguous ordinals. 'ST' is an ordinal only after a number ending in 1 (not 11) AND
    when a street-type word follows ('1 st Avenue'); otherwise it is the abbreviation for STREET and must be kept."""
    s = re.sub(r"(\d)\s+(nd|rd|th)\b", r"\1\2", s, flags=re.I)
    s = re.sub(rf"(?<!1)(1)\s+(st)\b(?=\s+{_STREET_TYPE_WORD}\b)", r"\1\2", s, flags=re.I | flags)
    s = re.sub(rf"(\d*[02-9]1|(?<!\d)1)\s+(st)\b(?=\s+{_STREET_TYPE_WORD}\b)", r"\1\2", s, flags=re.I)
    return s


def canonical_street(raw: str) -> str:
    """Canonical street-name key. Never includes the house number."""
    s = str(raw).upper().replace("’", "'").replace("&", " AND ")
    s = re.sub(r"\(.*?\)", " ", s)                          # drop "(aka ...)" asides
    s = _collapse_spaced_ordinals(s)                         # PDF artefact: "217 TH" -> "217TH"
    s = re.sub(r"[.,]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = _ordinal_words_to_numbers(s)
    s = re.sub(r"\b(\d+)(?:ST|ND|RD|TH)\b", r"\1", s)        # drop ordinal suffix
    toks = s.split(" ")
    if len(toks) > 1 and toks[0] in DIRECTION:               # E 57 ST -> EAST 57 ST
        toks[0] = DIRECTION[toks[0]]
    if len(toks) > 1 and toks[-1] in DIRECTION and len(toks) > 2:  # PARK AVENUE S
        toks[-1] = DIRECTION[toks[-1]]
    toks = [SUFFIX.get(t, t) if i > 0 else t for i, t in enumerate(toks)]
    s = " ".join(toks)
    s = re.sub(r"\bSAINT\b", "ST", s)                        # "ST" as saint vs street handled by position above
    return ALIASES.get(s, s)


_NUM_RE = re.compile(r"^\s*(\d+)(?:\s*-\s*(\d+))?\s*([A-Z]?)\s*$", re.I)


def parse_house_number(raw, borough: str | None = None):
    """Return dict(kind, low, high, text, suffix). Queens 'NN-NN' is a compound number, elsewhere it is a range."""
    if raw is None or str(raw).strip() == "":
        return None
    m = _NUM_RE.match(str(raw).replace("–", "-"))
    if not m:
        return None
    a, b, suffix = m.group(1), m.group(2), (m.group(3) or "").upper()
    if b is None:
        return {"kind": "single", "low": int(a), "high": int(a), "text": a + suffix, "suffix": suffix}
    if borough == "Queens":
        text = f"{a}-{b}{suffix}"
        return {"kind": "queens", "low": int(a) * 1000 + int(b), "high": int(a) * 1000 + int(b), "text": text,
                "suffix": suffix}
    # DOB shorthand: "321-3" means 321-323, "348-58" means 348-358. Complete the second number from the first.
    lo = int(a)
    hi = int(a[:len(a) - len(b)] + b) if len(b) < len(a) else int(b)
    if hi < lo:                     # not a coherent range (e.g. "84- 06" in a Queens-style number): keep low end only
        return {"kind": "single", "low": lo, "high": lo, "text": a + suffix, "suffix": suffix, "note": "unparseable_range"}
    return {"kind": "range", "low": lo, "high": hi, "text": f"{lo}-{hi}", "suffix": suffix}


def address_key(borough, number, street) -> str | None:
    """Exact-match key: 'Manhattan|776|6 AVENUE'. None when any component is missing."""
    b = canonical_borough(borough) or borough
    hn = parse_house_number(number, b)
    if not (b and hn and street):
        return None
    return f"{b}|{hn['text']}|{canonical_street(street)}"


# ---- Extraction of addresses from free text --------------------------------------------------
# "Park" is deliberately NOT a street type (it would truncate "3 Park Avenue" to "Park"); "Center" is (MetroTech Center).
_TYPE_WORDS = sorted({t.title() for t in STREET_TYPES if t != "PARK"} | {k.title() for k in SUFFIX} | {"Bway", "Blvd", "Center", "Centre"},
                     key=len, reverse=True)
_TYPES = "|".join(_TYPE_WORDS)
_ORD_WORDS = "|".join(sorted(_UNITS | _TENS_ORD, key=len, reverse=True)).lower()
_CAP = rf"(?:[A-Z0-9][\w'’-]*\.?|(?i:{_ORD_WORDS})\b)"   # capitalised token, or a lowercase ordinal word ("third Ave")
_ADDR_RE = re.compile(
    rf"""(?<![\w$,.\-/])
    (?P<num>\d{{1,5}}(?:\s?-\s?\d{{1,5}})?[A-Za-z]?)\s+
    (?P<street>
        (?i:Avenue\s+of\s+(?:the\s+)?Americas)                       # before the generic branch, or it loses to "Avenue"
      | (?:Central|Prospect)\s+Park\s+(?i:West|South|North|Southwest|East)\b
      | (?i:Avenue|Ave\.?)\s+[A-Z]\b(?![a-z'’])                        # Avenue A ... Avenue Z
      | (?:(?i:N|S|E|W|North|South|East|West)\.?\s+)?
        (?:{_CAP}\s+){{1,4}}?                                          # at least one name token before the type
        (?:(?i:{_TYPES})\b\.?(?:\s+(?:South|North|East|West)\b)?)
      | (?:(?i:West\s+)?(?i:Broadway|Bowery))\b
    )""", re.X)
_ANCHOR_RE = re.compile(
    r"(?i:\b(?:at|located at|recorded at|owners? of|premises at|site at|building at|property at|issued at|address(?:es)? at|"
    r"of the building at|of)\s*(?:the\s+)?(?:[A-Za-z' ]{0,30}?)?)\s*$")
_BOROUGH_AFTER = re.compile(
    r"^[\s,(]*(?:in\s+)?(?:the\s+)?(?P<b>Manhattan|Brooklyn|Bronx|Queens|Staten Island|New York(?:,?\s*NY)?)\b", re.I)


def fix_pdf_spacing(text: str) -> str:
    """Repair spacing artefacts seen in DOB PDFs: '217 th St', '$22, 500', 'St. ,'"""
    return _collapse_spaced_ordinals(text)


def extract_addresses(text: str) -> list[dict]:
    """All address-looking spans in order. Each: raw, number, street, borough_in_text, anchored, start, end."""
    text = fix_pdf_spacing(text)
    out = []
    for m in _ADDR_RE.finditer(text):
        street = m.group("street").strip().rstrip(".").strip()
        # a run of "45 tables and 180 chairs in the Plaza" must not become an address
        if re.search(r"\b(?:tables?|chairs?|feet|foot|units?|floors?|stor(?:y|ies)|percent|square)\b", street, re.I):
            continue
        # sentence fragments like "3 Street" preceded by lowercase words are not addresses
        head = text[max(0, m.start() - 45):m.start()]
        after = text[m.end():m.end() + 40]
        bm = _BOROUGH_AFTER.match(after)
        out.append({
            "raw": m.group(0).strip(), "number": re.sub(r"\s", "", m.group("num")), "street": street,
            "borough_in_text": canonical_borough(bm.group("b")) if bm else None,
            "anchored": bool(_ANCHOR_RE.search(head)), "start": m.start(), "end": m.end(),
        })
    return out


_ID_PATTERNS = {
    "bin": re.compile(r"\bBIN\s*(?:No\.?|#|number)?[:\s]*(\d{7})\b", re.I),
    "block_lot": re.compile(r"\bBlock\s*(?:No\.?|#)?\s*(\d{1,5})[,\s]+Lot\s*(?:No\.?|#)?\s*(\d{1,4})\b", re.I),
    "bbl": re.compile(r"\bBBL\s*(?:No\.?|#)?[:\s]*(\d{10})\b", re.I),
    "job_number": re.compile(r"\b(?:Job|Application)\s*(?:No\.?|#|number)?[:\s]*([A-Z]?\d{8,9})\b", re.I),
    "ecb_violation": re.compile(r"\bECB\s*(?:violation)?\s*(?:No\.?|#)?[:\s]*(\d{8,10}[A-Z]?)\b", re.I),
}


def extract_identifiers(text: str) -> dict:
    ids = {}
    for k, rx in _ID_PATTERNS.items():
        hits = [m.groups() if len(m.groups()) > 1 else m.group(1) for m in rx.finditer(text)]
        if hits:
            ids[k] = hits
    return ids
