# permit-pipeline

Turn state air-permit filings for US data centers into **source-linked, point-in-time
records of every generator unit**: count, kW rating, make/model, fuel, emissions tier,
permitted hours, and the page each value came from.

Status: scaffold (collection + storage + schema). Extraction, reconciliation,
versioning and owner resolution are next — see the plan below.

## Sources

Surveyed 2026-10-12:

| | Virginia DEQ (primary) | Texas TCEQ (secondary) |
|---|---|---|
| Index | [Issued Air Permits for Data Centers](https://www.deq.virginia.gov/news-info/shortcuts/permits/air/issued-air-permits-for-data-centers): one curated table | [Pending NSR applications](https://www.tceq.texas.gov/permitting/air/newsourcereview/airpermits-pendingpermit-apps): every industry |
| Size | 194 issued permits; 91 Loudoun, 29 Fairfax, 29 Prince William; 107 issued 2024–26 | 339 pending applications, ~5 obviously data centers |
| Equipment | Mostly diesel backup gensets: the bulk of US data center generator units | Gas turbines and recip engines for behind-the-meter prime power |
| Documents | Full permits, mostly **copier scans** → OCR | Plain-language summaries + public notices (text PDFs) |
| Machine access | CDN returns 403 to non-browser clients | robots.txt allows; plain HTTP works |
| Per-doc timestamp | Upload time encoded in the document URL (.NET ticks) | none |

**Why Virginia first:** it is the largest data center market in the world, DEQ already
curates the list (no guessing which permits are data centers), and the permits carry
the unit-level tables this project is about. The scans make extraction the hard,
interesting part.

**Why Texas too:** it is where on-site gas generation is growing fastest, and it has
the opposite problem: a general list where data center power plants hide behind
project LLCs, so *finding* them is the work.

### Collecting Virginia

`deq.virginia.gov` blocks automated clients. This project does not work around that.
Pages and PDFs are saved from a normal browser and imported:

```bash
permitpipe va-index ~/Downloads/issued-air-permits-for-data-centers.html
permitpipe va-pdfs ~/Downloads/va-permits/     # filenames must contain the reg. no or doc id
```

For a recurring feed, the right route is asking DEQ for bulk access or using the
Virginia Permitting Transparency platform.

### Collecting Texas

```bash
permitpipe tx-pull
```

## Design (mirrors how a production alt-data feed has to work)

- **Raw store**: every document kept as received, keyed by SHA-256, with `retrieved_at`.
  A URL re-posted with different bytes is a new document.
- **Unit rows**: one row per equipment line, with `source_sha` + `page`.
- **Normalization**: ratings converted to kW, reported value/unit kept, and conversions
  that need an assumption (kVA power factor, bhp → kWe) are flagged (`units.py`).
- **Point-in-time**: `unit_versions` is append-only with `version`, `published_at`,
  `first_seen_at`, `recorded_at`, `revision_reason`; the DB rejects
  `recorded_at < first_seen_at`.

## Plan

| Day | Work |
|---|---|
| 1 | ✅ Source survey, scaffold, TX collector. Save VA index + PDFs. |
| 2–4 | OCR → unit tables with page refs; facility-total reconciliation (hold rows that don't add up) |
| 5–6 | Manufacturer/model standardization, dedupe application/draft/final/amendment into one site, versioned records, change events |
| 7 | Owner resolution: project LLC → developer/operator via SCC business registry and county records, marked `direct` / `inferred` |
| 8 | Hand-label ~30 permits; report field-level extraction accuracy |
| 9 | Findings write-up: permitted MW by county/OEM, Tier 2 vs Tier 4, trends 2022–26 |
| 10 | Polish |

## Dev

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```
