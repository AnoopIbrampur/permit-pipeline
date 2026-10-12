"""Score the extractor against hand labels (eval/gold.csv).

Gold rows were typed from rendered page images, not from the text the
extractor reads, so OCR errors are not baked into the answer key. Gold IDs are
parsed here with a deliberately simple parser that shares no code with the
extractor.

Rows are matched within a permit by overlap of unit IDs (Jaccard >= 0.5,
greedy). Then:
  row recall      gold rows that were found
  row precision   extracted rows that correspond to a gold row
  field accuracy  per matched row: count, class, manufacturer, model, kW, section, IDs
  unit totals     generator units and MW, extracted vs gold
  check value     are rows that passed the checks more accurate than held ones?
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from .extract import extract
from .ocr import OCR_DIR

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
FIELDS = ["count", "equipment_class", "manufacturer", "model", "unit_kw", "section", "ref_ids"]


def canon_id(x: str) -> str:
    """'EG-16' == 'EG16', 'GEN001' == 'GEN1', 'ENG 155' == 'ENG155'."""
    x = re.sub(r"[\s-]", "", x.upper())
    return re.sub(r"(?<!\d)0+(?=\d)", "", x)     # leading zeros only: GEN010 -> GEN10, EG100 stays


def gold_ids(cell: str) -> set[str]:
    s = re.sub(r"\b(?:thru|through|to)\b", "~", cell)
    out = set()
    for piece in re.split(r",|\band\b", s):
        piece = piece.strip()
        if not piece:
            continue
        if "~" in piece or re.fullmatch(r"[A-Z/]*\d+\s*-\s*[A-Z/]*\d+", piece):
            a, b = re.split(r"\s*[~-]\s*", piece, maxsplit=1) if "~" not in piece else piece.split("~")
            ma, mb = re.fullmatch(r"(.*?)(\d+)", canon_id(a)), re.fullmatch(r"(.*?)(\d+)", canon_id(b))
            if ma and mb and ma.group(1) == mb.group(1):
                out |= {f"{ma.group(1)}{i}" for i in range(int(ma.group(2)), int(mb.group(2)) + 1)}
                continue
        out.add(canon_id(piece))
    return out


def _alnum(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def field_ok(name: str, gold: dict, pred) -> bool | None:
    """True/False, or None when the field is not scored for this row."""
    if name == "count":
        return pred.count == int(gold["count"])
    if name == "equipment_class":
        return pred.equipment_class == gold["equipment_class"]
    if name == "manufacturer":
        return None if not gold["manufacturer"] else (pred.manufacturer or "") == gold["manufacturer"]
    if name == "model":
        return None if not gold["model"] else bool(_alnum(gold["model"])) and _alnum(gold["model"]) in _alnum(pred.model)
    if name == "unit_kw":
        if not gold["unit_kw"]:
            return None
        g = float(gold["unit_kw"])
        return pred.unit_kw is not None and abs(pred.unit_kw - g) <= 0.01 * g
    if name == "section":
        return None if gold["section"] == "exempt" else pred.section == gold["section"]
    if name == "ref_ids":
        return {canon_id(x) for x in pred.ref_ids} == gold_ids(gold["ref_ids"])
    raise KeyError(name)


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def evaluate() -> dict:
    sample = {s["listing_key"]: s for s in json.loads((EVAL_DIR / "sample.json").read_text())}
    gold_by_permit = defaultdict(list)
    with open(EVAL_DIR / "gold.csv") as f:
        for g in csv.DictReader(f):
            gold_by_permit[g["listing_key"]].append(g)

    per_permit = []
    for key, golds in gold_by_permit.items():
        s = sample[key]
        ocr_dir = OCR_DIR / s["sha256"]
        pages = [(int(p.stem[5:8]), p.read_text())
                 for p in sorted(ocr_dir.glob("page-[0-9][0-9][0-9].txt"))]
        preds = extract(pages)
        g_ids = [gold_ids(g["ref_ids"]) for g in golds]
        p_ids = [{canon_id(x) for x in p.ref_ids} for p in preds]
        pairs = sorted(((_jaccard(g_ids[i], p_ids[j]), i, j)
                        for i in range(len(golds)) for j in range(len(preds))), reverse=True)
        used_g, used_p, matches = set(), set(), []
        for score, i, j in pairs:
            if score < 0.5 or i in used_g or j in used_p:
                continue
            used_g.add(i), used_p.add(j)
            matches.append((golds[i], preds[j]))
        rows = []
        for g, p in matches:
            fields = {f: field_ok(f, g, p) for f in FIELDS}
            rows.append({"gold": g, "pred": p, "fields": fields, "held": p.held,
                         "all_ok": all(v is not False for v in fields.values())})
        gens = lambda xs, cnt, kw: [(cnt(x) or 0, kw(x)) for x in xs]
        gold_gen = [g for g in golds if g["equipment_class"] == "genset"]
        pred_gen = [p for p in preds if p.equipment_class == "genset"]
        per_permit.append({
            "listing_key": key, "site_name": s["site_name"], "kind": s["kind"],
            "tuned": s.get("tuned", False),
            "gold_rows": len(golds), "pred_rows": len(preds), "matched": rows,
            "missed": [golds[i] for i in range(len(golds)) if i not in used_g],
            "spurious": [preds[j] for j in range(len(preds)) if j not in used_p],
            "gold_units": sum(int(g["count"]) for g in gold_gen),
            "gold_mw": sum(int(g["count"]) * float(g["unit_kw"] or 0) for g in gold_gen) / 1000,
            "pred_units": sum(p.count or 0 for p in pred_gen),
            "pred_units_ok": sum(p.count or 0 for p in pred_gen if not p.held),
            "pred_mw": sum((p.count or 0) * (p.unit_kw or 0) for p in pred_gen) / 1000,
        })
    return {"permits": per_permit}


def summarize(permits: list[dict]) -> dict:
    matched = [r for p in permits for r in p["matched"]]
    gold_rows = sum(p["gold_rows"] for p in permits)
    pred_rows = sum(p["pred_rows"] for p in permits)
    field_acc = {}
    for f in FIELDS:
        vals = [r["fields"][f] for r in matched if r["fields"][f] is not None]
        field_acc[f] = (sum(vals), len(vals))
    ok = [r for r in matched if not r["held"]]
    held = [r for r in matched if r["held"]]
    return {
        "permits": len(permits),
        "row_recall": (len(matched), gold_rows),
        "row_precision": (len(matched), pred_rows),
        "field_accuracy": field_acc,
        "rows_fully_correct": (sum(r["all_ok"] for r in matched), len(matched)),
        "passed_checks_fully_correct": (sum(r["all_ok"] for r in ok), len(ok)),
        "held_fully_correct": (sum(r["all_ok"] for r in held), len(held)),
        "gold_units": sum(p["gold_units"] for p in permits),
        "pred_units": sum(p["pred_units"] for p in permits),
        "pred_units_passed_checks": sum(p["pred_units_ok"] for p in permits),
        "gold_mw": round(sum(p["gold_mw"] for p in permits), 1),
        "pred_mw": round(sum(p["pred_mw"] for p in permits), 1),
    }
