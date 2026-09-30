"""The report PDFs/CSVs with options: defaults reproduce the old output,
each option does what the web app's reports.js does, nothing is cut off.
All names and numbers are invented."""

import csv
import json
import sys
from pathlib import Path

import pytest
from PIL import Image as PILImage

import main
import render_labels
import report_options as ro
from helpers import LONG_DESC, pages, pdf_layout, pdf_text, sample_labels, squash
from manifest import (
    ReportContext, ordered_parts, write_checklist_pdf, write_lot_counts_csv,
    write_lot_counts_pdf, write_parts_csv, write_parts_pdf,
)
from ordering import summarize_parts
from records import LabelRecord

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "report_defaults_layout.json").read_text())
LONG_NAME = "Maximilian Bartholomew Quillfeather-Montgomery-Ashworth of Brickshire"


def sec(name, **kw):
    return {**ro.default_options()[name], **kw}


@pytest.fixture
def recs():
    return sample_labels()


@pytest.fixture
def parts(recs):
    return summarize_parts(recs, {}, "sheet")


def make(kind, recs, path, opts=None, ctx=None):
    path = str(path)
    if kind == "checklist":
        write_checklist_pdf(recs, path, opts=opts, context=ctx)
    elif kind == "parts":
        write_parts_pdf(summarize_parts(recs, {}, "sheet"), path, opts, ctx)
    else:
        write_lot_counts_pdf(recs, path, opts=opts, context=ctx)
    return path


# ---- defaults are today's reports ----------------------------------------------------

@pytest.mark.parametrize("kind", ["checklist", "parts", "lots"])
def test_default_layout_is_unchanged(recs, tmp_path, kind):
    """Layout lines captured from the code before the report options existed."""
    assert pdf_layout(make(kind, recs, tmp_path / "x.pdf")) == GOLDEN[kind]
    # ...and the full default options are the same as passing none.
    full = ro.default_options()[kind]
    assert pdf_layout(make(kind, recs, tmp_path / "y.pdf", full)) == GOLDEN[kind]


def test_default_text(recs, tmp_path):
    text = pdf_text(make("parts", recs, tmp_path / "p.pdf"))
    assert text.startswith("Parts list5 parts, 369 pieces, 7 labels")
    assert "in label order" in text and "grouped" not in text
    assert "LEGO / BrickLink color" in text and "Total weight" not in text
    text = pdf_text(make("checklist", recs, tmp_path / "c.pdf"))
    assert "Ann Example3 lots, 229 pieces" in text and "Packed" not in text
    text = pdf_text(make("lots", recs, tmp_path / "l.pdf"))
    assert text.startswith("Lot counts by person3 people, 7 lots total")
    assert "sorted by last name" in text and "Total" not in text.replace("Total pieces", "")


def test_csv_defaults_are_unchanged(recs, parts, tmp_path):
    write_lot_counts_csv(recs, str(tmp_path / "l.csv"))
    assert (tmp_path / "l.csv").read_text().splitlines() == [
        "person,lot_count,total_pieces", "Ann Example,3,229", "Bob Sample,2,85", "Cy Tester,2,55"]
    write_parts_csv(parts, str(tmp_path / "p.csv"))
    rows = list(csv.reader((tmp_path / "p.csv").open()))
    assert rows[0] == ["order", "element_id", "description", "lego_color", "bl_color",
                       "total_pieces", "people", "grams_per_piece", "weight_source"]
    assert [r[1] for r in rows[1:]] == [p.element_id for p in parts]


# ---- options on every report ----------------------------------------------------------

@pytest.mark.parametrize("kind", ["checklist", "parts", "lots"])
@pytest.mark.parametrize("paper,orientation,size", [
    ("letter", "portrait", (612, 792)), ("letter", "landscape", (792, 612)),
    ("a4", "portrait", (595.28, 841.89)), ("a4", "landscape", (841.89, 595.28))])
