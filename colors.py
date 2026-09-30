"""LEGO <-> BrickLink color name lookup.

LUGBulk order sheets name colors two different ways, and a given sheet may
only have one of them filled in:

- LEGO's own names, usually in the abbreviated form LEGO's LUGBulk part
  list uses ("MED. ST-GREY", "BR.YEL-GREEN", "TR.L.BLUE", ...).
- BrickLink's names ("Light Bluish Gray", "Lime", "Trans-Light Blue", ...).

Labels show both, so whichever one the sheet is missing is filled in from
the table below. Lookups are forgiving about punctuation, spacing and case
("DK. ST. GREY", "DK.ST.GREY" and "Dark Stone Grey" all match).

Unknown colors are passed through unchanged and surfaced as an
"unmapped_color" issue by --validate; add the missing pair to COLORS (or a
per-event override in config_local.py) when that happens.
"""

import re

# (LEGO name, BrickLink name, extra LEGO spellings seen on LUGBulk lists)
COLORS: list[tuple[str, str, tuple[str, ...]]] = [
    ("White", "White", ("WHITE",)),
    ("Black", "Black", ("BLACK",)),
    ("Bright Red", "Red", ("BR.RED", "BR. RED")),
    ("Bright Blue", "Blue", ("BR.BLUE", "BR. BLUE")),
    ("Bright Yellow", "Yellow", ("BR.YEL", "BR. YEL", "BR.YELLOW")),
    ("Bright Green", "Bright Green", ("BR.GREEN", "BR. GREEN")),
    ("Dark Green", "Green", ("DK.GREEN", "DK. GREEN")),
    ("Earth Green", "Dark Green", ("EARTH GREEN",)),
    ("Earth Blue", "Dark Blue", ("EARTH BLUE",)),
    ("Medium Stone Grey", "Light Bluish Gray",
     ("MED. ST-GREY", "MED.ST-GREY", "MED. ST. GREY", "M. ST. GREY",
      # 2026's list abbreviates Medium Stone Grey as "LT. ST. GREY"
      # (e.g. element 6225242), not LEGO's separate Light Stone Grey.
      "LT. ST. GREY", "LT.ST.GREY")),
    ("Dark Stone Grey", "Dark Bluish Gray", ("DK. ST. GREY", "DK.ST.GREY", "DK. ST-GREY")),
    ("Brick Yellow", "Tan", ("BRICK-YEL", "BRICK YEL", "BRICK-YELLOW")),
    ("Sand Yellow", "Dark Tan", ("SAND YELLOW",)),
    ("Reddish Brown", "Reddish Brown", ("RED. BROWN", "RED.BROWN")),
    ("Dark Brown", "Dark Brown", ("DK. BROWN", "DK.BROWN")),
    ("New Dark Red", "Dark Red", ("NEW DARK RED",)),
    ("Sand Green", "Sand Green", ("SAND GREEN",)),
    ("Sand Blue", "Sand Blue", ("SAND BLUE",)),
    ("Olive Green", "Olive Green", ("OLIVE GREEN",)),
    ("Nougat", "Nougat", ("NOUGAT",)),
    ("Medium Nougat", "Medium Nougat", ("M. NOUGAT", "MED. NOUGAT", "M.NOUGAT")),
    ("Light Nougat", "Light Nougat", ("L.NOUGAT", "L. NOUGAT", "LGH. NOUGAT")),
    ("Dark Orange", "Dark Orange", ("DK.ORA", "DK. ORA", "DK.ORANGE")),
    ("Bright Orange", "Orange", ("BR.ORANGE", "BR. ORANGE", "BR.ORA")),
    ("Reddish Orange", "Reddish Orange", ("RED. ORANGE", "RED.ORANGE")),
    ("Flame Yellowish Orange", "Bright Light Orange", ("FL. YELL-ORA", "FL.YELL-ORA")),
    ("Bright Yellowish Green", "Lime", ("BR.YEL-GREEN", "BR. YEL-GREEN")),
    ("Bright Bluish Green", "Dark Turquoise", ("BR.BLUEGREEN", "BR. BLUEGREEN")),
    ("Aqua", "Light Aqua", ("AQUA",)),
    ("Lavender", "Lavender", ("LAVENDER",)),
    ("Medium Lavender", "Medium Lavender", ("M. LAVENDER", "MED. LAVENDER")),
    ("Medium Lilac", "Dark Purple", ("MEDIUM LILAC", "M. LILAC")),
    ("Bright Reddish Violet", "Magenta", ("BR.RED-VIOLET", "BR.RED.VIOLET")),
    ("Bright Purple", "Dark Pink", ("BR.PURPLE", "BR. PURPLE")),
    ("Light Purple", "Bright Pink", ("LGH. PURPLE", "LGH.PURPLE")),
    ("Medium Blue", "Medium Blue", ("MEDIUM BLUE", "M. BLUE")),
    ("Medium Azur", "Medium Azure", ("MEDIUM AZUR", "MED. AZUR")),
    ("Dark Azur", "Dark Azure", ("DARK AZUR", "DK. AZUR")),
    ("Light Royal Blue", "Bright Light Blue", ("LT.ROY.BLUE", "LGH. ROYAL BLUE")),
    ("Cool Yellow", "Bright Light Yellow", ("COOL YELLOW",)),
    ("Vibrant Coral", "Coral", ("VIBRANT CORAL",)),
    ("Warm Pink", "Warm Pink", ("WARM PINK",)),
    ("Spring Yellowish Green", "Yellowish Green", ("SPR. YEL-GREEN",)),
    ("Silver Metallic", "Flat Silver", ("SILVER MET.", "SILVER MET")),
    ("Titanium Metallic", "Pearl Dark Gray", ("TITAN. MET.", "TITANIUM MET.")),
    ("Warm Gold", "Pearl Gold", ("WARM GOLD",)),
    ("White Glow", "Glow In Dark White", ("WHITE GLOW",)),
    ("Transparent", "Trans-Clear", ("TR.", "TR", "TRANSPARENT")),
    ("Transparent Light Blue", "Trans-Light Blue", ("TR.L.BLUE", "TR. L. BLUE")),
    ("Transparent Blue", "Trans-Dark Blue", ("TR.BLUE", "TR. BLUE")),
    ("Transparent Brown", "Trans-Black", ("TR.BROWN", "TR. BROWN")),
    ("Transparent Red", "Trans-Red", ("TR.RED", "TR. RED")),
    ("Transparent Green", "Trans-Green", ("TR.GREEN", "TR. GREEN")),
    ("Transparent Yellow", "Trans-Yellow", ("TR.YEL", "TR. YELLOW", "TR.YELLOW")),
    ("Transparent Bright Orange", "Trans-Orange", ("TR.BR.ORANGE",)),
    ("Transparent Fluorescent Reddish Orange", "Trans-Neon Orange", ("TR.FL.RED-ORA",)),
    ("Transparent Fluorescent Green", "Trans-Neon Green", ("TR.FL.GREEN",)),
]


