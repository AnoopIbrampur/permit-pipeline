"""Page text for permit PDFs: embedded text layer if usable, else Tesseract OCR.

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
            else:
                if text.strip():
                    (out_dir / f"page-{i:03d}.layer.txt").write_text(text)
                png = Path(tmp) / f"p{i}.png"
                page.get_pixmap(dpi=DPI, colorspace=pymupdf.csGRAY).save(png)
                text, conf = _tesseract(png)
                method = "ocr"
            (out_dir / f"page-{i:03d}.txt").write_text(text)
            meta.append({"page": i, "method": method, "scanned": scanned,
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
