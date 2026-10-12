"""Who is behind a site: permittee entities -> developer / operator, with evidence.

A permit is issued to whoever applied, usually a single-purpose LLC ("CLOP Ashland VA
LLC", "Loudoun Prop 1, LLC"). The company behind it is resolved from public evidence and
every link carries that evidence:

  direct    a document about this site names the company
            (the DEQ cover letter is addressed to "Digital Realty")
  inferred  indirect evidence: the site shares a mailing address with a site whose
            company is known directly, or an entity name contains a known brand

If the evidence supports neither, the site stays unresolved. Names of individuals in
cover letters are never stored; only entities, titles and addresses are.

Evidence sources, in order of use:
  1. the permit itself: cover letter addressee block and the running page header
  2. other permits in this dataset (shared mailing address)
  3. outside public records (business registrations, announcements): see `add_link`
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .ocr import OCR_DIR
from .store import utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_entities (
    site_id      TEXT NOT NULL,
    source_sha   TEXT NOT NULL REFERENCES documents(sha256),
    entity       TEXT NOT NULL,            -- legal name as printed
    entity_key   TEXT NOT NULL,            -- normalized for matching
    role_hint    TEXT,                     -- addressee | header | listing
    address      TEXT,                     -- mailing address on the cover letter
    page         INTEGER,
    PRIMARY KEY (site_id, source_sha, entity_key)
);
CREATE TABLE IF NOT EXISTS owner_links (
    site_id      TEXT NOT NULL,
    role         TEXT NOT NULL,            -- operator | developer
    company      TEXT NOT NULL,
    link_type    TEXT NOT NULL,            -- direct | inferred
    rule         TEXT NOT NULL,            -- which evidence rule produced it
    evidence     TEXT NOT NULL,            -- JSON list of {source_sha|url, page, quote}
    recorded_at  TEXT NOT NULL,
    PRIMARY KEY (site_id, role, company, rule)
);
"""

# Companies recognised when a document names them, labelled as the documents name them.
# Renames (Corporate Office Properties -> COPT Defense Properties, Facebook -> Meta,
# Peak 10 -> Flexential) are not applied: they belong in a dated rename table, not here. Patterns match the company's own
# names and brands only; a match is evidence because the text says it, not because we
# know who owns what.
COMPANIES = {
    "Amazon (Amazon Data Services, Inc.)": r"\bamazon data services\b|\bamazon web services\b|\baws\b",
    "Microsoft": r"\bmicrosoft\b",
    "Digital Realty": r"\bdigital realty\b",
    "QTS Data Centers": r"\bqts\b",
    "Equinix": r"\bequinix\b",
    "CoreSite": r"\bcoresite\b",
    "Iron Mountain": r"\biron mountain\b",
    "DataBank": r"\bdatabank\b",
    "Yondr": r"\byondr\b",
    "Clean Arc Data Centers": r"\bclean arc\b",
    "Chirisa": r"\bchirisa\b",
    "TECfusions": r"\btecfusions\b",
    "Verizon": r"\bverizon\b",
    "Capital One": r"\bcapital one\b",
    "Bank of America": r"\bbank of america\b",
    "Sentara Healthcare": r"\bsentara\b",
    "Northrop Grumman": r"\bnorthrop grumman\b",
    "Peak 10": r"\bpeak 10\b",
    "Corporate Office Properties (COPT)": r"\bcorporate office properties\b|\bcopt\b",
    "Lincoln Property Company": r"\blincoln property company\b",
    "DP Facilities": r"\bdp facilities\b",
}
# what the named company is to the site; everything else defaults to operator
COMPANY_ROLE = {
    "Corporate Office Properties (COPT)": "developer",   # landlord / developer of leased buildings
    "Lincoln Property Company": "manager",        # named 'c/o' as property manager
}

_TITLE_RE = re.compile(
    r"\b(president|vice president|vp|director|manager|officer|signatory|ceo|cfo|coo|"
    r"principal|owner|engineer|counsel|partner|lead|head|chief|senior|sr\.?|general|"
    r"specialist|coordinator|representative|administrator|supervisor|analyst)\b", re.I)
# "Mr. Chris Doe", "Ms. Robin Lee Doe", 'Mr. Alex "AJ" Sample'
_PERSON_RE = re.compile(r"\b(?:Mr|Mrs|Ms|Mx|Dr)\.?\s+[A-Z][\w'’.-]*(?:\s+(?:[“\"][^”\"]+[”\"]|[A-Z][\w'’.-]*))*")


def redact_people(text: str) -> str:
    return _PERSON_RE.sub("[person]", text)
