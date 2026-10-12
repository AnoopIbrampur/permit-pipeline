from pathlib import Path

import pytest

from permitpipe import store
from permitpipe.sources import tx_tceq, va_deq
from permitpipe.units import to_kw

FIX = Path(__file__).parent / "fixtures"


def test_va_parse_index():
    rows = va_deq.parse_index((FIX / "va_index_sample.html").read_text())
    assert [r["listing_key"] for r in rows] == ["11541-3", "11790-1", "21527-7"]
    ms = rows[2]
    assert ms["site_name"] == "Microsoft Corporation - East Coast Data Center"
    assert ms["issued_on"] == "2024-04-24"
    assert ms["program"] == "Article 1 - Title V"
    assert ms["locality"] == "Mecklenburg Co."
    assert ms["doc_id"] == "25642"


def test_va_url_ticks_decode_to_upload_time():
    assert va_deq.ticks_to_utc(638627840699300000) == "2024-09-24T14:14:29+00:00"


def test_va_match_pdf_deq_filenames():
    keys = ["11790-1", "21527-7", "21527-15", "71804-3", "71804-4", "30142-3", "52221-9"]
    rows = [{"listing_key": k} for k in keys]
    match = lambda f: (lambda r, n: (r and r["listing_key"], n))(*va_deq.match_pdf(f, rows))
    assert match("2152715_DC_Permit.pdf") == ("21527-15", "exact")
    assert match("7180403_DC_Permit.pdf") == ("71804-3", "exact")
    assert match("522219_DC_Permit.pdf") == ("52221-9", "exact")
    assert match("11790_DC_Permit.pdf") == ("11790-1", "registration only")
    assert match("3014202_DC_Permit.pdf")[0] == "30142-3"          # seq differs, noted
    assert "seq 2" in match("3014202_DC_Permit.pdf")[1]
    assert match("21527_DC_Permit.pdf")[0] is None                 # ambiguous
    assert match("99999_DC_Permit.pdf")[0] is None


def test_tx_parse_and_flag():
    rows = tx_tceq.parse_index((FIX / "tx_pending_sample.html").read_text())
    assert [r["row_id"] for r in rows] == ["408777", "400428", "400999"]
    crusoe = rows[1]
    assert crusoe["permit_numbers"] == ["182126", "GHGPSDTX2 63", "PSDTX1688"]
    assert len(crusoe["documents"]) == 2
    assert crusoe["is_data_center"] == 1
    # a generic project LLC is unknown, not "not a data center"
    assert rows[2]["is_data_center"] is None


@pytest.mark.parametrize("value,unit,kw,flagged", [
    (2500, "kW", 2500, False),
    (57, "MW", 57000, False),
    (3125, "kVA", 2500, True),
    (3634, "bhp", 3634 * 0.745699872 * 0.95, True),
])
def test_to_kw(value, unit, kw, flagged):
    out, assumption = to_kw(value, unit)
    assert out == pytest.approx(kw)
    assert (assumption is not None) == flagged


def test_store_dedupes_by_hash_and_keeps_revisions(tmp_path):
    con = store.connect(tmp_path / "t.db")
    kw = dict(source="va_deq", url="u", content_type="application/pdf", raw_dir=tmp_path)
    a, new_a = store.put_document(con, b"v1", **kw)
    a2, new_a2 = store.put_document(con, b"v1", **kw)
    b, new_b = store.put_document(con, b"v2", **kw)   # same URL re-posted with new bytes
    assert (new_a, new_a2, new_b) == (True, False, True)
    assert a == a2 != b
    assert con.execute("SELECT COUNT(*) FROM documents WHERE url='u'").fetchone()[0] == 2


def test_unit_versions_reject_recorded_before_seen(tmp_path):
    con = store.connect(tmp_path / "t.db")
    sha, _ = store.put_document(con, b"x", source="va_deq", url="u", raw_dir=tmp_path)
    with pytest.raises(Exception):
        con.execute(
            "INSERT INTO unit_versions (record_id, version, site_id, source_sha, "
            "first_seen_at, recorded_at, revision_reason) VALUES (?,?,?,?,?,?,?)",
            ("s:1", 1, "s", sha, "2026-10-02", "2026-10-01", "new_document"))