def test_paper_and_orientation(recs, tmp_path, kind, paper, orientation, size):
    path = make(kind, recs, tmp_path / "x.pdf", sec(kind, paper=paper, orientation=orientation))
    got = pages(path)
    assert got and all(abs(w - size[0]) < 0.01 and abs(h - size[1]) < 0.01 for w, h in got)


@pytest.mark.parametrize("kind", ["checklist", "parts", "lots"])
def test_title_and_subtitle(recs, tmp_path, kind):
    o = sec(kind, title="Spring swap", subtitle="Table 4, hall B")
    text = pdf_text(make(kind, recs, tmp_path / "x.pdf", o))
    assert "Spring swap" in text and "Table 4, hall B" in text
    if kind != "checklist":  # the title replaces the heading
        assert {"parts": "Parts list", "lots": "Lot counts by person"}[kind] not in text
    data = open(tmp_path / "x.pdf", "rb").read()
    assert b"/Title (Spring swap)" in data


def test_checklist_title_runs_on_every_page(recs, tmp_path):
    path = make("checklist", recs, tmp_path / "c.pdf", sec("checklist", title="Spring swap"))
    assert len(pages(path)) == 3
    assert pdf_text(path).count("Spring swap") == 3


def test_checklist_without_title_has_no_running_header(recs, tmp_path):
    assert "Spring" not in pdf_text(make("checklist", recs, tmp_path / "c.pdf"))


# ---- checklist ---------------------------------------------------------------------------

def test_checklist_layout_continuous(recs, tmp_path):
    per_person = make("checklist", recs, tmp_path / "a.pdf")
    continuous = make("checklist", recs, tmp_path / "b.pdf", sec("checklist", layout="continuous"))
    assert len(pages(per_person)) == 3 and len(pages(continuous)) == 1
    text = pdf_text(continuous)
    assert text.index("Ann Example") < text.index("Bob Sample") < text.index("Cy Tester")


def test_checklist_continuous_flows_onto_more_pages(tmp_path):
    many = []
    for i in range(12):
        many += [LabelRecord(f"Person {chr(65 + i)}", f"60000{j:02d}", f"PART {j}", "Black",
                             "Black", "5", "", None, 1, 1) for j in range(6)]
    path = make("checklist", many, tmp_path / "c.pdf", sec("checklist", layout="continuous"))
    assert 1 < len(pages(path)) < 12
    text = pdf_text(path)
    assert all(f"Person {chr(65 + i)}" in text for i in range(12))


def count_boxes(path):
    return sum(ln.count(" re S") for ln in pdf_layout(path))


def test_checklist_checkbox_toggle(recs, tmp_path):
    with_box = make("checklist", recs, tmp_path / "a.pdf")
    without = make("checklist", recs, tmp_path / "b.pdf", sec("checklist", checkbox=False))
    assert count_boxes(with_box) == 7 and count_boxes(without) == 0


def test_checklist_color_toggle(recs, tmp_path):
    shown = pdf_text(make("checklist", recs, tmp_path / "a.pdf"))
    hidden = pdf_text(make("checklist", recs, tmp_path / "b.pdf", sec("checklist", color=False)))
    assert "LEGO / BrickLink color" in shown and "Bright Green / Green" in shown
    assert "color" not in hidden and "Bright Green" not in hidden
    assert "Element" in hidden and "Qty" in hidden


def test_checklist_weight_toggle(recs, tmp_path):
    text = pdf_text(make("checklist", recs, tmp_path / "a.pdf", sec("checklist", weight=True)))
    assert "Weight" in text and "g/pc" in text and "~" in text  # estimated from the description
    assert "2.5 g/pc" in text  # the sheet's own weight
    assert "g/pc" not in pdf_text(make("checklist", recs, tmp_path / "b.pdf"))


def test_checklist_packed_by_line(recs, tmp_path):
    text = pdf_text(make("checklist", recs, tmp_path / "a.pdf", sec("checklist", packed_by=True)))
    assert text.count("Packed by:") == 3 and text.count("Date:") == 3
    assert "Packed by" not in pdf_text(make("checklist", recs, tmp_path / "b.pdf"))


