# Extraction accuracy

`permitpipe eval` scores the extractor against hand labels.

- `sample.json`: 10 permits drawn at random (seed 20261012), 6 digital + 4 scanned,
  from the 29 downloaded. `tuned: true` marks the 4 permits inspected while building
  the extractor; their scores are optimistic.
- `gold.csv`: one row per equipment-table row, typed from rendered page images
  (`pages/`, not committed: some pages show individuals' names; re-render them from the
  permit PDFs with PyMuPDF at 100 dpi), not from the OCR text the extractor reads. First pass labelled by Claude;
  needs a human spot-check before the numbers are quoted.
- `baseline-2026-10-12.txt`: first full run.
- `after-fixes-2026-10-12.txt`: after fixing the failure modes the baseline found.

## Baseline (2026-10-12)

| | All 10 | 6 never seen | Digital (6) | Scanned (4) |
|---|---|---|---|---|
| Rows found (recall) | 75% | 50% | 92% | 8% |
| Rows that are real (precision) | 87% | 64% | 97% | 14% |
| Rows fully correct, of those found | 59% | 67% | n/a | n/a |
| Generator units, extracted / true | 648 / 672 | 433 / 453 | 624 / 635 | 24 / 37 |

Field accuracy on matched rows: manufacturer 100%, kW 100%, section 100%,
count 95%, IDs 95%, model 66%.

## What this says

- **Digital permits work; scanned permits don't.** 92% of rows found vs 8%.
- **Totals hide row errors.** Units are 96% right overall because a few big digital rows
  dominate, while 4 in 10 matched rows have a wrong field (mostly model).
- **The self-checks miss these errors.** Every wrong-but-found row passed its checks.
  Checks catch internal contradictions, not a missing model or a lost row.

## Failure modes, by rows affected

1. Scanned tables: IDs split across lines ("EG-16 / thru / EG-20"), bare numeric IDs
   ("1-5", "1, 2, 3, and 4"), OCR header noise. Values in those rows (count, maker, kW)
   are often right, but the row cannot be tied to its units.
2. Model printed after the rating ("Caterpillar 2,500 kWe Model 3516C"): 12 rows.
3. Unit IDs with no digits (EGHS, EGLS, EGR).

## After fixes (same 10 permits, 2026-10-12)

| | Baseline | After fixes |
|---|---|---|
| Rows found (recall) | 75% | **98%** |
| Rows that are real (precision) | 87% | **98%** |
| Rows fully correct, of those found | 59% | **94%** |
| Scanned permits: rows found | 8% | **92%** |
| Generator units, extracted / true | 648 / 672 | **672 / 672** |
| Generator MW, extracted / true | 1,660 / 1,709 | **1,702 / 1,709** |

Fixes: model read after the rating or after "Model"; IDs without digits (EGHS, EGR);
class from generator-style IDs; on OCR'd pages, the ID column rebuilt from the first
token of each printed line ("EG-16 / thru / EG-20"), numeric IDs ("1-5",
"1, 2, 3, and 4"), rows that open with their count, and section headings closing rows.
Scan rules apply only to OCR'd pages, so digital-page behaviour cannot regress through them.

What is left is OCR, not parsing: an unreadable rating ("aaeee"), unreadable IDs
("gand1o" for "9 and 10"), a rating printed on the line above its row. The one row with
an unreadable rating is held for review, as it should be.

**These numbers are optimistic.** The fixes were made while looking at these 10
permits, so this is now a development score. The honest number comes from permits nobody
has looked at.

## Next

