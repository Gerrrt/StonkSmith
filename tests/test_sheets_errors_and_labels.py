"""Sheets failures must report as one actionable line, and accounts need names.

Both regressions came from a real run: a deleted Google OAuth client produced a
40-line traceback through gspread and google-auth, and every saved account row
was named "Balance:" -- the page's label, not an account.
"""

import unittest
from unittest.mock import MagicMock, patch

import gspread.exceptions
from google.auth.exceptions import RefreshError

from helpers.schwab529plan import account_label, strip_label
from helpers.sheets import SheetsUnavailable, open_worksheet


class OpenWorksheetErrorTests(unittest.TestCase):
    def test_deleted_oauth_client_reports_how_to_fix_it(self) -> None:
        # The exact error from the field.
        failure = RefreshError(
            "deleted_client: The OAuth client was deleted.",
            {"error": "deleted_client"},
        )

        with (
            patch("helpers.sheets.gspread.oauth", side_effect=failure),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_worksheet(worksheet_name="529 Plan")

        message = str(caught.exception)
        self.assertIn("credentials.json", message)
        self.assertIn("authorized_user.json", message)

    def test_missing_spreadsheet_names_the_spreadsheet(self) -> None:
        client = MagicMock()
        client.open.side_effect = gspread.exceptions.SpreadsheetNotFound("nope")

        with (
            patch("helpers.sheets.gspread.oauth", return_value=client),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_worksheet(worksheet_name="529 Plan", spreadsheet="Missing Book")

        self.assertIn("Missing Book", str(caught.exception))

    def test_missing_worksheet_names_the_tab(self) -> None:
        client = MagicMock()
        client.open.return_value.worksheet.side_effect = (
            gspread.exceptions.WorksheetNotFound("nope")
        )

        with (
            patch("helpers.sheets.gspread.oauth", return_value=client),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_worksheet(worksheet_name="529 Plan")

        self.assertIn("529 Plan", str(caught.exception))

    def test_success_returns_the_worksheet(self) -> None:
        client = MagicMock()
        sentinel = client.open.return_value.worksheet.return_value

        with patch("helpers.sheets.gspread.oauth", return_value=client):
            self.assertIs(open_worksheet(worksheet_name="529 Plan"), sentinel)


class AccountLabelTests(unittest.TestCase):
    def test_bare_balance_label_loses_its_colon(self) -> None:
        # What actually landed in the database before this fix.
        self.assertEqual(
            account_label(beneficiaries=[], balance={"Title": "Balance:"}, index=0),
            "Balance",
        )

    def test_beneficiary_name_wins_over_the_balance_label(self) -> None:
        self.assertEqual(
            account_label(
                beneficiaries=[{"Title": "Beneficiary:", "Name": "Jane Doe"}],
                balance={"Title": "Balance:"},
                index=0,
            ),
            "Jane Doe",
        )

    def test_falls_back_to_the_account_number(self) -> None:
        self.assertEqual(
            account_label(
                beneficiaries=[{"Name": None, "Account": "1234"}],
                balance={"Title": "Balance:"},
                index=0,
            ),
            "1234",
        )

    def test_index_past_the_beneficiaries_uses_the_balance_label(self) -> None:
        self.assertEqual(
            account_label(
                beneficiaries=[{"Name": "Jane Doe"}],
                balance={"Title": "Balance:"},
                index=1,
            ),
            "Balance",
        )

    def test_nothing_usable_still_yields_a_name(self) -> None:
        self.assertEqual(
            account_label(beneficiaries=[], balance={"Title": None}, index=0),
            "Unknown account",
        )

    def test_strip_label_collapses_whitespace(self) -> None:
        self.assertEqual(strip_label(text="  Total   Balance :  "), "Total Balance")


class ModuleReportsSheetsFailureCleanlyTests(unittest.TestCase):
    # refresh() rather than sync(), deliberately. The "sync skipped" wording and
    # the decision not to fail the run both live inside sync() now, so patching
    # sync() would remove the behaviour this is here to check. Faulting the read
    # underneath it exercises the real path all five modules share.
    @patch("etc.portfolio_sheet.refresh")
    @patch("modules.schwab529plan_module.Parser")
    def test_sheets_failure_does_not_abort_the_run(
        self, mock_parser: MagicMock, mock_refresh: MagicMock
    ) -> None:
        from modules.schwab529plan_module import Schwab529Module

        parsed = mock_parser.return_value
        parsed.beneficiary_data.return_value = []
        parsed.balance_data.return_value = [{"Title": "Balance:", "Amount": "$10"}]
        parsed.investment_data.return_value = []
        parsed.transaction_data.return_value = []

        mock_refresh.side_effect = SheetsUnavailable("Google authorization failed")

        saved: list[tuple] = []

        class _DB:
            def get_credentials(self, filter_term=None):
                return []

            def save_account_data(self, account_name, balance, timestamp):
                saved.append((account_name, balance))

            def shutdown_db(self):
                pass

        context = MagicMock()
        context.db = _DB()

        connection = MagicMock()
        connection.session.get.return_value = MagicMock(
            ok=True, url="https://x/viewAggrOverview.cs", text="<html></html>"
        )

        result = Schwab529Module().on_login(context, connection)

        # The scrape still reached the database...
        self.assertEqual(saved, [("Balance", "$10")])
        # ...and the Sheets problem was reported, not raised.
        reported = " ".join(str(c) for c in context.log.fail.call_args_list)
        self.assertIn("Google Sheets sync skipped", reported)
        context.log.success.assert_called()

        # Sheets is best-effort: the balances are saved, so the run succeeded
        # and exits 0. But it must stop claiming it finished the job.
        self.assertIsNot(result, False, "a Sheets failure must not fail the run")
        succeeded = " ".join(str(c) for c in context.log.success.call_args_list)
        self.assertNotIn("sync complete", succeeded)
        self.assertIn("dashboard was not updated", succeeded)


if __name__ == "__main__":
    unittest.main()
