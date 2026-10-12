"""Equipment-list extraction from Virginia DEQ permit text.

DEQ permits carry an "Equipment List" table near the start of the conditions:

    Reference No. | Equipment Description                         | Rated Capacity
    ENG140-ENG145 | Six (6) Caterpillar Model C175-16 backup      | 4,376 bhp
                  | engine-generator sets                         | 3,100 kWe, each

The table is split into "equipment included in the project" (new) and "other
permitted equipment" (existing), may run across pages (with the header
repeated), and on scanned permits arrives as noisy OCR.

Extraction is rule-based and deterministic. Every row keeps its page and raw
text, and is checked against the document itself:
  - the count in words agrees with the count in digits ("Six (6)")
  - the number of reference IDs agrees with the stated count
  - no reference ID appears in two rows
  - the row has a manufacturer and an electrical rating (combustion units)
A row that fails a check is held for review, not dropped and not guessed.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .units import to_kw

# ---------------------------------------------------------------- vocab

OEMS = {
    "Caterpillar": r"caterpillar|\bcat\b",
    "MTU": r"\bmtu\b|rolls[- ]royce",
    "Cummins": r"cummins",
    "Kohler": r"kohler",
    "Generac": r"generac",
    "Detroit Diesel": r"detroit diesel",
    "Mitsubishi": r"mitsubishi",
    "Volvo Penta": r"volvo",
    "Perkins": r"perkins",
    "Baudouin": r"baudouin",
    "John Deere": r"john deere|\bdeere\b",
    "Doosan": r"doosan",
    "Solar Turbines": r"solar turbines",
    "GE": r"\bge\b|general electric",
    "Siemens": r"siemens",
    "Bloom Energy": r"bloom",
    "Clarke": r"\bclarke\b",
}

CLASSES = [  # first match wins; order matters
    ("cooling_tower", r"cooling tower"),
    ("storage_tank", r"\btank"),
    ("fire_pump", r"fire ?pump|fire water pump"),
    ("fuel_cell", r"fuel cell"),
    ("gas_turbine", r"turbine"),
    ("boiler", r"boiler|water heater"),
    ("genset", r"generat|gen-?set|engine"),
]
COMBUSTION = {"genset", "fire_pump", "engine", "gas_turbine", "boiler", "fuel_cell"}

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen " \
        "fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
NUMWORD = {w: i for i, w in enumerate(_ONES)} | {w: 10 * i for i, w in enumerate(_TENS) if w != "_"}


def words_to_int(s: str) -> int | None:
    """'One hundred thirty two' -> 132, 'Two hundred and ninety-five' -> 295."""
    total = cur = 0
    seen = False
    for w in re.split(r"[\s-]+", s.lower()):
        if w in ("and", ""):
            continue
        if w in NUMWORD:
            cur += NUMWORD[w]
        elif w == "hundred":
            cur = (cur or 1) * 100
        elif w == "thousand":
            total += (cur or 1) * 1000
            cur = 0
        else:
            return None
        seen = True
    return total + cur if seen else None


_NUMWORDS_RE = "|".join(sorted(list(NUMWORD) + ["hundred", "thousand", "and"], key=len, reverse=True))
COUNT_RE = re.compile(rf"\b((?:(?:{_NUMWORDS_RE})[\s-]*)+)\(\s*(\d[\d,]*)\s*\)", re.I)
PAREN_COUNT_RE = re.compile(r"^\W*\(\s*(\d[\d,]*)\s*\)")
LEAD_DIGIT_COUNT_RE = re.compile(r"^\W*(\d{1,4})\s+(?=[A-Z][a-z])")
LEAD_WORD_COUNT_RE = re.compile(rf"^\W*((?:(?:{_NUMWORDS_RE})[\s-]*)+)\b", re.I)

# EG01, ENG140, B-05, 00GEN-1, A/B10, HGEN
REF = r"(?:\d{1,3})?[A-Z]{1,6}(?:/[A-Z])?-?\d{1,4}[A-Z]?(?:-\d{1,3})?|[A-Z]{0,4}GEN"
REF_RANGE_RE = re.compile(rf"\b({REF})\s*(?:-|to|through)\s*({REF})\b")
_REF_NUM_RE = re.compile(r"^(.*?)(\d+)$")
REF_RE = re.compile(rf"\b({REF})\b")
ROW_START_RE = re.compile(
    rf"^\s*(?:{REF})\b(?:\s*(?:-|,|to|through|and|&)?\s*(?:{REF})\b|\s*(?:-|,))*[\s,]*")
# an ID cell continuing on a later line of the row, beside the description (OCR'd scans):
# "EG2-1 through EG2-4 | SR-4-HV emergency diesel ..."
CONT_REFS_RE = re.compile(rf"^\s*((?:{REF})\s*(?:-|to|through)\s*(?:{REF}))\s*(?:\||$)")
OLD_ROW_START_RE = re.compile(rf"^\s*(\d{{1,3}})\s+(?=(?:{_NUMWORDS_RE}|\(\d)\b)", re.I)

RATING_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(kWe|ekW|kW|MWe|MW|kVA|BHP|HP|brake\s+horsepower|horsepower|brake)\b",
    re.I,
)
NEW_SECTION_RE = re.compile(r"included in the project|to be (?:constructed|added|installed)|new equipment", re.I)
OLD_SECTION_RE = re.compile(r"other permitted|previously permitted|existing equipment", re.I)
HEADER_LINE_RE = re.compile(
    r"^\s*(reference\s*no\.?|ref\.?\s*no\.?|equipment\s+description|rated\s*capacity|referenced|"
    r"federal|requirements|original\s+permit\s+date|permit\s+date|registration\s+number.*|page\s+\d+|"
    r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},\s+\d{4}|--)\s*$",
    re.I,
)
END_RE = re.compile(
    r"specifications included in the above|OPERATING/EMISSION LIMITATIONS|"
    r"^\s*\d+\.\s*(?:emission controls|fuel\b|operating hours)|^\s*(?:emission controls|fuel)\s*-",
    re.I | re.M,
)
PAGE_RE = re.compile(r"<<p(\d+)>>")
HEADER_WORDS = set("""reference ref ref. no no. equipment description rated capacity referenced
    delegated federal requirements requirement location building original permit date applicable
    regulations""".split())


def _is_header_line(line: str) -> bool:
    words = re.findall(r"[A-Za-z.]+", line.lower())
    return bool(words) and all(w in HEADER_WORDS or w.rstrip(".") in HEADER_WORDS for w in words) \
        and not re.search(r"\d", line)


def normalize(text: str) -> str:
    text = text.replace("–", "-").replace("—", "-").replace("‐", "-").replace("\xa0", " ")
    text = re.sub(r"-{2,}", "-", text)
    # OCR: letter O inside a reference ID ("EGO1" -> "EG01")
    text = re.sub(r"\b([A-Z]{1,5})O(\d)", r"\g<1>0\2", text)
    text = re.sub(r"\b([A-Z]{1,5}\d)O\b", r"\g<1>0", text)
    # "ENG 155" -> "ENG155" (only unit-ID prefixes; "MTU 16V4000" must stay apart)
    text = re.sub(r"\b(ENG|EG|DG|GEN|GE|FP|CT)\s+(\d{1,4})\b", r"\1\2", text)
    return text


# ---------------------------------------------------------------- data


@dataclass
class UnitRow:
    page: int
    raw: str
    section: str | None                  # 'new' | 'existing' | None
    ref_ids: list[str]
    count: int | None
    count_words: int | None
    count_digits: int | None
    equipment_class: str | None
    manufacturer: str | None
    model: str | None
    fuel: str | None
    duty: str | None
    reported_value: float | None
    reported_unit: str | None
    unit_kw: float | None
    kw_assumption: str | None
    bhp: float | None
    alt_ratings_kw: list[float] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)

    @property
    def held(self) -> bool:
        return any(v is False for v in self.checks.values())

    def as_dict(self) -> dict:
        d = asdict(self)
        d["held"] = self.held
        return d


# ---------------------------------------------------------------- region + rows


LOCATION_COL_RE = re.compile(r"^\s*(location|building)\s*$", re.I | re.M)


def has_location_column(pages: list[tuple[int, str]]) -> bool:
    joined = "\n".join(t for _, t in pages)
    m = re.search(r"equipment\s+list|equipment at this facility", joined, re.I)
    return bool(m and LOCATION_COL_RE.search(joined[m.end(): m.end() + 600]))


def equipment_region(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Lines (page, text) of the equipment list table, header lines removed."""
    joined = "\n".join(f"<<p{n}>>\n{normalize(t)}" for n, t in pages)
    m = re.search(r"equipment\s+list|equipment at this facility (?:covered by this permit )?consists", joined, re.I)
    if not m:
        return []
    page = int(PAGE_RE.findall(joined[: m.start()])[-1])
    tail = joined[m.end():]
    tail = tail[tail.find("\n") + 1:] if "\n" in tail else ""   # rest of the intro sentence
    end = END_RE.search(tail, 30)
    region = tail[: end.start()] if end else tail[:6000]
    out, skip_running_header = [], False
    for line in region.splitlines():
        pm = PAGE_RE.fullmatch(line.strip())
        if pm:
            page, skip_running_header = int(pm.group(1)), True
            continue
        if skip_running_header:      # first line on a new page is the permittee name
            skip_running_header = False
            continue
        if not line.strip() or HEADER_LINE_RE.match(line) or _is_header_line(line):
            continue
        out.append((page, line.rstrip()))
    return out


