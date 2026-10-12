import pytest

from permitpipe import store
from permitpipe.extract import expand_refs, extract, load_units, normalize, words_to_int

# Shapes copied from real DEQ permits (born-digital layout, one cell per line).
MODERN = """Equipment List - Equipment at this facility covered by this permit document consists of:
Equipment included in the project:
Reference No.
Equipment Description
Rated Capacity
ENG140-ENG145
Six (6) Caterpillar Model C175-16 backup
engine-generator sets
4,376 bhp
3,100 kWe, each
--
Other Permitted Equipment:
Reference No.
Equipment Description
ENG1-ENG20,
ENG22-ENG41
Forty (40) Caterpillar Model
C175-16 backup engine-generator sets
4,376 bhp
3,100 kWe, each
ENG21
One (1) Caterpillar Model C15 backup engine-
generator set
762 bhp
500 kWe
Specifications included in the above tables are for informational purposes only.
"""

PAGE_BREAK = """Equipment List - Equipment at this facility consists of:
Other Permitted Equipment:
EG80-EG112
Thirty-three (33) MTU 16V4000
DS2250 diesel emergency generators
3,350 BHP, each
2,250 kW, each
"""
PAGE_BREAK_2 = """Quality Investment Properties Richmond, LLC
Registration Number: 51232
June 24, 2024
Page 4
Reference No.
Equipment Description
EG113-EG115
Three (3) Caterpillar model CAT
3516C diesel emergency generators
3,634 BHP, each
2,500 kW, each
CT01-CT04
Four (4) SPX Marley, 2-cell water
cooling towers
1. Emission Controls - Nitrogen oxides
"""

# Tesseract on an old scan: whole row on one line, bare row numbers as refs.
OLD_SCAN = """Equipment List - Equipment at this facility consists of the following:
No. |. Equipment Descnption Rated: Capacity - Requirements| Permit-Date :
Equipment to be added as part of this facility modification:
3 One Caterpillar 1500 KW diesel-powered 2500 brake NSPS 5/16/2008
emergency generator horsepower Subpart IIIl
Previously permitted equipment:
2 One Caterpillar 1500 KW diesel-powered 2500 brake NSPS 1413/2008
emergency generator horsepower Subpart Ill!
OPERATING/EMISSION LIMITATIONS
"""


@pytest.mark.parametrize("s,n", [
    ("Six", 6), ("Thirty-three", 33), ("One hundred thirty two", 132),
    ("Two hundred and ninety-five", 295), ("Ninety-nine", 99), ("banana", None),
])
def test_words_to_int(s, n):
    assert words_to_int(s) == n


def test_expand_refs_ranges_lists_and_padding():
    assert expand_refs("ENG1-ENG3, ENG5") == ["ENG1", "ENG2", "ENG3", "ENG5"]
    assert expand_refs("EG04-EG06") == ["EG04", "EG05", "EG06"]
    assert len(expand_refs("EG246-EG280, EG282-EG316")) == 70


def test_normalize_ocr_letter_o_in_ids():
    assert "EG01" in normalize("EGO1 - EGO6")
    assert "EG06" in normalize("EGO1 - EGO6")


def test_modern_table():
    rows = extract([(5, MODERN)])
    assert [r.count for r in rows] == [6, 40, 1]
    new, big, small = rows
    assert new.section == "new" and big.section == "existing"
    assert new.manufacturer == "Caterpillar" and new.model == "C175-16"
    assert new.unit_kw == 3100 and new.reported_unit == "kWe" and new.bhp == 4376
    assert new.duty == "emergency" and new.equipment_class == "genset"
    assert big.ref_ids[:2] == ["ENG1", "ENG2"] and len(big.ref_ids) == 40
    assert small.model == "C15" and small.unit_kw == 500
    assert not any(r.held for r in rows)


def test_table_across_pages_skips_running_header():
    rows = extract([(5, PAGE_BREAK), (6, PAGE_BREAK_2)])
    assert [(r.page, r.count, r.equipment_class) for r in rows] == [
        (5, 33, "genset"), (6, 3, "genset"), (6, 4, "cooling_tower")]
    assert rows[0].model == "16V4000 DS2250"     # 'DS2250' line did not start a new row
    assert rows[1].model == "3516C"


def test_count_mismatch_and_overlap_are_held():
    text = MODERN.replace("Forty (40)", "Thirty-nine (40)").replace("ENG1-ENG20,", "ENG1-ENG21,")
    rows = extract([(1, text)])
    big = rows[1]
    assert big.checks["count_words_match_digits"] is False
    assert big.checks["ref_ids_match_count"] is False
    assert big.checks["ref_ids_unique"] is False and rows[2].checks["ref_ids_unique"] is False
    assert big.held and not rows[0].held


def test_old_scan_rows():
    rows = extract([(4, OLD_SCAN)])
    assert [(r.ref_ids, r.section, r.count) for r in rows] == [(["3"], "new", 1), (["2"], "existing", 1)]
    assert rows[0].unit_kw == 1500 and rows[0].bhp == 2500 and rows[0].manufacturer == "Caterpillar"


