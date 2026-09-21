"""Step 4: split a bulletin's extracted text into individual enforcement actions and pull structured fields.

Design rules (this feeds journalism, so it is conservative):
  * The verbatim paragraph is always kept (`enforcement_text`); every extracted field is a convenience.
  * A field that cannot be extracted stays blank. Nothing is guessed.
  * Anything structurally unexpected is returned in `diagnostics` so QC can flag it.
"""
import hashlib
import re

from . import address as A

BULLET_CHARS = ("", "•", "●", "▪", "◦", "·")
BOROUGH_HEADERS = {"bronx": "Bronx", "brooklyn": "Brooklyn", "manhattan": "Manhattan", "queens": "Queens",
                   "staten island": "Staten Island"}
OTHER_HEADERS = {"construction and design professionals", "construction professionals", "design professionals",
                 "citywide", "multiple boroughs", "other"}
MARKER_RE = re.compile(r"individual\s+enforcement\s+highlights", re.I)

_BOILERPLATE = [
    re.compile(r"^CONTACT:", re.I),
    re.compile(r"^build safe\s*\|\s*live safe", re.I),
    re.compile(r"^\d{1,2}$"),                                      # bare page number
    re.compile(r"^dobcommunications@", re.I),
    re.compile(r"^Page \d+ of \d+$", re.I),
]

# leading penalty clause: "$4,000 in penalties issued to ..." (allow the "$22, 500" spacing artefact)
_MONEY = r"\$\s?(\d{1,3}(?:,\s?\d{3})+|\d+)(?:\.\d{2})?"
_MONEY_RE = re.compile(_MONEY)
_ADJ = r"(?:total|combined|daily|mitigated|default|civil|additional|cumulative|aggregate)"
_LEAD_PENALTY_RE = re.compile(rf"^\s*{_MONEY}\s+(?:in\s+)?(?:{_ADJ}[,\s]+)*(?:penalt(?:y|ies)|fines?|violations?)\b", re.I)
_RESPONDENT_RE = re.compile(
    r"(?:issued\s+to|imposed\s+(?:on|upon)|issued\s+against|levied\s+(?:on|against)|assessed\s+(?:to|against)|"
    r"issued\s+for\s+the\s+benefit\s+of)\s+"
    r"(?:(?P<owner_role>(?:the\s+)?(?:property|building|home|unit|apartment|condominium|co-?op)?\s*owners?)[,:]?\s+)?"
    r"(?P<who>.+?)(?=,\s*(?:the\s+)?owners?\b|\s+the\s+owners?\b|\s(?:for|at|after|following|due|related|regarding|who|which|whose|"
    r"as\s+a\s+result|where|when|during|because|by)\b|;\s|"
    r"(?<!\bCo)(?<!\bInc)(?<!\bCorp)(?<!\bLtd)(?<!\bAssoc)(?<!\bCtr)(?<!\bSt)(?<!\bJr)(?<!\bSr)(?<!\bBros)(?<!\bMgmt)"
    r"(?<!\bDev)(?<!\bAve)(?<!\bCo)(?<!\bL\.P)(?<!\bN\.Y)\.\s+(?=[A-Z])|$)", re.I)
_ROLE_RE = re.compile(
    r"^(?P<role>Safety Registrant|Registered General Contractor|General Contractor|Tracking Number Holder|"
    r"Construction Superintendent|Superintendent|Licensed Site Safety Manager|Site Safety Manager|Master Plumber|"
    r"Licensed Master Plumber|Master Electrician|Licensed Master Electrician|Registered Architect|Professional Engineer|"
    r"Special Rigger|Rigger|Sign Hanger|Licensed Sign Hanger|Filing Representative|Contractor|Expediter|Owner|"
    r"Lessee|Tenant|Property Manager|Managing Agent)\b[:,]?\s*(?P<name>.+)$", re.I)
_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_DATE_RE = re.compile(rf"\b(?P<m>{_MONTH})\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>\d{{4}})\b", re.I)


def is_boilerplate(line: str) -> bool:
    return any(rx.search(line) for rx in _BOILERPLATE)


def _strip_bullet(line: str):
    """Return (had_bullet, text_without_bullet)."""
    if line and line[0] in BULLET_CHARS:
        return True, line[1:].strip()
    return False, line


def _join_lines(lines: list[str]) -> str:
    """Join wrapped lines into one paragraph, repairing line-end hyphenation without altering the words."""
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if not out:
            out = ln
        elif out.endswith("-") and ln[:1].islower():
            out += ln              # 'site-' + 'safety' -> 'site-safety' (hyphen kept: source compound or break, unknowable)
        else:
            out += " " + ln
    out = re.sub(r"\s+", " ", out)
    return out


