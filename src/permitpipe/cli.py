"""permitpipe command line.

  permitpipe va-index <saved_index.html>   import a browser-saved VA DEQ index page
  permitpipe va-pdfs <dir> [--pattern]     import browser-saved VA permit PDFs
  permitpipe tx-pull                       fetch the TCEQ pending NSR table
  permitpipe status                        counts by source
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import store
from .sources import tx_tceq, va_deq


def cmd_va_index(args) -> None:
    con = store.connect()
    sha, n = va_deq.import_index(con, Path(args.html))
    print(f"va_deq index snapshot {sha[:12]}: {n} permits")


def cmd_va_pdfs(args) -> None:
    con = store.connect()
    snap = con.execute(
        "SELECT snapshot_sha FROM listings l JOIN documents d ON d.sha256 = l.snapshot_sha "
        "WHERE l.source = ? ORDER BY d.retrieved_at DESC LIMIT 1", (va_deq.SOURCE,)
    ).fetchone()
    if not snap:
        sys.exit("import the index page first (permitpipe va-index)")
    listings = [dict(r) for r in con.execute(
        "SELECT * FROM listings WHERE source = ? AND snapshot_sha = ?",
        (va_deq.SOURCE, snap["snapshot_sha"]))]
    for r in listings:
        m = va_deq._DOC_RE.search(r["doc_url"] or "")
        r["doc_id"] = m.group(1) if m else None
    new = unmatched = 0
    for pdf in sorted(Path(args.inbox).glob(args.pattern)):
        hit, note = va_deq.match_pdf(pdf.name, listings)
        if hit is None:
            unmatched += 1
            print(f"  unmatched  {pdf.name}: {note}")
            continue
        if note not in ("exact", "registration only"):
            print(f"  check      {pdf.name} -> {hit['listing_key']}: {note}")
        # the browser download time is when we actually retrieved the bytes
        downloaded = datetime.fromtimestamp(pdf.stat().st_mtime, timezone.utc)
        _, is_new = store.put_document(
            con, pdf.read_bytes(), source=va_deq.SOURCE, url=hit["doc_url"],
            content_type="application/pdf", published_at=hit["issued_on"],
            retrieved_at=downloaded.isoformat(timespec="seconds"))
        new += is_new
    print(f"imported {new} new PDFs, {unmatched} unmatched")


def cmd_tx_pull(args) -> None:
    con = store.connect()
    content, ctype = tx_tceq.fetch_index()
    sha, is_new = store.put_document(con, content, source=tx_tceq.SOURCE,
                                     url=tx_tceq.INDEX_URL, content_type=ctype)
    rows = tx_tceq.parse_index(content.decode("utf-8", errors="replace"))
    con.executemany(
        """INSERT OR IGNORE INTO listings
           (source, snapshot_sha, listing_key, site_name, applicant, doc_url, is_data_center)
           VALUES (?,?,?,?,?,?,?)""",
        [(tx_tceq.SOURCE, sha, ",".join(r["permit_numbers"]) or r["row_id"],
          r["facility"], r["applicant"], d["url"], r["is_data_center"])
         for r in rows for d in (r["documents"] or [{"url": ""}])],
    )
    con.commit()
    dc = [r for r in rows if r["is_data_center"]]
    print(f"tx_tceq snapshot {sha[:12]} ({'new' if is_new else 'unchanged'}): "
          f"{len(rows)} pending applications, {len(dc)} flagged as data center")
    for r in dc:
        print(f"  {r['applicant']} | {r['facility']} | {', '.join(r['permit_numbers'])}")


def cmd_status(args) -> None:
    con = store.connect()
    for row in con.execute(
        "SELECT source, COUNT(*) n, SUM(n_bytes) b FROM documents GROUP BY source"):
        print(f"{row['source']}: {row['n']} documents, {row['b'] / 1e6:.1f} MB")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="permitpipe")
    sub = p.add_subparsers(required=True)
    s = sub.add_parser("va-index"); s.add_argument("html"); s.set_defaults(fn=cmd_va_index)
    s = sub.add_parser("va-pdfs"); s.add_argument("inbox")
    s.add_argument("--pattern", default="*_DC_Permit.pdf"); s.set_defaults(fn=cmd_va_pdfs)
    sub.add_parser("tx-pull").set_defaults(fn=cmd_tx_pull)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