@pytest.fixture
def photos(monkeypatch, tmp_path):
    jpg = tmp_path / "photo.jpg"
    PILImage.new("RGB", (40, 30), (200, 30, 30)).save(jpg)
    monkeypatch.setattr(render_labels, "_cached_image_path", lambda *_: str(jpg))


def image_count(path):
    return open(path, "rb").read().count(b"/Subtype /Image")


def test_checklist_photo_toggle(recs, tmp_path, photos):
    plain = make("checklist", recs, tmp_path / "a.pdf")
    shown = make("checklist", recs, tmp_path / "b.pdf", sec("checklist", photo=True))
    assert image_count(plain) == 0 and image_count(shown) >= 1
    assert "Photo" in pdf_text(shown) and "Photo" not in pdf_text(plain)


def test_checklist_photo_missing_leaves_the_cell_empty(recs, tmp_path, monkeypatch):
    monkeypatch.setattr(render_labels, "_cached_image_path", lambda *_: None)
    path = make("checklist", recs, tmp_path / "a.pdf", sec("checklist", photo=True))
    assert image_count(path) == 0 and "Photo" in pdf_text(path)


def element_order(text, recs):
    ids = list(dict.fromkeys(r.element_id for r in recs))
    return sorted((i for i in ids if i in text), key=text.index)


def test_checklist_part_order(tmp_path):
    # One person; sheet order 1 (small), 2 (big), 3 (medium). Label order is
    # invented to be 3, 1, 2 — "labels" must follow it, not the sheet.
    def rec(eid, desc):
        return LabelRecord("Ann Example", eid, desc, "Black", "Black", "5", "", None, 1, 1)
    sheet = [rec("6100001", "PLATE 1X2"), rec("6100002", "PLATE 8X8"), rec("6100003", "PLATE 4X4")]
    labels = [sheet[2], sheet[0], sheet[1]]
    ctx = ReportContext(sheet, {}, {})
    want = {"labels": ["6100003", "6100001", "6100002"],
            "sheet": ["6100001", "6100002", "6100003"],
            "heaviest": ["6100002", "6100003", "6100001"],
            "lightest": ["6100001", "6100003", "6100002"]}
    for order, ids in want.items():
        path = make("checklist", labels, tmp_path / f"{order}.pdf", sec("checklist", order=order), ctx)
        text = pdf_text(path)
        assert sorted(ids, key=text.index) == ids, order


def test_checklist_reordering_keeps_label_numbers(recs, tmp_path):
    ctx = ReportContext(recs, {}, {})
    text = pdf_text(make("checklist", recs, tmp_path / "a.pdf", sec("checklist", order="lightest"), ctx))
    assert "1 of 2" in text and "2 of 2" in text and "1 of 1" in text


def test_checklist_sort_first_name(tmp_path):
    rs = [LabelRecord("Zoe Adams", "6100001", "PLATE", "Black", "Black", "1", "", None, 1, 1),
          LabelRecord("Adam Zed", "6100001", "PLATE", "Black", "Black", "2", "", None, 1, 1)]
    last = pdf_text(make("checklist", rs, tmp_path / "a.pdf"))
    first = pdf_text(make("checklist", rs, tmp_path / "b.pdf", sec("checklist", sort="first")))
    assert last.index("Zoe Adams") < last.index("Adam Zed")
    assert first.index("Adam Zed") < first.index("Zoe Adams")


# ---- parts list --------------------------------------------------------------------------

@pytest.fixture
def ctx(recs):
    return ReportContext(recs, {}, {})


