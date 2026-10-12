# Extraction accuracy

`permitpipe eval` scores the extractor against hand labels.

- `sample.json`: 10 permits drawn at random (seed 20261012), 6 digital + 4 scanned,
  from the 29 downloaded. `tuned: true` marks the 4 permits inspected while building
  the extractor; their scores are optimistic.
- `gold.csv`: one row per equipment-table row, typed from rendered page images
  (`pages/`), not from the OCR text the extractor reads. First pass labelled by Claude;
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
