import config
from pivot import build_records


def test_qty_marker_layout():
    """The ArkLUG sheet: names on row 1, "qty"/"$$" markers on row 2."""
    rows = [
        ["#", "Element ID", "Photo", "Description", "BL Color", "Cost Each", "Total",
         "Ann Lee", "", "Bob Roe", ""],
        ["", "", "", "", "", "", "", "qty", "$$", "qty", "$$"],
        ["1", "4211388", "", "BRICK 1X2", "Light Bluish Gray", "0.05", "", "2,000", "$1",
         "", ""],
        ["2", "6508677", "", "BRICK 2X4, TRANSPARENT", "Trans-Clear", "0.2", "", "0", "",
         "25", "$5"],
    ]
    records, issues = build_records(rows)
    assert [(r.person, r.element_id, r.qty, r.lego_color, r.bl_color) for r in records] == [
        ("Ann Lee", "4211388", "2000", "Medium Stone Grey", "Light Bluish Gray"),
        ("Bob Roe", "6508677", "25", "Transparent", "Trans-Clear"),
    ]
    assert issues == []


def test_name_cost_pair_layout_with_totals_row_above_header():
    """Master-sheet layout (made-up values): totals row, then a header row where each
    person is (name, running cost total), and LEGO rather than BL colors."""
    rows = [
        [41234, None, None, None, None, None, None, "Ann Lee", None],
        ["Total Ordered", "Part Number", "Description", "LEGO Color", "BL Color", "Price",
         "Nominated for", "Ann Lee", 120.50, "Bob Roe", "30.00"],
        [None] * 11,
        [1500, 4211407.0, "PLATE 4X8", "WHITE", None, 0.10, "ZZZ", 100.0, 10, "x", None],
    ]
    records, issues = build_records(rows)
    assert [(r.person, r.element_id, r.qty, r.lego_color, r.bl_color) for r in records] == [
        ("Ann Lee", "4211407", "100", "White", "White"),
    ]
    assert [i.kind for i in issues] == ["bad_qty"]  # Bob's "x"


def test_bad_element_id_is_reported_not_used_as_a_path():
    rows = [
        ["#", "Element ID", "", "Description", "BL Color", "", "", "Ann"],
        ["", "", "", "", "", "", "", "qty"],
        ["1", "../../etc/passwd", "", "BRICK", "Red", "", "", "5"],
        ["", "TOTAL", "", "", "", "", "", ""],  # footer with no qty: skipped silently
    ]
    records, issues = build_records(rows)
    assert records == []
    assert [i.kind for i in issues] == ["bad_element_id"]


def test_duplicates_unmapped_colors_and_weight(monkeypatch):
    monkeypatch.setattr(config, "COLOR_OVERRIDES", {"6584805": "Warm Pink"})
    rows = [
        ["#", "Element ID", "", "Description", "LEGO Color", "Weight", "", "Ann", ""],
        ["", "", "", "", "", "", "", "qty", "$$"],
        ["1", "6584805", "", "PROFILE BRICK", "WARM PINK", "0.9 g", "", "5", ""],
        ["2", "6584805", "", "PROFILE BRICK", "WARM PINK", "", "", "5", ""],
        ["3", "1234567", "", "THING", "NEWCOLOR", "heavy", "", "1", ""],
    ]
    records, issues = build_records(rows)
    assert records[0].bl_color == "Warm Pink" and records[0].weight == 0.9
    assert sorted(i.kind for i in issues) == ["bad_weight", "duplicate", "unmapped_color"]


def test_placeholder_color_counts_as_missing(monkeypatch):
    monkeypatch.setattr(config, "COLOR_OVERRIDES", {})
    rows = [
        ["#", "Element ID", "", "Description", "BL Color", "", "", "Ann"],
        ["", "", "", "", "", "", "", "qty"],
        ["1", "6584805", "", "PROFILE BRICK", "unknown", "", "", "5"],
    ]
    records, issues = build_records(rows)
    assert records[0].bl_color == ""
    assert [(i.kind, i.element_id) for i in issues] == [("missing_color", "6584805")]