def test_parts_orders(recs, parts, ctx):
    # `parts` here is the label order; make it differ from the sheet's.
    labels = list(reversed(parts))
    assert [p.element_id for p in ordered_parts(labels, "labels", ctx)] == [
        p.element_id for p in labels]
    sheet = [p.element_id for p in ordered_parts(labels, "sheet", ctx)]
    assert sheet == list(dict.fromkeys(r.element_id for r in recs))
    heavy = ordered_parts(labels, "heaviest", ctx)
    light = ordered_parts(labels, "lightest", ctx)
    known = [p for p in heavy if p.weight is not None]
    assert [p.weight for p in known] == sorted((p.weight for p in known), reverse=True)
    assert [p.weight for p in light if p.weight is not None] == sorted(
        p.weight for p in known)
    assert heavy[0].element_id == "6097276"  # the 32x32 base plate
    assert sorted(p.element_id for p in heavy) == sorted(sheet)
    element = [p.element_id for p in ordered_parts(labels, "element", ctx)]
    assert element == sorted(element, key=lambda e: (len(e), e))


def test_parts_order_in_pdf_and_csv(recs, parts, ctx, tmp_path):
    labels = list(reversed(parts))
    for order in ("labels", "heaviest", "lightest", "sheet", "element"):
        want = [p.element_id for p in ordered_parts(labels, order, ctx)]
        pdf = tmp_path / f"{order}.pdf"
        write_parts_pdf(labels, str(pdf), sec("parts", order=order), ctx)
        text = pdf_text(pdf)
        assert sorted(want, key=text.index) == want, order
        write_parts_csv(labels, str(tmp_path / f"{order}.csv"), sec("parts", order=order), ctx)
        rows = list(csv.reader((tmp_path / f"{order}.csv").open()))[1:]
        assert [r[1] for r in rows] == want and [r[0] for r in rows] == [
            str(i) for i in range(1, len(want) + 1)]
    words = {"labels": "in label order", "heaviest": "heaviest first",
             "lightest": "lightest first", "sheet": "in sheet order", "element": "by element ID"}
    for order, phrase in words.items():
        assert phrase in pdf_text(tmp_path / f"{order}.pdf")


def test_parts_columns(recs, parts, tmp_path):
    def text(**kw):
        path = tmp_path / "x.pdf"
        write_parts_pdf(parts, str(path), sec("parts", **kw))
        return pdf_text(path)
    default = text()
    assert all(h in default for h in ("Element", "LEGO / BrickLink color", "Pieces", "People",
                                      "Weight"))
    assert "Photo" not in default and "Total weight" not in default
    only_lego = text(bl_color=False)
    assert "LEGO color" in only_lego and "BrickLink" not in only_lego and "Green" in only_lego
    assert "Light Bluish Gray" not in only_lego
    only_bl = text(lego_color=False)
    assert "BrickLink color" in only_bl and "Light Bluish Gray" in only_bl
    assert "Medium Stone Grey" not in only_bl
    no_colors = text(lego_color=False, bl_color=False)
    assert "color" not in no_colors and "Black" not in no_colors
    assert "Pieces" not in text(pieces=False) and "People" not in text(people=False)
    no_weight = text(weight=False)
    assert "Weight" not in no_weight and "g/pc" not in no_weight
    total = text(total_weight=True)
    assert "Total weight" in total
    assert "g/pc" in total and ("2.4 kg" in total or " g" in total)


def test_parts_total_weight_values(tmp_path):
    rs = [LabelRecord("Ann Example", "6100001", "PLATE", "Black", "Black", "100", "", 12.0, 1, 1),
          LabelRecord("Ann Example", "6100002", "BRICK", "Black", "Black", "200", "", 10.0, 1, 1),
          LabelRecord("Ann Example", "6100003", "FROG", "Black", "Black", "3", "", None, 1, 1),
          LabelRecord("Ann Example", "6100004", "BRICK 2X2", "Black", "Black", "10", "", None, 1, 1)]
    path = tmp_path / "p.pdf"
    write_parts_pdf(summarize_parts(rs, {}, "sheet"), str(path), sec("parts", total_weight=True))
    text = pdf_text(path)
    assert "1.20 kg" in text and "2.00 kg" in text  # 100 x 12 g, 200 x 10 g
    assert "size unknown" in text and "?" in text
    assert "~" in text  # the 2x2 brick is estimated