_SALUTATION_RE = re.compile(r"^\s*(mr|mrs|ms|dr|mx)\.?\s", re.I)
_ADDRESS_START_RE = re.compile(r"^\s*(\d{1,6}\s+\S|p\.?\s*o\.?\s*box|one\s|two\s|suite\b)", re.I)
_CITY_STATE_ZIP_RE = re.compile(r"\b[A-Z]{2}\.?\s+\d{5}(?:-\d{4})?\b|\bVirginia\s+\d{5}\b")
_ENTITY_RE = re.compile(r"\b(LLC|L\.L\.C\.|Inc\.?|Incorporated|Corporation|Corp\.?|LP|L\.P\.|Ltd|"
                        r"Company|Co\.|Holdings|Partners|Association|Trust)\b", re.I)


def entity_key(name: str) -> str:
    s = re.sub(r"\b(llc|inc|incorporated|corporation|corp|lp|ltd|the)\b", "",
               name.lower().replace(".", ""))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def address_key(addr: str) -> str:
    a = addr.lower()
    a = re.sub(r"\b\d+(?:st|nd|rd|th)\s+(?:floor|fl)\b\.?", "", a)   # "10th Floor"
    a = re.sub(r"\b(suite|ste|floor|fl)\b\.?\s*\S+", "", a)      # same building, any suite
    a = re.sub(r"\bparkway\b", "pkwy", a)
    a = re.sub(r"\bstreet\b", "st", a)
    a = re.sub(r"\broad\b", "rd", a)
    a = re.sub(r"\bboulevard\b", "blvd", a)
    a = re.sub(r"\bdrive\b", "dr", a)
    a = re.sub(r"\b(\d{5})-\d{4}\b", r"\1", a)
    return re.sub(r"[^a-z0-9]+", " ", a).strip()


@dataclass
class CoverLetter:
    entities: list[str] = field(default_factory=list)
    address: str | None = None
    title: str | None = None
    quote: str = ""


def parse_cover_letter(text: str) -> CoverLetter:
    """Addressee block: [Mr. Name] / [Title] / Entity line(s) / street / city, ST zip /
    'Location:'. The person's name line is skipped and never returned."""
    lines = [l.strip() for l in text.splitlines()]
    try:
        end = next(i for i, l in enumerate(lines) if re.match(r"(location|re|registration no)\b", l, re.I))
    except StopIteration:
        return CoverLetter()
    # walk back to the salutation line ("Mr. ...") that opens the block
    start = None
    for i in range(end - 1, max(end - 14, -1), -1):
        if _SALUTATION_RE.match(lines[i]):
            start = i + 1
            break
    if start is None:
        return CoverLetter()
    # drop lines that are about a person ("c/o Ms. ...") before anything is kept
    block = [l for l in lines[start:end] if l and not _PERSON_RE.search(l)]
    out = CoverLetter(quote=redact_people(" / ".join(block)))
    addr: list[str] = []
    for l in block:
        if addr or _ADDRESS_START_RE.match(l):
            addr.append(l)
            continue
        if _TITLE_RE.search(l) and not _ENTITY_RE.search(l) and out.title is None:
            out.title = l
            continue
        if re.match(r"(january|february|march|april|may|june|july|august|september|october|"
                    r"november|december)\s+\d", l, re.I):
            continue
        # "Buildings 3 & 4: Belmont Holdings I, LLC" -> entity after the label
        out.entities.append(re.sub(r"^[^:]{0,40}:\s*", "", l).strip(" ,"))
    out.address = ", ".join(addr) or None
    return out