def _key(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.upper())


_BY_LEGO: dict[str, tuple[str, str]] = {}
_BY_BL: dict[str, tuple[str, str]] = {}
for _lego, _bl, _aliases in COLORS:
    for _alias in (_lego, *_aliases):
        _BY_LEGO.setdefault(_key(_alias), (_lego, _bl))
    # _key drops punctuation, so "Trans-Clear" and "Trans Clear" both hit.
    _BY_BL.setdefault(_key(_bl), (_lego, _bl))


def resolve(lego: str, bl: str) -> tuple[str, str, bool]:
    """Fill in whichever of (LEGO name, BrickLink name) is missing.

    Returns (lego, bl, mapped). A recognized LEGO abbreviation is expanded
    to LEGO's full name ("MED. ST-GREY" -> "Medium Stone Grey"); a BrickLink
    name the sheet provides is kept as-is. `mapped` is False when one side
    was missing and couldn't be looked up (so the label will only show one
    color name)."""
    lego, bl = (lego or "").strip(), (bl or "").strip()
    if lego:
        hit = _BY_LEGO.get(_key(lego))
        if hit:
            return hit[0], bl or hit[1], True
        return lego, bl, bool(bl)
    if bl:
        hit = _BY_BL.get(_key(bl)) or _BY_LEGO.get(_key(bl))
        return (hit[0] if hit else ""), bl, hit is not None
    return "", "", True  # nothing to map; missing_color is reported separately


def is_transparent(lego: str, bl: str) -> bool:
    """True for trans colors, whose parts photograph as a faint outline on
    LEGO's white-background product shots."""
    # Every trans color starts "TR"/"Trans" in both naming schemes, and no
    # opaque color does.
    return any(_key(name or "").startswith("TR") for name in (lego, bl))


def is_light(lego: str, bl: str) -> bool:
    """True for white-family colors (White, Glow In Dark White, ...), which
    are hard to see on LEGO's white-background product shots."""
    return any("WHITE" in _key(name or "") for name in (lego, bl))
