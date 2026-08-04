"""Scrape selectors for the Fidelity portfolio summary.

Verified against a live signed-in session: the account list is Fidelity's
"acct-selector" component, one `__acct-wrapper` per account. The earlier
guesses -- `[data-testid='account-row']`, `.acct-selector__acct-row`,
`.pvd-table__row` -- match nothing on the real page.

The balance element is written for screen readers and reads
", balance:  $1,234.56", so the amount has to be extracted rather than used raw.
"""

import unittest
from unittest.mock import MagicMock

from modules.fidelity_module import (
    ACCOUNT_BALANCE_SELECTORS,
    ACCOUNT_NAME_SELECTORS,
    ACCOUNT_NUMBER_SELECTORS,
    ACCOUNT_RENDER_TIMEOUT_MS,
    ACCOUNT_ROW_SELECTORS,
    FidelityModule,
    clean_money,
)


class CleanMoneyTests(unittest.TestCase):
    def test_strips_the_screen_reader_prefix(self) -> None:
        # The exact shape observed on the live page.
        self.assertEqual(clean_money(text=", balance:  $1,234.56"), "$1,234.56")

    def test_handles_a_bare_amount(self) -> None:
        self.assertEqual(clean_money(text="$0.00"), "$0.00")

    def test_handles_a_negative_balance(self) -> None:
        self.assertEqual(clean_money(text=", balance:  -$42.10"), "-$42.10")

    def test_falls_back_to_the_stripped_text(self) -> None:
        self.assertEqual(clean_money(text="  unavailable  "), "unavailable")

    def test_empty_text_stays_empty(self) -> None:
        self.assertEqual(clean_money(text=""), "")


class SelectorContractTests(unittest.TestCase):
    def test_row_selector_targets_the_verified_component(self) -> None:
        self.assertEqual(ACCOUNT_ROW_SELECTORS[0], ".acct-selector__acct-wrapper")

    def test_guessed_selectors_are_gone(self) -> None:
        # These matched nothing against the real page.
        for dead in (
            "[data-testid='account-row']",
            ".acct-selector__acct-row",
            ".pvd-table__row",
        ):
            self.assertNotIn(dead, ACCOUNT_ROW_SELECTORS)

    def test_field_selectors_are_present(self) -> None:
        self.assertIn(".acct-selector__acct-name", ACCOUNT_NAME_SELECTORS)
        self.assertIn(".acct-selector__acct-balance", ACCOUNT_BALANCE_SELECTORS)
        self.assertIn(".acct-selector__acct-num", ACCOUNT_NUMBER_SELECTORS)


def _row(name: str, number: str, balance: str) -> MagicMock:
    """A Playwright row locator whose child lookups resolve by selector."""

    def locator(selector: str) -> MagicMock:
        text = {
            ".acct-selector__acct-name": name,
            ".acct-selector__acct-num": number,
            ".acct-selector__acct-balance": balance,
        }.get(selector, "")
        child = MagicMock()
        child.first.count.return_value = 1 if text else 0
        child.first.inner_text.return_value = text
        return child

    row = MagicMock()
    row.locator.side_effect = locator
    return row


class RenderWaitTests(unittest.TestCase):
    """The account list hydrates after the spinner clears.

    Observed live: immediately after wait_for_loading_sign() the page reports
    0 account rows; a moment later there are 5. Scraping in that window
    produced "No accounts found" from a fully authenticated page.
    """

    def test_waits_for_the_component_before_reading(self) -> None:
        page = MagicMock()
        page.locator.return_value.all.return_value = []

        FidelityModule().scrape_accounts(page=page, context=MagicMock())

        page.wait_for_selector.assert_any_call(
            ".acct-selector__acct-wrapper",
            timeout=ACCOUNT_RENDER_TIMEOUT_MS,
            state="attached",
        )

    def test_a_selector_that_never_appears_moves_to_the_next(self) -> None:
        page = MagicMock()
        page.wait_for_selector.side_effect = RuntimeError("timeout")
        page.locator.return_value.all.return_value = []

        # Must not raise: the caller reports and captures instead.
        self.assertEqual(
            FidelityModule().scrape_accounts(page=page, context=MagicMock()), []
        )
        self.assertEqual(page.wait_for_selector.call_count, len(ACCOUNT_ROW_SELECTORS))


class ScrapeAccountsTests(unittest.TestCase):
    def _page(self, rows: list[MagicMock]) -> MagicMock:
        page = MagicMock()

        def locator(selector: str) -> MagicMock:
            found = MagicMock()
            found.all.return_value = (
                rows if selector == ".acct-selector__acct-wrapper" else []
            )
            return found

        page.locator.side_effect = locator
        return page

    def test_extracts_name_number_and_cleaned_balance(self) -> None:
        page = self._page([_row(" ROTH IRA ", " 123456789 ", ", balance:  $1.00")])

        accounts = FidelityModule().scrape_accounts(page=page, context=MagicMock())

        self.assertEqual(
            accounts, [{"Account": "ROTH IRA (123456789)", "Balance": "$1.00"}]
        )

    def test_account_number_disambiguates_shared_nicknames(self) -> None:
        page = self._page(
            [
                _row("BROKERAGE", "111", ", balance:  $1.00"),
                _row("BROKERAGE", "222", ", balance:  $2.00"),
            ]
        )

        accounts = FidelityModule().scrape_accounts(page=page, context=MagicMock())

        self.assertEqual(
            [a["Account"] for a in accounts],
            ["BROKERAGE (111)", "BROKERAGE (222)"],
        )

    def test_missing_number_still_yields_the_name(self) -> None:
        page = self._page([_row("ESPP", "", ", balance:  $3.00")])

        accounts = FidelityModule().scrape_accounts(page=page, context=MagicMock())

        self.assertEqual(accounts[0]["Account"], "ESPP")

    def test_no_rows_yields_nothing(self) -> None:
        accounts = FidelityModule().scrape_accounts(
            page=self._page([]), context=MagicMock()
        )

        self.assertEqual(accounts, [])


if __name__ == "__main__":
    unittest.main()
