"""Pivot the wide "Order Here" matrix (one qty column per person) into one
LabelRecord per (person, part) with qty > 0.

Shared by the Google Sheets and .xlsx sources — both hand over the tab as
a list of rows of raw cell values (strings from the Sheets API; strings,
numbers or None from openpyxl). Two sheet layouts are handled:

- "qty marker" layout (the ArkLUG sheet): person names on the header row,
  and the row below it marks each person's qty column with "qty" (paired
  with a "$$" cost column).
- "name/cost pair" layout (seen in 2026's master sheet and its exports):
  each person is a header cell holding their name followed by a header
  cell holding their running cost total (a number).

Front-matter columns are found by header text, falling back to fixed
positions only if a header is missing.
"""

import re

import config
from records import (
    LabelRecord, SheetIssue, is_valid_element_id, parse_weight, resolve_colors,
)


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _cell(row: list, idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return _text(row[idx])


_NUMBER = re.compile(r"^[$€£]?\s*-?[\d,]*\.?\d+$")


def _is_number(value) -> bool:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    return bool(_NUMBER.match(_text(value)))


def parse_qty(qty: str) -> float:
    """Parse a qty cell ("150", "2,000", "25.0"). Raises ValueError."""
    return float(qty.replace(",", ""))


def format_qty(qty_num: float) -> str:
    return str(int(qty_num)) if qty_num.is_integer() else str(qty_num)


def _find_col(header: list, candidates: tuple[str, ...], data_rows: list[list] = ()) -> int | None:
    """First header matching a candidate (in candidate priority order). If
    several match, prefer one whose column actually has data — an export
    has been seen with a blank "BL Color" next to a populated "LEGO Color"."""
    lower = [_text(h).lower() for h in header]
    matches = [lower.index(name.lower()) for name in candidates if name.lower() in lower]
    for col in matches:
        if any(_cell(row, col) for row in data_rows[:50]):
            return col
    return matches[0] if matches else None


def _find_header_row(rows: list[list]) -> int | None:
    """config.HEADER_ROW fits the live sheet; exports have been seen with
    extra rows above the real header (e.g. a totals row)."""
    for row_idx in dict.fromkeys([config.HEADER_ROW, *range(min(len(rows), 10))]):
        if row_idx < len(rows) and _find_col(rows[row_idx], config.ELEMENT_ID_HEADERS) is not None:
            return row_idx
    return None


def _qty_marker_columns(header: list, subheader: list) -> list[tuple[int, str]]:
    return [
        (col, _cell(header, col))
        for col, marker in enumerate(subheader)
        if _text(marker).lower() == config.QTY_MARKER and _cell(header, col)
    ]


def _name_cost_pair_columns(header: list, scan_start: int) -> list[tuple[int, str]]:
    """A contiguous run of (name, cost) header pairs. Single metadata
    headers ("BL Price", "Nominated for", ...) aren't followed by a number
    so they're skipped; stop at the first break in the run — exports have
    unrelated debris further right."""
    def is_pair(col: int) -> bool:
        if col + 1 >= len(header):
            return False
        name = _text(header[col])
        return bool(name) and not _is_number(name) and _is_number(header[col + 1])

    col = scan_start
    while col < len(header) and not is_pair(col):
        col += 1
    people = []
    while col < len(header) and is_pair(col):
        people.append((col, _text(header[col])))
        col += 2
    return people


def build_records(rows: list[list]) -> tuple[list[LabelRecord], list[SheetIssue]]:
    if not rows:
        return [], []

    header_row = _find_header_row(rows)
    fixed_layout = header_row is None
    if fixed_layout:
        header_row = config.HEADER_ROW
    if header_row >= len(rows):
        return [], []
    header = rows[header_row]
    subheader = rows[header_row + 1] if header_row + 1 < len(rows) else []

    people = _qty_marker_columns(header, subheader)
    data_start = header_row + 2
    data_rows = rows[data_start:]

    if fixed_layout:
        col_id, col_desc = config.COL_ELEMENT_ID, config.COL_DESCRIPTION
        col_lego, col_bl, col_weight = None, config.COL_COLOR, None
    else:
        col_id = _find_col(header, config.ELEMENT_ID_HEADERS)
        col_desc = _find_col(header, config.DESCRIPTION_HEADERS, data_rows)
        col_lego = _find_col(header, config.LEGO_COLOR_HEADERS, data_rows)
        col_bl = _find_col(header, config.BL_COLOR_HEADERS, data_rows)
        col_weight = _find_col(header, config.WEIGHT_HEADERS, data_rows)
        if col_desc is None:
            col_desc = config.COL_DESCRIPTION

    if not people:
        front = [c for c in (col_id, col_desc, col_lego, col_bl, col_weight) if c is not None]
        people = _name_cost_pair_columns(header, max(front) + 1)

    records: list[LabelRecord] = []
    issues: list[SheetIssue] = []
    seen: set[tuple[str, str]] = set()

    for offset, row in enumerate(data_rows):
        sheet_row = data_start + offset + 1  # 1-indexed, matches the Sheets UI
        element_id = _cell(row, col_id)
        if not element_id:
            continue  # blank/footer row
        if not is_valid_element_id(element_id):
            if any(_cell(row, col) for col, _ in people):
                issues.append(SheetIssue(sheet_row, "bad_element_id",
                                          f"'{element_id}' isn't a LEGO element ID; row skipped"))
            continue

        description = _cell(row, col_desc)
        if not description:
            issues.append(SheetIssue(sheet_row, "missing_description",
                                      f"Element {element_id} has no description"))

        wanted = []
        for qty_col, person in people:
            qty = _cell(row, qty_col)
            if not qty:
                continue  # blank cell, not a mistake
            try:
                qty_num = parse_qty(qty)
            except ValueError:
                issues.append(SheetIssue(
                    sheet_row, "bad_qty",
                    f"{person}'s qty for element {element_id} is non-numeric: '{qty}'",
                ))
                continue
            if qty_num > 0:
                wanted.append((person, format_qty(qty_num)))
        if not wanted:
            continue  # nobody ordered it; don't nag about its colors

        lego, bl = resolve_colors(element_id, _cell(row, col_lego), _cell(row, col_bl),
                                  sheet_row, issues)
        weight = parse_weight(_cell(row, col_weight), element_id, sheet_row, issues)
        image_url = config.IMAGE_URL_TEMPLATE.format(element_id=element_id)

        for person, qty in wanted:
            key = (person, element_id)
            if key in seen:
                issues.append(SheetIssue(
                    sheet_row, "duplicate",
                    f"{person} has more than one qty entry for element {element_id}",
                ))
            seen.add(key)
            records.append(LabelRecord(
                person=person, element_id=element_id, description=description,
                lego_color=lego, bl_color=bl, qty=qty, image_url=image_url, weight=weight,
            ))

    return records, issues
