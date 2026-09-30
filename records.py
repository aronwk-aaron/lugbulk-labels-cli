"""Record types shared by both sources (Google Sheet and .xlsx), plus the
post-processing both apply: color override/lookup and element ID checks."""

import re
from dataclasses import dataclass, field

import colors
import config


@dataclass
class LabelRecord:
    person: str
    element_id: str
    description: str
    lego_color: str
    bl_color: str
    qty: str
    image_url: str
    weight: float | None = None  # grams per piece, from the sheet's Weight column if any
    # Filled in by ordering.order_records: "part_seq of part_total".
    part_seq: int = field(default=0, compare=False)
    part_total: int = field(default=0, compare=False)


@dataclass
class SheetIssue:
    """A problem noticed while walking the sheet, surfaced by --validate
    (and folded into a warning count on a normal run)."""
    row: int  # 1-indexed sheet row, for easy cross-reference while eyeballing the sheet
    # "duplicate" | "bad_qty" | "bad_element_id" | "missing_description" |
    # "missing_color" | "unmapped_color" | "bad_weight"
    kind: str
    detail: str
    element_id: str = ""


# LEGO element IDs are all digits. Anything else is a typo or a stray
# footer/notes row — and since the ID also becomes a filename in the image
# cache and part of the image URL, it must never contain path characters.
_ELEMENT_ID = re.compile(r"^\d{4,8}$")


def is_valid_element_id(element_id: str) -> bool:
    return bool(_ELEMENT_ID.match(element_id))


# What sheets put in a color cell when they don't know it; treated as blank.
PLACEHOLDER_COLORS = {"unknown", "n/a", "na", "?", "-", "tbd", "none"}


def resolve_colors(element_id: str, lego: str, bl: str, sheet_row: int,
                   issues: list[SheetIssue]) -> tuple[str, str]:
    """Apply per-event overrides, then fill whichever of LEGO/BrickLink
    color the sheet lacks from the colors table."""
    lego = "" if lego.strip().lower() in PLACEHOLDER_COLORS else lego
    bl = "" if bl.strip().lower() in PLACEHOLDER_COLORS else bl
    bl = config.COLOR_OVERRIDES.get(element_id, bl)
    lego = config.LEGO_COLOR_OVERRIDES.get(element_id, lego)
    if not lego and not bl:
        issues.append(SheetIssue(sheet_row, "missing_color", f"Element {element_id} has no color",
                                 element_id))
        return "", ""
    lego, bl, mapped = colors.resolve(lego, bl)
    if not mapped:
        known = lego or bl
        issues.append(SheetIssue(
            sheet_row, "unmapped_color",
            f"Element {element_id}: don't know the "
            f"{'BrickLink' if lego else 'LEGO'} name for '{known}' — add it to "
            f"colors.py or {'COLOR_OVERRIDES' if lego else 'LEGO_COLOR_OVERRIDES'}",
        ))
    return lego, bl


def parse_weight(raw, element_id: str, sheet_row: int,
                 issues: list[SheetIssue]) -> float | None:
    text = str(raw or "").strip().lower().removesuffix("g").strip()
    if not text:
        return None
    try:
        weight = float(text.replace(",", ""))
    except ValueError:
        issues.append(SheetIssue(sheet_row, "bad_weight",
                                  f"Element {element_id} has a non-numeric weight: '{raw}'"))
        return None
    return weight if weight > 0 else None
