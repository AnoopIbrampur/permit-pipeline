# Extraction accuracy

`permitpipe eval` scores the extractor against hand labels.

- `sample.json`: 10 permits drawn at random (seed 20261012), 6 digital + 4 scanned,
  from the 29 downloaded. `tuned: true` marks the 4 permits inspected while building
  the extractor; their scores are optimistic.
- `gold.csv`: one row per equipment-table row, typed from rendered page images
  (`pages/`), not from the OCR text the extractor reads. First pass labelled by Claude;
  needs a human spot-check before the numbers are quoted.
- `baseline-2026-10-12.txt`: first full run.

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

## Next

These 10 permits are now a development set. After fixing against them, accuracy must
be re-measured on permits nobody has looked at (a fresh labelled test set).
