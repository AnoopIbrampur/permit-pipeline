import pymupdf

from permitpipe.ocr import is_scanned


def _page_with_image(doc, frac):
    page = doc.new_page(width=612, height=792)
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 10, 10), False)
    pix.clear_with(255)
    page.insert_image(pymupdf.Rect(0, 0, 612 * frac, 792 * frac), pixmap=pix, keep_proportion=False)
    return page


def test_full_page_image_is_scan():
    with pymupdf.open() as doc:
        assert is_scanned(_page_with_image(doc, 1.0))


def test_logo_or_text_page_is_not_scan():
    with pymupdf.open() as doc:
        assert not is_scanned(_page_with_image(doc, 0.2))   # letterhead logo
        page = doc.new_page()
        page.insert_text((72, 72), "Equipment List")
        assert not is_scanned(page)
