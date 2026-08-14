"""What the brief says a position has made, and what it refuses to say.

The performance half of the brief reports lifetime return, which the rest of it
does not: the headline answers "what moved since you last looked" and these
numbers answer "what have I made since I bought it". Different question, and it
depends on a field most of this workspace's sources do not report.

**Cost basis is the fault line.** SnapTrade states one; TSP, a Microsoft 401k and
a scraped 529 do not. Every figure that divides by it -- purchase price, gain,
growth, yield on cost, the win/loss flag -- is therefore absent for those
positions, and the single most tempting bug in this file is to let an absent cost
become 0.0. It does not raise, it does not look wrong, and it reports a holding
that has made exactly nothing as though somebody had checked. On a 401k that is
two thirds of the portfolio it would put a made-up zero next to the largest
number on the page.

So the rule is: absent stays absent, all the way to a dash on the screen. And
where a total *is* summed over the subset that has a cost, the count travels with
it and the render states it, on the same reasoning as the observed/carried split.
"""

import datetime as dt
import unittest

from config_isolation import UserConfigMixin
from stonksmith.etc.brief import (
    Mark,
    Performance,
    build_brief,
    dividends,
    performance,
    positions,
    trends,
)
from stonksmith.etc.brief_html import render
from stonksmith.etc.portfolio import (
    OBSERVED,
    AccountRow,
    HoldingRow,
    NetWorthRow,
    Portfolio,
    TransactionRow,
)

TODAY: dt.date = dt.date(2026, 8, 14)
NOW: dt.datetime = dt.datetime(2026, 8, 14, 6, 30, tzinfo=dt.UTC)


def _held(symbol: str, **fields: object) -> HoldingRow:
    """One position, with only the fields a case cares about set."""

    return HoldingRow(
        broker="snaptrade",
        source="snaptrade",
        account="Brokerage",
        account_key="a1",
        symbol=symbol,
        **fields,  # type: ignore[arg-type]
    )


