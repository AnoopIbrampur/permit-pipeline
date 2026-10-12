"""Texas TCEQ: pending New Source Review air permit applications.

https://www.tceq.texas.gov/permitting/air/newsourcereview/airpermits-pendingpermit-apps

~430 pending applications: applicant, facility, permit numbers, and links to
plain-language summaries (PLS) and public notices (NORI / NAPD). robots.txt
allows this page, so it is fetched directly, politely, once per run.

Unlike Virginia, this list is not curated to data centers. Many data center
power plants are filed under project LLCs ("... POWER, LLC"), so flagging them
is part of the problem (see `looks_like_data_center`).

Note: TCEQ says documents processed on or after 2026-08-31 go to its new
Permit Search Portal; this page covers applications pending before then.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

SOURCE = "tx_tceq"
INDEX_URL = "https://www.tceq.texas.gov/permitting/air/newsourcereview/airpermits-pendingpermit-apps"
USER_AGENT = "permitpipe/0.1 (research project; github.com/anoopibrampur)"

# Strong signals only. Everything else stays unknown (None) for review, not 0.
_DC_TERMS = re.compile(r"\bdata ?cent(er|re)s?\b|\bhyperscale|\bAI campus\b|\bcompute campus\b", re.I)
_KNOWN_DC_APPLICANTS = re.compile(
    r"crusoe|aligned data|vantage data|stack infrastructure|cyrusone|qts |"
    r"digital realty|switch ltd|lancium|fermi america|cloudburst|"
    r"core ?scientific|galaxy digital|poolside|oracle|meta platforms|"
    r"microsoft|amazon data|google",
    re.I,
)


def looks_like_data_center(applicant: str, facility: str) -> int | None:
    if _DC_TERMS.search(facility) or _DC_TERMS.search(applicant):
        return 1
    if _KNOWN_DC_APPLICANTS.search(applicant):
        return 1
    return None


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def fetch_index(session: requests.Session | None = None) -> tuple[bytes, str]:
    s = session or requests.Session()
    r = s.get(INDEX_URL, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    return r.content, r.headers.get("content-type", "text/html")


def parse_index(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("tr[id]"):
        if not tr["id"].isdigit():   # letter rows ("A", "B", ...) are section jumps
            continue
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue
        applicant, facility, permits = (_clean(c.get_text()) for c in cells[:3])
        docs = [
            {"label": _clean(a.get_text()), "url": a["href"]}
            for a in cells[3].find_all("a", href=True)
            if a["href"].lower().endswith(".pdf")
        ]
        rows.append({
            "row_id": tr["id"],
            "applicant": applicant,
            "facility": facility,
            "permit_numbers": [p.strip() for p in permits.split(",") if p.strip()],
            "documents": docs,
            "is_data_center": looks_like_data_center(applicant, facility),
        })
    return rows
