"""Sheets failures must report as one actionable line, and accounts need names.

Both regressions came from a real run: a deleted Google OAuth client produced a
40-line traceback through gspread and google-auth, and every saved account row
was named "Balance:" -- the page's label, not an account.
"""

import unittest
from unittest.mock import MagicMock, patch

import gspread.exceptions
from google.auth.exceptions import RefreshError

from gspread_isolation import GspreadConfigMixin
from stonksmith.helpers.schwab529plan import account_label, strip_label
from stonksmith.helpers.sheets import SheetsUnavailable, open_worksheet


class OpenWorksheetErrorTests(GspreadConfigMixin, unittest.TestCase):
    def test_deleted_oauth_client_reports_how_to_fix_it(self) -> None:
        # The exact error from the field.
        failure = RefreshError(
            "deleted_client: The OAuth client was deleted.",
            {"error": "deleted_client"},
        )

        with (
            patch("stonksmith.helpers.sheets.gspread.oauth", side_effect=failure),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_worksheet(worksheet_name="529 Plan")

        message = str(caught.exception)
        self.assertIn("credentials.json", message)
        self.assertIn("authorized_user.json", message)

    def test_an_expired_token_is_not_told_to_replace_the_client(self) -> None:
        # The exact error from the field, 2026-08-10. It is not the same failure
        # as the one above and it does not have the same fix: the token expired
        # on its own and the OAuth client behind it is untouched.
        failure = RefreshError(
            "invalid_grant: Token has been expired or revoked.",
            {"error": "invalid_grant"},
        )

        with (
            patch("stonksmith.helpers.sheets.gspread.oauth", side_effect=failure),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_worksheet(worksheet_name="529 Plan")

        message = str(caught.exception)

        # The whole fix, and the only file that has to go.
        self.assertIn("authorized_user.json", message)

        # And not the expensive advice: a trip to the Google console to make a
        # new client ID does nothing for a token that merely aged out. This is
        # the assertion that would have failed before the split.
        self.assertNotIn("create a new OAuth client", message)

    def test_a_lazy_refresh_failure_still_says_what_to_do(self) -> None:
        # gspread.oauth() reads the cached token off disk without touching the
        # network, so an expired one gets past it and fails on the first real
        # call instead. That is the branch a returning runner actually hits, and
        # it used to report the failure with no fix attached at all.
        client = MagicMock()
        client.open_by_key.side_effect = RefreshError(
            "invalid_grant: Token has been expired or revoked.",
            {"error": "invalid_grant"},
        )

        with (
            patch("stonksmith.helpers.sheets.gspread.oauth", return_value=client),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_worksheet(worksheet_name="529 Plan")

        self.assertIn("authorized_user.json", str(caught.exception))

    def test_an_unrecognised_auth_failure_offers_both_fixes_in_order(self) -> None:
        # Neither marker present -- a transport error, say. The function cannot
        # tell which applies, so it names the cheap fix first rather than
        # guessing, and both are better than the bare failure it used to give.
        failure = RefreshError("Failed to retrieve token", {})

        with (
            patch("stonksmith.helpers.sheets.gspread.oauth", side_effect=failure),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_worksheet(worksheet_name="529 Plan")

        message = str(caught.exception)
        self.assertIn("authorized_user.json", message)
        self.assertIn("credentials.json", message)
        self.assertLess(
            message.index("authorized_user.json"),
            message.index("credentials.json"),
            "The cheap fix has to come first, or the expensive one reads as the "
            "thing to try.",
        )

    def test_missing_spreadsheet_names_the_spreadsheet(self) -> None:
        client = MagicMock()
        client.open_by_key.side_effect = gspread.exceptions.SpreadsheetNotFound("nope")

        with (
            patch("stonksmith.helpers.sheets.gspread.oauth", return_value=client),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_worksheet(worksheet_name="529 Plan", spreadsheet="Missing Book")

        self.assertIn("Missing Book", str(caught.exception))

    def test_missing_worksheet_names_the_tab(self) -> None:
        client = MagicMock()
        client.open_by_key.return_value.worksheet.side_effect = (
            gspread.exceptions.WorksheetNotFound("nope")
        )

        with (
            patch("stonksmith.helpers.sheets.gspread.oauth", return_value=client),
            self.assertRaises(SheetsUnavailable) as caught,
        ):
            open_worksheet(worksheet_name="529 Plan")

        self.assertIn("529 Plan", str(caught.exception))

    def test_success_returns_the_worksheet(self) -> None:
        client = MagicMock()
        sentinel = client.open_by_key.return_value.worksheet.return_value

        with patch("stonksmith.helpers.sheets.gspread.oauth", return_value=client):
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


class ModuleReportsSheetsFailureCleanlyTests(GspreadConfigMixin, unittest.TestCase):
    # refresh() rather than sync(), deliberately. The "sync skipped" wording and
    # the decision not to fail the run both live inside sync() now, so patching
    # sync() would remove the behaviour this is here to check. Faulting the read
    # underneath it exercises the real path all five modules share.
    @patch("stonksmith.etc.portfolio_sheet.refresh")
    @patch("stonksmith.modules.schwab529plan_module.Parser")
    def test_sheets_failure_does_not_abort_the_run(
        self, mock_parser: MagicMock, mock_refresh: MagicMock
    ) -> None:
        from stonksmith.modules.schwab529plan_module import Schwab529Module

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
        # Set rather than left to the mock: sync() reads this with getattr, and
        # every attribute of a MagicMock is a truthy MagicMock -- so the flag
        # would read as passed and skip the very path this test exercises.
        context.args.no_sheet = False

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


class NoSheetSkipsTheRefreshTests(GspreadConfigMixin, unittest.TestCase):
    """`--no-sheet` exists so a batch rewrites the sheet once, not once a broker.

    Every broker calls sync() when it finishes, so a schedule running four of
    them rewrites all five tabs four times over before the step that exists to
    do it runs at all. Spread across a crontab that is waste; run back to back
    it exhausts Sheets' per-minute write quota and the final rewrite -- the only
    one that mattered -- is the one Google refuses.
    """

    @patch("stonksmith.etc.portfolio_sheet.refresh")
    def test_the_flag_skips_the_refresh_entirely(self, mock_refresh: MagicMock) -> None:
        from stonksmith.etc.portfolio_sheet import sync

        context = MagicMock()
        context.args.no_sheet = True

        result = sync(context=context)

        mock_refresh.assert_not_called()
        self.assertFalse(
            result,
            "a skipped refresh did not update the dashboard, and the callers "
            "turn that into 'saved locally; the dashboard was not updated'",
        )

    @patch("stonksmith.etc.portfolio_sheet.refresh")
    def test_without_the_flag_the_refresh_still_happens(
        self, mock_refresh: MagicMock
    ) -> None:
        from stonksmith.etc.portfolio_sheet import sync

        context = MagicMock()
        context.args.no_sheet = False

        sync(context=context)

        mock_refresh.assert_called_once()


if __name__ == "__main__":
    unittest.main()