def test_parts_group_by_color(tmp_path):
    def rec(eid, color, desc="PLATE"):
        return LabelRecord("Ann Example", eid, desc, color, color, "5", "", None, 1, 1)
    rs = [rec("6100001", "Red"), rec("6100002", "Black"), rec("6100003", "Red"),
          rec("6100004", ""), rec("6100005", "Black")]
    parts = summarize_parts(rs, {}, "sheet")
    plain = tmp_path / "a.pdf"
    grouped = tmp_path / "b.pdf"
    write_parts_pdf(parts, str(plain), sec("parts", lego_color=True, bl_color=False))
    write_parts_pdf(parts, str(grouped), sec("parts", lego_color=True, bl_color=False,
                                             group_by_color=True))
    text = pdf_text(grouped)
    assert "grouped by color" in text and "grouped" not in pdf_text(plain)
    for heading in ("Black (2 parts)", "Red (2 parts)", "No color (1 part)"):
        assert heading in text
    assert text.index("Black (2 parts)") < text.index("Red (2 parts)") < text.index("No color (1 part)")
    ids = ["6100002", "6100005", "6100001", "6100003", "6100004"]  # stable within a color
    assert sorted(ids, key=text.index) == ids


def test_parts_photo_column(recs, parts, tmp_path, photos):
    path = tmp_path / "p.pdf"
    write_parts_pdf(parts, str(path), sec("parts", photo=True))
    assert image_count(path) >= 1 and "Photo" in pdf_text(path)
    write_parts_pdf(parts, str(tmp_path / "q.pdf"))
    assert image_count(tmp_path / "q.pdf") == 0


# ---- lot counts --------------------------------------------------------------------------

def test_lots_columns(recs, tmp_path):
    def text(**kw):
        return pdf_text(make("lots", recs, tmp_path / "x.pdf", sec("lots", **kw)))
    default = text()
    assert "Lots" in default and "Total pieces" in default and "Total weight" not in default
    assert "Lots" not in text(lots=False).replace("7 lots total", "")
    assert "Total pieces" not in text(pieces=False)
    weights = text(total_weight=True)
    assert "Total weight" in weights and " kg" in weights
    bare = text(lots=False, pieces=False)
    assert "Ann Example" in bare and "Total pieces" not in bare


def test_lots_total_weight_marks(tmp_path):
    rs = [LabelRecord("Ann Example", "6100001", "PLATE", "Black", "Black", "100", "", 12.0, 1, 1),
          LabelRecord("Bob Sample", "6100001", "PLATE", "Black", "Black", "10", "", 12.0, 1, 1),
          LabelRecord("Bob Sample", "6100003", "FROG", "Black", "Black", "3", "", None, 1, 1),
          LabelRecord("Cy Tester", "6100003", "FROG", "Black", "Black", "3", "", None, 1, 1),
          LabelRecord("Dee Probe", "6100004", "BRICK 2X2", "Black", "Black", "10", "", None, 1, 1)]
    path = make("lots", rs, tmp_path / "l.pdf", sec("lots", total_weight=True))
    text = pdf_text(path)
    assert "1.20 kg" in text  # exact
    assert "120 g+" in text   # some weights unknown
    assert "?" in text        # nothing known
    assert "~" in text        # estimated


def test_lots_totals_row(recs, tmp_path):
    text = pdf_text(make("lots", recs, tmp_path / "x.pdf", sec("lots", totals=True)))
    assert "Total (3 people)" in text and text.endswith("Total (3 people)7369")
    text = pdf_text(make("lots", recs, tmp_path / "y.pdf",
                         sec("lots", totals=True, total_weight=True)))
    assert "Total (3 people)" in text
    assert "Total (" not in pdf_text(make("lots", recs, tmp_path / "z.pdf"))


