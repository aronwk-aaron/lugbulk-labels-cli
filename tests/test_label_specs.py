import pytest

from config import LABEL_SPECS, ACTIVE_LABEL_SPEC, find_label_spec
from render_labels import _specification


def test_lookup_by_any_part_number():
    assert find_label_spec("avery5162") == "avery5162"
    assert find_label_spec("8162") == "avery5162"
    assert find_label_spec("Avery 8162") == "avery5162"
    assert find_label_spec("dymo30857") == "dymo30857"
    assert find_label_spec("L7163") == "avery7163"
    assert find_label_spec("bogus") is None
    assert ACTIVE_LABEL_SPEC in LABEL_SPECS


@pytest.mark.parametrize("spec_id", sorted(LABEL_SPECS))
def test_every_stock_is_a_valid_pylabels_layout(spec_id):
    _specification(spec_id)  # raises InvalidDimension if the grid doesn't fit


def test_rolls_are_one_landscape_label_per_page():
    for spec in LABEL_SPECS.values():
        if spec["page"] == "roll":
            assert (spec["columns"], spec["rows"]) == (1, 1)
            assert spec["label_width_mm"] >= spec["label_height_mm"]