_DESC_EVIDENCE_RE = re.compile(
    rf"\(\s*\d+\s*\)|generat|gen-?set|engine|turbine|boiler|tower|tank|pump|heater|fuel cell|"
    rf"\d\s*(?:kw|bhp|hp|mmbtu)|\b(?:{_NUMWORDS_RE})\s+\w", re.I)
_DESC_START_RE = re.compile(rf"^\W*(?:\(\s*\d|(?:{_NUMWORDS_RE})\b)", re.I)


def _starts_row(line: str) -> bool:
    """A reference cell, alone or followed by the start of a description ('Six (6) ...').

    Rules out wrapped description lines that happen to begin with a model
    number shaped like an ID ('DS2250 diesel emergency generators').
    """
    if OLD_ROW_START_RE.match(line):
        return True
    m = ROW_START_RE.match(line)
    if not m:
        return False
    rest = line[m.end():].lstrip(" |")
    return not rest or bool(_DESC_START_RE.match(rest))


def split_rows(lines: list[tuple[int, str]]) -> list[tuple[int, str, str | None]]:
    """Group region lines into table rows: (page, row_text, section)."""
    rows: list[list] = []
    section = None
    for page, line in lines:
        if NEW_SECTION_RE.search(line) and len(line) < 90:
            section = "new"
            continue
        if OLD_SECTION_RE.search(line) and len(line) < 90:
            section = "existing"
            continue
        starts = _starts_row(line)
        cur = rows[-1] if rows else None
        # a line of only reference IDs continues a row whose ID cell wrapped
        # glue onto the current row only if it is a bare ID cell still waiting for its
        # description (an ID cell wrapped over lines, or a location column)
        cur_waiting = cur and _starts_row(cur[1].splitlines()[0]) \
            and not _DESC_EVIDENCE_RE.search(cur[1])
        if starts and not cur_waiting:
            rows.append([page, line, section])
        elif cur is not None:
            cur[1] += "\n" + line
        else:
            rows.append([page, line, section])
    return [tuple(r) for r in rows]


