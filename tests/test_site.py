import json

from permitpipe import store
from permitpipe.owners import SCHEMA as OWNER_SCHEMA
from permitpipe.site import export

EMAIL_QUOTE = "Datacenter Operations Manager / Example Corp / 1 Main St / Jane.Doe@example.com"


def _db(path):
    con = store.connect(path)
    con.executescript(OWNER_SCHEMA)
    con.execute("INSERT INTO documents VALUES ('sha1','va_deq','https://deq.example/p.pdf','2026-10-12T00:00:00+00:00',"
                "'2026-06-01','application/pdf',10,'data/raw/sha1.pdf')")
    con.execute("INSERT INTO documents VALUES ('idx','va_deq','https://deq.example/index','2026-10-12T00:00:00+00:00',"
                "NULL,'text/html',10,'data/raw/idx.html')")
    con.execute("INSERT INTO listings VALUES ('va_deq','idx','12345-1','Example Campus','Example LLC','2026-06-01',"
                "'NSR','Loudoun Co.','Northern','https://deq.example/p.pdf',NULL,1)")
    cols = ("record_id, version, site_id, source_sha, page, section, ref_ids, equipment_class, unit_count, "
            "reported_value, reported_unit, unit_kw, kw_assumption, manufacturer, model, fuel, emissions_tier, "
            "hours_limit, duty, raw_text, checks, flags, review_status, published_at, first_seen_at, recorded_at, "
            "revision_reason")

    def add(rid, version, cls, count, status, checks):
        con.execute(f"INSERT INTO unit_versions ({cols}) VALUES ({','.join('?' * 27)})",
                    (rid, version, "VA-12345", "sha1", 4, "new", "[]", cls, count, 2000.0, "kW", 2000.0, None,
                     "Caterpillar", "C175", None, None, None, "emergency", "row", json.dumps(checks), "[]",
                     status, "2026-06-01", "2026-10-12T00:00:00+00:00", "2026-10-12T00:00:00+00:00",
                     "new_document"))

    add("VA-12345:G1-G10", 1, "genset", 10, "ok", {"has_count": True})
    add("VA-12345:G11-G13", 1, "genset", 3, "held", {"ref_ids_match_count": False})
    add("VA-12345:B1", 1, "boiler", 1, "ok", {})
    add("VA-12345:OLD", 1, "genset", 99, "ok", {})
    add("VA-12345:OLD", 2, "genset", 99, "retracted", {})  # later fix retracted it
    con.execute("INSERT INTO site_checks VALUES ('VA-12345','sha1','2026-10-12T00:00:00+00:00','ok',13,13,'[]')")
    con.execute("INSERT INTO site_entities VALUES ('VA-12345','sha1','Example LLC','example','addressee',NULL,1)")
    con.execute("INSERT INTO owner_links VALUES ('VA-12345','operator','Example Corp','direct','named_in_permit',?,"
                "'2026-10-12T00:00:00+00:00')",
                (json.dumps([{"source_sha": "sha1", "page": 1, "quote": EMAIL_QUOTE}]),))
    con.commit()


def test_export_counts_current_checked_gensets_and_drops_quotes(tmp_path):
    db = tmp_path / "permits.db"
    _db(db)
    s = export(tmp_path / "site", db)
    assert s["gens_ok"] == 10 and s["gens_held"] == 3  # boiler and retracted rows not counted
    assert s["permits_read"] == 1 and s["permits_listed"] == 1 and s["sites_linked"] == 1

    raw = (tmp_path / "site" / "data.json").read_text()
    assert "Jane.Doe" not in raw and "@example.com" not in raw  # cover-letter quotes never published
    data = json.loads(raw)
    site = data["sites"][0]
    assert site["links"][0]["permit_page"] == 1 and site["mw_ok"] == 20.0
    ids = {u["ids"] for u in data["units"]}
    assert "OLD" not in ids and {"G1-G10", "G11-G13", "B1"} <= ids
    held = next(u for u in data["units"] if u["ids"] == "G11-G13")
    assert held["failed_checks"] == ["ref_ids_match_count"]
