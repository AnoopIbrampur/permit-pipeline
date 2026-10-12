"""LLM reading of equipment tables, accepted only when the permit agrees with it.

The rule-based extractor is precise but brittle: a new table layout means missed rows.
This module asks a local model (Ollama) to read the same equipment-table text and return
one JSON object per row. Nothing it says is trusted on its own. Every row goes through:

  grounding   each value must appear in the source text: the ID text, the count, the
              rating, the model (catches values the model made up or copied from
              another row of the prompt)
  the usual   count words vs digits, IDs vs count, duplicate IDs, has maker / rating
  site check  the permit's conditions list the unit IDs; the table must cover them

`hybrid()` keeps the rules' answer when it is clean, and only switches a permit to the
LLM's answer when that answer passes more checks.

Responses are cached per (document, model, prompt version), at temperature 0, so a run
is repeatable and re-scoring costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .extract import (OEMS, UnitRow, _first_maker, cross_check, equipment_regions, extract,
                      normalize, parse_id_list, words_to_int)
from .store import DATA_DIR
from .units import to_kw

MODEL = "qwen3.5:9b"
PROMPT_VERSION = "v2"
CACHE_DIR = DATA_DIR / "llm"

ROW_SCHEMA = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref_ids": {"type": "string"},
                    "count": {"type": ["integer", "null"]},
                    "equipment": {"type": "string", "enum": [
                        "generator", "fire_pump", "boiler", "turbine", "fuel_cell",
                        "cooling_tower", "tank", "other"]},
                    "manufacturer": {"type": ["string", "null"]},
                    "model": {"type": ["string", "null"]},
                    "rating_value": {"type": ["number", "null"]},
                    "rating_unit": {"type": ["string", "null"]},
                    "section": {"type": "string", "enum": ["new", "existing", "exempt", "unknown"]},
                    "duty": {"type": "string", "enum": ["emergency", "non_emergency", "unknown"]},
                },
                "required": ["ref_ids", "count", "equipment", "manufacturer", "model",
                             "rating_value", "rating_unit", "section", "duty"],
            },
        }
    },
    "required": ["rows"],
}

PROMPT = """You are reading the equipment list of a Virginia air permit for a data center.
Return one JSON object per table row, in table order. Rules:
- ref_ids: the reference number cell copied exactly as printed (e.g. "EG-1 through EG-112",
  "1, 2, 12, 17, 18, 19, and 36", "GEN001-GEN247"). Never invent or renumber IDs.
- count: the number of units the row describes, as printed ("Forty (40)" -> 40). If the row
  states no number, null.
- manufacturer/model: the first maker and model named in the row. Copy the model as printed.
- rating_value/rating_unit: the electrical output per unit (kW, ekW, kWe, MW, kVA). Use bhp
  only if no electrical rating is printed. Ignore "mkW" mechanical ratings.
- section: "new" for equipment to be constructed / included in this project, "existing" for
  previously or otherwise permitted equipment, "exempt" for exempt equipment.
- duty: "non_emergency" if the row says non-emergency, else "emergency" if it says
  emergency/backup/standby, else "unknown".