# ---------------------------------------------------------------- row parsing


def expand_refs(text: str) -> list[str]:
    ids: list[str] = []
    spans = []
    for m in REF_RANGE_RE.finditer(text):
        ma, mb = _REF_NUM_RE.match(m.group(1)), _REF_NUM_RE.match(m.group(2))
        if not (ma and mb):
            continue
        (pa, na), (pb, nb) = ma.groups(), mb.groups()
        if pa == pb and int(na) <= int(nb) and int(nb) - int(na) < 2000:
            width = len(na) if na.startswith("0") else 0
            ids += [f"{pa}{str(i).zfill(width)}" for i in range(int(na), int(nb) + 1)]
            spans.append(m.span())
    rest = "".join(" " if any(s <= i < e for s, e in spans) else c for i, c in enumerate(text))
    for m in REF_RE.finditer(rest):
        short = re.fullmatch(r"([A-Z]+)(\d+)-(\d+)", m.group(1))     # "EG1-20" = EG1..EG20
        if short and int(short.group(2)) < int(short.group(3)) < 2000:
            p, a, b = short.group(1), int(short.group(2)), int(short.group(3))
            ids += [f"{p}{i}" for i in range(a, b + 1)]
        else:
            ids.append(m.group(1))
    return ids


def _first(patterns: dict[str, str] | list, text: str):
    items = patterns.items() if isinstance(patterns, dict) else patterns
    for name, pat in items:
        if re.search(pat, text, re.I):
            return name
    return None


