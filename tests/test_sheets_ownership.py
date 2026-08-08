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

from helpers.sheets import (
    SheetsUnavailable,
    ensure_worksheet,
    open_spreadsheet,
    open_worksheet,
)


class OpenSpreadsheetTests(unittest.TestCase):
    def test_the_book_comes_back_whole(self) -> None:
        client = MagicMock()

        with patch("helpers.sheets.gspread.oauth", return_value=client):
            self.assertIs(open_spreadsheet(), client.open.return_value)

    def test_a_missing_book_still_names_it(self) -> None:
        client = MagicMock()
        client.open.side_effect = gspread.exceptions.SpreadsheetNotFound("nope")

        with (
            patch("helpers.sheets.gspread.oauth", return_value=client),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_spreadsheet(spreadsheet="Missing Book")

        self.assertIn("Missing Book", str(caught.exception))

    def test_open_worksheet_still_refuses_a_missing_tab(self) -> None:
        # Unchanged on purpose. Only StonkSmith's own tabs are created; anything
        # else asking for a tab by name is still asking for one that should be
        # there.
        client = MagicMock()
        client.open.return_value.worksheet.side_effect = (
            gspread.exceptions.WorksheetNotFound("nope")
        )

        with (
            patch("helpers.sheets.gspread.oauth", return_value=client),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_worksheet(worksheet_name="Accounts")

        self.assertIn("Accounts", str(caught.exception))


class EnsureWorksheetTests(unittest.TestCase):
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

        with patch("helpers.sheets.gspread.oauth") as oauth:
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
