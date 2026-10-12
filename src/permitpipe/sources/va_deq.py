"""Virginia DEQ: 'Issued Air Permits for Data Centers'.

https://www.deq.virginia.gov/news-info/shortcuts/permits/air/issued-air-permits-for-data-centers

One table, ~194 permits (Oct 2026): site name, registration no. (linked to the
permit PDF), issuance date, program, county, regional office. Permit PDFs are
mostly copier scans, so text comes from OCR.

Collection note: deq.virginia.gov sits behind a CDN that returns 403 to
non-browser clients (robots.txt included). We do NOT try to get around that.
The index page and PDFs are saved from a normal browser into an inbox folder
and imported from there; see README "Collecting Virginia".

Document URLs look like /home/showpublisheddocument/<doc_id>/<ticks>, where
<ticks> is a .NET timestamp (100 ns since 0001-01-01 UTC) that changes when DEQ
re-uploads the file. That gives a per-document "posted at" for free.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from ..store import put_document

SOURCE = "va_deq"
INDEX_URL = "https://www.deq.virginia.gov/news-info/shortcuts/permits/air/issued-air-permits-for-data-centers"
_DOC_RE = re.compile(r"/showpublisheddocument/(\d+)/(\d{15,})")
_DOTNET_EPOCH = datetime(1, 1, 1, tzinfo=timezone.utc)


def ticks_to_utc(ticks: int) -> str:
    return (_DOTNET_EPOCH + timedelta(microseconds=ticks // 10)).isoformat(timespec="seconds")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def _iso_date(mdy: str) -> str | None:
    try:
        return datetime.strptime(mdy, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def parse_index(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = next(
        (t for t in soup.find_all("table") if "Air Site Name" in t.get_text()), None
    )
    if table is None:
        raise ValueError("data center permit table not found; page layout changed?")
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 6:
            continue
        name = _clean(cells[0].get_text())
        if not name:
            continue
        link = cells[1].find("a")
        url = link["href"] if link and link.has_attr("href") else None
        m = _DOC_RE.search(url or "")
        rows.append({
            "listing_key": _clean(cells[1].get_text()),
            "site_name": name,
            "applicant": name,
            "issued_on": _iso_date(_clean(cells[2].get_text())),
            "program": _clean(cells[3].get_text()),
            "locality": _clean(cells[4].get_text()),
            "region": _clean(cells[5].get_text()),
            "doc_url": url,
            "doc_id": m.group(1) if m else None,
            "doc_posted_at": ticks_to_utc(int(m.group(2))) if m else None,
            "is_data_center": 1,  # the page is curated by DEQ as data centers
        })
    return rows


def import_index(con, html_path: Path, retrieved_at: str | None = None) -> tuple[str, int]:
    """Store a saved copy of the index page and its listing rows."""
    content = html_path.read_bytes()
    sha, _ = put_document(con, content, source=SOURCE, url=INDEX_URL,
                          content_type="text/html", retrieved_at=retrieved_at)
    rows = parse_index(content.decode("utf-8", errors="replace"))
    con.executemany(
        """INSERT OR IGNORE INTO listings
           (source, snapshot_sha, listing_key, site_name, applicant, issued_on,
            program, locality, region, doc_url, doc_posted_at, is_data_center)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(SOURCE, sha, r["listing_key"], r["site_name"], r["applicant"], r["issued_on"],
          r["program"], r["locality"], r["region"], r["doc_url"], r["doc_posted_at"],
          r["is_data_center"]) for r in rows],
    )
    con.commit()
    return sha, len(rows)


_FILE_RE = re.compile(r"^(\d{5})-?(\d*)")


def match_pdf(filename: str, listings: list[dict]) -> tuple[dict | None, str]:
    """Match a saved permit PDF to its listing row. Returns (row, note).

    DEQ serves permits as '<reg><seq>_DC_Permit.pdf': a 5-digit registration
    number followed by the permit sequence, sometimes zero-padded, sometimes
    absent ('2152715' = 21527-15, '7180403' = 71804-3, '11790' = 11790-1).
    The sequence in the filename does not always equal the listing's, so a
    single registration match with a different sequence is accepted but noted.
    """
    m = _FILE_RE.match(Path(filename).stem)
    if not m:
        return None, "no registration number in filename"
    base, seq = m.group(1), int(m.group(2)) if m.group(2) else None
    cands = [r for r in listings if (r["listing_key"] or "").split("-")[0] == base]
    if not cands:
        return None, f"registration {base} not in index"
    if seq is not None:
        exact = [r for r in cands if r["listing_key"].split("-")[-1].lstrip("0") == str(seq)]
        if exact:
            return exact[0], "exact"
    if len(cands) == 1:
        note = "registration only" if seq is None else (
            f"filename seq {seq} != listing {cands[0]['listing_key']}")
        return cands[0], note
    return None, f"ambiguous: {base} has {len(cands)} listings"