def _model(desc: str, oem: str | None) -> str | None:
    if not oem:
        return None
    m = re.search(OEMS[oem], desc, re.I)
    after = desc[m.end():]
    after = re.sub(r"^\s*(?:,|/\s*\w+|corporation|corp\.?|inc\.?|model|cat\b|\s)*", "", after, flags=re.I)
    toks = []
    for tok in after.split():
        if re.fullmatch(r"[A-Za-z]*\d[\w./-]*|[A-Z]{2,}[\w./-]*|DS\d+\w*", tok) and tok.lower() not in ("or",):
            toks.append(tok.strip(",;"))
            if len(toks) == 3:
                break
        else:
            break
    return " ".join(toks) or None


def _id_cell(text: str) -> str:
    """With a location column the ID cell is the first line plus lines it wraps onto
    (a line ending in ',' or '-'); the next line belongs to the location column."""
    lines = text.splitlines()
    cell = [lines[0]]
    for line in lines[1:]:
        if not re.search(r"[,\-]\s*$", cell[-1]):
            break
        cell.append(line)
    return " ".join(cell)


def parse_row(page: int, text: str, section: str | None, location_col: bool = False) -> UnitRow:
    flat = re.sub(r"\s+", " ", text).strip()
    lead = ROW_START_RE.match(flat) or OLD_ROW_START_RE.match(flat)
    if location_col and ROW_START_RE.match(flat):
        id_cell = _id_cell(text)
        lead = ROW_START_RE.match(re.sub(r"\s+", " ", id_cell).strip())
    ref_part = flat[: lead.end()] if lead else ""
    desc = flat[lead.end():] if lead else flat
    if OLD_ROW_START_RE.match(flat) and not ROW_START_RE.match(flat):
        ref_ids = [lead.group(1)]
    else:
        ref_ids = expand_refs(ref_part)
        for line in ([] if location_col else text.splitlines()[1:]):
            c = CONT_REFS_RE.match(normalize(line))
            if c:
                ref_ids += [x for x in expand_refs(c.group(1)) if x not in ref_ids]

    cw = cd = None
    m = COUNT_RE.search(desc)
    if m:
        cw, cd = words_to_int(m.group(1)), int(m.group(2).replace(",", ""))
    else:
        mp = PAREN_COUNT_RE.match(desc) or LEAD_DIGIT_COUNT_RE.match(desc)
        ml = LEAD_WORD_COUNT_RE.match(desc)
        if mp:
            cd = int(mp.group(1).replace(",", ""))
        elif ml:
            cw = words_to_int(ml.group(1))
    count = cd if cd is not None else cw
    count_from_refs = False
    if count is None and ref_ids and not ref_ids[0].isdigit():
        # one row per unit ("00GEN-1  Emergency engine-generator set ...") states no count
        count, count_from_refs = len(ref_ids), True

    cls = _first(CLASSES, desc)
    if cls == "genset" and not re.search(r"generat|gen-?set", desc, re.I):
        # "Sixty (60) Cummins C3000 D6e engines" under IDs EG1-EG60 are generators
        if any(x.startswith("FP") for x in ref_ids):
            cls = "fire_pump"
        elif not any(re.match(r"\d*(?:EG|GEN|DG|G\d|ENG|GE)", x) for x in ref_ids):
            cls = "engine"
    oem = _first(OEMS, desc)
    fuel = ("diesel" if re.search(r"diesel|distillate|ulsd|no\. ?2 fuel", desc, re.I)
            else "natural_gas" if re.search(r"natural gas", desc, re.I) else None)
    duty = ("non_emergency" if re.search(r"non-?emergency|prime|peak", desc, re.I)
            else "emergency" if re.search(r"emergency|backup|back-up|stand-?by", desc, re.I) else None)

    elec, mech = [], []
    for v, u in RATING_RE.findall(flat):
        val = float(v.replace(",", ""))
        ul = u.lower()
        if "horsepower" in ul or ul in ("bhp", "hp", "brake"):   # OCR splits "brake / horsepower"
            mech.append(val)
        else:
            elec.append((val, u))
    reported = elec[0] if elec else None
    kw = assumption = None
    if reported:
        kw, assumption = to_kw(*reported)
    elif mech and cls == "genset":
        # only engine shaft power stated; convert with a flagged efficiency assumption
        reported = (mech[0], "bhp")
        kw, assumption = to_kw(*reported)
    alts = sorted({to_kw(v, u)[0] for v, u in elec})

    row = UnitRow(
        page=page, raw=text, section=section, ref_ids=ref_ids, count=count,
        count_words=cw, count_digits=cd, equipment_class=cls, manufacturer=oem,
        model=_model(desc, oem), fuel=fuel, duty=duty,
        reported_value=reported[0] if reported else None,
        reported_unit=reported[1] if reported else None,
        unit_kw=kw, kw_assumption=assumption, bhp=mech[0] if mech else None,
        alt_ratings_kw=alts if len(alts) > 1 else [],
    )
    if cw is not None and cd is not None:
        row.checks["count_words_match_digits"] = cw == cd
    if ref_ids and count is not None and not (len(ref_ids) == 1 and OLD_ROW_START_RE.match(flat)):
        row.checks["ref_ids_match_count"] = len(ref_ids) == count
    if cls in COMBUSTION and cls != "boiler":
        row.checks["has_manufacturer"] = oem is not None
        row.checks["has_electrical_rating"] = kw is not None or cls in ("fire_pump", "engine")
        row.checks["has_count"] = count is not None
    if count_from_refs:
        row.flags.append("count_from_ref_ids")
    if row.alt_ratings_kw:
        row.flags.append("alternative_equipment")
    if re.search(r"or equivalent", desc, re.I):
        row.flags.append("or_equivalent")
    return row