def test_load_units_versions(tmp_path):
    con = store.connect(tmp_path / "t.db")
    sha, _ = store.put_document(con, b"permit", source="va_deq", url="u", raw_dir=tmp_path)
    kw = dict(site_id="VA-52903", source_sha=sha, first_seen_at="2026-10-12T05:00:00+00:00",
              published_at="2026-09-29")
    rows = extract([(5, MODERN)])
    assert load_units(con, rows, recorded_at="2026-10-12T06:00:00+00:00", **kw)["new"] == 3
    # re-running on the same text writes nothing
    assert load_units(con, rows, recorded_at="2026-10-12T07:00:00+00:00", **kw)["unchanged"] == 3
    # extractor fix on the same document -> 'correction' version
    rows[0].model = "C175-16 (fixed)"
    rows[0].manufacturer = "MTU"
    stats = load_units(con, rows, recorded_at="2026-10-12T08:00:00+00:00", **kw)
    assert stats["changed"] == 1
    v = con.execute("SELECT version, revision_reason FROM unit_versions "
                    "WHERE record_id = 'VA-52903:ENG140-ENG145' ORDER BY version").fetchall()
    assert [tuple(x) for x in v] == [(1, "new_document"), (2, "correction")]


def test_space_separated_ranges_and_shorthand():
    text = """Equipment List - Equipment at this facility covered by this permit consists of:
Equipment to be Constructed:
EG1-20
EG22-EG41
EG43-EG62
Sixty (60) Cummins C3000 D6e engines
4,308 bhp, each
"""
    (row,) = extract([(4, text)])
    assert len(row.ref_ids) == 60 and row.count == 60 and not row.held
    assert row.equipment_class == "genset"           # 'engines' under EG IDs
    assert row.reported_unit == "bhp" and row.kw_assumption   # kW derived, flagged


def test_ids_continuing_beside_description_in_scans():
    text = """Equipment List - Equipment at this facility covered by this permit consists of:
EG1-2 through EG1-4 | Seven (7) Caterpillar 3516B 2,876 bhp
EG2-1 through EG2-4 | SR-4-HV emergency diesel 2,000 ekW None
engine gen-sets (each unit)
"""
    (row,) = extract([(4, text)])
    assert row.ref_ids == ["EG1-2", "EG1-3", "EG1-4", "EG2-1", "EG2-2", "EG2-3", "EG2-4"]
    assert row.count == 7 and not row.held and row.unit_kw == 2000


def test_rows_no_longer_extracted_are_retracted(tmp_path):
    con = store.connect(tmp_path / "t.db")
    sha, _ = store.put_document(con, b"permit", source="va_deq", url="u", raw_dir=tmp_path)
    kw = dict(site_id="VA-1", source_sha=sha, first_seen_at="2026-10-12T05:00:00+00:00",
              published_at=None)
    rows = extract([(5, MODERN)])
    load_units(con, rows, recorded_at="2026-10-12T06:00:00+00:00", **kw)
    stats = load_units(con, rows[:2], recorded_at="2026-10-12T07:00:00+00:00", **kw)
    assert stats["retracted"] == 1
    last = con.execute("SELECT version, review_status, revision_reason FROM unit_versions "
                       "WHERE record_id = 'VA-1:ENG21' ORDER BY version DESC").fetchone()
    assert tuple(last) == (2, "retracted", "correction")
    # retracting is idempotent
    assert load_units(con, rows[:2], recorded_at="2026-10-12T08:00:00+00:00", **kw)["retracted"] == 0


# Real Tesseract output from scanned DEQ permits (cells interleave line by line).
SCAN_CORESITE = """Equipment List -
Equipment to be constructed:
EG-16 Five (5) Caterpillar diesel 2,000 kW 9 VAC 5-50-410
thru fired engine generator sets, (2937 bhp) and
EG-20 Model # 3516C each 9 VAC 5-60-100
Equipment permitted prior to this permit:
Four (4) Caterpillar diesel-
1, 2, 3, and 4 | fired engine generator sets, aaeee 9 VAC 5-60-100
Model # 3516
Equipment exempt from air permitting:
11 and 12 water heaters 0.25 million Btu/nr each 9 VAC 5-80-1105 B.1.
"""
SCAN_VIENNA = """Equipment List - Equipment at this facility consists of:
Equipment to be Constructed:
Five (5) Cummins 900DQFAD | 900 ekW Non
1-5 emergency diesel engine- 1,482 bhp
generator sets (each unit)
6-8 Three (3) Cummins 1,365 ekW N
: 1,365DQGAB emergency 2,200 bhp ume
diesel engine-generator sets (each unit)
"""
SCAN_DP = """Equipment List - Equipment at this facility consists of the following:
Equipment to be constructed:
EGO1—-— | (6) Cummins QSK78-G12 diesel-fueled 2500 kW
EGO6 engine-generator sets 4060 hp (nam eplate) 8/23/2016
Cummins QSK19-G8 diesel-fueled engine- 600 kw
EGO7 generator set 967 hp (nameplate) 8/23/2016
"""


