"""Nothing on a label or in a report PDF is ever cut off: text that is too
long wraps (and on labels shrinks further) instead of ending in an
ellipsis. Every name and quantity here is invented."""

import base64
import re
import zlib

import pytest
from reportlab.graphics.shapes import Drawing, String
from reportlab.pdfbase.pdfmetrics import stringWidth

import render_labels
from manifest import write_checklist_pdf, write_lot_counts_pdf, write_parts_pdf
from ordering import summarize_parts
from records import LabelRecord
from render_labels import LabelOptions, _fit_text, _wrap_lines, draw_label

LONG_DESC = ("BRICK 1X2 W/ BOW 1/2 AND CROSS AXLE HOLE, TRANSPARENT FLUORESCENT REDDISH ORANGE, "
             "WITH PRINTED STRIPES ON BOTH SIDES 012")
NEON = ("Transparent Fluorescent Reddish Orange", "Trans-Neon Orange")
GREY = ("Medium Stone Grey", "Light Bluish Gray")
LONG_NAME = "Maximilian Bartholomew Quillfeather-Montgomery-Ashworth of Brickshire"


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def test_long_description_is_120_characters():
    assert len(LONG_DESC) == 120


def test_wrap_lines_words_then_characters():
    width = len
    lines = _wrap_lines(LONG_DESC, 30, width)
    assert len(lines) >= 4 and all(len(line) <= 30 for line in lines)
    assert squash("".join(lines)) == squash(LONG_DESC)
    word = "W" * 70
    split = _wrap_lines(f"Ann {word} end", 20, width)
    assert all(len(line) <= 20 for line in split)
    assert squash("".join(split)) == f"Ann{word}end"
    assert _wrap_lines("", 10, width) == [""]
    assert _wrap_lines("PLATE 1X2", 10, width) == ["PLATE 1X2"]


def test_fit_text_unchanged_when_it_fits():
    lines, size, _ = _fit_text("BRICK 1X1", "Helvetica", 10, 7, 200, 12)
    assert lines == ["BRICK 1X1"] and size == 10
    # Fits once shrunk: one line at the first size that fits, as before.
    text = "PLATE 2X4"
    wide = stringWidth(text, "Helvetica", 8)
    lines, size, _ = _fit_text(text, "Helvetica", 10, 7, wide + 0.01, 12)
    assert lines == [text] and size == 8


@pytest.mark.parametrize("text", [
    f"LEGO: {NEON[0]}", f"BL: {NEON[1]}", " / ".join(GREY), " / ".join(NEON), LONG_DESC,
    "BL: " + "Z" * 90, LONG_NAME])
@pytest.mark.parametrize("height", [9.0, 30.0])
def test_fit_text_wraps_and_keeps_everything(text, height):
    lines, size, leading = _fit_text(text, "Helvetica", 8, 5.6, 60, height)
    assert squash("".join(lines)) == squash(text)
    assert all(stringWidth(line, "Helvetica", size) <= 60 + 1e-9 for line in lines)
    assert size * 0.94 + (len(lines) - 1) * leading <= height + 1e-9
    assert not any(line.endswith("…") for line in lines)


def _strings(drawing) -> list[String]:
    out = []
    for item in drawing.contents:
        if isinstance(item, String):
            out.append(item)
        elif hasattr(item, "contents"):
            out += _strings(item)
    return out


@pytest.fixture
def no_photos(monkeypatch):
    monkeypatch.setattr(render_labels, "_cached_image_path", lambda *_: None)


@pytest.mark.parametrize("size", [(189, 72), (288, 96), (252, 81)])
@pytest.mark.parametrize("hide", ["", "photo", "photo,name,count"])
def test_labels_show_all_text(no_photos, size, hide):
    width, height = size
    record = LabelRecord(LONG_NAME, "6284070", LONG_DESC, *NEON, "250", "", None, 3, 12)
    drawing = Drawing(width, height)
    draw_label(drawing, width, height, record, LabelOptions.parse(hide))
    strings = _strings(drawing)
    text = squash("".join(s.text for s in strings))
    for want in (f"LEGO:{NEON[0]}", f"BL:{NEON[1]}", LONG_DESC, "6284070", "Qty:250"):
        assert squash(want) in text
    if "name" not in hide:
        assert squash(LONG_NAME) in text
    for s in strings:
        assert not s.text.endswith("…")
        w = stringWidth(s.text, s.fontName, s.fontSize)
        assert s.x >= -1e-6 and s.x + w <= width + 1e-6, s.text
        assert s.y >= 0, s.text


def test_short_label_text_is_drawn_as_before(no_photos):
    """Text that already fits: one String per field, at the layout's line."""
    record = LabelRecord("Ann Example", "3001", "BRICK 2X4", *GREY, "10", "")
    drawing = Drawing(288, 96)
    draw_label(drawing, 288, 96, record, LabelOptions())
    texts = [s.text for s in _strings(drawing)]
    assert texts.count("BRICK 2X4") == 1 and "LEGO: Medium Stone Grey" in texts


def _pdf_text(path) -> str:
    """Everything a reportlab PDF draws with Tj, in order."""
    data = open(path, "rb").read()
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        raw = m.group(1).strip()
        if raw.endswith(b"~>"):  # reportlab's default: ASCII85, then Flate
            raw = base64.a85decode(raw[:-2])
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        for s in re.findall(rb"\(((?:[^()\\]|\\.)*)\)\s*Tj", raw):
            out.append(re.sub(rb"\\(.)", rb"\1", s).decode("latin-1"))
    return "".join(out)


def test_report_pdfs_show_all_text(tmp_path):
    records = [
        LabelRecord(LONG_NAME, "6284070", LONG_DESC, *NEON, "3", ""),
        LabelRecord("Ann Example", "6225242", "BRICK 1X2X5", *GREY, "5", "", 12.5),
        LabelRecord("Ann Example", "300126", "TILE " + "X" * 90, "Black", "Black", "7", ""),
    ]
    checklist, parts, lots = (tmp_path / n for n in ("c.pdf", "p.pdf", "l.pdf"))
    write_checklist_pdf(records, str(checklist))
    write_parts_pdf(summarize_parts(records, "sheet"), str(parts))
    write_lot_counts_pdf(records, str(lots))
    for path in (checklist, parts):
        text = squash(_pdf_text(path))
        for want in (LONG_DESC, " / ".join(NEON), " / ".join(GREY), "TILE " + "X" * 90):
            assert squash(want) in text, (path.name, want)
    assert squash(LONG_NAME) in squash(_pdf_text(lots))
