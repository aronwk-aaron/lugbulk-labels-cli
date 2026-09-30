"""Report options: the same names, defaults and clamping as the web app's
static/js/report_options.js, and the flags that set them."""

import json
import sys

import pytest

import main
import report_options as ro


def test_defaults_match_the_web_apps():
    page = {"title": "", "subtitle": "", "paper": "letter", "orientation": "portrait"}
    assert ro.normalize_options(None) == {
        "checklist": {**page, "sort": "last", "order": "labels", "layout": "page",
                      "color": True, "weight": False, "photo": False, "checkbox": True,
                      "packed_by": False},
        "parts": {**page, "order": "labels", "photo": False, "lego_color": True,
                  "bl_color": True, "pieces": True, "people": True, "weight": True,
                  "total_weight": False, "group_by_color": False},
        "lots": {**page, "sort": "last", "lots": True, "pieces": True, "total_weight": False,
                 "totals": False, "min_lots": 0},
        "zip": {k: True for k in ("labels", "checklist_pdf", "parts_pdf", "parts_csv",
                                  "lots_pdf", "lots_csv", "check_txt")},
    }


@pytest.mark.parametrize("raw", [None, [], "x", 5, {"checklist": 3}, {"parts": []}])
def test_anything_normalizes_to_defaults(raw):
    assert ro.normalize_options(raw) == ro.normalize_options(None)


def test_unknown_keys_dropped_and_bad_values_fall_back():
    got = ro.normalize_options({
        "evil": 1,
        "checklist": {"paper": "a3", "orientation": 1, "layout": "grid", "order": "element",
                      "color": "yes", "weight": 1, "photo": True, "extra": 1, "sort": "middle"},
        "parts": {"order": "element", "paper": "a4", "group_by_color": True, "people": None},
        "lots": {"min_lots": "x", "totals": True},
    })
    assert "evil" not in got and "extra" not in got["checklist"]
    c = got["checklist"]
    assert (c["paper"], c["orientation"], c["layout"], c["order"], c["sort"]) == (
        "letter", "portrait", "page", "labels", "last")  # "element" is for the parts list only
    assert c["color"] is True and c["weight"] is False and c["photo"] is True
    p = got["parts"]
    assert p["order"] == "element" and p["paper"] == "a4" and p["group_by_color"] is True
    assert p["people"] is True
    assert got["lots"]["min_lots"] == 0 and got["lots"]["totals"] is True


def test_title_and_subtitle_cleaned_and_capped():
    assert ro.clean_text("  a \t\n b c   d  ", 80) == "a b c d"
    assert ro.clean_text(5, 80) == "" and ro.clean_text(None, 80) == ""
    got = ro.normalize_options({"parts": {"title": "T" * 200, "subtitle": "s" * 200}})["parts"]
    assert got["title"] == "T" * ro.MAX_TITLE == "T" * 80
    assert got["subtitle"] == "s" * ro.MAX_SUBTITLE == "s" * 120
    # cut at the limit, then trimmed again
    assert ro.clean_text("ab " + "c" * 10, 3) == "ab"
    assert ro.clean_text("é" * 100, 80) == "é" * 80  # counted in characters


@pytest.mark.parametrize("value,want", [
    (0, 0), (5, 5), ("12", 12), (" 7 ", 7), (-3, 0), (10 ** 9, 9999), (9999.9, 9999),
    (7.9, 7), (-0.5, 0), ("abc", 0), ("", 0), (None, 0), (True, 0), ([], 0), ("1e2", 100),
    (float("nan"), 0), (float("inf"), 0),
])
def test_min_lots_clamped(value, want):
    assert ro.normalize_options({"lots": {"min_lots": value}})["lots"]["min_lots"] == want


def test_parse_options_json():
    assert ro.parse_options("not json") == ro.normalize_options(None)
    assert ro.parse_options(None) == ro.normalize_options(None)
    assert ro.parse_options("x" * (ro.MAX_OPTIONS_BYTES * 4 + 1)) == ro.normalize_options(None)
    assert ro.parse_options('{"lots": {"min_lots": 3}}')["lots"]["min_lots"] == 3


def test_page_sizes():
    assert ro.page_size({"paper": "letter", "orientation": "portrait"}) == (612, 792)
    assert ro.page_size({"paper": "letter", "orientation": "landscape"}) == (792, 612)
    w, h = ro.page_size({"paper": "a4", "orientation": "portrait"})
    assert (round(w, 2), round(h, 2)) == (595.28, 841.89)
    assert ro.page_size({"paper": "a4", "orientation": "landscape"}) == (h, w)


# ---- flags -------------------------------------------------------------------------

