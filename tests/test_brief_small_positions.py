"""A few cents of a sweep fund is not a holding, and hiding it changes no total.

A settlement account leaves eight cents of a cash sweep sitting beside a real
position. It renders as a full row with a dash in every derived column -- true,
and not a holding anybody is tracking. A table where one row in twelve is noise
is a table that gets skimmed, which costs more than the row is worth.

**The filter is display only, and that is the whole point of this file.** The
portfolio value, the invested figure and the cash line all still count what falls
below the floor, so hiding a row cannot move a number. A row removed from a page
is a presentation choice; a dollar removed from a total is a lie, and the two
must not be confused by an implementation that filters `held` before
performance() sees it.

The count of what was hidden is stated under the table, on the rule the movers
cap already follows: a list that silently ends is one whose reader cannot tell a
short book from a truncated view.
"""

import datetime as dt
import unittest

from config_isolation import UserConfigMixin
from stonksmith.etc.brief import build_brief
from stonksmith.etc.brief_html import render
from stonksmith.etc.portfolio import (
    OBSERVED,
    AccountRow,
    HoldingRow,
    NetWorthRow,
    Portfolio,
)

TODAY: dt.date = dt.date(2026, 8, 14)
NOW: dt.datetime = dt.datetime(2026, 8, 14, 6, 30, tzinfo=dt.UTC)

#: One real position and the sweep balance beside it, which is the shape a
#: Fidelity brokerage account actually arrives in.
PORTFOLIO: Portfolio = Portfolio(
    accounts=(
        AccountRow(
            broker="snaptrade",
            source="Fidelity",
            account="Joint Brokerage (Fidelity)",
            account_key="f1",
            value=1922.70,
            as_of="2026-08-14",
        ),
    ),
    holdings=(
        HoldingRow(
            broker="snaptrade",
            source="Fidelity",
            account="Joint Brokerage (Fidelity)",
            account_key="f1",
            symbol="FSKAX",
            units=8.93,
            value=1922.62,
        ),
        HoldingRow(
            broker="snaptrade",
            source="Fidelity",
            account="Joint Brokerage (Fidelity)",
            account_key="f1",
            symbol="FCASH",
            units=0.08,
            value=0.08,
        ),
    ),
    net_worth=(
        NetWorthRow(
            broker="snaptrade",
            source="Fidelity",
            account="Joint Brokerage (Fidelity)",
            account_key="f1",
            date="2026-08-14",
            value=1922.70,
            basis=OBSERVED,
            observed_on="2026-08-14",
        ),
    ),
)


class TheSweepBalanceLosesItsRow(UserConfigMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.brief = build_brief(
            portfolio=PORTFOLIO, baseline=None, today=TODAY, floor=1.0
        )

    def test_only_the_real_position_is_rendered(self) -> None:
        self.assertEqual([row.symbol for row in self.brief.positions], ["FSKAX"])

    def test_the_hidden_one_is_counted(self) -> None:
        self.assertEqual(self.brief.positions_hidden, 1)

    def test_the_page_says_it_hid_something(self) -> None:
        page: str = render(brief=self.brief, now=NOW)

        self.assertIn("1 smaller position not shown", page)
        self.assertNotIn("FCASH", page)

    def test_a_floor_of_zero_shows_everything(self) -> None:
        # A real answer rather than a disabled feature.
        brief = build_brief(portfolio=PORTFOLIO, baseline=None, today=TODAY, floor=0.0)

        self.assertEqual(len(brief.positions), 2)
        self.assertEqual(brief.positions_hidden, 0)

    def test_nothing_is_said_when_nothing_was_hidden(self) -> None:
        # A line that appeared every morning is one nobody reads on the morning
        # it means something.
        page: str = render(
            brief=build_brief(
                portfolio=PORTFOLIO, baseline=None, today=TODAY, floor=0.0
            ),
            now=NOW,
        )

        self.assertNotIn("not shown", page)


class HidingARowMovesNoNumber(UserConfigMixin, unittest.TestCase):
    """The claim the whole feature rests on."""

    def setUp(self) -> None:
        super().setUp()
        self.shown = build_brief(
            portfolio=PORTFOLIO, baseline=None, today=TODAY, floor=0.0
        )
        self.hidden = build_brief(
            portfolio=PORTFOLIO, baseline=None, today=TODAY, floor=1.0
        )

    def test_the_invested_total_is_unchanged(self) -> None:
        # The one that would break if the filter were applied to `held` before
        # performance() totalled it -- eight cents, which is small enough to
        # look like rounding and wrong for a reason nobody would find.
        self.assertEqual(
            self.shown.performance.invested, self.hidden.performance.invested
        )

    def test_the_portfolio_value_is_unchanged(self) -> None:
        self.assertEqual(self.shown.performance.value, self.hidden.performance.value)

    def test_the_holdings_count_still_counts_them_all(self) -> None:
        # The tile says "13 holdings" while the table shows twelve, and that is
        # correct: the count is of what is held, not of what is rendered.
        self.assertEqual(
            self.shown.performance.holdings, self.hidden.performance.holdings
        )

    def test_the_cash_line_is_unchanged(self) -> None:
        # value - invested is the cash, and hiding a position must not move it.
        gap_shown = self.shown.performance.value - self.shown.performance.invested
        gap_hidden = self.hidden.performance.value - self.hidden.performance.invested

        self.assertAlmostEqual(gap_shown, gap_hidden, places=2)


class AnUnpricedPositionIsNotJudgedAtAll(UserConfigMixin, unittest.TestCase):
    def test_a_holding_the_source_never_valued_stays_visible(self) -> None:
        # `row.value or 0.0` reads None as zero and puts it under every floor
        # above zero -- the absent-is-not-zero conflation this project forbids
        # everywhere else, and the worst place to make it. A holding nobody could
        # price is exactly the one a reader needs to see, and it would vanish
        # precisely because nothing is known about it.
        unpriced = Portfolio(
            holdings=(
                HoldingRow(
                    broker="b",
                    source="b",
                    account="Somewhere",
                    account_key="s",
                    symbol="UNKNOWN",
                    units=3.0,
                    value=None,
                ),
            )
        )
        brief = build_brief(portfolio=unpriced, baseline=None, today=TODAY, floor=1.0)

        self.assertEqual([row.symbol for row in brief.positions], ["UNKNOWN"])
        self.assertEqual(brief.positions_hidden, 0)


class ANegativePositionIsJudgedOnItsSize(UserConfigMixin, unittest.TestCase):
    def test_a_short_or_owed_position_is_not_hidden_for_being_negative(self) -> None:
        # Compared on magnitude, not on value. A position at -$400 is a debt
        # worth a row, and a floor applied to the signed number would hide every
        # one of them -- which is the opposite of what a floor is for.
        owed = Portfolio(
            holdings=(
                HoldingRow(
                    broker="b",
                    source="b",
                    account="Margin",
                    account_key="m",
                    symbol="OWED",
                    value=-400.0,
                ),
            )
        )
        brief = build_brief(portfolio=owed, baseline=None, today=TODAY, floor=1.0)

        self.assertEqual([row.symbol for row in brief.positions], ["OWED"])
        self.assertEqual(brief.positions_hidden, 0)


if __name__ == "__main__":
    unittest.main()
