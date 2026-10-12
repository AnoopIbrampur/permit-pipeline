# permit-pipeline

Reads Virginia's air permits for data centers and turns each equipment table into one
record per generator: how many units, maker, model, kW rating, fuel, whether it is new
in that permit, and the page it came from. Records are versioned, so you can ask what
the data said on any past date. Each site is also linked to the company behind the
permit, with the evidence for that link.

The write-up of what the data shows is in [FINDINGS.md](FINDINGS.md).

## What came out of it

From 42 of the 194 permits DEQ lists (41 sites):

- 3,190 generators, 8.6 GW, at 37 sites, that pass every consistency check
- 1,439 more held for review, 1,332 of them at one campus whose unit IDs the parser
  can't read yet
- 266 non-emergency generators (739 MW), all in permits issued in 2026
- SCR mentioned in 9 of 20 permits issued in 2026, against 1 of 22 before
- every site linked to a company; six needed outside records because the permit was
  filed by an LLC that doesn't name its parent

## How far to trust it

I scored the extractor against hand labels typed from page images, never from the text
the extractor reads. Three rounds:

| | Permits | Rows found | Found rows fully correct |
|---|---|---|---|
| Development set (fixed against) | 10 | 98% | 94% |
| First test, before fixes | 7 | 55% | 75% |
| Final test, never looked at before scoring | 6 | 67% | 70% |

The last row is the honest number. Each new batch brought table layouts the first ones
didn't have, and a rule-based extractor only knows what it has seen.

What held up was the checking. In the final test no wrong generator count got through:
the four permits with problems were all flagged, and the two marked clean were exactly
right. The cost is coverage, since a lot of real data sits in the review queue. Details
and the full error lists are in [eval/README.md](eval/README.md).

## How it works

1. Collect. Every document is stored exactly as received, keyed by its SHA-256, with
   the time it was retrieved. A URL re-posted with different bytes counts as a new
   document.
2. Get the text. Digital pages with ruled tables are rebuilt row by row from
   PyMuPDF's table detection. That step mattered more than anything else here, because
   PDF text layers often list a table column by column (all the IDs, then all the
   descriptions) and no line-based parser can pair them back up. Scanned pages go
   through Tesseract, which keeps each printed row on one line.
3. Extract. One row per equipment line, with count, IDs, maker, model, rating and
   page. Ratings are converted to kW; the reported value is kept, and any conversion
   that needed an assumption (kVA power factor, shaft horsepower) is flagged.
4. Check against the permit itself. Does "Six (6)" agree with itself? Do the unit
   IDs add up to the stated count? Does any ID appear twice? A row that fails is held,
   not guessed. Then the site as a whole is compared with the unit IDs the permit's
   conditions refer to; IDs in the conditions but missing from the table mark the site
   incomplete. That cross-check caught a mistake in my own answer key.
5. Version. `unit_versions` is append-only. Re-running on the same documents writes
   nothing. A better read of the same document becomes a `correction`, a newer permit
   becomes a `new_document`, and rows a fixed extractor no longer produces get a
   `retracted` version instead of being deleted.
6. Resolve owners. Cover letters give the legal entity and a mailing address. Where
   the company isn't named, I linked it from outside records and kept the evidence in
   [research/owner_evidence.json](research/owner_evidence.json). A link is `direct` when
   a document about the site names the company and `inferred` when it rests on something
   like a shared address. The loader rejects links with no evidence from the permit, or
   with nothing but a single directory listing behind them. Names of individuals in
   cover letters are redacted before anything is stored.

## Running it

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
brew install tesseract
.venv/bin/pytest
```

DEQ's site refuses requests that don't come from a browser, and this project doesn't
try to get around that. Save the permit list page and the PDFs from a browser, then:

```bash
permitpipe va-index ~/Downloads/"Issued Air Permits for Data Centers | Virginia DEQ.html"
permitpipe va-pdfs ~/Downloads     # DEQ's own file names, e.g. 2152715_DC_Permit.pdf
permitpipe ocr                     # page text, cached per document hash
permitpipe extract                 # unit records, checks, cross-check
permitpipe owners                  # site -> company links
permitpipe eval --set test2        # score against hand labels (dev | test | test2)
```

`permitpipe tx-pull` fetches the Texas TCEQ list of pending air permit applications,
which robots.txt allows. Texas is collected but not extracted yet.

Downloaded documents, page text and the SQLite database live in `data/`, which is not
committed.

## Layout

```
src/permitpipe/
  store.py      raw document store and schema
  ocr.py        text layer, table detection, Tesseract
  extract.py    equipment rows, ID lists, checks, cross-check, versioned loading
  owners.py     cover letters, company links, evidence rules
  evaluate.py   scoring against hand labels
  units.py      kW conversion
  sources/      va_deq.py, tx_tceq.py
eval/           samples, hand labels and results for each round
research/       hand-researched ownership evidence
tests/          55 tests, many built from real permit text
```

## Known gaps

- 152 of DEQ's 194 permits haven't been read. The sample is the first 29 by
  registration number plus 13 recent ones, so it isn't representative of the state.
- Formats the last test exposed are not handled yet: several equipment tables in one
  permit, footnote marks on unit IDs ("BYEG60*"), and thousands separators in ID ranges.
- Permitted operating hours and emissions tiers are in the permits but not extracted.
- Four of the ownership links rest on addresses and directory listings rather than
  registry records. Virginia's business registry blocks automated access, so those
  lookups are manual.
- Company renames (Facebook to Meta, for example) aren't tracked as dated changes yet;
  names are kept as the documents print them.