def money_to_int(s: str) -> int:
    return int(re.sub(r"[,\s]", "", s))


def split_entries(pages: list[str]) -> tuple[list[dict], dict]:
    """Return (raw_entries, diagnostics). raw_entry = dict(section, page, page_end, lines, had_bullet)."""
    lines = []
    for pno, txt in enumerate(pages, 1):
        for ln in txt.split("\n"):
            s = ln.strip()
            if s and not is_boilerplate(s):
                lines.append((pno, s))

    diag = {"marker_found": False, "n_lines": len(lines), "notes": []}
    start = None
    for i, (pno, s) in enumerate(lines):
        window = " ".join(x[1] for x in lines[i:i + 2])
        if MARKER_RE.search(s) or MARKER_RE.search(window):
            j = i if MARKER_RE.search(s) else i + 1        # line on which the wrapped marker sentence ends
            start, diag["marker_found"] = j + 1, True
            # the marker sentence often wraps: "...highlights for" / "July 2026:" -- consume that tail
            while start < len(lines) and re.match(rf"^(?:for\s+)?(?:{_MONTH}\s+\d{{4}})?:?$", lines[start][1], re.I):
                start += 1
            break
    if start is None:
        # structure changed: fall back to the first recognisable header/bullet and say so.
        diag["notes"].append("marker 'individual enforcement highlights' not found; using first header/bullet")
        for i, (pno, s) in enumerate(lines):
            if s.lower() in BOROUGH_HEADERS or s.lower() in OTHER_HEADERS or s[0] in BULLET_CHARS:
                start = i
                break
        start = start or 0

    entries, cur, section = [], None, None

    def flush():
        nonlocal cur
        if cur and _join_lines(cur["lines"]):
            entries.append(cur)
        elif cur:
            diag["empty_bullets"] = diag.get("empty_bullets", 0) + 1   # stray bullet glyph with no text
        cur = None

    for idx in range(start, len(lines)):
        pno, s = lines[idx]
        had, body = _strip_bullet(s)
        low = s.lower()
        if not had and (low in BOROUGH_HEADERS or low in OTHER_HEADERS):
            flush()
            section = BOROUGH_HEADERS.get(low) or s
            continue
        if had:
            flush()
            cur = {"section": section, "page": pno, "page_end": pno, "lines": [body], "had_bullet": True}
            continue
        if cur is None:
            # text with no open entry: a bulletless paragraph (or trailing prose). Start an entry if it looks like one.
            if s.startswith("$") or _LEAD_PENALTY_RE.match(s):
                cur = {"section": section, "page": pno, "page_end": pno, "lines": [s], "had_bullet": False}
            else:
                diag["notes"].append(f"orphan line p{pno}: {s[:60]}")
            continue
        # bulletless entry boundary: a new '$' lead after a completed sentence
        prev = cur["lines"][-1].rstrip()
        if s.startswith("$") and _LEAD_PENALTY_RE.match(s) and prev.endswith((".", "”", '"', ")")):
            flush()
            cur = {"section": section, "page": pno, "page_end": pno, "lines": [s], "had_bullet": False}
            continue
        cur["lines"].append(s)
        cur["page_end"] = pno
    flush()
    return entries, diag


def classify_lead(text: str) -> dict:
    """Penalty + respondent from the opening clause. Blank when the pattern is absent."""
    res = {"penalty_amount": None, "penalty_basis": "", "respondent": "", "respondent_role": "", "description_start": 0}
    lm = _LEAD_PENALTY_RE.match(text)
    if lm:
        res["penalty_amount"] = money_to_int(lm.group(1))
        res["penalty_basis"] = "leading_amount_violations_wording" if re.search(r"violations?$", lm.group(0), re.I) else "leading_amount"
        span_end = lm.end()
    else:
        span_end = 0
    rm = _RESPONDENT_RE.search(text, span_end) if span_end else _RESPONDENT_RE.search(text)
    if rm:
        who = rm.group("who").strip(" ,")
        if re.match(r"^of\s", who, re.I):        # "the owner of 190-08 Nashville Blvd": the owner is not named
            who = ""
        role = ""
        roleman = _ROLE_RE.match(who)
        if roleman:
            role, who = roleman.group("role"), roleman.group("name").strip(" ,")
        if rm.group("owner_role"):
            role = re.sub(r"^the\s+", "", rm.group("owner_role").strip(), flags=re.I).strip()
        res.update(respondent=who, respondent_role=role, description_start=rm.end())
    return res


