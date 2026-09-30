import os

from ordering import order_records
from xlsx_source import validate_source

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_order.xlsx")


def test_fixture_end_to_end_order():
    records, issues = validate_source(FIXTURE)
    assert issues == []
    ordered = order_records(records)
    assert [(r.element_id, r.person, r.qty, f"{r.part_seq}/{r.part_total}") for r in ordered] == [
        ("6097276", "Bob Roe", "2", "1/1"),       # baseplate: heaviest
        ("6508677", "Ann Lee", "25", "1/1"),
        ("4211388", "Bob Roe", "25", "1/2"),      # smallest qty first
        ("4211388", "Ann Lee", "100", "2/2"),
        ("6584302", "Ann Lee", "50", "1/2"),      # frog: size unknown, last
        ("6584302", "Bob Roe", "50", "2/2"),
    ]
    assert ordered[2].lego_color == "Medium Stone Grey" and ordered[2].bl_color == "Light Bluish Gray"
