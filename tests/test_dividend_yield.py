"""What the holdings pay, and the two ways that number could be a lie.

The brief's dividend tiles read $0.00 for as long as this workspace existed,
because they were built from the transaction log and these brokers do not
itemise a distribution. A tile that says zero every morning is one nobody reads,
and it was not even wrong -- the money is real, it just never appeared as a
movement.

So the figure now comes from the same quote feed the prices do, and the two
things it must not do are the two this file pins.

**It must not claim to be money that arrived.** A fund's trailing per-share
distributions times the units held today is a forecast of a year at the current
position. It is not a record. The received figure stays beside it, labelled, and
neither overwrites the other -- which is also why the cache stores dividends *per
share* and never an income: a stored income would be wrong the moment a share
was bought.

**It must not blend the known with the unknown.** Two thirds of this portfolio
sits in a 401k, a TSP fund and a 529, none of which has a public ticker. Dividing
the income of nine known funds by the value of all thirteen positions reports
0.29% where the real answer for what is known is 1.33%, and the reader has no way
to see which they were given. The coverage travels with the figure, on the rule
the priced/unpriced gain split already follows.
"""

import datetime as dt
import unittest

from config_isolation import UserConfigMixin
from stonksmith.etc.brief import build_brief, performance, positions
from stonksmith.etc.brief_html import render
from stonksmith.etc.dividends import Dividends, Paid
from stonksmith.etc.portfolio import HoldingRow, Portfolio
from stonksmith.helpers.quotes import (
    QuotesUnavailable,
    dividend_events,
    trailing_dividend,
)

TODAY: dt.date = dt.date(2026, 8, 14)
NOW: dt.datetime = dt.datetime(2026, 8, 14, 6, 30, tzinfo=dt.UTC)

#: One fund that pays, one that has no quote page at all -- the shape of this
#: workspace, where a 401k fund code sits beside a Schwab index fund.
HELD: tuple[HoldingRow, ...] = (
    HoldingRow(
        broker="b",
        source="b",
        account="Alex Brokerage",
        account_key="a1",
        symbol="SWPPX",
        units=100.0,
        value=2000.0,
    ),
    HoldingRow(
        broker="b",
        source="b",
        account="Robin 401(k)",
        account_key="a2",
        symbol="Q4R7",
        units=1000.0,
        value=8000.0,
    ),
)

RATES: Dividends = Dividends(
    fetched_on="2026-08-14",
    paid={"SWPPX": Paid(per_share=0.195, covered_days=245, found=True)},
)


class ThePayloadIsReadTheWayThePricesAre(unittest.TestCase):
    def _payload(self, events: str) -> str:
        return (
            '{"chart":{"error":null,"result":[{"meta":{"gmtoffset":-14400},'
            f'"timestamp":[1],{events}}}]}}}}'
        )

    def test_a_dividend_is_read_with_its_ex_date(self) -> None:
        paid = dividend_events(
            payload=self._payload(
                events='"events":{"dividends":{"1765555200":'
                '{"amount":0.195,"date":1765555200}}}'
            )
        )

        self.assertEqual(list(paid.values()), [0.195])

    def test_events_present_but_null_is_not_an_error(self) -> None:
        # The shape the feed actually returns for a fund that pays nothing, and
        # the reason every step is `or {}` rather than `.get(key, {})`: a default
        # only applies to a missing key, and the key is not missing.
        self.assertEqual(dividend_events(payload=self._payload('"events":null')), {})

    def test_no_events_key_at_all_is_not_an_error(self) -> None:
        self.assertEqual(dividend_events(payload=self._payload('"x":1')), {})

    def test_two_distributions_on_one_day_are_summed(self) -> None:
        # An income distribution and a capital gain routinely share a December
        # ex-date. Assigning rather than summing would drop one silently.
        paid = dividend_events(
            payload=self._payload(
                events='"events":{"dividends":{'
                '"1765555200":{"amount":0.10},"1765555201":{"amount":0.05}}}'
            )
        )

        self.assertEqual(len(paid), 1, "one ex-date, not two")
        self.assertAlmostEqual(sum(paid.values()), 0.15, places=6)

    def test_a_symbol_the_feed_refuses_raises(self) -> None:
        # FCASH answers 404 with an in-band error and a 200-shaped body. That is
        # a different thing from a fund that pays nothing, and it must not
        # arrive as the same empty dict.
        with self.assertRaises(QuotesUnavailable):
            dividend_events(
                payload='{"chart":{"error":{"code":"Not Found"},"result":null}}'
            )


