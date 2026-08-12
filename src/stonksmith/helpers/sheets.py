# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Google Sheets helpers shared by everything that writes to the dashboard."""

from pathlib import Path
from typing import Any

import gspread
import gspread.exceptions
from google.auth.exceptions import GoogleAuthError

from stonksmith.etc.permissions import restrict, restrict_dir

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


def _authorization_failure(e: BaseException, doing: str = "") -> str:
    """
    Say what to do about an authorization failure, by cause.

    Two causes look alike in the log and have different fixes, and conflating
    them is expensive in one direction: a stale token needs one file deleted,
    while a deleted OAuth client needs a new client ID from the Google console.
    Telling someone with an expired token to go and make a new client sends them
    to the console for nothing, so ``invalid_grant`` gets the cheap fix and only
    ``deleted_client`` gets the expensive one.

    Anything else -- a transport error, a clock skew -- gets the cheap fix first
    and the expensive one as the fallback, because that is the order worth trying
    them in and this function cannot tell which applies.
    :param e: The authorization error, quoted into the message
    :param doing: What was being attempted, if it narrows the report down
    :return: One actionable line
    :rtype: str
    """

    detail: str = str(object=e)
    where: str = f" while {doing}" if doing else ""
    opening: str = f"Google authorization failed{where} ({detail})."

    new_client: str = (
        "create a new OAuth client ID (Desktop app) with the Sheets and Drive "
        f"APIs enabled and save it as {GSPREAD_CONFIG_DIR}/credentials.json"
    )
    fresh_token: str = (
        f"delete {GSPREAD_CONFIG_DIR}/authorized_user.json and re-run to reauthorize"
    )

    if "deleted_client" in detail:
        return (
            f"{opening} The OAuth client itself is gone, so {new_client}, then "
            f"{fresh_token}."
        )

    if "invalid_grant" in detail:
        # The common one, and the one whose fix is cheapest: a refresh token
        # expires on its own -- after a week, for a client Google still lists as
        # in testing -- without anything happening to the client behind it.
        return (
            f"{opening} The cached token has expired or been revoked, which is "
            f"not the same as the client being gone: {fresh_token}. "
            f"{GSPREAD_CONFIG_DIR}/credentials.json stays as it is."
        )

    return (
        f"{opening} Try this first: {fresh_token}. If that does not help, "
        f"{new_client} and try again."
    )


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
        raise SheetsUnavailable(_authorization_failure(e=e)) from e

    _restrict_google_credentials()

    try:
        return client.open(spreadsheet)

    except gspread.exceptions.SpreadsheetNotFound as e:
        raise SheetsUnavailable(
            f"No spreadsheet named '{spreadsheet}' in this Google account. "
            "Create it, or share it with the account you authorized."
        ) from e

    except GoogleAuthError as e:
        # Credentials can also refresh lazily on the first API call, which is
        # the path an expired token actually takes: gspread.oauth() above hands
        # back a client without touching the network, and the refresh fails here.
        # So this is the branch that has to carry the fix, not the spare one.
        raise SheetsUnavailable(_authorization_failure(e=e)) from e

    except gspread.exceptions.APIError as e:
        raise SheetsUnavailable(
            f"Google rejected the request ({e}). Check that the Sheets API and "
            "the Drive API are both enabled for this project."
        ) from e


def _restrict_google_credentials() -> None:
    """
    Make gspread's stored Google credentials owner-readable only.

    These are another library's files, in a directory StonkSmith does not own,
    and gspread writes them at the process umask -- 0644 here, in a 0755
    directory with nothing above it. They are also the highest-value secret on
    the machine: ``authorized_user.json`` is a refresh token, renewable
    indefinitely, and gspread.oauth() asks for full ``spreadsheets`` and
    ``drive`` rather than the file-scoped variants, so it reaches the operator's
    entire Drive rather than the one spreadsheet this tool writes.

    Done here rather than documented as a step for the operator to run, because
    an instruction is not a mechanism. Only ever tightening, and best-effort, so
    the worst case is that it changes nothing.
    """

    config_dir: Path = Path(GSPREAD_CONFIG_DIR).expanduser()

    if not config_dir.is_dir():
        return

    restrict_dir(path=config_dir)

    for name in ("authorized_user.json", "credentials.json"):
        candidate: Path = config_dir / name
        if candidate.is_file():
            restrict(path=candidate)


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
            _authorization_failure(e=e, doing=f"looking for the tab '{worksheet_name}'")
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

    return require_worksheet(
        book=open_spreadsheet(spreadsheet=spreadsheet),
        worksheet_name=worksheet_name,
        spreadsheet=spreadsheet,
    )


def require_worksheet(book: Any, worksheet_name: str, spreadsheet: str) -> Any:
    """
    The tab, or an actionable refusal -- never a created one.

    Split out of open_worksheet so that a caller holding an open book can insist
    on several tabs without re-authorizing per tab, and without reaching for
    ensure_worksheet. The difference matters: ensure_worksheet creates what is
    missing, which is right for a sync and wrong for anything checking what a
    sync wrote, where a created tab would manufacture the thing being checked.
    :param book: An open spreadsheet
    :param worksheet_name: The tab that has to be there
    :param spreadsheet: The spreadsheet's name, for the message
    :return: The worksheet
    :rtype: Any
    :raises SheetsUnavailable: if the tab is missing or the lookup fails
    """

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


def tab_exists(book: Any, worksheet_name: str, spreadsheet: str) -> bool:
    """
    Whether a tab of that name is already in the book.

    A question rather than a lookup, for the one caller that needs to know a name
    is free before taking it: absence is the answer it wants and not a failure.
    Routed through _find_worksheet rather than asking gspread directly so that an
    APIError or an expired token still arrives as one actionable line -- a caller
    reading "is this tab there?" as False because the request was rejected would
    go on to create a tab beside one that already exists.
    :param book: An open spreadsheet
    :param worksheet_name: The tab to look for
    :param spreadsheet: The spreadsheet's name, for the message
    :return: True if the tab is there
    :rtype: bool
    :raises SheetsUnavailable: if the lookup itself fails
    """

    try:
        _find_worksheet(
            book=book, worksheet_name=worksheet_name, spreadsheet=spreadsheet
        )

    except gspread.exceptions.WorksheetNotFound:
        return False

    return True


def remove_tab(book: Any, worksheet: Any, worksheet_name: str) -> str:
    """
    Delete a tab, reporting rather than raising.

    The only deletion in StonkSmith, and it exists for one caller: the throwaway
    tab an ownership check makes for itself. It reports instead of raising
    because it runs in a teardown, where an exception would replace whatever the
    check had found with the news that a scratch tab is still there -- true, and
    less useful than the result it threw away.

    Callers pass the worksheet object they created, not a name to look up. A
    deletion that resolved its own target could be pointed at a tab somebody
    wanted; this one can only remove a handle the caller already had.
    :param book: The open spreadsheet
    :param worksheet: The worksheet to delete, as returned when it was created
    :param worksheet_name: Its name, for the message
    :return: An empty string on success, or why it could not be removed
    :rtype: str
    """

    try:
        book.del_worksheet(worksheet)

    except (gspread.exceptions.APIError, GoogleAuthError) as e:
        return (
            f"The tab '{worksheet_name}' could not be removed ({e}). It is a "
            "scratch tab and nothing reads it, so deleting it by hand is safe."
        )

    return ""


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
