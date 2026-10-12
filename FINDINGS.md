# What 42 Virginia air permits say about data center backup power

Anoop Ibrampur, October 2026. Code and data pipeline: this repository.

A data center in Virginia needs an air permit for its generators, and the permit lists
each one: how many, which engine, how big, what it may burn. DEQ publishes
194 of these permits on one page. I pulled 42 of them, turned each equipment table into
one row per unit with the page it came from, and checked every row against the permit's
own numbers before counting it.

Out of that come 3,190 generators (8.6 GW) at 37 sites that pass every check. Another
1,439 are held for review, almost all of them one unusual site (below). Most of what
follows is about the 2026 permits, because that is where the paperwork is changing.

## 1. Generators permitted to run outside emergencies showed up in 2026

Three permits in this sample allow "non-emergency" generators: Amazon IAD-110 to 113 in
Prince William (96 units), Amazon IAD-243 to 292 in Loudoun (148 units), and the Brick
Plant building on Digital Realty's Manassas campus (22 units). That is 266 generators and 739 MW. All
three were issued in 2026, every one of those units comes with SCR and a particulate
filter, and nothing earlier in the sample has this.

The permits don't say what the extra running hours are for. Demand response or riding
through grid shortfalls would be my guess, but that is a guess. What I can say is that a
permit allowing non-emergency operation describes a different asset from a backup
generator that only runs for tests and outages, and anyone estimating engine hours or
fuel demand from headline megawatts would miss the difference.

Digital Realty's permit has 120 more non-emergency units that my pipeline failed to read
(footnote markers on the unit IDs). It flagged the site as incomplete rather than
counting it, so 266 is a floor.

## 2. SCR went from rare to common in one year

Nine of the 20 permits issued in 2026 mention selective catalytic reduction. Before
that it was 1 of 22. DEQ revised its diesel generator guidance (APG-576, effective April
9, 2026) to make SCR, an oxidation catalyst and a particulate filter the presumptive
controls for applications received from July 1, 2026, so this should keep climbing.

The permits name the aftertreatment suppliers: Caterpillar's 5X4X3 SCR and DPF system,
Johnson Matthey's cSCR3000, Safety Power's ecoCube and Miratech. I hadn't thought of
aftertreatment as its own market before reading these, but it clearly is one now.

## 3. Caterpillar's share is higher in the 2026 permits

By capacity that passes checks, Caterpillar has 48%, Cummins 36% and MTU (Rolls-Royce)
16%. Among units newly permitted in 2026 it is 59%, though with a
sample this small and this unevenly picked I wouldn't call it a trend yet. Unit size is flat:
new units average about 2.8 MW in 2026 and 2.9 MW in 2023 to 2025. The largest new unit
in the sample is a 3.62 MW Caterpillar C175-20 at the Belmont campus in Loudoun.

## 4. One campus looks nothing like the others

Clean Arc's VA-1 campus in Caroline County is permitted for 1,332 Volvo Penta
generators at 625 kW each, about 833 MW. Every other campus in the sample is built
around 2 to 3.6 MW units. Thirteen hundred small engines is a different maintenance, fuel and supplier story, and Volvo
Penta is not a name most data center equipment trackers follow. My pipeline holds this
row for review because it can't parse "1 through 1,332" as a list of unit IDs yet. The
count itself is right.

## 5. Six sites were filed by LLCs that hide the company behind them

35 of the 41 sites are filed under a name that identifies the company. The other six
took outside records, and I only accepted a link when the evidence tied back to the
permit itself, usually through its mailing address:

| Filed as | Company | How I know |
|---|---|---|
| Belmont Holdings I, Loudoun Prop 1 and 2 | SDC Capital Partners | Permit address is SDC's floor at 817 Broadway; press names SDC as applicant |
| GCDC Purchaser Phase 1 | Corscale, with Affinius Capital | Press names Corscale; permit address is Affinius's San Antonio HQ |
| CLOP Ashland VA | Connect Data Centers (Oppidan) | Permit address is Connect's HQ in Excelsior, MN |
| Scout Development | Meta | Henrico County resolution names Scout as developer of Facebook's site |
| Quality Investment Properties Richmond | QTS | Permit address is the QTS Richmond 1 campus |
| Herndon Technology Partners | Menlo Digital | Site address is Menlo's MD-DC1; permit calls it "MD-VA1" |

Four of these are inferred from addresses and directories, not registry records.
Virginia's business registry blocks automated access, so those lookups are still manual.

## 6. You can't just add up permit tables

The permits contradict themselves more often than I expected:

- Amazon's IAD-51/56/88/89 permit lists "Thirty-six (36)" generators for a row whose unit IDs cover 29.
- Digital Realty lists four groups of 60 generators over the same 120 unit IDs, with a
  footnote saying only 120 will be built. Summing the table gives double the real number.
- Microsoft's LYH10 permit cites units EG1 to EG105 once in its conditions, which looks
  copied from a different Microsoft permit.
- Microsoft's East Coast permit names ENG111 and ENG112 in its conditions but not in its
  equipment table.

So the pipeline checks every row against the permit's own counts, unit IDs and
conditions, and holds anything that disagrees instead of guessing.

## How much to trust these numbers

I hand-labelled permits from page images and scored the extractor on them. The last
test used six permits nobody had looked at (2,023 generators), scored before any fixes:
it found 67% of table rows, and 70% of the rows it found were fully correct. Coverage is
the weak part. What it did get right is that no wrong generator count got through. All
four permits with problems were flagged, and the two it called clean were exactly right.

The sample is not random either. It is the first 29 permits on DEQ's list, ordered by
registration number, plus 13 recent ones, mostly from Northern Virginia. Microsoft's southern
Virginia campuses are over-represented and Loudoun is under-represented, so the
company totals describe this sample, not the state.

## What I'd do next

Read the remaining 152 permits, fix the three formats the last test exposed (several
equipment tables in one permit, footnote marks on unit IDs, thousands separators in ID
ranges), add permitted operating hours, and run the same thing on Texas, where the newest
data center permits are for gas turbines and engines that run all the time.
