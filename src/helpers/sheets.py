# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Google Sheets helpers shared by everything that writes to the dashboard."""

from typing import Any

import gspread
import gspread.exceptions
from google.auth.exceptions import GoogleAuthError

#: The spreadsheet StonkSmith writes into. It owns a named handful of tabs in
#: there; every other tab in the book is the user's and is never opened.
SPREADSHEET_NAME = "Investment Account Scrapes"

GSPREAD_CONFIG_DIR = "~/.config/gspread"


class SheetsUnavailable(RuntimeError):
    """
    The dashboard could not be opened.

    Carries a message the user can act on. Sheets sync is best-effort -- the
    scrape is already saved to the broker database by the time it runs -- so
    callers report this and carry on rather than failing the run.
    """


class SheetNotOwned(SheetsUnavailable):
    """
    The tab is reachable, and is not StonkSmith's to overwrite.

    A subclass rather than a sibling, deliberately. Every caller already catches
    SheetsUnavailable and carries on, and for the run this is the same outcome
    as Sheets being unreachable: the database has the data either way, so
    nothing is lost by declining to write. Subclassing gets that behaviour at
    every call site without editing any of them, while still being a type a
    test -- and a reader -- can tell apart from an authorization failure.
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


def open_spreadsheet(spreadsheet: str = SPREADSHEET_NAME) -> Any:
    """
    Authenticate once and return the whole spreadsheet.

    Split out of open_worksheet so that one sync can claim several tabs on a
    single authorization rather than one per tab. Every failure mode is
    translated into a SheetsUnavailable carrying the fix, so a Sheets problem
    reports as one actionable line instead of a traceback through gspread and
    google-auth.
    :param spreadsheet: The spreadsheet to open
    :return: A gspread spreadsheet
    :rtype: Any
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
        return client.open(spreadsheet)

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


def _find_worksheet(book: Any, worksheet_name: str, spreadsheet: str) -> Any:
    """
    Look one tab up, translating everything but its absence.

    Spreadsheet.worksheet() is not a dictionary lookup: it calls
    fetch_sheet_metadata() first, so it reaches the network and can fail every
    way a request can. Left unwrapped those came out as raw gspread and
    google-auth exceptions -- which is the traceback this module exists to
    replace with one actionable line, and which a caller distinguishing a Sheets
    problem from a real one would misfile.

    WorksheetNotFound is deliberately not handled here. It is the one outcome
    whose right answer differs by caller: open_worksheet reports it, and
    ensure_worksheet creates the tab.
    :param book: An open spreadsheet
    :param worksheet_name: The tab to look for
    :param spreadsheet: The spreadsheet's name, for the message
    :return: The worksheet
    :rtype: Any
    :raises gspread.exceptions.WorksheetNotFound: if there is no such tab
    :raises SheetsUnavailable: if the lookup itself fails
    """

    try:
        return book.worksheet(worksheet_name)

    except GoogleAuthError as e:
        raise SheetsUnavailable(
            f"Google authorization failed while looking for the tab "
            f"'{worksheet_name}' ({e})."
        ) from e

    except gspread.exceptions.APIError as e:
        raise SheetsUnavailable(
            f"Google rejected the request for the tabs in '{spreadsheet}' "
            f"({e}). Check that the Sheets API and the Drive API are both "
            "enabled for this project, and that the authorized account may "
            "read the spreadsheet."
        ) from e


def open_worksheet(worksheet_name: str, spreadsheet: str = SPREADSHEET_NAME) -> Any:
    """
    Authenticate once and return a worksheet handle.
    :param worksheet_name: The tab to open, e.g. "Accounts"
    :param spreadsheet: The spreadsheet to open it in
    :return: A gspread worksheet
    :raises SheetsUnavailable: if authorization or lookup fails
    """

    book: Any = open_spreadsheet(spreadsheet=spreadsheet)

    try:
        return _find_worksheet(
            book=book, worksheet_name=worksheet_name, spreadsheet=spreadsheet
        )

    except gspread.exceptions.WorksheetNotFound as e:
        raise SheetsUnavailable(
            f"Spreadsheet '{spreadsheet}' has no tab named '{worksheet_name}'. "
            "Add the tab, or rename an existing one to match."
        ) from e


def ensure_worksheet(
    worksheet_name: str,
    spreadsheet: str = SPREADSHEET_NAME,
    book: Any | None = None,
    rows: int = 1000,
    cols: int = 26,
) -> Any:
    """
    The tab, created if it is not there yet.

    open_worksheet refuses a missing tab, which was right while a broker naming
    a tab that did not exist was most likely a typo. Creating is only safe
    because of the ownership check the caller runs next: a tab StonkSmith
    creates is empty, so creation can never be the step that adopts something a
    human wrote. Without that check this would be the most dangerous function in
    the file.
    :param worksheet_name: The tab to open or create
    :param spreadsheet: The spreadsheet to look in
    :param book: An already-open spreadsheet, to save an authorization
    :param rows: Initial row count for a tab being created
    :param cols: Initial column count for a tab being created
    :return: A gspread worksheet
    :rtype: Any
    :raises SheetsUnavailable: if authorization or lookup fails
    """

    opened: Any = (
        book if book is not None else open_spreadsheet(spreadsheet=spreadsheet)
    )

    try:
        return _find_worksheet(
            book=opened, worksheet_name=worksheet_name, spreadsheet=spreadsheet
        )

    except gspread.exceptions.WorksheetNotFound:
        pass

    try:
        return opened.add_worksheet(title=worksheet_name, rows=rows, cols=cols)

    except gspread.exceptions.APIError as e:
        raise SheetsUnavailable(
            f"Could not create a tab named '{worksheet_name}' in "
            f"'{spreadsheet}' ({e}). Add it by hand, or check that the "
            "authorized account may edit the spreadsheet."
        ) from e


def fit(worksheet: Any, rows: int, cols: int) -> None:
    """
    Grow a tab's grid to hold a write. Never shrink it.

    clear() empties cells; it does not resize the grid, and an update addressing
    a row past the last one is rejected outright rather than expanding to meet
    it. A workspace that grew past the default thousand rows would otherwise
    start failing its sync with a grid-limits error that says nothing about row
    counts. Shrinking is left alone deliberately -- a tab the user widened is
    theirs to have widened, and narrowing it would delete cells to the right.
    :param worksheet: The tab about to be written
    :param rows: Rows the write needs
    :param cols: Columns the write needs
    :return: None
    """

    grow_rows: int = max(0, rows - int(getattr(worksheet, "row_count", 0) or 0))
    grow_cols: int = max(0, cols - int(getattr(worksheet, "col_count", 0) or 0))

    if grow_rows:
        worksheet.add_rows(grow_rows)

    if grow_cols:
        worksheet.add_cols(grow_cols)