def parse_entry(raw: dict, bulletin: dict) -> dict:
    text = _join_lines(raw["lines"])
    text = A.fix_pdf_spacing(text)
    lead = classify_lead(text)
    amounts = [money_to_int(m.group(1)) for m in _MONEY_RE.finditer(text)]
    addrs = A.extract_addresses(text)
    section = raw["section"]
    section_borough = section if section in A.BOROCODE else None
    prof_only = section is not None and section not in A.BOROCODE

    primary = next((a for a in addrs if a["anchored"]), addrs[0] if addrs else None)
    alt = [a for a in addrs if a is not primary]
    anchored = [a for a in addrs if a["anchored"]]
    borough_text = primary["borough_in_text"] if primary else None
    if borough_text is None:  # any borough named alongside any address in the text
        borough_text = next((a["borough_in_text"] for a in addrs if a["borough_in_text"]), None)
    borough = borough_text or section_borough
    borough_source = "text" if borough_text else ("section" if section_borough else "")
    if not borough and addrs:
        named = {A.canonical_borough(m.group(0)) for m in re.finditer(r"\b(?:Manhattan|Brooklyn|Bronx|Queens|Staten Island)\b", text)}
        if len(named) == 1:                      # exactly one borough mentioned anywhere: use it, and say so
            borough, borough_source = named.pop(), "text_elsewhere"
    b_conflict = bool(borough_text and section_borough and borough_text != section_borough)

    dm = _DATE_RE.search(text)
    enf_date = None
    if dm:
        try:
            import datetime as dt
            enf_date = dt.datetime.strptime(f"{dm['m']} {int(dm['d'])} {dm['y']}", "%B %d %Y").date().isoformat()
        except ValueError:
            enf_date = None

    norm = re.sub(r"[^a-z0-9$]+", " ", text.lower()).strip()
    return {
        "bulletin_id": bulletin["bulletin_id"], "bulletin_month": int(bulletin["bulletin_month"]),
        "bulletin_year": int(bulletin["bulletin_year"]), "pdf_url": bulletin["pdf_url"],
        "source_pdf": bulletin["local_filename"], "source_page": raw["page"], "source_page_end": raw["page_end"],
        "section": section or "", "had_bullet": raw["had_bullet"],
        "enforcement_date": enf_date or "", "enforcement_date_text": dm.group(0) if dm else "",
        "penalty_amount": lead["penalty_amount"] if lead["penalty_amount"] is not None else "",
        "penalty_basis": lead["penalty_basis"], "all_dollar_amounts": ";".join(str(a) for a in amounts),
        "respondent": lead["respondent"], "respondent_role": lead["respondent_role"],
        "address_raw": primary["raw"] if primary else "", "address_number": primary["number"] if primary else "",
        "address_street": primary["street"] if primary else "",
        "address_anchored": bool(primary and primary["anchored"]),
        "addresses_other": " | ".join(a["raw"] for a in alt), "n_anchored_addresses": len(anchored),
        "borough": borough or "", "borough_source": borough_source,
        "borough_conflict": b_conflict, "professional_section": prof_only,
        "identifiers_mentioned": A.extract_identifiers(text),
        "violation_description": text[lead["description_start"]:].strip(" ,.;") if lead["description_start"] else text,
        "enforcement_text": text,
        "_norm": norm,
        "_addresses": _candidate_addresses(addrs, primary, borough),
    }


def _candidate_addresses(addrs, primary, action_borough, limit=8):
    """Every address in the entry goes to the matcher: one action can cite several properties
    ("... properties in Manhattan, including 1801 2nd Avenue, 154 West 71st Street, ... and 75 West End Avenue")."""
    picked = [{"number": a["number"], "street": a["street"], "anchored": a["anchored"],
               "borough": a["borough_in_text"] or action_borough or None} for a in addrs]
    return picked[:limit]


def assign_ids(actions: list[dict]) -> None:
    """Stable IDs: bulletin + hash of the normalised paragraph; exact repeats inside one bulletin get -2, -3."""
    seen = {}
    for a in actions:
        h = hashlib.sha1(a["_norm"].encode()).hexdigest()[:10]
        base = f"EA-{a['bulletin_year']}{a['bulletin_month']:02d}-{h}"
        seen[base] = seen.get(base, 0) + 1
        a["enforcement_id"] = base if seen[base] == 1 else f"{base}-{seen[base]}"


def parse_bulletin(bulletin: dict, extracted: dict) -> tuple[list[dict], dict]:
    """bulletin = registry row (dict); extracted = JSON from extract.py. Returns (actions, diagnostics)."""
    raw_entries, diag = split_entries(extracted["pages"])
    actions = [parse_entry(r, bulletin) for r in raw_entries]
    assign_ids(actions)
    diag.update(n_entries=len(actions), n_bulleted=sum(a["had_bullet"] for a in actions),
                n_with_penalty=sum(a["penalty_amount"] != "" for a in actions),
                n_with_address=sum(bool(a["address_raw"]) for a in actions))
    return actions, diag
