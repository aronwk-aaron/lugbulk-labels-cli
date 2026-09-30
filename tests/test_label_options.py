import pytest

import colors
from manifest import write_checklist_pdf
from render_labels import LabelOptions, _layout, build_pdf, build_test_page
from samples import sample_records


def test_parse_defaults_and_switches():
    assert not LabelOptions().show("qr") and LabelOptions().show("photo")
    opts = LabelOptions.parse("photo, bl_color", "qr")
    assert not opts.show("photo") and not opts.show("bl_color") and opts.show("qr")
    with pytest.raises(ValueError, match="unknown label part 'bogus'"):
        LabelOptions.parse("bogus")


def test_hidden_parts_free_their_space():
    full = _layout(288, 96, LabelOptions(), 3)
    no_photo = _layout(288, 96, LabelOptions.parse("photo"), 3)
    assert no_photo["text_x"] < full["text_x"] and no_photo["img"] == 0
    # Fewer lines -> the name row sits no higher than it does with more.
    assert _layout(288, 96, LabelOptions(), 1)["y_name"] >= full["y_name"]
    with_qr = _layout(288, 96, LabelOptions.parse(None, "qr"), 3)
    assert with_qr["qr"] > 0 and with_qr["text_right"] < full["text_right"]
    no_top = _layout(288, 96, LabelOptions.parse("element_id,qty"), 3)
    assert no_top["lines"][0] > full["lines"][0]  # text moves up into the free row


def test_swatch_colors():
    assert colors.swatch_rgb("", "Light Bluish Gray") == pytest.approx((0.627, 0.647, 0.663), abs=0.01)
    assert colors.swatch_rgb("MYSTERY", "") is None


def test_samples_render_and_reports(tmp_path, monkeypatch):
    # No network in tests: every photo is a cached miss.
    import render_labels
    monkeypatch.setattr(render_labels, "_cached_image_path", lambda *_: None)
    records = sample_records()
    assert records and all(r.part_total for r in records)
    for opts in (LabelOptions(), LabelOptions.parse("photo,name,count", "qr")):
        out = tmp_path / "labels.pdf"
        assert build_pdf(records, str(out), "avery5162", opts) == len(records)
        assert out.read_bytes().startswith(b"%PDF")
    write_checklist_pdf(records, str(tmp_path / "checklist.pdf"))
    build_test_page(str(tmp_path / "test.pdf"), "avery5160")
    assert (tmp_path / "checklist.pdf").stat().st_size > 1000
    assert (tmp_path / "test.pdf").stat().st_size > 1000
