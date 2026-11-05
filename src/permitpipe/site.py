"""Export the current records to a static explorer (site/), for GitHub Pages.

    permitpipe site            # writes site/data.json; site/index.html is checked in

The database lives in data/ and isn't committed, so the export is run locally and its
output committed. It publishes only what the pipeline derives from public permits:
current unit rows (latest version, retracted rows dropped), their checks, site
cross-checks and company links. Cover-letter quotes are left out because they can carry
contact details; each link points to the permit page instead, and outside evidence comes
from research/owner_evidence.json, which is already paraphrased.
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import store
from .owners import SCHEMA as OWNER_SCHEMA

ROOT = Path(__file__).resolve().parents[2]
SITE_DIR = ROOT / "site"
EVIDENCE = ROOT / "research" / "owner_evidence.json"

# Held-out evaluation rounds, as reported in eval/README.md.
EVAL_ROUNDS = [
    {"round": "First", "permits": 7, "rows_found": 0.55, "rows_correct": 0.75},
    {"round": "Second", "permits": 6, "rows_found": 0.67, "rows_correct": 0.70},
    {"round": "Third", "permits": 5, "rows_found": 0.87, "rows_correct": 1.00},
]


def counted(r) -> bool:
    """Rows that go into generator totals: gensets in the permit's equipment, not exempt."""
    return r["equipment_class"] == "genset" and r["section"] != "exempt"


def current_units(con) -> list:
    return con.execute(
        """SELECT * FROM unit_versions u
           WHERE version = (SELECT MAX(version) FROM unit_versions WHERE record_id = u.record_id)
             AND review_status != 'retracted'
           ORDER BY site_id, page, record_id""").fetchall()


def _outside_evidence() -> dict:
    if not EVIDENCE.exists():
        return {}
    links = json.loads(EVIDENCE.read_text())["links"]
    out = {}
    for link in links:
        out[(link["site_id"], link["company"])] = [
            {"kind": e["kind"], "claim": e.get("claim"), "url": e.get("url"), "page": e.get("page")}
            for e in link.get("evidence", [])]
    return out


def _listed_in_latest_index(con) -> int:
    """Data center permits on the most recently saved DEQ index page."""
    snap = con.execute(
        """SELECT l.snapshot_sha FROM listings l JOIN documents d ON d.sha256 = l.snapshot_sha
           WHERE l.source = 'va_deq' GROUP BY l.snapshot_sha ORDER BY MAX(d.retrieved_at) DESC LIMIT 1""").fetchone()
    if not snap:
        return 0
    return con.execute("SELECT COUNT(DISTINCT listing_key) FROM listings WHERE snapshot_sha = ? "
                       "AND is_data_center = 1", (snap[0],)).fetchone()[0]


