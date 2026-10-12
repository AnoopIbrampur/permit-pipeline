"""Page text for permit PDFs: embedded text layer if usable, else Tesseract OCR.

Digital pages with ruled tables are rebuilt row by row from PyMuPDF's table detection:
a PDF text layer often lists a multi-row table column by column (all IDs, then all
descriptions, ...), which no line-based parser can pair back up. Columns that never hold
equipment data (location, controls, federal requirements, dates) are dropped by header.

A page that is a scanned image gets Tesseract even when the copier embedded
its own text layer: copier OCR splits table rows apart, Tesseract (--psm 4)
keeps each equipment row on one line. The copier text is kept alongside as a
second reading.

Output is cached per document hash under data/ocr/<sha>/:
  page-001.txt         text used downstream for page 1
  page-001.layer.txt   embedded text layer, when the page was OCR'd anyway
  meta.json            per-page method ('text' | 'ocr'), scan flag, mean word confidence

Pages keep their 1-based number so every extracted value can cite its page.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

import pymupdf

from .store import DATA_DIR

OCR_DIR = DATA_DIR / "ocr"
DPI = 300
MIN_TEXT_CHARS = 200   # below this, treat the text layer as missing (scan with a stray stamp)
SCAN_COVERAGE = 0.6    # an image covering this share of the page means the page is a scan


def is_scanned(page: "pymupdf.Page") -> bool:
    area = page.rect.width * page.rect.height
    for img in page.get_image_info():
        x0, y0, x1, y1 = img["bbox"]
        if (x1 - x0) * (y1 - y0) >= SCAN_COVERAGE * area:
            return True
    return False


LAYOUT_VERSION = 4          # bump when text-page layout changes; text pages are rebuilt
ROW_MARK = "<<row>>"        # starts each table row in rebuilt text; the extractor splits on it
_DROP_COL_RE = re.compile(r"location|building|control|federal|requirement|date|citation|exemption", re.I)
_HEADER_CELL_RE = re.compile(
    r"^(?:ref(?:erence)?\.?|nos?\.?(?:\(s\))?|equipment|description|rated|maximum|capacity|\(each\)|"
    r"add-on|control|controls|technology|referenced|delegated|federal|requirements?|original|permit|"
    r"date|location|building|exemption|citation|\s)+$", re.I)


def _is_header_row(cells: list[str]) -> bool:
    filled = [c for c in cells if c and c.strip()]
    return bool(filled) and all(_HEADER_CELL_RE.match(c.replace("\n", " ").strip()) for c in filled)


def _table_lines(table) -> list[tuple[float, str]]:
    rows = table.extract()
    header_n = 0
    while header_n < len(rows) and _is_header_row(rows[header_n]):
        header_n += 1
    ncol = max(len(r) for r in rows) if rows else 0
    headers = [" ".join((rows[i][c] or "") for i in range(header_n) if c < len(rows[i])) for c in range(ncol)]
    keep = [c for c in range(ncol) if not (headers[c].strip() and _DROP_COL_RE.search(headers[c]))]
    out = []
    for i in range(header_n, len(rows)):
        cells = [(rows[i][c] or "").strip() for c in keep if c < len(rows[i])]
        text = "\n".join(c for c in cells if c)
        if text:
            out.append((table.rows[i].bbox[1], f"{ROW_MARK}\n{text}"))
    return out


def page_text_with_tables(page) -> str:
    try:
        tables = page.find_tables().tables
    except Exception:          # table detection is best effort; fall back to the text layer
        tables = []
    if not tables:
        return page.get_text("text")
    boxes = [pymupdf.Rect(t.bbox) + (-3, -3, 3, 3) for t in tables]
    cell_words = [set(" ".join(c or "" for row in t.extract() for c in row).split()) for t in tables]
    items = []
    for x0, y0, x1, y1, text, *_ in page.get_text("blocks", sort=True):
        block = pymupdf.Rect(x0, y0, x1, y1)
        area = max(block.get_area(), 1e-6)
        # drop a block only if it sits in a table AND its words are that table's cell text;
        # a heading between two tables that detection merged must survive
        inside = any((block & b).get_area() >= 0.5 * area and set(text.split()) <= words
                     for b, words in zip(boxes, cell_words))
        if not inside:
            items.append((y0, text.rstrip("\n")))
    for t in tables:
        items += _table_lines(t)
    return "\n".join(text for _, text in sorted(items, key=lambda it: it[0]))


def _tesseract(png: Path) -> tuple[str, float | None]:
    # --psm 4: a single column of variable-size text; keeps table rows on one line
    tsv = subprocess.run(
        ["tesseract", str(png), "stdout", "--psm", "4", "tsv"],
        capture_output=True, text=True, check=True,
    ).stdout
    lines: dict[tuple, list[str]] = {}
    confs = []
    for row in tsv.splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip():
            continue
        lines.setdefault((int(f[2]), int(f[3]), int(f[4])), []).append(f[11])
        if float(f[10]) >= 0:
            confs.append(float(f[10]))
    text = "\n".join(" ".join(w) for _, w in sorted(lines.items()))
    return text, (round(sum(confs) / len(confs), 1) if confs else None)


def page_texts(pdf_path: Path, sha: str, force: bool = False) -> list[dict]:
    out_dir = OCR_DIR / sha
    meta_path = out_dir / "meta.json"
    if meta_path.exists() and not force:
        meta = json.loads(meta_path.read_text())
        stale = [m for m in meta if m["method"] == "text" and m.get("layout", 1) < LAYOUT_VERSION]
        if stale:      # rebuild digital pages only; OCR'd pages are expensive and unaffected
            with pymupdf.open(pdf_path) as doc:
                for m in stale:
                    text = page_text_with_tables(doc[m["page"] - 1])
                    (out_dir / f"page-{m['page']:03d}.txt").write_text(text)
                    m.update(layout=LAYOUT_VERSION, chars=len(text))
            meta_path.write_text(json.dumps(meta, indent=1))
        for m in meta:
            m["text"] = (out_dir / f"page-{m['page']:03d}.txt").read_text()
        return meta

    out_dir.mkdir(parents=True, exist_ok=True)
    meta = []
    with pymupdf.open(pdf_path) as doc, tempfile.TemporaryDirectory() as tmp:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text")
            scanned = is_scanned(page)
            if len(text.strip()) >= MIN_TEXT_CHARS and not scanned:
                method, conf = "text", None
                text = page_text_with_tables(page)
            else:
                if text.strip():
                    (out_dir / f"page-{i:03d}.layer.txt").write_text(text)
                png = Path(tmp) / f"p{i}.png"
                page.get_pixmap(dpi=DPI, colorspace=pymupdf.csGRAY).save(png)
                text, conf = _tesseract(png)
                method = "ocr"
            (out_dir / f"page-{i:03d}.txt").write_text(text)
            meta.append({"page": i, "method": method, "scanned": scanned, "layout": LAYOUT_VERSION,
                         "mean_conf": conf, "chars": len(text)})
    meta_path.write_text(json.dumps(meta, indent=1))
    for m in meta:
        m["text"] = (out_dir / f"page-{m['page']:03d}.txt").read_text()
    return meta


def ocr_page_numbers(sha: str) -> frozenset[int]:
    """Pages of a document whose text came from Tesseract rather than the PDF."""
    meta_path = OCR_DIR / sha / "meta.json"
    if not meta_path.exists():
        return frozenset()
    return frozenset(m["page"] for m in json.loads(meta_path.read_text()) if m["method"] == "ocr")
