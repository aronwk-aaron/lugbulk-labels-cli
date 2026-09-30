import pytest

from ordering import estimate_weight, order_records, summarize_parts
from records import LabelRecord


@pytest.mark.parametrize("desc, bricks", [
    ("BRICK 1X2", 2),
    ("PLATE 4X8", 32 / 3),
    ("FLAT TILE 2X2", 4 / 3),
    ("BRICK 1X2X5", 10),
    ("BRICK 1X1X1 2/3 W/2 KNOBS", 5 / 3),
    ("ROOF TILE 1X2X2/3", 4 / 3),
    ("ROOF TILE 1X2X3/73°", 6),  # 3 bricks tall, 73° slope — not 3/73
    ("DUPLO BRICK 2X4", 64),
    ("Profile brick 1x2 single gro.", 2),
])
def test_estimate_weight(desc, bricks):
    assert estimate_weight(desc) == pytest.approx(bricks * 0.43)


def test_estimate_weight_unknown():
    assert estimate_weight("FROG") is None
    assert estimate_weight("") is None


def _rec(person, element_id, desc, qty, weight=None):
    return LabelRecord(person, element_id, desc, "", "", qty, "", weight)


def test_order_groups_by_part_heaviest_first_then_qty_ascending():
    records = [
        _rec("Ann", "1111", "PLATE 1X1", "50"),
        _rec("Bob", "2222", "BASE PLATE 32X32", "5"),
        _rec("Cat", "1111", "PLATE 1X1", "10"),
        _rec("Dan", "3333", "FROG", "1"),
        _rec("Eve", "2222", "BASE PLATE 32X32", "2"),
    ]
    ordered = order_records(records)
    assert [(r.element_id, r.person, r.part_seq, r.part_total) for r in ordered] == [
        ("2222", "Eve", 1, 2), ("2222", "Bob", 2, 2),
        ("1111", "Cat", 1, 2), ("1111", "Ann", 2, 2),
        ("3333", "Dan", 1, 1),  # unknown size sorts last
    ]


def test_lightest_and_sheet_orders():
    records = [_rec("A", "1111", "PLATE 1X1", "1"), _rec("B", "2222", "BRICK 2X4", "1")]
    assert [p.element_id for p in summarize_parts(records, part_order="lightest")] == ["1111", "2222"]
    assert [p.element_id for p in summarize_parts(records, part_order="sheet")] == ["1111", "2222"]
    assert [p.element_id for p in summarize_parts(records)] == ["2222", "1111"]


def test_weight_priority_override_then_sheet_then_estimate():
    records = [
        _rec("A", "1111", "BRICK 1X1", "1", weight=9.0),
        _rec("B", "2222", "BRICK 1X1", "1"),
        _rec("C", "3333", "FROG", "1"),
    ]
    parts = {p.element_id: p for p in summarize_parts(records, overrides={"3333": 50})}
    assert (parts["1111"].weight, parts["1111"].weight_source) == (9.0, "sheet")
    assert parts["2222"].weight_source == "estimate"
    assert (parts["3333"].weight, parts["3333"].weight_source) == (50, "override")


def test_part_summary_counts_people_and_pieces():
    records = [_rec("A", "1111", "BRICK 1X1", "25"), _rec("B", "1111", "BRICK 1X1", "100")]
    [part] = summarize_parts(records)
    assert (part.lots, part.pieces) == (2, 125)


def test_bricklink_weight_beats_estimate_but_not_sheet():
    records = [
        _rec("A", "1111", "BRICK 1X1", "1", weight=9.0),
        _rec("B", "2222", "BRICK 1X1", "1"),
    ]
    parts = {p.element_id: p for p in summarize_parts(records, bricklink={"1111": 1.0, "2222": 2.5})}
    assert (parts["1111"].weight, parts["1111"].weight_source) == (9.0, "sheet")
    assert (parts["2222"].weight, parts["2222"].weight_source) == (2.5, "bricklink")