1. Spot-check gold labels for 2-3 permits by hand (labels are Claude's first pass).
2. Label 5-10 permits nobody has looked at (ideally recent Loudoun/Prince William/Fairfax)
   and report that as the test score.

## Test set (2026-10-12): 7 permits nobody had looked at

`eval/test/`: 7 recent Northern Virginia permits (Loudoun, Fairfax, Prince William,
Culpeper; issued Jul-Sep 2026), labelled from page images *before* looking at extractor
output, scored with the extractor exactly as committed (`9b33df2`). All 7 are digital, so
this says nothing new about scans.

| | Dev set (after fixes) | **Test set** |
|---|---|---|
| Rows found (recall) | 98% | **55%** |
| Rows that are real (precision) | 98% | **73%** |
| Rows fully correct, of those found | 94% | **75%** |
| ...of rows that passed checks | 96% | **92%** |
| ...of rows held for review | n/a | **0% (3/3 held rows were wrong)** |
| Generator units, extracted / true | 672 / 672 | **473 / 674** |
| Generator MW, extracted / true | 1,702 / 1,709 | **1,429 / 1,934** |

**The dev score did not carry over.** The fixes fit the 10 permits they were made on;
newer permits use formats those didn't have. The checks held up better: rows that passed
were 92% fully correct, and every held row was in fact wrong.

Why rows were lost, by units affected:
1. Number-only IDs on *digital* pages ("1 through 22", "99 and 100",
   "1, 2, 12, 17, 18, 19, and 36"): the number-ID rules were only enabled for OCR'd pages.
   About 190 of the 201 missing units.
2. "Either Cummins ... or Caterpillar" / "and/or": the maker is chosen by a fixed list
   order, not by which name comes first in the text (DataBank row credited to Caterpillar).
3. New ID shapes: "EG5-H1".
4. Yondr: two rows merged (EG-01..EG-40 picked up EG-41..EG-55).

Any fix made against these 7 turns them into another development set; the next honest
score needs another fresh sample.

## Cross-check and fixes (2026-10-12, after the test result)

**Conditions cross-check.** Every permit restates its unit IDs in its conditions
("(Ref. Nos. 1 through 68, T1, and T2) shall be..."). The pipeline now collects those IDs
and compares them with the IDs in the equipment table. IDs in the conditions but not the
table mean rows were missed: the site is marked `incomplete`. An ID counts only if the
conditions mention it at least twice, which filters one-off typos (LYH10's conditions
once cite "EG1-EG105", copied from another permit) and OCR misreads ("EG-713").

- Measured while the extractor was still missing rows: it flagged **5 of 5** test permits
  and **2 of 2** dev permits that had missed units.
- False alarms now: 1 of 17 evaluated permits (Microsoft East Coast, whose conditions
  cite ENG111-ENG112, which its table does not list: a real inconsistency in the permit).
- Limit: it can only compare IDs it can parse. Rows whose IDs do not parse are reported
  as `unchecked_rows` instead of passing silently.

**Fixes.** One ID-list parser for tables, scans and conditions ("1 through 22",
"1, 2, 12, 17, 18, 19, and 36", "D1-D7", "EG5-H1", "EG-DD1A-01 through EG-DD1A-24");
maker = the one named first; and, the main one, **digital tables are rebuilt from
PyMuPDF table detection**, because PDF text layers often list a multi-row table column
by column (all IDs, then all descriptions), which no line-based rule can pair back up.

| | Dev (10) | Test (7) |
|---|---|---|
| Rows found | 98% | 100% |
| Rows fully correct | 94% | 100% |
| Generator units | 672 / 672 | 674 / 674 |

**The test column is no longer a held-out score**: these fixes were made after looking at
the test permits' failures. The last honest held-out number is the one above (55% of rows,
70% of units). The next honest number needs a third, untouched sample.

## Final held-out score (2026-10-12): 6 permits nobody had looked at

`eval/test2/`: 6 recent permits (Loudoun, Prince William, Caroline; Jun-Jul 2026),
**2,023 true generators**. Labelled from page images before looking at extractor output;
scored with the extractor exactly as committed (`919e852`), unchanged afterwards.

