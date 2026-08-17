"""Read-only access to the 'Order Here' sheet: pivots the wide per-person
qty matrix into one label-record per (person, part) pair where qty > 0.

READ-ONLY: only ever calls spreadsheets().values().get — never writes,
updates, or appends to the sheet.
"""

from dataclasses import dataclass

from google.oauth2 import service_account
from googleapiclient.discovery import build

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


def _get_service(service_account_file: str):
    creds = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)


def get_label_records(
    sheet_id: str = config.SHEET_ID,
    tab: str = config.SOURCE_TAB,
    service_account_file: str = config.SERVICE_ACCOUNT_FILE,
) -> list[LabelRecord]:
    service = _get_service(service_account_file)
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=f"'{tab}'!A1:CT")
        .execute()
    )
    rows = result.get("values", [])
    if len(rows) <= config.DATA_START_ROW:
        return []

    header = rows[config.HEADER_ROW]

    def cell(row, idx, default=""):
        return row[idx] if idx < len(row) and row[idx] != "" else default

    records: list[LabelRecord] = []
    for row in rows[config.DATA_START_ROW :]:
        if not row:
            continue
        element_id = cell(row, config.COL_ELEMENT_ID)
        if not element_id:
            continue  # blank/footer row

        description = cell(row, config.COL_DESCRIPTION)
        color = config.COLOR_OVERRIDES.get(element_id, cell(row, config.COL_COLOR))
        image_url = config.IMAGE_URL_TEMPLATE.format(element_id=element_id)

        for qty_col in range(
            config.FIRST_PERSON_COL, config.LAST_PERSON_COL + 1, config.PERSON_COL_STRIDE
        ):
            person = cell(header, qty_col)
            if not person:
                continue
            qty = cell(row, qty_col).strip()
            try:
                qty_num = float(qty)
            except ValueError:
                continue  # blank or non-numeric qty cell
            if qty_num <= 0:
                continue

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

    return records
