# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Google Sheets helpers shared by every broker's saver."""

from typing import Any

import gspread
import gspread.exceptions
from google.auth.exceptions import GoogleAuthError

#: The spreadsheet every broker writes into; each broker owns one worksheet tab.
SPREADSHEET_NAME = "Investment Account Scrapes"

GSPREAD_CONFIG_DIR = "~/.config/gspread"


class SheetsUnavailable(RuntimeError):
    """
    The dashboard could not be opened.

    Carries a message the user can act on. Sheets sync is best-effort -- the
    scrape is already saved to the broker database by the time it runs -- so
    callers report this and carry on rather than failing the run.
    """


def a1_range(first_col: str, last_col: str, first_row: int, row_count: int) -> str:
    """
    Build an A1 range that spans exactly ``row_count`` rows.
    :param first_col: Left-hand column letter, e.g. "B"
    :param last_col: Right-hand column letter, e.g. "D"
    :param first_row: 1-indexed row the data starts on
    :param row_count: Number of data rows being written
    :return: An A1 range such as "B3:D5"
    """

    last_row: int = first_row + row_count - 1
    return f"{first_col}{first_row}:{last_col}{last_row}"


def open_worksheet(worksheet_name: str, spreadsheet: str = SPREADSHEET_NAME) -> Any:
    """
    Authenticate once and return a worksheet handle.

    Every failure mode is translated into a SheetsUnavailable carrying the fix,
    so a Sheets problem reports as one actionable line instead of a traceback
    through gspread and google-auth.
    :param worksheet_name: The tab to open, e.g. "529 Plan"
    :param spreadsheet: The spreadsheet to open it in
    :return: A gspread worksheet
    :raises SheetsUnavailable: if authorization or lookup fails
    """

    try:
        client: Any = gspread.oauth()

    except GoogleAuthError as e:
        raise SheetsUnavailable(
            f"Google authorization failed ({e}). If this says 'deleted_client' "
            "or 'invalid_grant', the OAuth client behind the cached token no "
            "longer exists: create a new OAuth client ID (Desktop app) with the "
            f"Sheets and Drive APIs enabled, save it as {GSPREAD_CONFIG_DIR}/"
            f"credentials.json, delete {GSPREAD_CONFIG_DIR}/authorized_user.json, "
            "and re-run to reauthorize."
        ) from e

    try:
        book = client.open(spreadsheet)

    except gspread.exceptions.SpreadsheetNotFound as e:
        raise SheetsUnavailable(
            f"No spreadsheet named '{spreadsheet}' in this Google account. "
            "Create it, or share it with the account you authorized."
        ) from e

    except GoogleAuthError as e:
        # Credentials can also refresh lazily on the first API call.
        raise SheetsUnavailable(f"Google authorization failed ({e}).") from e

    except gspread.exceptions.APIError as e:
        raise SheetsUnavailable(
            f"Google rejected the request ({e}). Check that the Sheets API and "
            "the Drive API are both enabled for this project."
        ) from e

    try:
        return book.worksheet(worksheet_name)

    except gspread.exceptions.WorksheetNotFound as e:
        raise SheetsUnavailable(
            f"Spreadsheet '{spreadsheet}' has no tab named '{worksheet_name}'. "
            "Add the tab, or rename an existing one to match."
        ) from e