- A row that lists alternative makers or models for the same units ("Caterpillar 3516C;
  MTU 20V4000 DS2500; or MTU 16V4000 DS2250", "Cummins ... and/or Caterpillar ...") is ONE
  row: use the first maker/model and the first rating listed.
- Rows that are table headers or section titles are not rows.

Equipment list text:
"""


def _cache_path(sha: str) -> Path:
    key = hashlib.sha256(f"{MODEL}|{PROMPT_VERSION}|{PROMPT}".encode()).hexdigest()[:12]
    return CACHE_DIR / f"{sha}.{key}.json"


def region_text(pages: list[tuple[int, str]]) -> str:
    out = []
    for region in equipment_regions(pages):
        out.append("\n".join(line for _, line in region if line != "<<row>>"))
    return "\n\n--- next equipment list ---\n\n".join(out)


def ask(text: str, sha: str | None = None) -> list[dict]:
    """Model rows for one permit's equipment-list text (cached by document hash)."""
    if sha:
        cached = _cache_path(sha)
        if cached.exists():
            return json.loads(cached.read_text())
    import ollama

    resp = ollama.chat(model=MODEL, think=False, format=ROW_SCHEMA,
                       options={"temperature": 0, "num_ctx": 16384},
                       messages=[{"role": "user", "content": PROMPT + text}])
    rows = json.loads(resp.message.content).get("rows", [])
    if sha:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(sha).write_text(json.dumps(rows, indent=1))
    return rows


# ------------------------------------------------------------------ grounding


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _num_forms(v: float) -> list[str]:
    n = int(v) if float(v).is_integer() else v
    return [str(n), f"{n:,}"] if isinstance(n, int) else [str(n)]


def grounding(row: dict, text: str) -> dict[str, bool]:
    t = normalize(text)
    flat = re.sub(r"\s+", " ", t)
    checks = {}
    ids = re.sub(r"\s+", " ", normalize(row["ref_ids"] or "")).strip()
    # every ID the model printed must be in the text; split on list/range words only, so
    # "00GEN-1" and "EG5-H1" stay whole. Dashes and spaces inside an ID may differ.
    pieces = [p.strip(" -") for p in re.split(
        r"\s*(?:,|;|&|\band\b|\bthrough\b|\bthru\b|\bto\b)\s*|\s+-\s+", ids) if p.strip(" -")]

    def present(piece: str) -> bool:
        pat = r"[\s-]*".join(re.escape(ch) for ch in re.sub(r"[\s-]", "", piece))
        return bool(re.search(rf"(?<![A-Za-z0-9]){pat}(?![A-Za-z0-9])", flat))

    checks["grounded_ids"] = bool(pieces) and all(present(p) for p in pieces)
    if row["count"] is not None:
        c = row["count"]
        words = {w for w in re.findall(r"[A-Za-z][A-Za-z\- ]+(?=\s*\(\s*\d)", flat)
                 if words_to_int(w.strip()) == c}
        checks["grounded_count"] = bool(re.search(rf"\(\s*{c:,}\s*\)|\(\s*{c}\s*\)", flat)) or bool(words) \
            or len(parse_id_list(ids)) == c
    if row["model"]:
        parts = [_alnum(x) for x in re.split(r"[\s(),;/]+", row["model"]) if _alnum(x)]
        checks["grounded_model"] = bool(parts) and all(x in _alnum(flat) for x in parts)
    if row["rating_value"] is not None:
        checks["grounded_rating"] = any(f in flat for f in _num_forms(row["rating_value"]))
    if row["manufacturer"]:
        maker = _first_maker(row["manufacturer"])
        checks["grounded_maker"] = bool(maker and re.search(OEMS[maker], flat, re.I)) \
            or row["manufacturer"].lower() in flat.lower()
    return checks


_CLASS = {"generator": "genset", "fire_pump": "fire_pump", "boiler": "boiler",
          "turbine": "gas_turbine", "fuel_cell": "fuel_cell", "cooling_tower": "cooling_tower",
          "tank": "storage_tank", "other": None}


def to_unit_rows(model_rows: list[dict], text: str) -> list[UnitRow]:
    out = []
    for r in model_rows:
        ids = parse_id_list(r["ref_ids"] or "")
        count_from_ids = r["count"] is None and bool(ids)
        if count_from_ids:              # "00GEN-1  Emergency engine-generator set": no count printed
            r = dict(r, count=len(ids))
        kw = assumption = None
        unit = (r["rating_unit"] or "").strip()
        if r["rating_value"] is not None and unit:
            try:
                kw, assumption = to_kw(float(r["rating_value"]), unit)
            except ValueError:
                pass
        cls = _CLASS.get(r["equipment"])
        maker = _first_maker(r["manufacturer"] or "") or (r["manufacturer"] or None)
        row = UnitRow(
            page=0, raw=json.dumps(r), section=None if r["section"] == "unknown" else r["section"],
            ref_ids=ids, count=r["count"], count_words=None, count_digits=r["count"],
            equipment_class=cls, manufacturer=maker, model=r["model"], fuel=None,
            duty=None if r["duty"] == "unknown" else r["duty"],
            reported_value=r["rating_value"], reported_unit=unit or None, unit_kw=kw,
            kw_assumption=assumption, bhp=None)
        row.checks.update(grounding(r, text))
        if ids and r["count"] is not None:
            row.checks["ref_ids_match_count"] = len(ids) == r["count"]
        if cls in ("genset", "fire_pump", "gas_turbine", "fuel_cell"):
            row.checks["has_manufacturer"] = maker is not None
            row.checks["has_electrical_rating"] = kw is not None or cls == "fire_pump"
            row.checks["has_count"] = r["count"] is not None
        row.flags.append(f"llm:{MODEL}:{PROMPT_VERSION}")
        if count_from_ids:
            row.flags.append("count_from_ref_ids")
            row.checks.pop("ref_ids_match_count", None)
        out.append(row)
    owner: dict[str, int] = {}
    for i, r in enumerate(out):         # same unit ID in two rows -> both held
        for x in r.ref_ids:
            if x in owner and owner[x] != i:
                r.checks["ref_ids_unique"] = False
                out[owner[x]].checks["ref_ids_unique"] = False
            owner.setdefault(x, i)
    return out


def llm_extract(pages: list[tuple[int, str]], sha: str | None = None) -> list[UnitRow]:
    text = region_text(pages)
    if not text.strip():
        return []
    return to_unit_rows(ask(text, sha), text)


# ------------------------------------------------------------------ hybrid

_STATUS_RANK = {"ok": 0, "unchecked_rows": 1, "no_reference": 1, "incomplete": 2}


def _score(rows: list[UnitRow], pages) -> tuple:
    """Lower is better: site status, then rows held, then fewer generator units found."""
    x = cross_check(rows, pages)
    return (_STATUS_RANK[x["status"]], sum(r.held for r in rows),
            -sum(r.count or 0 for r in rows if not r.held))


def hybrid(pages: list[tuple[int, str]], ocr_pages=frozenset(), sha: str | None = None
           ) -> tuple[list[UnitRow], str]:
    """Rules first; the LLM only when the rules' answer is not clean, and its answer is
    used only if it scores better on the permit's own checks. Returns (rows, source)."""
    rules = extract(pages, ocr_pages)
    rs = _score(rules, pages)
    if rs[0] == 0 and rs[1] == 0:
        return rules, "rules"
    llm = llm_extract(pages, sha)
    if llm and _score(llm, pages) < rs:
        return llm, "llm"
    return rules, "rules"