def build_data(con) -> dict:
    con.executescript(OWNER_SCHEMA)  # no-op once `permitpipe owners` has run
    units = current_units(con)
    docs = {r["sha256"]: r["url"] for r in con.execute("SELECT sha256, url FROM documents")}
    listing = {}
    for r in con.execute(
            """SELECT l.* FROM listings l JOIN documents d ON d.url = l.doc_url
               WHERE l.source = 'va_deq' ORDER BY l.issued_on"""):
        listing["VA-" + r["listing_key"].split("-")[0]] = r  # latest issued wins
    checks = {}
    for r in con.execute("SELECT * FROM site_checks ORDER BY recorded_at"):
        checks[r["site_id"]] = r
    links = defaultdict(list)
    for r in con.execute("SELECT site_id, role, company, link_type, rule, evidence FROM owner_links"):
        first = json.loads(r["evidence"])[0]
        links[r["site_id"]].append({
            "company": r["company"], "role": r["role"], "link_type": r["link_type"], "rule": r["rule"],
            "permit_page": first.get("page") if "source_sha" in first else None})
    outside = _outside_evidence()

    by_site = defaultdict(list)
    for u in units:
        by_site[u["site_id"]].append(u)

    # Every site read, including one whose rows were all retracted by a later fix.
    site_ids = sorted(set(by_site) | {r[0] for r in con.execute("SELECT DISTINCT site_id FROM site_entities")})
    sites, rows = [], []
    for site_id in site_ids:
        us = by_site.get(site_id, [])
        lst, chk = listing.get(site_id), checks.get(site_id)
        gens = [u for u in us if counted(u)]
        ok = [u for u in gens if u["review_status"] == "ok"]
        held = [u for u in gens if u["review_status"] == "held"]
        site_links = []
        for link in links.get(site_id, []):
            ev = outside.get((site_id, link["company"]), [])
            site_links.append({**link, "evidence": [e for e in ev if e["kind"] != "permit"]})
        makers = Counter()
        for u in ok:
            makers[u["manufacturer"] or "Unknown"] += (u["unit_count"] or 0) * (u["unit_kw"] or 0)
        sites.append({
            "id": site_id,
            "name": lst["site_name"] if lst else site_id,
            "applicant": lst["applicant"] if lst else None,
            "locality": lst["locality"] if lst else None,
            "region": lst["region"] if lst else None,
            "issued": lst["issued_on"] if lst else None,
            "doc_url": lst["doc_url"] if lst else None,
            "check": chk["status"] if chk else None,
            "missing_ids": len(json.loads(chk["missing_ids"])) if chk else 0,
            "links": site_links,
            "gens_ok": sum(u["unit_count"] or 0 for u in ok),
            "mw_ok": round(sum((u["unit_count"] or 0) * (u["unit_kw"] or 0) for u in ok) / 1000, 1),
            "gens_held": sum(u["unit_count"] or 0 for u in held),
            "non_emergency": sum(u["unit_count"] or 0 for u in ok if u["duty"] == "non_emergency"),
            "top_maker": makers.most_common(1)[0][0] if makers else None,
        })
        for u in us:
            failed = [k for k, v in json.loads(u["checks"]).items() if v is False]
            rows.append({
                "site": site_id,
                "ids": u["record_id"].split(":", 1)[1],
                "page": u["page"],
                "section": u["section"],
                "class": u["equipment_class"],
                "count": u["unit_count"],
                "maker": u["manufacturer"],
                "model": u["model"],
                "kw": u["unit_kw"],
                "reported": f"{u['reported_value']:g} {u['reported_unit']}" if u["reported_value"] else None,
                "assumption": u["kw_assumption"],
                "duty": u["duty"],
                "status": u["review_status"],
                "counted": counted(u),
                "failed_checks": failed,
                "flags": json.loads(u["flags"]),
                "published": u["published_at"],
                "doc_url": docs.get(u["source_sha"]),
            })

    ok_rows = [r for r in rows if r["counted"] and r["status"] == "ok"]
    makers = Counter()
    for r in ok_rows:
        makers[r["maker"] or "Unknown"] += (r["count"] or 0) * (r["kw"] or 0)
    total_kw = sum(makers.values())
    sites.sort(key=lambda s: -s["mw_ok"])
    return {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "permits_read": con.execute(
                "SELECT COUNT(*) FROM documents WHERE source = 'va_deq' "
                "AND content_type = 'application/pdf'").fetchone()[0],
            "permits_listed": _listed_in_latest_index(con),
            "sites": len(sites),
            "sites_with_ok": sum(1 for s in sites if s["gens_ok"]),
            "gens_ok": sum(r["count"] or 0 for r in ok_rows),
            "gw_ok": round(total_kw / 1e6, 2),
            "gens_held": sum(r["count"] or 0 for r in rows if r["counted"] and r["status"] == "held"),
            "non_emergency": sum(r["count"] or 0 for r in ok_rows if r["duty"] == "non_emergency"),
            "sites_linked": sum(1 for s in sites if s["links"]),
        },
        "makers": [{"maker": m, "mw": round(kw / 1000, 1), "share": round(kw / total_kw, 3)}
                   for m, kw in makers.most_common()],
        "eval": EVAL_ROUNDS,
        "sites": sites,
        "units": rows,
    }


def export(out: Path = SITE_DIR, db_path: Path | None = None) -> dict:
    con = store.connect(db_path)
    data = build_data(con)
    out.mkdir(parents=True, exist_ok=True)
    (out / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    return data["summary"]