def test_lots_min_lots(recs, tmp_path):
    o = sec("lots", min_lots=3, totals=True)
    text = pdf_text(make("lots", recs, tmp_path / "x.pdf", o))
    assert "Ann Example" in text and "Bob Sample" not in text and "Cy Tester" not in text
    assert "1 people, 3 lots total" in text
    assert "2 with fewer than 3 lots left out" in text
    assert "Total (1 people)" in text
    # 1 means everyone (every person has a lot): no note
    text = pdf_text(make("lots", recs, tmp_path / "y.pdf", sec("lots", min_lots=1)))
    assert "left out" not in text and "Cy Tester" in text
    write_lot_counts_csv(recs, str(tmp_path / "l.csv"), opts=o)
    assert (tmp_path / "l.csv").read_text().splitlines() == [
        "person,lot_count,total_pieces", "Ann Example,3,229"]
    # above anyone's count: an empty table, not a crash
    assert pdf_text(make("lots", recs, tmp_path / "e.pdf", sec("lots", min_lots=9999)))


def test_lots_sort(tmp_path):
    rs = [LabelRecord("Zoe Adams", "6100001", "PLATE", "Black", "Black", "1", "", None, 1, 1),
          LabelRecord("Adam Zed", "6100001", "PLATE", "Black", "Black", "2", "", None, 1, 1)]
    first = pdf_text(make("lots", rs, tmp_path / "a.pdf", sec("lots", sort="first")))
    assert first.index("Adam Zed") < first.index("Zoe Adams") and "sorted by first name" in first
    write_lot_counts_csv(rs, str(tmp_path / "l.csv"), opts=sec("lots", sort="first"))
    assert (tmp_path / "l.csv").read_text().splitlines()[1].startswith("Adam Zed")


# ---- nothing is ever cut off -------------------------------------------------------------

@pytest.mark.parametrize("paper", ["letter", "a4"])
@pytest.mark.parametrize("orientation", ["portrait", "landscape"])
def test_no_truncation_with_every_option(tmp_path, paper, orientation):
    big = "6" + "9" * 60
    rs = [LabelRecord(LONG_NAME, "6284070", LONG_DESC, "Transparent Fluorescent Reddish Orange",
                      "Trans-Neon Orange", "3", "", None, 1, 1),
          LabelRecord("Ann Example", big, "TILE " + "X" * 90, "Black", "Black", "7" * 30, "",
                      None, 2, 2)]
    title, sub = "T" * 50 + " " + "t" * 29, "S" * 70 + " " + "s" * 49
    page = dict(paper=paper, orientation=orientation, title=title, subtitle=sub)
    ctx = ReportContext(rs, {}, {})
    sets = {
        "checklist": sec("checklist", weight=True, photo=True, packed_by=True, **page),
        "parts": sec("parts", photo=True, total_weight=True, group_by_color=True, **page),
        "lots": sec("lots", total_weight=True, totals=True, **page),
    }
    wants = {
        "checklist": (LONG_NAME, LONG_DESC, big, "X" * 90, "7" * 30),
        "parts": (LONG_DESC, big, "X" * 90),
        "lots": (LONG_NAME,),
    }
    for kind, o in sets.items():
        text = squash(pdf_text(make(kind, rs, tmp_path / f"{kind}.pdf", o, ctx)))
        for want in (title, sub) + wants[kind]:
            assert squash(want) in text, (kind, want[:20])
        assert "…" not in text


def test_long_checklist_weight_and_color_columns_wrap(tmp_path):
    rs = [LabelRecord("Ann Example", "6284070", "P", "Transparent Fluorescent Reddish Orange",
                      "Trans-Neon Orange", "3", "", None, 1, 1)]
    text = squash(pdf_text(make("checklist", rs, tmp_path / "c.pdf",
                                sec("checklist", weight=True))))
    assert "sizeunknown" in text and "TransparentFluorescentReddishOrange/Trans-NeonOrange" in text


# ---- keep-parts and the label order ---------------------------------------------------------