def extract(pages: list[tuple[int, str]]) -> list[UnitRow]:
    loc = has_location_column(pages)
    rows = [parse_row(*r, location_col=loc) for r in split_rows(equipment_region(pages))]
    rows = [r for r in rows if r.equipment_class or r.manufacturer or r.ref_ids]
    seen: dict[str, int] = {}
    for i, r in enumerate(rows):
        # bare row numbers ("1", "2") in old scans are not facility-wide unit IDs
        dupes = [x for x in r.ref_ids if x in seen and not x.isdigit()]
        if dupes:
            r.checks["ref_ids_unique"] = False
            r.flags.append(f"ref_overlap:{','.join(dupes[:5])}")
            rows[seen[dupes[0]]].checks["ref_ids_unique"] = False
        for x in r.ref_ids:
            seen.setdefault(x, i)
    return rows


# ---------------------------------------------------------------- persistence

_VALUE_FIELDS = ("page", "section", "ref_ids", "equipment_class", "unit_count",
                 "reported_value", "reported_unit", "unit_kw", "kw_assumption",
                 "manufacturer", "model", "fuel", "duty", "review_status")


def record_id(site_id: str, row: UnitRow, idx: int) -> str:
    """Stable within a site: the permit's own unit reference IDs, else row position."""
    if row.ref_ids:
        a, b = row.ref_ids[0], row.ref_ids[-1]
        return f"{site_id}:{a}" if a == b else f"{site_id}:{a}-{b}"
    return f"{site_id}:row{idx}"


