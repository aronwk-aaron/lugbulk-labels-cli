"""Part sizing, label ordering, and per-part summaries.

Labels come out grouped by part: parts ordered by (estimated) weight,
heaviest first by default, and within a part by quantity, smallest first.
Each label is numbered within its part ("3 of 10") so a sorter can tell at
a glance when a part's pile is complete.

Weight is taken, in priority order, from WEIGHT_OVERRIDES in
config_local.py, a "Weight" column on the sheet (grams per piece), the
BrickLink catalog (see bricklink.py), or an estimate parsed from the part
description's stud dimensions ("PLATE 4X8",
"BRICK 1X2X5", "BRICK 1X1X1 2/3"). Parts none of those cover (plants,
animals, minifig parts...) sort after everything else, in sheet order, and
are listed as "size unknown" in the parts report so they can be given an
override.
"""

import re
from collections import OrderedDict
from dataclasses import dataclass

# Rough mass of one 1x1x1 brick-volume of ABS, in grams. Only used to put
# description-derived sizes on the same scale as real per-piece weights.
GRAMS_PER_BRICK_UNIT = 0.43

PART_ORDERS = ("heaviest", "lightest", "sheet")

_DIMS = re.compile(
    r"(\d+)\s*X\s*(\d+)"  # footprint, in studs
    r"(?:\s*X\s*(\d+)(?:\s+(\d+)/(\d+)|/(\d+)(°)?)?)?"  # optional height, in bricks
)


def _height_in_bricks(match: re.Match, description: str) -> float:
    whole, frac_num, frac_den, slash_den, degree = match.group(3, 4, 5, 6, 7)
    if whole is not None:
        height = float(whole)
        if frac_num:  # "1X1X1 2/3"
            height += int(frac_num) / int(frac_den)
        elif slash_den and not degree and slash_den == "3":  # "2X2X2/3"
            height = int(whole) / 3
        # otherwise "1X2X3/73°": 3 bricks tall, 73° slope
        return height
    # No explicit height: plates and tiles are a third of a brick tall.
    if re.search(r"\b(BRICK|ROOF|DUPLO)\b", description):
        return 1.0
    if re.search(r"\b(PLATE|TILE|PLADE)\b", description):
        return 1 / 3
    return 1.0


def estimate_weight(description: str) -> float | None:
    """Grams per piece estimated from the description's stud dimensions,
    or None if it has none."""
    desc = (description or "").upper()
    match = _DIMS.search(desc)
    if not match:
        return None
    volume = int(match.group(1)) * int(match.group(2)) * _height_in_bricks(match, desc)
    if "DUPLO" in desc:
        volume *= 8  # twice the size in every dimension
    return volume * GRAMS_PER_BRICK_UNIT


@dataclass
class PartSummary:
    element_id: str
    description: str
    lego_color: str
    bl_color: str
    lots: int  # number of people (labels) ordering this part
    pieces: float
    weight: float | None  # grams per piece; None if unknown
    weight_source: str  # "override" | "sheet" | "bricklink" | "estimate" | ""
    image_url: str = ""  # the part's photo, for reports that show it


def part_weight(record, overrides: dict[str, float],
                bricklink: dict[str, float] | None = None) -> tuple[float | None, str]:
    if record.element_id in overrides:
        return float(overrides[record.element_id]), "override"
    if record.weight is not None:
        return record.weight, "sheet"
    if bricklink and bricklink.get(record.element_id) is not None:
        return bricklink[record.element_id], "bricklink"
    estimate = estimate_weight(record.description)
    return (estimate, "estimate") if estimate is not None else (None, "")


def _qty(record) -> float:
    return float(record.qty.replace(",", ""))


def summarize_parts(records, overrides: dict[str, float] | None = None,
                    part_order: str = "heaviest",
                    bricklink: dict[str, float] | None = None) -> list[PartSummary]:
    """One PartSummary per distinct element, in label order. `bricklink`
    maps element ID -> catalog weight in grams."""
    overrides = overrides or {}
    parts: "OrderedDict[str, PartSummary]" = OrderedDict()
    for r in records:
        part = parts.get(r.element_id)
        if part is None:
            weight, source = part_weight(r, overrides, bricklink)
            part = parts[r.element_id] = PartSummary(
                r.element_id, r.description, r.lego_color, r.bl_color, 0, 0.0, weight, source,
                r.image_url)
        part.lots += 1
        part.pieces += _qty(r)

    summaries = list(parts.values())  # sheet order
    if part_order == "sheet":
        return summaries
    sign = -1 if part_order == "heaviest" else 1
    # Stable sort: unknown-weight parts keep sheet order after the rest.
    return sorted(summaries, key=lambda p: (p.weight is None, sign * (p.weight or 0)))


def order_records(records, overrides: dict[str, float] | None = None,
                  part_order: str = "heaviest", person_key=None,
                  bricklink: dict[str, float] | None = None):
    """Return records grouped by part in `part_order`, smallest qty first
    within each part, with part_seq/part_total filled in."""
    by_part: dict[str, list] = {}
    for r in records:
        by_part.setdefault(r.element_id, []).append(r)

    person_key = person_key or (lambda p: p.lower())
    ordered = []
    for part in summarize_parts(records, overrides, part_order, bricklink):
        group = sorted(by_part[part.element_id], key=lambda r: (_qty(r), person_key(r.person)))
        for i, r in enumerate(group, start=1):
            r.part_seq, r.part_total = i, len(group)
        ordered.extend(group)
    return ordered