| Permit | True units | Extracted | Passed row checks | Site cross-check |
|---|---|---|---|---|
| Amazon IAD-51/56/88/89 | 112 | 119 | 83 | unchecked_rows (permit's own count typo held) |
| Gainesville Crossing | 229 | 65 | 65 | **incomplete** (only 1 of 3 equipment lists read) |
| Digital Realty Manassas | 146 | 29 | 25 | **incomplete** ("BYEG60*" IDs not parsed) |
| Amazon IAD-243-292 | 155 | 155 | 155 | ok |
| Clean Arc VA-1 | 1,332 | 1,332 | 0 | unchecked_rows ("1 through 1,332" not parsed) |
| Amazon IAD-264 | 49 | 49 | 49 | ok |
| **Total** | **2,023** | **1,749** | **377** | 2 ok, 4 flagged |

**Headline.** Taken at face value, the pipeline gets 67% of table rows and 70% of found rows
fully right. **But it never passed a wrong generator count:** every permit with a
problem was flagged, by a held row or by the site cross-check, and the 2 sites it marked
clean (204 units) are exactly right. The cost is coverage: only 204 of 2,023 units
(10%) come out of fully clean sites; 377 (19%) pass row checks. Errors that do get
through are labels, not counts: 3 rows typed "engine" instead of generator ("gen-/sets"
split by a line break) and 2 models read as "MTU".

**The cross-check also caught a labelling error.** The first pass of these labels read
only Gainesville's first equipment list; the cross-check's "incomplete" flag led to the
other two (pages 22 and 39, +164 units). The labels were corrected from the page images;
the extractor was not touched.

New failure modes (not yet fixed, so this score stays held-out):
1. Several equipment lists in one permit (one per building).
2. Footnote markers on IDs ("BYEG1 through BYEG60*"), plus a footnote that changes the
   meaning: four groupings over the same 120 IDs, "only 120 total units".
3. Thousands separators in IDs ("1 through 1,332").
4. "gen-/sets" split across lines; maker "Rolls Royce MTU" read as model "MTU".

**After scoring (not part of the held-out number):** two line-break bugs seen in the
final test were fixed afterwards ("gen- / sets" read as a non-generator engine, and
"non- / emergency" read as emergency). With them, the final set's fully-correct share
of found rows is 85% (was 70%); recall is unchanged at 67%.

## LLM fallback (2026-10-12)

`llm.py` asks a local model (qwen3.5:9b through Ollama, temperature 0, JSON schema) to
read the equipment-list text. Its rows are checked like the rules' rows plus grounding
checks (every ID, count, model and rating must appear in the text). `--mode hybrid` keeps
the rules' answer when it is clean and only switches a permit to the LLM's answer when
that answer does better on the permit's own checks.

Developed on the dev and test sets (prompt v1 -> v2: alternatives are one row; code: count
from IDs when none is printed, grounding that tolerates "00GEN-1" and split model names).

| LLM alone | v1 | v2 |
|---|---|---|
| dev: found rows fully correct | 51% | 91% |
| dev: correct among rows passing checks | 92% | 98% |
| test: fully correct / generator units | 97% / 722 of 674 | 100% / 674 of 674 |

**Held-out (test2), code frozen at `aa3c1b6`, scored once:** the hybrid made things
worse. Found rows fully correct fell from 88% (rules) to 50% (hybrid), and only 59% of
LLM rows that passed the checks were correct. Cause: on one Amazon permit the model
labelled all ten generator rows "cooling_tower", the checks only applied to combustion
equipment, so the mislabelled rows skipped them; the hybrid then preferred that answer
because it had fewer held rows. A label was a way out of the checks.

**Fix (after seeing the held-out result, so not a held-out number):** every row gets the
count and grounding checks whatever its label; a row with an engine maker and an
electrical rating must be power-producing equipment; and the hybrid may only switch to the
LLM if it does not lose checked generators. Re-scored on the same permits: LLM rows that
pass the checks are 13/13 correct, and the hybrid now matches the rules (it never picks
the LLM on any of the 23 evaluation permits).

What this says: with the gate closed, a 9B model is safe to run but not yet useful here.
The permits the rules still miss fail on ID grammar and permit semantics ("1 through
1,332"; four alternative groupings over the same 120 IDs), and the LLM's output goes
through the same ID parser and the same checks, so it fails on them too.

## Row-level merge, ID fixes (2026-10-12; all three sets have now been used for fixes)

- **Row-level merge**: the hybrid keeps every clean rules row and adds an LLM row only if
  it passed every check, overlaps no accepted unit ID, and either fills IDs the permit's
  conditions name but the table lacks, or replaces a held rules row.
- **ID grammar**: thousands separators ("1 through 1,332"), footnote marks ("BYEG60*"),
  two trailing letters ("BYPBB1MW"). Rows over **identical** unit IDs are now alternatives
  for the same units (kept once, other options recorded); **partial** overlaps are still
  held as contradictions.
- Maker-name words are not models ("Rolls Royce MTU 16V4000", "Volvo Penta TWD1683GE-B").

On test2 (no longer held-out), generators passing every check went from 541 to 1,994 of
2,023; the other 29 are the row where the permit contradicts itself (36 vs 29 IDs), held.
Scored by printed rows the tool reports 93% found and 89% fully correct; the remaining
"errors" are the four printed Digital Realty groupings that the extractor now folds into
two alternative pairs, which is right by true unit count (146 of 146).

**Where that leaves the LLM.** With the parser fixed, the rules handle all 23 evaluated
permits and the hybrid never calls the model. The ID grammar, not reading ability, was the
bottleneck: every improvement in coverage today came from parsing the permits' own ID
formats and semantics. The LLM path stays as a checked fallback for layouts the rules
haven't seen; whether it earns its place needs permits nobody has looked at.
