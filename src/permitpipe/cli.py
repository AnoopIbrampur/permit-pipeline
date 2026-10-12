"""permitpipe command line.

  permitpipe va-index <saved_index.html>   import a browser-saved VA DEQ index page
  permitpipe va-pdfs <dir> [--pattern]     import browser-saved VA permit PDFs
  permitpipe ocr [--force]                 page text for every stored permit PDF
  permitpipe extract                       equipment rows -> versioned unit records
  permitpipe eval                          score extraction against eval/gold.csv
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


def cmd_ocr(args) -> None:
    from .ocr import page_texts

    con = store.connect()
    docs = con.execute(
        "SELECT sha256, path FROM documents WHERE content_type = 'application/pdf'").fetchall()
    for n, d in enumerate(docs, 1):
        pages = page_texts(Path(d["path"]), d["sha256"], force=args.force)
        ocr = [p for p in pages if p["method"] == "ocr"]
        confs = [p["mean_conf"] for p in ocr if p["mean_conf"] is not None]
        low = f", min conf {min(confs):.0f}" if confs else ""
        print(f"[{n}/{len(docs)}] {d['sha256'][:12]}: {len(pages)} pages, {len(ocr)} OCR{low}",
              flush=True)


def cmd_extract(args) -> None:
    from .extract import extract, load_units
    from .ocr import OCR_DIR, ocr_page_numbers

    con = store.connect()
    now = store.utcnow()
    docs = con.execute(
        """SELECT d.sha256, d.retrieved_at, l.listing_key, l.site_name, l.issued_on
           FROM documents d JOIN listings l ON l.doc_url = d.url AND l.source = 'va_deq'
           WHERE d.content_type = 'application/pdf'
           GROUP BY d.sha256 ORDER BY l.issued_on""").fetchall()
    for d in docs:
        ocr_dir = OCR_DIR / d["sha256"]
        if not (ocr_dir / "meta.json").exists():
            print(f"  skip {d['listing_key']}: no page text yet (run permitpipe ocr)")
            continue
        pages = [(int(p.stem[5:8]), p.read_text())
                 for p in sorted(ocr_dir.glob("page-[0-9][0-9][0-9].txt"))]
        rows = extract(pages, ocr_page_numbers(d["sha256"]))
        site_id = "VA-" + d["listing_key"].split("-")[0]
        stats = load_units(con, rows, site_id=site_id, source_sha=d["sha256"],
                           first_seen_at=d["retrieved_at"], published_at=d["issued_on"],
                           recorded_at=now)
        gens = [r for r in rows if r.equipment_class == "genset"]
        held = sum(r.held for r in rows)
        print(f"{d['listing_key']:9} {d['site_name'][:38]:38} rows={len(rows):3} held={held:2} "
              f"gensets={sum(r.count or 0 for r in gens):4} new={stats['new']} "
              f"changed={stats['changed']} retracted={stats['retracted']}")


def cmd_eval(args) -> None:
    from .evaluate import EVAL_DIR, evaluate, summarize

    eval_dir = EVAL_DIR if args.set == "dev" else EVAL_DIR / args.set
    permits = evaluate(eval_dir)["permits"]
    pct = lambda a, b: f"{a}/{b} = {100 * a / b:.0f}%" if b else "n/a"

    def show(title, ps):
        s = summarize(ps)
        print(f"\n## {title} ({s['permits']} permits)")
        print(f"  rows found (recall)        {pct(*s['row_recall'])}")
        print(f"  rows real (precision)      {pct(*s['row_precision'])}")
        for f, (a, b) in s["field_accuracy"].items():
            print(f"  {f:26} {pct(a, b)}")
        print(f"  rows fully correct         {pct(*s['rows_fully_correct'])}")
        print(f"    of rows that passed checks {pct(*s['passed_checks_fully_correct'])}")
        print(f"    of rows held for review    {pct(*s['held_fully_correct'])}")
        print(f"  generator units            gold {s['gold_units']}, extracted {s['pred_units']}"
              f" ({s['pred_units_passed_checks']} passed checks)")
        print(f"  generator MW               gold {s['gold_mw']}, extracted {s['pred_mw']}")

    show("All", permits)
    if args.set == "dev":
        show("Never seen during development", [p for p in permits if not p["tuned"]])
        show("Seen during development", [p for p in permits if p["tuned"]])
        show("Digital PDFs", [p for p in permits if p["kind"] == "digital"])
        show("Scanned PDFs", [p for p in permits if p["kind"] == "scanned"])

    print("\n## Errors")
    for p in permits:
        tag = "seen" if p["tuned"] else "unseen"
        for r in p["matched"]:
            bad = [f for f, v in r["fields"].items() if v is False]
            if bad:
                g, pr = r["gold"], r["pred"]
                got = {"count": pr.count, "equipment_class": pr.equipment_class,
                       "manufacturer": pr.manufacturer, "model": pr.model,
                       "unit_kw": pr.unit_kw, "section": pr.section,
                       "ref_ids": f"{len(pr.ref_ids)} ids"}
                want = dict(g, ref_ids=f"{len(__import__('permitpipe.evaluate', fromlist=['x']).gold_ids(g['ref_ids']))} ids")
                diffs = ", ".join(f"{f}: {got[f]!r} != {want[f]!r}" for f in bad)
                print(f"  {p['listing_key']} [{tag}{', HELD' if r['held'] else ''}] {g['ref_ids'][:28]}: {diffs}")
        for g in p["missed"]:
            print(f"  {p['listing_key']} [{tag}] MISSED {g['ref_ids'][:28]} ({g['count']} x {g['manufacturer']} {g['model']})")
        for x in p["spurious"]:
            print(f"  {p['listing_key']} [{tag}] SPURIOUS row p{x.page}: {x.raw.splitlines()[0][:60]!r}")


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
    s = sub.add_parser("ocr"); s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_ocr)
    sub.add_parser("extract").set_defaults(fn=cmd_extract)
    s = sub.add_parser("eval"); s.add_argument("--set", default="dev", help="dev | test")
    s.set_defaults(fn=cmd_eval)
    sub.add_parser("tx-pull").set_defaults(fn=cmd_tx_pull)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