def load_units(con, rows: list[UnitRow], *, site_id: str, source_sha: str,
               first_seen_at: str, published_at: str | None, recorded_at: str) -> dict:
    """Append versions for changed rows. Unchanged rows write nothing."""
    import json

    stats = {"new": 0, "changed": 0, "unchanged": 0}
    used: set[str] = set()
    for idx, r in enumerate(rows):
        rid = record_id(site_id, r, idx)
        if rid in used:            # same IDs twice in one document: keep both rows
            rid = f"{rid}#row{idx}"
        used.add(rid)
        vals = {
            "page": r.page, "section": r.section, "ref_ids": json.dumps(r.ref_ids),
            "equipment_class": r.equipment_class, "unit_count": r.count,
            "reported_value": r.reported_value, "reported_unit": r.reported_unit,
            "unit_kw": r.unit_kw, "kw_assumption": r.kw_assumption,
            "manufacturer": r.manufacturer, "model": r.model, "fuel": r.fuel,
            "duty": r.duty, "review_status": "held" if r.held else "ok",
        }
        prev = con.execute(
            "SELECT * FROM unit_versions WHERE record_id = ? ORDER BY version DESC LIMIT 1",
            (rid,)).fetchone()
        # Already recorded from this document with these values (latest or superseded by a
        # newer permit for the same site): re-running must not write anything.
        same = con.execute(
            "SELECT * FROM unit_versions WHERE record_id = ? AND source_sha = ? "
            "ORDER BY version DESC LIMIT 1", (rid, source_sha)).fetchone()
        if same and all(same[k] == vals[k] for k in _VALUE_FIELDS) and (
                prev["source_sha"] == source_sha or (published_at or "") <= (prev["published_at"] or "")):
            stats["unchanged"] += 1
            continue
        if prev is None:
            version, reason = 1, "new_document"
            stats["new"] += 1
        else:
            version = prev["version"] + 1
            # same document read again = our correction; different document = the source changed
            reason = "correction" if prev["source_sha"] == source_sha else "new_document"
            stats["changed"] += 1
        con.execute(
            """INSERT INTO unit_versions (record_id, version, site_id, source_sha, page, section,
                   ref_ids, equipment_class, unit_count, reported_value, reported_unit, unit_kw,
                   kw_assumption, manufacturer, model, fuel, emissions_tier, hours_limit, duty,
                   raw_text, checks, flags, review_status, published_at, first_seen_at,
                   recorded_at, revision_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, version, site_id, source_sha, vals["page"], vals["section"], vals["ref_ids"],
             vals["equipment_class"], vals["unit_count"], vals["reported_value"],
             vals["reported_unit"], vals["unit_kw"], vals["kw_assumption"], vals["manufacturer"],
             vals["model"], vals["fuel"], None, None, vals["duty"], r.raw,
             json.dumps(r.checks), json.dumps(r.flags), vals["review_status"],
             published_at, first_seen_at, recorded_at, reason))

    # Records this document produced before but no longer does (an earlier misread):
    # append a 'retracted' version so as-of queries before now still see what we published.
    stale = con.execute(
        """SELECT * FROM unit_versions u
           WHERE source_sha = ? AND site_id = ? AND review_status != 'retracted'
             AND version = (SELECT MAX(version) FROM unit_versions WHERE record_id = u.record_id)""",
        (source_sha, site_id)).fetchall()
    stats["retracted"] = 0
    for prev in stale:
        if prev["record_id"] in used:
            continue
        cols = [k for k in prev.keys()]
        vals = dict(prev)
        vals.update(version=prev["version"] + 1, review_status="retracted",
                    recorded_at=recorded_at, revision_reason="correction")
        con.execute(f"INSERT INTO unit_versions ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    [vals[c] for c in cols])
        stats["retracted"] += 1
    con.commit()
    return stats