class ACostNobodyReportedStaysAbsent(UserConfigMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()

        self.built = positions(
            portfolio=Portfolio(
                holdings=(
                    _held(
                        symbol="VTI",
                        units=10.0,
                        price=100.0,
                        value=1000.0,
                        cost_basis=800.0,
                    ),
                    # The 401k shape: a value and a unit count, no cost.
                    _held(symbol="O7M8", units=50.0, price=20.0, value=1000.0),
                )
            ),
            classes={},
            income={},
            history={},
        )
        self.by_symbol = {row.symbol: row for row in self.built}

    def test_a_priced_position_gets_every_derived_figure(self) -> None:
        vti = self.by_symbol["VTI"]

        self.assertEqual(vti.cost_basis, 800.0)
        self.assertEqual(vti.purchase_price, 80.0)
        self.assertEqual(vti.gain, 200.0)
        self.assertAlmostEqual(vti.growth or 0.0, 0.25)
        self.assertIs(vti.winning, True)

    def test_an_unpriced_position_gets_none_of_them(self) -> None:
        # The whole file in one case. Any of these coming back 0.0 is a claim
        # that somebody checked and the position had made nothing.
        held = self.by_symbol["O7M8"]

        self.assertIsNone(held.cost_basis)
        self.assertIsNone(held.purchase_price)
        self.assertIsNone(held.gain)
        self.assertIsNone(held.growth)
        self.assertIsNone(held.yield_on_cost)

    def test_it_is_neither_a_win_nor_a_loss(self) -> None:
        # Three-valued rather than two. Defaulting to False would flag every TSP
        # and 401k holding as losing money.
        self.assertIsNone(self.by_symbol["O7M8"].winning)

    def test_the_page_shows_dashes_rather_than_zeros(self) -> None:
        page: str = render(
            brief=build_brief(
                portfolio=Portfolio(
                    holdings=(_held(symbol="O7M8", units=50.0, value=1000.0),)
                ),
                baseline=None,
                today=TODAY,
            ),
            now=NOW,
        )

        self.assertIn("O7M8", page)
        self.assertNotIn("$0.00", page.split("<h2>Holdings</h2>")[1])


class TheTotalsSayWhatTheyStandOn(UserConfigMixin, unittest.TestCase):
    # UserConfigMixin because one case below reaches build_brief, which asks the
    # config for the asset classes -- and get_config() merges the shipped
    # defaults into the developer's real ~/.stonksmith/stonksmith.conf and
    # writes it back. tests/test_suite_does_not_touch_home.py fails the whole
    # suite for that, which is how this omission was caught rather than shipped.
    def setUp(self) -> None:
        super().setUp()

        self.built = positions(
            portfolio=Portfolio(
                holdings=(
                    _held(symbol="VTI", units=10.0, value=1000.0, cost_basis=800.0),
                    _held(symbol="BND", units=10.0, value=500.0, cost_basis=600.0),
                    _held(symbol="O7M8", units=50.0, value=2000.0),
                )
            ),
            classes={},
            income={},
            history={},
        )

    def test_gain_is_summed_over_the_priced_positions_only(self) -> None:
        money: Performance = performance(
            held=self.built, income={}, covered=0, currency="USD", total=3500.0
        )

        # +200 on VTI and -100 on BND. The 401k contributes nothing because
        # nothing is known about what it cost.
        self.assertEqual(money.gain, 100.0)
        self.assertEqual(money.priced, 2)
        self.assertEqual(money.unpriced, 1)

    def test_the_value_is_the_account_total_not_the_position_sum(self) -> None:
        # The two differ by whatever is sitting uninvested, and the headline
        # reports the account total. A tile summing positions instead puts two
        # numbers on one page both fairly called "portfolio value" and leaves
        # the reader to reconcile them.
        money: Performance = performance(
            held=self.built, income={}, covered=0, currency="USD", total=3869.50
        )

        self.assertEqual(money.value, 3869.50)
        self.assertEqual(money.invested, 3500.0)

    def test_wins_and_losses_are_reported_separately(self) -> None:
        # Netted they are +$100, which hides both. The sheet this was modelled
        # on keeps a Total Win and a Total Loss for exactly that reason.
        money: Performance = performance(
            held=self.built, income={}, covered=0, currency="USD", total=3500.0
        )

        self.assertEqual(money.total_win, 200.0)
        self.assertEqual(money.total_loss, -100.0)

    def test_the_page_states_how_many_positions_the_gain_covers(self) -> None:
        page: str = render(
            brief=build_brief(
                portfolio=Portfolio(
                    holdings=(
                        _held(symbol="VTI", units=10.0, value=1000.0, cost_basis=800.0),
                        _held(symbol="O7M8", units=50.0, value=2000.0),
                    )
                ),
                baseline=None,
                today=TODAY,
            ),
            now=NOW,
        )

        self.assertIn("across 1 of 2 positions", page)
        self.assertIn("1 report no cost basis", page)


class DividendsComeFromTheLog(unittest.TestCase):
    def _paid(self, **fields: object) -> TransactionRow:
        return TransactionRow(
            broker="snaptrade",
            source="snaptrade",
            account="Brokerage",
            account_key="a1",
            **fields,  # type: ignore[arg-type]
        )

    def test_a_dividend_inside_the_window_counts(self) -> None:
        income, covered = dividends(
            rows=[
                self._paid(
                    tx_type="DIVIDEND",
                    symbol="VTI",
                    value=12.0,
                    processed_on="2026-06-01",
                )
            ],
            today=TODAY,
        )

        self.assertEqual(income, {"VTI": 12.0})
        self.assertGreater(covered, 0)

    def test_a_contribution_does_not(self) -> None:
        income, _ = dividends(
            rows=[
                self._paid(
                    tx_type="CONTRIBUTION",
                    symbol="VTI",
                    value=500.0,
                    processed_on="2026-06-01",
                )
            ],
            today=TODAY,
        )

        self.assertEqual(income, {})

    def test_a_reinvested_dividend_still_counts_as_income(self) -> None:
        # The sources disagree about wording and always will. Money received and
        # immediately spent on more shares is still money received.
        income, _ = dividends(
            rows=[
                self._paid(
                    tx_type="Dividend Reinvest",
                    symbol="SWPPX",
                    value=3.0,
                    processed_on="2026-07-01",
                )
            ],
            today=TODAY,
        )

        self.assertEqual(income, {"SWPPX": 3.0})

    def test_the_window_is_cut_on_the_payment_date(self) -> None:
        # processed_on, not first_seen. A workspace rebuilt this morning saw
        # every movement today, so a window cut on first_seen would either admit
        # a decade of dividends or drop all of them depending on which way it
        # compared -- and neither is a fact about the money.
        income, _ = dividends(
            rows=[
                self._paid(
                    tx_type="DIVIDEND",
                    symbol="VTI",
                    value=12.0,
                    processed_on="2020-01-01",
                    first_seen="2026-08-14T06:30:00",
                )
            ],
            today=TODAY,
        )

        self.assertEqual(income, {})

    def test_no_dividends_is_distinct_from_zero_income(self) -> None:
        # The distinction the tile's wording rests on. A log that has never
        # carried a dividend is not a portfolio that pays nothing.
        money: Performance = performance(
            held=[], income={}, covered=0, currency="USD", total=0.0
        )

        self.assertFalse(money.dividends_seen)

        earned: Performance = performance(
            held=[], income={"VTI": 0.0}, covered=200, currency="USD", total=0.0
        )

        self.assertTrue(earned.dividends_seen)


class TrendsArePerPositionAndPerReading(unittest.TestCase):
    def _snapshot(self, symbol: str, when: str, value: float) -> HoldingRow:
        return HoldingRow(
            broker="snaptrade",
            source="snaptrade",
            account="Brokerage",
            account_key="a1",
            symbol=symbol,
            value=value,
            scraped_at=when,
        )

    def test_two_runs_in_one_day_are_two_points(self) -> None:
        # The opposite of what the net worth axis does, and deliberate. That one
        # collapses a date to one point so every date sums the same accounts;
        # this is one position's own history, where an intraday mark is simply
        # another reading. With the opening-bell agent there are now two a day.
        series = trends(
            rows=[
                self._snapshot(symbol="VTI", when="2026-08-13 06:35:00", value=100.0),
                self._snapshot(symbol="VTI", when="2026-08-13 18:30:00", value=110.0),
            ]
        )

        self.assertEqual(series[("snaptrade", "a1", "VTI")], [100.0, 110.0])

    def test_the_same_symbol_in_two_accounts_stays_two_series(self) -> None:
        rows = [
            self._snapshot(symbol="SWPPX", when="2026-08-13 18:30:00", value=100.0),
            HoldingRow(
                broker="snaptrade",
                source="snaptrade",
                account="Joint",
                account_key="a2",
                symbol="SWPPX",
                value=250.0,
                scraped_at="2026-08-13 18:30:00",
            ),
        ]

        self.assertEqual(len(trends(rows=rows)), 2)

    def test_a_day_change_needs_two_readings(self) -> None:
        # None on a single reading, which is not a flat day -- it is a position
        # nobody has measured twice.
        built = positions(
            portfolio=Portfolio(holdings=(_held(symbol="VTI", value=110.0),)),
            classes={},
            income={},
            history={("snaptrade", "a1", "VTI"): [100.0]},
        )

        self.assertIsNone(built[0].day_change)

    def test_a_day_change_is_the_move_between_the_last_two(self) -> None:
        built = positions(
            portfolio=Portfolio(holdings=(_held(symbol="VTI", value=110.0),)),
            classes={},
            income={},
            history={("snaptrade", "a1", "VTI"): [90.0, 100.0, 110.0]},
        )

        self.assertAlmostEqual(built[0].day_change or 0.0, 0.10)


class UnitsMovedIsAnEventAndRepricingIsNot(UserConfigMixin, unittest.TestCase):
    def test_a_bought_position_carries_a_note(self) -> None:
        built = positions(
            portfolio=Portfolio(
                holdings=(_held(symbol="VTI", units=12.0, value=1200.0),)
            ),
            classes={},
            income={},
            history={},
            baseline={("snaptrade", "a1", "VTI"): Mark(value=1000.0, units=10.0)},
        )

        self.assertEqual(built[0].units_delta, 2.0)

    def test_a_repriced_position_does_not(self) -> None:
        built = positions(
            portfolio=Portfolio(
                holdings=(_held(symbol="VTI", units=10.0, value=1200.0),)
            ),
            classes={},
            income={},
            history={},
            baseline={("snaptrade", "a1", "VTI"): Mark(value=1000.0, units=10.0)},
        )

        self.assertIsNone(built[0].units_delta)

    def test_a_first_brief_reports_no_purchases(self) -> None:
        # Without a baseline every holding would otherwise look newly bought,
        # which is the invented-change failure the state machine prevents one
        # level up.
        built = positions(
            portfolio=Portfolio(
                holdings=(_held(symbol="VTI", units=10.0, value=1000.0),)
            ),
            classes={},
            income={},
            history={},
            baseline=None,
        )

        self.assertIsNone(built[0].units_delta)


class TheValueTileMatchesTheHeadline(UserConfigMixin, unittest.TestCase):
    def test_both_report_the_account_total(self) -> None:
        # The bug this was written after: the tile summed positions and the
        # headline summed accounts, so a workspace with $369.50 of uninvested
        # cash showed two different portfolio values a few inches apart.
        portfolio = Portfolio(
            accounts=(
                AccountRow(
                    broker="snaptrade",
                    source="snaptrade",
                    account="Brokerage",
                    account_key="a1",
                    value=1369.50,
                    as_of="2026-08-13",
                ),
            ),
            holdings=(_held(symbol="VTI", units=10.0, value=1000.0),),
            net_worth=(
                NetWorthRow(
                    broker="snaptrade",
                    source="snaptrade",
                    account="Brokerage",
                    account_key="a1",
                    date="2026-08-13",
                    value=1369.50,
                    basis=OBSERVED,
                    observed_on="2026-08-13",
                ),
            ),
        )
        brief = build_brief(portfolio=portfolio, baseline=None, today=TODAY)

        self.assertEqual(brief.total, 1369.50)
        self.assertEqual(brief.performance.value, 1369.50)
        self.assertEqual(brief.performance.invested, 1000.0)

    def test_the_page_names_the_uninvested_remainder(self) -> None:
        portfolio = Portfolio(
            accounts=(
                AccountRow(
                    broker="snaptrade",
                    source="snaptrade",
                    account="Brokerage",
                    account_key="a1",
                    value=1369.50,
                    as_of="2026-08-13",
                ),
            ),
            holdings=(_held(symbol="VTI", units=10.0, value=1000.0),),
            net_worth=(
                NetWorthRow(
                    broker="snaptrade",
                    source="snaptrade",
                    account="Brokerage",
                    account_key="a1",
                    date="2026-08-13",
                    value=1369.50,
                    basis=OBSERVED,
                    observed_on="2026-08-13",
                ),
            ),
        )
        page: str = render(
            brief=build_brief(portfolio=portfolio, baseline=None, today=TODAY),
            now=NOW,
        )

        self.assertIn("$369.50 not in any position", page)

    def test_positions_exceeding_the_balances_is_not_called_cash(self) -> None:
        # The other direction, which "plus $X not in any position" renders as a
        # negative quantity of cash. It is not cash: it is the same source's own
        # balance and positions disagreeing, which on this workspace happens on
        # every SnapTrade account and by a third on one of them. A reader owed
        # that fact should not be handed arithmetic instead.
        portfolio = Portfolio(
            accounts=(
                AccountRow(
                    broker="snaptrade",
                    source="snaptrade",
                    account="Brokerage",
                    account_key="a1",
                    value=2222.73,
                    as_of="2026-08-13",
                ),
            ),
            holdings=(_held(symbol="SWPPX", units=148.499, value=2986.31),),
            net_worth=(
                NetWorthRow(
                    broker="snaptrade",
                    source="snaptrade",
                    account="Brokerage",
                    account_key="a1",
                    date="2026-08-13",
                    value=2222.73,
                    basis=OBSERVED,
                    observed_on="2026-08-13",
                ),
            ),
        )
        page: str = render(
            brief=build_brief(portfolio=portfolio, baseline=None, today=TODAY),
            now=NOW,
        )

        self.assertIn("positions total $763.58 more than the account balances", page)
        self.assertNotIn("not in any position", page)
        self.assertNotIn("$-", page)


if __name__ == "__main__":
    unittest.main()