def page_header(text: str) -> str | None:
    """Running header on later pages names the permittee ('Yondr JK 2, LLC')."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, l in enumerate(lines[:6]):
        if re.match(r"registration (number|no)", l, re.I) and i > 0:
            return lines[i - 1]
    return None


def companies_named(text: str) -> list[str]:
    return [c for c, pat in COMPANIES.items() if re.search(pat, text, re.I)]


def collect(con, site_id: str, sha: str, listing_name: str) -> list[dict]:
    # (entities and quotes pass through redact_people; no individual's name is stored)
    """Entities and addresses for one permit; returns direct-evidence candidates."""
    con.executescript(SCHEMA)
    p1 = OCR_DIR / sha / "page-001.txt"
    p3 = OCR_DIR / sha / "page-003.txt"
    cover = parse_cover_letter(p1.read_text()) if p1.exists() else CoverLetter()
    header = page_header(p3.read_text()) if p3.exists() else None
    rows = [(e, "addressee", cover.address, 1) for e in cover.entities]
    if header:
        rows.append((header, "header", None, 3))
    rows.append((listing_name, "listing", None, None))
    rows = [(redact_people(e), r, a, p) for e, r, a, p in rows]
    for entity, role, addr, page in rows:
        con.execute("INSERT OR IGNORE INTO site_entities VALUES (?,?,?,?,?,?,?)",
                    (site_id, sha, entity, entity_key(entity), role, addr, page))
    found = []
    for entity, role, _, page in rows:
        for company in companies_named(entity):
            quote = cover.quote if role == "addressee" else entity
            found.append({"company": company, "role_hint": role, "page": page, "quote": quote})
    return found


def add_link(con, site_id: str, role: str, company: str, link_type: str, rule: str,
             evidence: list[dict]) -> None:
    evidence = [dict(e, quote=redact_people(e.get("quote", ""))) for e in evidence]
    con.execute("INSERT OR REPLACE INTO owner_links VALUES (?,?,?,?,?,?,?)",
                (site_id, role, company, link_type, rule, json.dumps(evidence), utcnow()))


RESEARCH_FILE = Path(__file__).resolve().parents[2] / "research" / "owner_evidence.json"
STRONG_KINDS = {"permit", "press", "local_government", "registry", "company"}


def validate_research(link: dict) -> list[str]:
    """Rules every hand-researched link must meet."""
    kinds = [e["kind"] for e in link["evidence"]]
    problems = []
    if "permit" not in kinds:
        problems.append("no evidence from the permit itself")
    if not any(k in STRONG_KINDS - {"permit"} for k in kinds) and not kinds.count("directory") >= 2:
        problems.append("outside evidence rests on a single directory listing")
    if link["link_type"] == "direct" and not any(k in ("press", "local_government", "registry", "company")
                                                 for k in kinds):
        problems.append("direct link needs a press, government, registry or company document")
    return problems


def load_research(con, path: Path = RESEARCH_FILE) -> int:
    if not path.exists():
        return 0
    links = json.loads(path.read_text())["links"]
    n = 0
    for link in links:
        problems = validate_research(link)
        if problems:
            raise ValueError(f"{link['site_id']} -> {link['company']}: {'; '.join(problems)}")
        sha = con.execute(
            "SELECT source_sha FROM site_entities WHERE site_id = ? LIMIT 1", (link["site_id"],)).fetchone()
        evidence = []
        for e in link["evidence"]:
            if e["kind"] == "permit":
                evidence.append({"source_sha": sha[0] if sha else None, "page": e.get("page"),
                                 "quote": e["claim"], "kind": "permit"})
            else:
                evidence.append({"url": e["url"], "quote": e["claim"], "kind": e["kind"]})
        add_link(con, link["site_id"], link["role"], link["company"], link["link_type"],
                 "public_record", evidence)
        n += 1
    return n


def resolve(con) -> dict:
    """Run the in-dataset rules over every permit with page text."""
    con.executescript(SCHEMA)
    con.execute("DELETE FROM owner_links WHERE rule IN ('named_in_permit', 'shared_address', 'public_record')")
    con.execute("DELETE FROM site_entities")      # rebuilt from the documents every run
    docs = con.execute(
        """SELECT d.sha256, l.listing_key, l.site_name FROM documents d
           JOIN listings l ON l.doc_url = d.url AND l.source = 'va_deq'
           WHERE d.content_type = 'application/pdf' GROUP BY d.sha256""").fetchall()
    direct: dict[str, set[str]] = {}
    for d in docs:
        if not (OCR_DIR / d["sha256"] / "meta.json").exists():
            continue
        site_id = "VA-" + d["listing_key"].split("-")[0]
        for hit in collect(con, site_id, d["sha256"], d["site_name"]):
            if hit["role_hint"] == "listing":
                continue        # DEQ's own index label is not a document about the site
            role = COMPANY_ROLE.get(hit["company"], "operator")
            add_link(con, site_id, role, hit["company"], "direct", "named_in_permit",
                     [{"source_sha": d["sha256"], "page": hit["page"], "quote": hit["quote"]}])
            direct.setdefault(site_id, set()).add(hit["company"])

    # shared mailing address with a site resolved directly -> inferred
    addrs = con.execute(
        "SELECT DISTINCT site_id, source_sha, address FROM site_entities WHERE address IS NOT NULL").fetchall()
    by_addr: dict[str, list] = {}
    for a in addrs:
        by_addr.setdefault(address_key(a["address"]), []).append(a)
    for key, group in by_addr.items():
        known = {c for g in group for c in direct.get(g["site_id"], ())}
        for g in group:
            if direct.get(g["site_id"]):
                continue
            for company in known:
                src = next(x for x in group if company in direct.get(x["site_id"], ()))
                add_link(con, g["site_id"], "operator", company, "inferred", "shared_address", [
                    {"source_sha": g["source_sha"], "page": 1, "quote": g["address"]},
                    {"source_sha": src["source_sha"], "page": 1,
                     "quote": f"same address on {src['site_id']}, resolved directly to {company}"}])
    load_research(con)
    con.commit()
    sites = {"VA-" + d["listing_key"].split("-")[0] for d in docs}
    linked = {r[0] for r in con.execute("SELECT DISTINCT site_id FROM owner_links")}
    return {"sites": len(sites), "resolved": len(linked & sites), "unresolved": sorted(sites - linked)}
