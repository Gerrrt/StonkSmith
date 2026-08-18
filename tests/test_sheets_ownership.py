"""Opening a book once, and making a tab that is not there.

The five broker tabs had to be created by hand, because a broker naming a tab
that did not exist was most likely a typo worth reporting. StonkSmith's own tabs
are a different case: their names are fixed, and a tab that does not exist cannot
hold anybody's work. So these get created -- and that is only safe because the
ownership check runs immediately afterwards.
"""

import unittest
from unittest.mock import MagicMock, patch

import gspread.exceptions
from google.auth.exceptions import RefreshError

from gspread_isolation import GspreadConfigMixin
from stonksmith.helpers.sheets import (
    SheetsUnavailable,
    ensure_worksheet,
    open_spreadsheet,
    open_worksheet,
)


class OpenSpreadsheetTests(GspreadConfigMixin, unittest.TestCase):
    def test_the_book_comes_back_whole(self) -> None:
        client = MagicMock()

        with patch("stonksmith.helpers.sheets.gspread.oauth", return_value=client):
            self.assertIs(open_spreadsheet(), client.open_by_key.return_value)

    def test_a_missing_book_still_names_it(self) -> None:
        client = MagicMock()
        client.open_by_key.side_effect = gspread.exceptions.SpreadsheetNotFound("nope")

        with (
            patch("stonksmith.helpers.sheets.gspread.oauth", return_value=client),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_spreadsheet(spreadsheet="Missing Book")

        self.assertIn("Missing Book", str(caught.exception))

    def test_open_worksheet_still_refuses_a_missing_tab(self) -> None:
        # Unchanged on purpose. Only StonkSmith's own tabs are created; anything
        # else asking for a tab by name is still asking for one that should be
        # there.
        client = MagicMock()
        client.open_by_key.return_value.worksheet.side_effect = (
            gspread.exceptions.WorksheetNotFound("nope")
        )

        with (
            patch("stonksmith.helpers.sheets.gspread.oauth", return_value=client),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_worksheet(worksheet_name="Accounts")

        self.assertIn("Accounts", str(caught.exception))


class WorksheetLookupFailureTests(GspreadConfigMixin, unittest.TestCase):
    """Looking a tab up reaches the network, so it can fail like anything else.

    Spreadsheet.worksheet() is not a dictionary lookup -- it fetches the book's
    metadata first. An APIError or an expired token coming out of there used to
    escape as a raw gspread or google-auth exception, which is the traceback
    this module exists to replace, and which sends a caller down its
    "something unexpected broke" path rather than its "Sheets is unavailable"
    one.
    """

    def _api_error(self) -> gspread.exceptions.APIError:
        return gspread.exceptions.APIError(
            MagicMock(
                status_code=429,
                json=lambda: {
                    "code": 429,
                    "message": "quota exceeded",
                    "status": "RESOURCE_EXHAUSTED",
                },
            )
        )

    def test_a_rejected_lookup_reports_as_sheets_unavailable(self) -> None:
        client = MagicMock()
        client.open_by_key.return_value.worksheet.side_effect = self._api_error()

        with (
            patch("stonksmith.helpers.sheets.gspread.oauth", return_value=client),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_worksheet(worksheet_name="Accounts")

        self.assertIn("Sheets API", str(caught.exception))

    def test_an_expired_token_during_lookup_says_so(self) -> None:
        client = MagicMock()
        client.open_by_key.return_value.worksheet.side_effect = RefreshError("expired")

        with (
            patch("stonksmith.helpers.sheets.gspread.oauth", return_value=client),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_worksheet(worksheet_name="Accounts")

        self.assertIn("Accounts", str(caught.exception))

    def test_ensure_worksheet_does_not_create_a_tab_over_a_failed_lookup(self) -> None:
        # The dangerous version of this bug: a lookup that failed for a reason
        # other than absence, treated as absence, makes a second tab beside one
        # that is already there.
        book = MagicMock()
        book.worksheet.side_effect = self._api_error()

        with self.assertRaises(SheetsUnavailable):
            ensure_worksheet(worksheet_name="Holdings", book=book)

        book.add_worksheet.assert_not_called()


class EnsureWorksheetTests(GspreadConfigMixin, unittest.TestCase):
    def test_an_existing_tab_is_returned_untouched(self) -> None:
        book = MagicMock()

        self.assertIs(
            ensure_worksheet(worksheet_name="Accounts", book=book),
            book.worksheet.return_value,
        )
        book.add_worksheet.assert_not_called()

    def test_a_missing_tab_is_created(self) -> None:
        book = MagicMock()
        book.worksheet.side_effect = gspread.exceptions.WorksheetNotFound("nope")

        self.assertIs(
            ensure_worksheet(worksheet_name="Holdings", book=book),
            book.add_worksheet.return_value,
        )
        book.add_worksheet.assert_called_once_with(title="Holdings", rows=1000, cols=26)

    def test_an_already_open_book_is_not_reauthorized(self) -> None:
        # Three tabs on one authorization rather than one each.
        book = MagicMock()

        with patch("stonksmith.helpers.sheets.gspread.oauth") as oauth:
            ensure_worksheet(worksheet_name="Dashboard", book=book)

        oauth.assert_not_called()

    def test_a_tab_that_cannot_be_created_says_so_in_one_line(self) -> None:
        book = MagicMock()
        book.worksheet.side_effect = gspread.exceptions.WorksheetNotFound("nope")
        book.add_worksheet.side_effect = gspread.exceptions.APIError(
            MagicMock(
                status_code=403,
                json=lambda: {
                    "error": {
                        "code": 403,
                        "message": "denied",
                        "status": "PERMISSION_DENIED",
                    }
                },
            )
        )

        with self.assertRaises(SheetsUnavailable) as caught:
            ensure_worksheet(worksheet_name="Dashboard", book=book)

        self.assertIn("Dashboard", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