@pytest.fixture
def no_network(monkeypatch):
    monkeypatch.setattr(render_labels, "_cached_image_path", lambda *_: None)


def test_same_as_labels_follows_keep_parts_optimize(monkeypatch, tmp_path, no_network):
    """Sheets of 30: sizes 20, 25, 10, 5 (heaviest first) pack as 20+10 and
    25+5, so the labels run 1, 3, 2, 4 — and so must "same as labels"."""
    import samples

    def rec(eid, n, desc):
        return [LabelRecord(f"P{i:02d} Test", eid, desc, "Black", "Black", "1", "") for i in range(n)]
    orders = (rec("6100001", 20, "PLATE 8X8") + rec("6100002", 25, "PLATE 6X6")
              + rec("6100003", 10, "PLATE 4X4") + rec("6100004", 5, "PLATE 2X2"))
    monkeypatch.setattr(samples, "sample_records", lambda: orders)
    monkeypatch.chdir(tmp_path)
    for name in ("PARTS_PATH", "PARTS_PDF_PATH", "CHECKLIST_PDF_PATH", "OUTPUT_PDF"):
        monkeypatch.setattr(main, name, str(tmp_path / f"{name}.out"))

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["main.py", "--sample", "--no-bricklink",
                                          "--label-spec", "avery5160", *argv])
        main.main()

    run("--parts", "--keep-parts", "optimize")
    ids = [r[1] for r in list(csv.reader(open(main.PARTS_PATH)))[1:]]
    assert ids == ["6100001", "6100003", "6100002", "6100004"]
    run("--parts", "--keep-parts", "optimize", "--parts-order", "heaviest")
    ids = [r[1] for r in list(csv.reader(open(main.PARTS_PATH)))[1:]]
    assert ids == ["6100001", "6100002", "6100003", "6100004"]
    run("--parts")  # no packing: plain part order
    ids = [r[1] for r in list(csv.reader(open(main.PARTS_PATH)))[1:]]
    assert ids == ["6100001", "6100002", "6100003", "6100004"]
    # The checklist for one person ("P00 Test" is on every part) follows the packed order.
    run("--checklist", "--keep-parts", "optimize", "--hide", "photo")
    text = pdf_text(main.CHECKLIST_PDF_PATH)
    chunk = text[text.index("P00 Test"):text.index("P01 Test")]
    order = sorted(("6100001", "6100002", "6100003", "6100004"), key=chunk.index)
    assert order == ["6100001", "6100003", "6100002", "6100004"]


def test_main_flags_reach_the_pdfs(monkeypatch, tmp_path, no_network):
    monkeypatch.chdir(tmp_path)
    for name in ("PARTS_PATH", "PARTS_PDF_PATH", "CHECKLIST_PDF_PATH", "OUTPUT_PDF",
                 "LOT_COUNTS_PATH", "LOT_COUNTS_PDF_PATH"):
        monkeypatch.setattr(main, name, str(tmp_path / f"{name}.out"))

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["main.py", "--sample", "--no-bricklink", *argv])
        main.main()

    run("--checklist", "--paper", "a4", "--orientation", "landscape", "--report-title", "Hello",
        "--checklist-layout", "continuous", "--checklist-hide", "checkbox")
    assert pages(main.CHECKLIST_PDF_PATH)[0] == pytest.approx((841.89, 595.28), abs=0.01)
    assert "Hello" in pdf_text(main.CHECKLIST_PDF_PATH)
    run("--parts", "--parts-hide", "people", "--parts-show", "total-weight", "--report-subtitle", "Sub")
    text = pdf_text(main.PARTS_PDF_PATH)
    assert "Total weight" in text and "People" not in text and "Sub" in text
    run("--lot-counts", "--lots-min-lots", "2", "--lots-show", "totals")
    text = pdf_text(main.LOT_COUNTS_PDF_PATH)
    assert "Total (" in text and "left out" in text
    assert open(main.LOT_COUNTS_PATH).read().splitlines()[0] == "person,lot_count,total_pieces"