class ThePartialYearSaysSo(unittest.TestCase):
    def test_it_reports_how_much_history_it_stands_on(self) -> None:
        # A fund listed four months ago has paid four months of dividends, and
        # calling that an annual figure understates its yield by two thirds.
        paid = {dt.date(2026, 6, 1): 0.10}
        total, covered = trailing_dividend(paid=paid, today=TODAY)

        self.assertEqual(total, 0.10)
        self.assertEqual(covered, 74)

    def test_a_payment_outside_the_window_is_not_counted(self) -> None:
        paid = {dt.date(2024, 1, 1): 5.00, dt.date(2026, 6, 1): 0.10}
        total, _covered = trailing_dividend(paid=paid, today=TODAY)

        self.assertEqual(total, 0.10)

    def test_a_fund_that_paid_nothing_covers_nothing(self) -> None:
        self.assertEqual(trailing_dividend(paid={}, today=TODAY), (0.0, 0))


class AForecastIsNotMoneyThatArrived(UserConfigMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.built = positions(
            portfolio=Portfolio(holdings=HELD),
            classes={},
            income={},
            history={},
            paid=RATES.paid,
        )
        self.by_symbol = {row.symbol: row for row in self.built}

    def test_a_known_fund_gets_units_times_the_per_share_rate(self) -> None:
        self.assertAlmostEqual(
            self.by_symbol["SWPPX"].indicated_income or 0.0, 19.50, places=2
        )

    def test_its_indicated_yield_is_over_its_own_value(self) -> None:
        self.assertAlmostEqual(
            self.by_symbol["SWPPX"].indicated_yield or 0.0, 0.00975, places=5
        )

    def test_a_symbol_the_feed_never_answered_gets_none(self) -> None:
        # None rather than zero. A 401k fund code no quote page has heard of and
        # a fund that genuinely pays nothing both come to 0.0, and only the
        # second is a fact about money.
        self.assertIsNone(self.by_symbol["Q4R7"].indicated_income)
        self.assertIsNone(self.by_symbol["Q4R7"].indicated_yield)

    def test_the_received_figure_is_left_alone(self) -> None:
        # The whole reason the two are carried apart. An indicated figure written
        # over div_income would report a forecast under a heading that means
        # money that landed in an account.
        self.assertIsNone(self.by_symbol["SWPPX"].div_income)


class TheYieldSaysWhatItCovers(UserConfigMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.money = performance(
            held=positions(
                portfolio=Portfolio(holdings=HELD),
                classes={},
                income={},
                history={},
                paid=RATES.paid,
            ),
            income={},
            covered=0,
            currency="USD",
            total=10_000.0,
        )

    def test_the_income_totals_only_the_known_funds(self) -> None:
        self.assertAlmostEqual(self.money.indicated_income, 19.50, places=2)

    def test_the_yield_divides_by_what_it_knows_not_the_portfolio(self) -> None:
        # 19.50 over SWPPX's own 2,000 is 0.975%. Over all 10,000 it would be
        # 0.195% -- a real number about nothing anybody asked, and the one a
        # naive implementation produces.
        self.assertAlmostEqual(self.money.indicated_yield or 0.0, 0.00975, places=5)
        self.assertEqual(self.money.indicated_value, 2000.0)

    def test_it_counts_the_positions_it_stands_on(self) -> None:
        self.assertEqual(self.money.indicated_over, 1)
        self.assertEqual(self.money.holdings, 2)

    def test_the_page_states_the_coverage(self) -> None:
        page: str = render(
            brief=build_brief(
                portfolio=Portfolio(holdings=HELD),
                baseline=None,
                today=TODAY,
                rates=RATES,
            ),
            now=NOW,
        )

        self.assertIn("across 1 of 2 positions", page)
        self.assertIn("Indicated Income", page)


class NoCacheMeansNoFigures(UserConfigMixin, unittest.TestCase):
    def test_an_empty_cache_renders_a_dash_rather_than_zero(self) -> None:
        # Zero would say the holdings pay nothing. The truth is that nobody has
        # asked yet, and the page says which.
        brief = build_brief(
            portfolio=Portfolio(holdings=HELD), baseline=None, today=TODAY, rates=None
        )
        page: str = render(brief=brief, now=NOW)

        self.assertEqual(brief.performance.indicated_over, 0)
        self.assertIsNone(brief.performance.indicated_yield)
        self.assertIn("no holding has a published dividend", page)


if __name__ == "__main__":
    unittest.main()
