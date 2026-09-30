"""Part weights and BrickLink color names from BrickLink's catalog download.

BrickLink's API is for sellers only, but any (free) member can download the
catalog at https://www.bricklink.com/catalogDownload.asp as Tab-Delimited
files. Two are used, from a folder (default ./bricklink/):

- Catalog Items -> Parts, with "Include Weight": BrickLink part number ->
  weight in grams (header has "Number" and "Weight (in Grams)"; unknown
  weights are "?").
- Part and Color Codes: LEGO element ID -> BrickLink part number and color
  (header "Item No", "Color", "Code").

Files are recognised by their header row, not their names. Re-download them
now and then to pick up new parts.
"""

import os
from dataclasses import dataclass

DEFAULT_DIR = "bricklink"


@dataclass(frozen=True)
class PartInfo:
    part_no: str  # BrickLink item number, e.g. "3004"
    color: str  # BrickLink color name
    weight: float | None  # grams per piece; None if BrickLink doesn't know it


def _rows(path: str):
    """Tab-separated rows (header first), tolerant of CRLF and stray bytes."""
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if line.strip():
                yield line.split("\t")


def _weight(text: str) -> float | None:
    try:
        weight = float(text)
    except ValueError:
        return None  # "?" = unknown
    return weight if weight > 0 else None


def load(folder: str = DEFAULT_DIR) -> dict[str, PartInfo]:
    """element ID -> PartInfo from the catalog files in `folder`; empty if
    the folder or either file is missing."""
    weights: dict[str, float | None] | None = None
    codes: dict[str, tuple[str, str]] | None = None
    if not os.path.isdir(folder):
        return {}
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        rows = _rows(path)
        header = [h.strip().lower() for h in next(rows, [])]
        if "number" in header and any(h.startswith("weight") for h in header):
            number = header.index("number")
            weight = next(i for i, h in enumerate(header) if h.startswith("weight"))
            weights = {r[number]: _weight(r[weight]) for r in rows if len(r) > max(number, weight)}
        elif {"item no", "color", "code"} <= set(header):
            item, color, code = (header.index(h) for h in ("item no", "color", "code"))
            codes = {}
            for r in rows:
                if len(r) > max(item, color, code):
                    codes.setdefault(r[code].strip(), (r[item], r[color]))
    if weights is None or codes is None:
        return {}
    return {element: PartInfo(part, color, weights.get(part))
            for element, (part, color) in codes.items()}
