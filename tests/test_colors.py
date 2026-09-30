import colors


def test_lego_abbreviation_fills_bricklink():
    assert colors.resolve("MED. ST-GREY", "") == ("Medium Stone Grey", "Light Bluish Gray", True)
    assert colors.resolve("DK. ST. GREY", "") == ("Dark Stone Grey", "Dark Bluish Gray", True)
    # 2026's list spells Medium Stone Grey "LT. ST. GREY"
    assert colors.resolve("LT. ST. GREY", "")[1] == "Light Bluish Gray"
    assert colors.resolve("TR.", "")[1] == "Trans-Clear"


def test_bricklink_fills_lego():
    assert colors.resolve("", "Tan") == ("Brick Yellow", "Tan", True)
    assert colors.resolve("", "Trans Black") == ("Transparent Brown", "Trans Black", True)


def test_both_given_expands_lego_abbreviation_keeps_bricklink():
    assert colors.resolve("BR.YEL-GREEN", "Lime") == ("Bright Yellowish Green", "Lime", True)
    assert colors.resolve("MYSTERY", "Mystery") == ("MYSTERY", "Mystery", True)


def test_unknown_color_passes_through_unmapped():
    assert colors.resolve("MYSTERY", "") == ("MYSTERY", "", False)
    assert colors.resolve("", "Mystery") == ("", "Mystery", False)


def test_is_transparent():
    assert colors.is_transparent("TR.L.BLUE", "")
    assert colors.is_transparent("", "Trans-Clear")
    assert not colors.is_transparent("WHITE", "White")
