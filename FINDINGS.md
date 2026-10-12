# What 47 Virginia air permits say about data center backup power

Anoop Ibrampur, October 2026. Code and data pipeline: this repository.

A data center in Virginia needs an air permit for its generators, and the permit lists
each one: how many, which engine, how big, what it may burn. DEQ publishes 194 of these
permits on one page. I pulled 47 of them, turned each equipment table into one row per
unit with the page it came from, and checked every row against the permit's own numbers
before counting it.

That gives 5,370 generators (11.8 GW) at 43 sites that pass every check. Another 106 are
held for review. Most of what follows is about the 2026 permits, because that is where
the paperwork is changing.

## 1. Non-emergency generators are mostly a 2026 story

Five permits in the sample allow generators to run outside emergencies: 767 units and
2.2 GW.

| Site | Units | MW | First permitted |
|---|---|---|---|
| Cashvad Ventures, Manassas | 195 | 615 | April 2026 |
| Amazon IAD450, Spotsylvania | 186 | 512 | October 2024 |
| Amazon IAD-243 to 292, Loudoun | 148 | 407 | July 2026 |
| Digital Realty, Manassas | 142 | 426 | October 2023 and August 2025 |
| Amazon IAD-110 to 113, Prince William | 96 | 266 | June 2026 |

All five permit documents were issued in 2026, but the "original permit date" column in
their tables shows the idea is older: Digital Realty had non-emergency units on paper in
October 2023. Still, 439 of the 767 were first permitted this year, and Amazon holds three
of the five sites. Every one of these units comes with SCR and a particulate filter.

The permits don't say what the extra running hours are for. Demand response or riding
through grid shortfalls would be my guess, but that is a guess. What I can say is that a
permit allowing non-emergency operation describes a different asset from a backup
generator that only runs for tests and outages, and anyone estimating engine hours or
fuel demand from headline megawatts would miss the difference.

## 2. SCR went from rare to common in one year

Twelve of the 25 permits issued in 2026 mention selective catalytic reduction. Before
that it was 1 of 22. DEQ revised its diesel generator guidance (APG-576, effective April
9, 2026) to make SCR, an oxidation catalyst and a particulate filter the presumptive
controls for applications received from July 1, 2026, so this should keep climbing. It
is already reaching emergency units: the Word of Grace site in Fairfax puts SCR on 60
generators that may only run in emergencies.

The permits name the aftertreatment suppliers: Caterpillar's 5X4X3 SCR and DPF system,
Johnson Matthey's cSCR3000, Safety Power's ecoCube and Miratech. I hadn't thought of
aftertreatment as its own market before reading these, but it clearly is one now.

## 3. Caterpillar leads the new permits, and the biggest units got bigger

By capacity that passes checks, Caterpillar has 50%, Cummins 29%, MTU (Rolls-Royce) 14%
and Volvo Penta 7%, all of the Volvo Penta at one campus (below). Among units newly
permitted in 2026, Caterpillar's share is 56%. With a sample this uneven I wouldn't call
that a trend yet.

The typical unit hasn't changed: new units average about 2.8 MW in 2026 against 2.9 MW in
2023 to 2025. The top end has. Before 2026 nothing in the sample was larger than 3.1 MW.
This year's permits include 3.6 MW Caterpillar C175-20s at Belmont in Loudoun and thirty
4.0 MW C175-20s at Cashvad in Manassas.

## 4. One campus looks nothing like the others

Clean Arc's VA-1 campus in Caroline County is permitted for 1,332 Volvo Penta generators
at 625 kW each, about 833 MW. Every other campus in the sample is built around 2 to 4 MW
units. Thirteen hundred small engines is a different maintenance, fuel and supplier
story, and Volvo Penta is not a name most data center equipment trackers follow.

## 5. Eight sites were filed by LLCs that hide the company behind them

38 of the 46 sites are filed under a name that identifies the company. For the other
eight I looked for outside records, and only accepted a link when the evidence tied back
to the permit itself, usually through its mailing address or site name:

| Filed as | Company | How I know |
|---|---|---|
| Belmont Holdings I, Loudoun Prop 1 and 2 | SDC Capital Partners | Permit address is SDC's floor at 817 Broadway; press names SDC as applicant |
| GCDC Purchaser Phase 1 | Corscale, with Affinius Capital | Press names Corscale; permit address is Affinius's San Antonio HQ |
| 13832 Redskin Acquisition, LP | Starwood Capital Group | A Starwood affiliate bought the Word of Grace site at 13832 Redskin Drive |
| CLOP Ashland VA | Connect Data Centers (Oppidan) | Permit address is Connect's HQ in Excelsior, MN |
| Scout Development | Meta | Henrico County resolution names Scout as developer of Facebook's site |
| Quality Investment Properties Richmond | QTS | Permit address is the QTS Richmond 1 campus |
| Herndon Technology Partners | Menlo Digital | Site address is Menlo's MD-DC1; permit calls it "MD-VA1" |

The eighth, Cashvad Ventures LLC, is still unresolved. Its permit gives a Washington, DC
office address and I found nothing public that names the company behind it, so the field
stays empty. Four of these links rest on addresses and directories rather than registry
records; Virginia's business registry blocks automated access, so those lookups are
still manual.

## 6. You can't just add up permit tables

The permits contradict themselves more often than I expected:

- Amazon's IAD-51/56/88/89 permit lists "Thirty-six (36)" generators for a row whose unit
  IDs cover 29.
- Digital Realty lists four groups of 60 generators over the same 120 unit IDs, with a
  footnote saying only 120 will be built. Summing the table gives 266 generators for a
  site that will have 146.
- Microsoft's LYH10 permit cites units EG1 to EG105 once in its conditions, which looks
  copied from a different Microsoft permit.
- Microsoft's East Coast permit names ENG111 and ENG112 in its conditions but not in its
  equipment table.

So the pipeline checks every row against the permit's own counts, unit IDs and
conditions. Rows over identical unit IDs are treated as alternatives for the same units;
anything else that disagrees is held instead of guessed.

## How much to trust these numbers

I hand-labelled permits from page images and scored the extractor on permits it had never
seen, three times, fixing what each round exposed before the next one:

| Held-out round | Permits | Rows found | Found rows fully correct |
|---|---|---|---|
| First | 7 | 55% | 75% |
| Second | 6 | 67% | 70% |
| Third | 5 | 87% | 100% |

In the last round 368 of 563 generators passed every check, and none of the accepted
counts was wrong. The other 195 were held because one permit used a unit-ID format the
parser hadn't seen. That format is handled now, but only a fourth round can say where the
next miss will come from.

I also tried a local LLM (a 9B model through Ollama) as a fallback, with the permit's
checks deciding whether to accept its answer. The first held-out run made things worse:
the model labelled ten generators as cooling towers, my checks only applied to combustion
equipment, and so the mislabelled rows skipped them. After closing that hole every LLM
row the checks accepted was correct, but the model no longer adds anything, because the
misses that remain come from unit-ID formats and permit logic, not from reading the table.

The sample is not random either: the first 29 permits on DEQ's list, ordered by
registration number, plus 18 recent ones, mostly from Northern Virginia. Microsoft's
southern Virginia campuses are over-represented, so the company totals describe this
sample, not the state.

## What I'd do next

Read the remaining 147 permits, extract the original-permit-date column (section 1 had
to be checked against it by hand) and the permitted operating hours, and run the same
thing on Texas, where the newest data center permits are for gas turbines and engines
that run all the time.
