"""Read-only access to the 'Order Here' sheet: pivots the wide per-person
qty matrix into one label-record per (person, part) pair where qty > 0.

READ-ONLY: only ever calls spreadsheets().values().get — never writes,
updates, or appends to the sheet.
"""

import sys
from dataclasses import dataclass

from google.auth.exceptions import GoogleAuthError
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


@dataclass
class LabelRecord:
    person: str
    element_id: str
    description: str
    color: str
    qty: str
    image_url: str


@dataclass
class SheetIssue:
    """A problem noticed while walking the sheet, surfaced by --validate
    (and folded into a warning count on a normal run)."""
    row: int  # 1-indexed sheet row, for easy cross-reference while eyeballing the sheet
    kind: str  # "duplicate" | "bad_qty" | "missing_description" | "missing_color"
    detail: str


def _get_service(service_account_file: str):
    creds = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)


def _fetch_rows(
    sheet_id: str, tab: str, service_account_file: str
) -> list[list[str]]:
    try:
        service = _get_service(service_account_file)
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=f"'{tab}'!A1:CT")
            .execute()
        )
    except FileNotFoundError:
        sys.exit(
            f"Service account key not found at '{service_account_file}' "
            "(see README.md for setup)."
        )
    except GoogleAuthError as e:
        sys.exit(f"Google auth failed: {e}")
    except HttpError as e:
        sys.exit(
            f"Sheets API request failed ({e.resp.status}): check SHEET_ID and that the "
            f"sheet is shared with the service account's email.\n{e}"
        )
    except OSError as e:
        sys.exit(f"Network error reaching Google Sheets API: {e}")

    return result.get("values", [])


def _build_records(
    rows: list[list[str]],
) -> tuple[list[LabelRecord], list[SheetIssue]]:
    """Pivot the wide per-person qty matrix into label records, collecting
    SheetIssues for anything that looked like a data-entry mistake along the way."""
    if len(rows) <= config.DATA_START_ROW:
        return [], []

    header = rows[config.HEADER_ROW]

    def cell(row, idx, default=""):
        return row[idx] if idx < len(row) and row[idx] != "" else default

    records: list[LabelRecord] = []
    issues: list[SheetIssue] = []
    seen: set[tuple[str, str]] = set()  # (person, element_id) -> duplicate check

    for offset, row in enumerate(rows[config.DATA_START_ROW :]):
        sheet_row = config.DATA_START_ROW + offset + 1  # 1-indexed, matches Sheets UI
        if not row:
            continue
        element_id = cell(row, config.COL_ELEMENT_ID)
        if not element_id:
            continue  # blank/footer row

        description = cell(row, config.COL_DESCRIPTION)
        if not description:
            issues.append(SheetIssue(sheet_row, "missing_description",
                                      f"Element {element_id} has no description"))

        color = config.COLOR_OVERRIDES.get(element_id, cell(row, config.COL_COLOR))
        if not color:
            issues.append(SheetIssue(sheet_row, "missing_color",
                                      f"Element {element_id} has no color"))

        image_url = config.IMAGE_URL_TEMPLATE.format(element_id=element_id)

        for qty_col in range(
            config.FIRST_PERSON_COL, config.LAST_PERSON_COL + 1, config.PERSON_COL_STRIDE
        ):
            person = cell(header, qty_col)
            if not person:
                continue
            qty = cell(row, qty_col).strip()
            if not qty:
                continue  # blank cell, not a mistake
            try:
                # Sheets displays large numbers with thousands separators
                # (e.g. "2,000"); strip them before parsing.
                qty_num = float(qty.replace(",", ""))
            except ValueError:
                issues.append(SheetIssue(
                    sheet_row, "bad_qty",
                    f"{person}'s qty for element {element_id} is non-numeric: '{qty}'",
                ))
                continue
            if qty_num <= 0:
                continue

            key = (person, element_id)
            if key in seen:
                issues.append(SheetIssue(
                    sheet_row, "duplicate",
                    f"{person} has more than one qty entry for element {element_id}",
                ))
            seen.add(key)

            records.append(
                LabelRecord(
                    person=person,
                    element_id=element_id,
                    description=description,
                    color=color,
                    qty=qty,
                    image_url=image_url,
                )
            )

    return records, issues


def get_label_records(
    sheet_id: str = config.SHEET_ID,
    tab: str = config.SOURCE_TAB,
    service_account_file: str = config.SERVICE_ACCOUNT_FILE,
) -> list[LabelRecord]:
    rows = _fetch_rows(sheet_id, tab, service_account_file)
    records, _issues = _build_records(rows)
    return records


def validate_sheet(
    sheet_id: str = config.SHEET_ID,
    tab: str = config.SOURCE_TAB,
    service_account_file: str = config.SERVICE_ACCOUNT_FILE,
) -> tuple[list[LabelRecord], list[SheetIssue]]:
    """Like get_label_records, but also returns the SheetIssues found along
    the way — for --validate / --manifest, where you want to see problems
    rather than have them silently skipped."""
    rows = _fetch_rows(sheet_id, tab, service_account_file)
    return _build_records(rows)
