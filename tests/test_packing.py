import itertools
import json
import os
from types import SimpleNamespace

import pytest

from packing import (KEEP_MODES, flow_summary, pack_records, pack_sizes, slots_of,
                     split_parts)

GOLDEN = os.path.join(os.path.dirname(__file__), "fixtures", "packing_golden.json")


def recs(ids):
    return [SimpleNamespace(element_id=i) for i in ids]


@pytest.fixture(scope="module")
def golden():
    with open(GOLDEN) as f:
        return json.load(f)


def test_same_packing_as_the_web_app(golden):
    # tests/fixtures/packing_golden.json comes from the web app's packing.js
    # (tools/packing_golden.mjs): same bins, bounds and flags for every case.
    for case in golden["sizes"]:
        out = pack_sizes(case["sizes"], case["C"], time_box=60)
        want = case["out"]
        assert out["bins"] == want["bins"], case
        assert out["proven"] == want["proven"]
        assert out["lower_bound"] == want["lowerBound"]
        assert out["order_exact"] == want["orderExact"]


def test_same_layout_as_the_web_app(golden):
    for case in golden["records"]:
        r = recs(case["ids"])
        p = pack_records(r, case["per"], time_box=60)
        want = case["out"]
        assert p.layout == want["layout"]
        assert (p.sheets, p.blanks, p.proven, p.lower_bound, p.order_exact) == (
            want["sheets"], want["blanks"], want["proven"], want["lowerBound"], want["orderExact"])
        flow = flow_summary(r, case["per"])
        assert (flow["sheets"], flow["blanks"], flow["split_parts"]) == (
            case["flow"]["sheets"], case["flow"]["blanks"], case["flow"]["splitParts"])
        assert split_parts(slots_of(r, p.layout), case["per"]) == case["split"]


def brute_force_bins(sizes, C):
    """Fewest bins by trying every assignment (tiny inputs only)."""
    for k in range(1, len(sizes) + 1):
        for assign in itertools.product(range(k), repeat=len(sizes)):
            load = [0] * k
            for s, b in zip(sizes, assign):
                load[b] += s
            if max(load) <= C:
                return k
    return 0


def test_optimal_against_brute_force():
    import random
    rng = random.Random(7)
    for _ in range(150):
        C = rng.choice([4, 6, 10])
        sizes = [rng.randint(1, C) for _ in range(rng.randint(1, 7))]
        out = pack_sizes(sizes, C)
        assert out["proven"]
        assert len(out["bins"]) == brute_force_bins(sizes, C), (sizes, C)
        assert sorted(i for b in out["bins"] for i in b) == list(range(len(sizes)))
        assert all(sum(sizes[i] for i in b) <= C for b in out["bins"])


def test_no_part_that_fits_is_split_and_big_parts_start_fresh_sheets():
    # 10-up: parts of 7, 6, 4, 3 and a 23-label part (2 whole sheets + 3).
    ids = ["1"] * 7 + ["2"] * 6 + ["3"] * 23 + ["4"] * 4 + ["5"] * 3
    r = recs(ids)
    p = pack_records(r, 10)
    slots = slots_of(r, p.layout)
    assert split_parts(slots, 10) == 0
    assert p.sheets == 5 and p.proven  # 7+3, 6+4, 10, 10, 3
    assert sorted(i for i in p.layout if i >= 0) == list(range(len(r)))
    for s in range(p.sheets):
        page = [x.element_id for x in slots[s * 10:(s + 1) * 10] if x]
        if page.count("3") == 10:
            assert slots[s * 10].element_id == "3"  # whole sheets of a big part
    # "off" splits parts here.
    assert flow_summary(r, 10)["split_parts"] > 0


def test_rolls_and_empty_input_pass_through():
    r = recs(["1", "1", "2"])
    assert pack_records(r, 1).layout == [0, 1, 2]
    assert pack_records([], 10).sheets == 0


def test_time_box_gives_a_valid_packing():
    import random
    rng = random.Random(3)
    sizes = [rng.randint(1, 30) for _ in range(120)]
    ticks = iter(range(10**9))
    out = pack_sizes(sizes, 30, time_box=5, now=lambda: next(ticks))  # expires fast
    assert sorted(i for b in out["bins"] for i in b) == list(range(len(sizes)))
    assert all(sum(sizes[i] for i in b) <= 30 for b in out["bins"])


def test_modes():
    assert KEEP_MODES == ("off", "optimize")


def test_blank_slots_render_as_empty_labels(tmp_path):
    # Invented orders on 10-up sheets: parts of 7, 6, 4 and 3 labels.
    from records import LabelRecord
    from render_labels import LabelOptions, build_pdf

    records = []
    for eid, n in (("4211388", 7), ("3004", 6), ("6097276", 4), ("6508677", 3)):
        records += [LabelRecord(f"Person {k}", eid, "BRICK 1X2", "Black", "Black", "5", "")
                    for k in range(n)]
    packed = pack_records(records, 10)
    slots = slots_of(records, packed.layout)
    assert packed.sheets == 2 and packed.blanks == 0  # 7+3 and 6+4
    out = tmp_path / "labels.pdf"
    count = build_pdf(slots + [None] * 3, str(out), spec_name="avery5163",
                      opts=LabelOptions.parse("photo,backdrop,swatch"))
    assert count == len(records)  # blanks aren't counted as labels
    import re
    pages = len(re.findall(rb"/Type\s*/Page(?![s\w])", out.read_bytes()))
    assert pages == 3  # two full sheets and one with 3 empty slots