def test_scan_id_column_thru_and_numeric_lists():
    rows = extract([(4, SCAN_CORESITE)], ocr_pages=frozenset({4}))
    got = [(r.ref_ids, r.count, r.section, r.unit_kw) for r in rows]
    assert got[0] == (["EG-16", "EG-17", "EG-18", "EG-19", "EG-20"], 5, "new", 2000)
    assert got[1][:3] == (["1", "2", "3", "4"], 4, "existing")
    assert rows[1].held                     # kW unreadable ('aaeee') -> held, not guessed
    assert rows[2].section == "exempt" and rows[2].equipment_class == "boiler"


def test_scan_count_printed_above_ids():
    rows = extract([(4, SCAN_VIENNA)], ocr_pages=frozenset({4}))
    assert [(r.ref_ids, r.count, r.unit_kw) for r in rows] == [
        (["1", "2", "3", "4", "5"], 5, 900), (["6", "7", "8"], 3, 1365)]


def test_scan_ocr_noise_in_ids_and_maker_starts_row():
    rows = extract([(4, SCAN_DP)], ocr_pages=frozenset({4}))
    assert [(len(r.ref_ids), r.count, r.model) for r in rows] == [(6, 6, "QSK78-G12"), (1, 1, "QSK19-G8")]


def test_scan_rules_do_not_apply_to_digital_pages():
    # same text without the OCR flag: numeric 'Five (5)' line must not split digital rows
    assert [r.count for r in extract([(5, MODERN)], ocr_pages=frozenset({5}))] == [6, 40, 1]


from permitpipe.extract import condition_ids, cross_check, parse_id_list  # noqa: E402


@pytest.mark.parametrize("text,n,first,last", [
    ("EG1-20 EG22-EG41 EG43-EG62", 60, "EG1", "EG62"),
    ("1, 2, 12, 17, 18, 19, and 36", 7, "1", "36"),
    ("3 through 11 and 13 through 16", 13, "3", "16"),
    ("GEN-97 through GEN-144", 48, "GEN-97", "GEN-144"),
    ("EG5-H1, EG5-H2, EG6-H1, and EG6-H2", 4, "EG5-H1", "EG6-H2"),
    ("EG1-2 through EG1-4", 3, "EG1-2", "EG1-4"),
    ("1 through 68, T1, and T2", 70, "1", "T2"),
    ("D1-D7, D18- D24", 14, "D1", "D24"),
    ("EG1-EG3 and EGR", 4, "EG1", "EGR"),
    ("00GEN-1", 1, "00GEN-1", "00GEN-1"),
])
def test_parse_id_list(text, n, first, last):
    ids = parse_id_list(text)
    assert (len(ids), ids[0], ids[-1]) == (n, first, last)


def test_table_rows_delimited_by_markers():
    # rebuilt from table detection: a model alone on a line must not start a row
    text = """Equipment List - Equipment at this facility covered by this permit document consists of:
Equipment to be Constructed:
<<row>>
EG5-H1,
EG5-H2,
EG6-H1,
and
EG6-H2
(4) Either Cummins
QSK38-G18
(C1500D6E) or
Caterpillar 3512C
emergency diesel-fired
engine gen-sets
1,500 ekW
2,011 bhp
"""
    (row,) = extract([(5, text)])
    assert row.count == 4 and len(row.ref_ids) == 4
    assert row.manufacturer == "Cummins" and row.model.startswith("QSK38-G18") and row.unit_kw == 1500


CONDITIONS = """
1. Emission Controls - emissions from the engine gen-sets (Ref. Nos. 1 through 4 and EG-13 through EG-28) shall be
2. Monitoring - Each engine (Ref. Nos. 1 through 4 and EG-13 through EG-28) shall be equipped
3. Fuel - the engines (Ref. Nos. 1 through 4 and EG-713 through EG-28) is diesel
4. Limits - engines (Ref. Nos. EG-13 through EG-28) shall not exceed
"""


def test_condition_ids_ignore_one_off_misreads():
    ids = set(condition_ids([(9, CONDITIONS)]))
    assert ids == {"1", "2", "3", "4"} | {f"EG{i}" for i in range(13, 29)}   # 'EG-713' dropped


def test_cross_check_flags_missing_rows():
    table = extract([(5, MODERN)])           # ENG1-ENG41, ENG140-ENG145 (no ENG42)
    conditions = "\n".join(f"{c} (Ref. Nos. ENG1-ENG42) shall" for c in ("Controls", "Hours", "Fuel"))
    pages = [(5, MODERN), (9, conditions)]
    x = cross_check(table, pages)
    assert x["status"] == "incomplete" and x["missing"] == ["ENG42"]
    assert cross_check(table, [(5, MODERN)])["status"] == "no_reference"
