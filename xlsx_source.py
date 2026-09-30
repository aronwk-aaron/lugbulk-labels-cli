"""Read-only access to a local .xlsx export of the order sheet.

Same pivot as the Google Sheets path (see pivot.py) — which already finds
columns by header name and tolerates the layout drift seen in exports.
The only export-specific quirk handled here is tab naming.

READ-ONLY: only ever reads the workbook, never writes to it.
"""

import sys

from openpyxl import load_workbook

import config
from pivot import build_records
from records import LabelRecord, SheetIssue


def _resolve_tab_name(tab: str, sheetnames: list[str]) -> str | None:
    """Exact match first; otherwise fall back to a whitespace/case-insensitive
    match — an .xlsx export of the sheet has been seen to drop spaces from
    tab names (e.g. "Order Here" -> "OrderHere")."""
    if tab in sheetnames:
        return tab
    normalized = tab.replace(" ", "").lower()
    for name in sheetnames:
        if name.replace(" ", "").lower() == normalized:
            return name
    return None


def _load_rows(path: str, tab: str) -> list[list]:
    try:
        wb = load_workbook(path, data_only=True, read_only=True)
    except FileNotFoundError:
        sys.exit(f"Source file not found: '{path}'")
    except (KeyError, OSError, ValueError) as e:
        sys.exit(f"Couldn't open '{path}' as an Excel workbook: {e}")

    try:
        resolved = _resolve_tab_name(tab, wb.sheetnames)
        if resolved is None:
            sys.exit(
                f"Tab '{tab}' not found in '{path}'. Sheets in this file: "
                f"{', '.join(wb.sheetnames)}"
            )
        return [list(row) for row in wb[resolved].iter_rows(values_only=True)]
    finally:
        wb.close()  # read-only workbooks keep the file handle open until closed


def validate_source(
    path: str, tab: str = config.SOURCE_TAB
) -> tuple[list[LabelRecord], list[SheetIssue]]:
    return build_records(_load_rows(path, tab))
