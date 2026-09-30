"""Read-only access to the 'Order Here' sheet on Google Sheets.

READ-ONLY: only ever calls spreadsheets().values().get — never writes,
updates, or appends to the sheet.
"""

import sys

from google.auth.exceptions import GoogleAuthError
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config
from pivot import build_records
from records import LabelRecord, SheetIssue

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def _get_service(service_account_file: str):
    creds = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)


def _fetch_rows(sheet_id: str, tab: str, service_account_file: str) -> list[list[str]]:
    try:
        service = _get_service(service_account_file)
        result = (
            service.spreadsheets()
            .values()
            # ZZ (702 columns): the roster grows every year, and a fixed
            # narrower cutoff would silently drop the newest people.
            .get(spreadsheetId=sheet_id, range=f"'{tab}'!A1:ZZ")
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
            f"Sheets API request failed ({e.resp.status}): check SHEET_ID, that the tab is "
            f"named '{tab}', and that the sheet is shared with the service account's email.\n{e}"
        )
    except OSError as e:
        sys.exit(f"Network error reaching Google Sheets API: {e}")

    return result.get("values", [])


def validate_sheet(
    sheet_id: str | None = None,
    tab: str = config.SOURCE_TAB,
    service_account_file: str = config.SERVICE_ACCOUNT_FILE,
) -> tuple[list[LabelRecord], list[SheetIssue]]:
    """Label records plus any SheetIssues noticed along the way."""
    rows = _fetch_rows(sheet_id or config.SHEET_ID, tab, service_account_file)
    return build_records(rows)
