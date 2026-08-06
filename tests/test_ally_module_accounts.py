"""Ally shows one account's positions at a time, and that is a data-loss risk.

The holdings page renders the selected account's table and lists every other
account only in the sidebar. A module that read the table alone would report a
single account and exit 0 -- indistinguishable from a correct run for anyone
with one account, and a silent hole for anyone with two.

So the sidebar is the account list and the table is one account's detail, and
the two are reconciled on the account number: the sidebar masks it ("...0111"),
the heading does not ("1AB20111"). The reconciliation matters beyond
attribution -- deriving one identity from the masked number and another from
the full one would give a single account two rows in the database the first
time the sidebar failed to render, which is the same double count that
excluding overlapping SnapTrade accounts exists to prevent.
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from bs4 import BeautifulSoup

from modules.ally_module import AllyModule, holding_rows

FIXTURE = Path(__file__).resolve().parents[0] / "ally_holdings.html"

#: A second investment account in the sidebar, whose positions are therefore
#: not on screen.
SECOND_ACCOUNT = """
          <li class="investments-account">
            <div class="left">
              <div>Investments</div>
              <div>
                <a href="#">Roth IRA</a>
                <span>...0333</span>
              </div>
            </div>
            <div class="right">
              <div>Account Value</div>
              <div><span>$9,000.00</span></div>
            </div>
          </li>"""


def _page(markup: str | None = None) -> BeautifulSoup:
    """The captured holdings page, or a variation on it."""

    text = markup if markup is not None else FIXTURE.read_text(encoding="utf-8")
    return BeautifulSoup(markup=text, features="html.parser")


def _with_second_account() -> BeautifulSoup:
    """The captured page plus an account whose holdings are not shown."""

    return _page(
        markup=FIXTURE.read_text(encoding="utf-8").replace(
            '<li class="savings-account">',
            f'{SECOND_ACCOUNT}<li class="savings-account">',
        )
    )


def _scrape(soup: BeautifulSoup):
    """Run the reconciliation, returning the rows and the context it logged to."""

    context = MagicMock()
    return AllyModule().scrape_accounts(soup=soup, context=context), context


class SingleAccountTests(unittest.TestCase):
    def test_the_selected_account_gets_its_balance_and_its_positions(self) -> None:
        rows, _context = _scrape(soup=_page())

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Account"], "Brokerage (...0111)")
        self.assertEqual(rows[0]["Balance"], "$1,500.00")
        self.assertEqual(len(rows[0]["Holdings"]), 1)

    def test_the_headline_gain_and_loss_keep_the_sign_the_class_encodes(self) -> None:
        rows, _context = _scrape(soup=_page())

        self.assertEqual(rows[0]["Total G/L"], "$250.00")
        self.assertEqual(rows[0]["Today's G/L"], "-$3.00")

    def test_the_full_account_number_is_recorded_beside_the_masked_label(self) -> None:
        # The label is identity and stays masked; the number is recorded
        # because it is useful, never used to join anything.
        rows, _context = _scrape(soup=_page())

        self.assertEqual(rows[0]["Number"], "1AB20111")

    def test_the_bank_account_is_not_reported_as_a_brokerage_one(self) -> None:
        rows, _context = _scrape(soup=_page())

        self.assertNotIn("Savings Account (...0222)", [row["Account"] for row in rows])

    def test_skipping_the_bank_account_says_so(self) -> None:
        # Silently dropping an account is the worst outcome available here,
        # even when dropping it is right.
        _rows, context = _scrape(soup=_page())

        said = " ".join(
            str(object=call.kwargs.get("msg", ""))
            for call in context.log.display.call_args_list
        )

        self.assertIn("Savings Account (...0222)", said)


class SecondAccountTests(unittest.TestCase):
    def test_an_account_whose_holdings_are_not_shown_still_gets_a_row(self) -> None:
        # The regression: reading only the table reports one account out of
        # two, with a successful exit code and nothing to notice.
        rows, _context = _scrape(soup=_with_second_account())

        self.assertEqual(
            sorted(row["Account"] for row in rows),
            ["Brokerage (...0111)", "Roth IRA (...0333)"],
        )

    def test_its_balance_comes_from_the_sidebar(self) -> None:
        rows, _context = _scrape(soup=_with_second_account())
        other = next(row for row in rows if row["Account"] == "Roth IRA (...0333)")

        self.assertEqual(other["Balance"], "$9,000.00")

    def test_its_positions_are_left_empty_rather_than_borrowed(self) -> None:
        # The positions on screen belong to the selected account. Attaching
        # them to a second account would invent holdings it does not have.
        rows, _context = _scrape(soup=_with_second_account())
        other = next(row for row in rows if row["Account"] == "Roth IRA (...0333)")

        self.assertEqual(other["Holdings"], [])

    def test_the_missing_positions_are_reported_with_what_to_do(self) -> None:
        _rows, context = _scrape(soup=_with_second_account())

        said = " ".join(
            str(object=call.kwargs.get("msg", ""))
            for call in context.log.highlight.call_args_list
        )

        self.assertIn("Roth IRA (...0333)", said)
        self.assertIn("re-run", said)

    def test_the_selected_account_keeps_its_own_totals(self) -> None:
        rows, _context = _scrape(soup=_with_second_account())
        other = next(row for row in rows if row["Account"] == "Roth IRA (...0333)")

        # The headline figures describe the account on screen, so they must not
        # be copied onto one that is not.
        self.assertEqual(other["Total G/L"], "")
        self.assertEqual(other["Today's G/L"], "")


class UnlistedAccountTests(unittest.TestCase):
    def _without_sidebar(self) -> BeautifulSoup:
        text = FIXTURE.read_text(encoding="utf-8")
        start = text.index("<ally-accounts-list>")
        end = text.index("</ally-accounts-list>") + len("</ally-accounts-list>")
        return _page(markup=text[:start] + text[end:])

    def test_an_account_the_sidebar_omits_is_still_recorded(self) -> None:
        rows, _context = _scrape(soup=self._without_sidebar())

        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]["Holdings"]), 1)

    def test_it_keys_to_the_same_identity_the_sidebar_would_have_given(self) -> None:
        # The double count this prevents: one account keyed "Brokerage
        # (...0111)" on the runs that see the sidebar and "Brokerage
        # (1AB20111)" on the runs that do not is two accounts in the database,
        # each with half the history.
        with_sidebar, _ = _scrape(soup=_page())
        without_sidebar, _ = _scrape(soup=self._without_sidebar())

        self.assertEqual(without_sidebar[0]["Account"], with_sidebar[0]["Account"])

    def test_it_says_the_account_was_not_in_the_list(self) -> None:
        _rows, context = _scrape(soup=self._without_sidebar())

        said = " ".join(
            str(object=call.kwargs.get("msg", ""))
            for call in context.log.highlight.call_args_list
        )

        self.assertIn("not in the", said)


class EmptyPageTests(unittest.TestCase):
    def test_a_page_with_nothing_on_it_yields_no_accounts(self) -> None:
        # The caller treats this as a failure and captures the markup, which is
        # only correct if nothing here invents a row out of an empty page.
        rows, _context = _scrape(soup=_page(markup="<html><body></body></html>"))

        self.assertEqual(rows, [])


class HoldingRowTests(unittest.TestCase):
    def test_positions_carry_the_account_they_belong_to(self) -> None:
        rows, _context = _scrape(soup=_page())
        sheet_rows = holding_rows(
            account=rows[0]["Account"], positions=rows[0]["Holdings"]
        )

        self.assertEqual(sheet_rows[0]["Account"], "Brokerage (...0111)")
        self.assertEqual(sheet_rows[0]["Symbol"], "EXMPL")
        self.assertEqual(sheet_rows[0]["Value"], "$1,500.00")

    def test_an_account_with_no_positions_contributes_no_rows(self) -> None:
        self.assertEqual(holding_rows(account="Roth IRA (...0333)", positions=[]), [])


if __name__ == "__main__":
    unittest.main()
