"""Raw document store and record tables (SQLite).

Every source document is kept exactly as received, keyed by content hash, with
the time we retrieved it. A URL re-posted with different bytes gets a new row,
so downstream records can say which revision of a document they came from.

Records are append-only. A changed value is a new version, never an update;
`recorded_at` is when the version was written and is never earlier than
`first_seen_at` (when we first held the source document).
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    sha256        TEXT PRIMARY KEY,
    source        TEXT NOT NULL,          -- 'va_deq' | 'tx_tceq'
    url           TEXT,
    retrieved_at  TEXT NOT NULL,          -- UTC ISO, when we got these bytes
    published_at  TEXT,                   -- as stated by the source, if known
    content_type  TEXT,
    n_bytes       INTEGER NOT NULL,
    path          TEXT NOT NULL           -- data/raw/<sha256>.<ext>
);
CREATE INDEX IF NOT EXISTS documents_url ON documents(url);

-- One row per listing entry per snapshot of a source index page.
CREATE TABLE IF NOT EXISTS listings (
    source        TEXT NOT NULL,
    snapshot_sha  TEXT NOT NULL REFERENCES documents(sha256),
    listing_key   TEXT NOT NULL,          -- registration / permit number
    site_name     TEXT,
    applicant     TEXT,
    issued_on     TEXT,
    program       TEXT,
    locality      TEXT,
    region        TEXT,
    doc_url       TEXT,
    doc_posted_at TEXT,                   -- upload time encoded in URL, if any
    is_data_center INTEGER,               -- 1 / 0 / NULL (unknown)
    PRIMARY KEY (source, snapshot_sha, listing_key, doc_url)
);

-- Point-in-time unit records (filled by extraction; schema fixed up front).
CREATE TABLE IF NOT EXISTS unit_versions (
    record_id       TEXT NOT NULL,        -- stable: <site_id>:<unit_tag>
    version         INTEGER NOT NULL,
    site_id         TEXT NOT NULL,
    source_sha      TEXT NOT NULL REFERENCES documents(sha256),
    page            INTEGER,
    equipment_class TEXT,                 -- diesel_genset | gas_turbine | recip_engine | fuel_cell
    unit_count      INTEGER,
    reported_value  REAL,
    reported_unit   TEXT,                 -- kW | MW | kVA | hp | bhp
    unit_kw         REAL,
    kw_assumption   TEXT,                 -- e.g. 'pf=0.8' when a conversion needed one
    manufacturer    TEXT,
    model           TEXT,
    fuel            TEXT,
    emissions_tier  TEXT,
    hours_limit     REAL,
    published_at    TEXT,
    first_seen_at   TEXT NOT NULL,
    recorded_at     TEXT NOT NULL,
    revision_reason TEXT NOT NULL,        -- new_document | amendment | correction | ...
    PRIMARY KEY (record_id, version),
    CHECK (recorded_at >= first_seen_at)
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or DATA_DIR / "permits.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def put_document(
    con: sqlite3.Connection,
    content: bytes,
    *,
    source: str,
    url: str | None,
    content_type: str | None = None,
    published_at: str | None = None,
    retrieved_at: str | None = None,
    raw_dir: Path | None = None,
) -> tuple[str, bool]:
    """Store bytes if unseen. Returns (sha256, is_new)."""
    sha = hashlib.sha256(content).hexdigest()
    if con.execute("SELECT 1 FROM documents WHERE sha256 = ?", (sha,)).fetchone():
        return sha, False
    ext = {"application/pdf": "pdf", "text/html": "html"}.get(
        (content_type or "").split(";")[0].strip(), "bin"
    )
    raw_dir = raw_dir or DATA_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{sha}.{ext}"
    path.write_bytes(content)
    con.execute(
        "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
        (sha, source, url, retrieved_at or utcnow(), published_at,
         content_type, len(content), str(path)),
    )
    con.commit()
    return sha, True