def parse(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    return main.parse_args().report_options_parsed


def test_no_flags_give_the_defaults(monkeypatch):
    assert parse(monkeypatch) == ro.normalize_options(None)


def test_flags_set_the_options(monkeypatch):
    o = parse(
        monkeypatch, "--report-title", "  My  title ", "--report-subtitle", "Sub", "--paper", "a4",
        "--orientation", "landscape", "--checklist-layout", "continuous",
        "--checklist-order", "lightest", "--checklist-show", "weight,photo,packed-by",
        "--checklist-hide", "checkbox,color", "--parts-order", "element",
        "--parts-show", "photo,total-weight,group-by-color", "--parts-hide", "bl_color,people",
        "--lots-show", "total-weight,totals", "--lots-hide", "lots", "--lots-min-lots", "3",
        "--sort-by", "first")
    for name in ro.REPORTS:
        assert (o[name]["title"], o[name]["subtitle"]) == ("My title", "Sub")
        assert (o[name]["paper"], o[name]["orientation"]) == ("a4", "landscape")
    assert o["checklist"] == {**o["checklist"], "layout": "continuous", "order": "lightest",
                              "weight": True, "photo": True, "packed_by": True,
                              "checkbox": False, "color": False, "sort": "first"}
    assert o["parts"]["order"] == "element" and o["parts"]["photo"] is True
    assert o["parts"]["total_weight"] is True and o["parts"]["group_by_color"] is True
    assert o["parts"]["bl_color"] is False and o["parts"]["people"] is False
    assert o["parts"]["lego_color"] is True
    l = o["lots"]
    assert (l["total_weight"], l["totals"], l["lots"], l["min_lots"], l["sort"]) == (
        True, True, False, 3, "first")


def test_per_person_layout_is_the_webs_page(monkeypatch):
    assert parse(monkeypatch, "--checklist-layout", "per-person")["checklist"]["layout"] == "page"


def test_min_lots_flag_is_clamped(monkeypatch):
    assert parse(monkeypatch, "--lots-min-lots", "-4")["lots"]["min_lots"] == 0
    assert parse(monkeypatch, "--lots-min-lots", "123456")["lots"]["min_lots"] == 9999


def test_long_title_flag_is_capped(monkeypatch):
    assert parse(monkeypatch, "--report-title", "x" * 300)["parts"]["title"] == "x" * 80


@pytest.mark.parametrize("argv", [
    ["--checklist-show", "sparkles"], ["--parts-hide", "element"], ["--lots-show", "weight"],
    ["--checklist-show", "photo", "--checklist-hide", "photo"], ["--lots-min-lots", "many"],
    ["--paper", "a3"], ["--orientation", "tilted"], ["--parts-order", "nope"],
    ["--checklist-order", "element"], ["--checklist-layout", "page"],
    ["--report-options", "/no/such/file.json"],
])
def test_bad_flags_are_refused(monkeypatch, argv, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    with pytest.raises(SystemExit) as e:
        main.parse_args()
    assert e.value.code == 2
    assert "error" in capsys.readouterr().err


def test_report_options_file_then_flags_override(monkeypatch, tmp_path):
    saved = tmp_path / "design.json"
    saved.write_text(json.dumps({
        "checklist": {"layout": "continuous", "weight": True, "sort": "first", "paper": "a4"},
        "parts": {"order": "heaviest", "title": "Saved title", "group_by_color": True},
        "lots": {"min_lots": 2, "totals": True, "sort": "first"},
        "zip": {"labels": False},
        "unknown": {"a": 1},
    }))
    o = parse(monkeypatch, "--report-options", str(saved), "--paper", "letter",
              "--parts-hide", "group-by-color")
    assert o["checklist"]["layout"] == "continuous" and o["checklist"]["weight"] is True
    assert o["checklist"]["paper"] == "letter"  # the flag beats the file
    assert o["checklist"]["sort"] == "first" and o["lots"]["sort"] == "first"
    assert o["parts"]["order"] == "heaviest" and o["parts"]["title"] == "Saved title"
    assert o["parts"]["group_by_color"] is False
    assert o["lots"]["min_lots"] == 2 and o["lots"]["totals"] is True
    # an explicit --sort-by beats the file's sort
    o = parse(monkeypatch, "--report-options", str(saved), "--sort-by", "last")
    assert o["checklist"]["sort"] == "last" and o["lots"]["sort"] == "last"


def test_report_options_file_is_normalized(monkeypatch, tmp_path):
    saved = tmp_path / "d.json"
    saved.write_text(json.dumps({"lots": {"min_lots": 10 ** 9}, "parts": {"order": "bogus"}}))
    o = parse(monkeypatch, "--report-options", str(saved))
    assert o["lots"]["min_lots"] == 9999 and o["parts"]["order"] == "labels"


def test_report_options_file_must_be_json(monkeypatch, tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    monkeypatch.setattr(sys, "argv", ["main.py", "--report-options", str(bad)])
    with pytest.raises(SystemExit):
        main.parse_args()
    assert "not valid JSON" in capsys.readouterr().err
