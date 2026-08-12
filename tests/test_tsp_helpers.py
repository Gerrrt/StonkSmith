"""Parsing the two public-ish inputs a TSP account can be valued from.

TSP does not report a balance so much as compute one, and it computes it as
units x share price. Checked against a real quarterly statement: the units and
unit price it printed multiply out to the closing balance on the same page, to
the cent, and that unit price is byte-identical to the public file's entry for
the same date. The public feed is not an approximation of what TSP marks an
account with; it is the same number.

That is why these two parsers are the whole substrate: with them, a daily value
needs no login, and stays exact until units change.

tests/tsp_prices.csv is a genuine slice of the published file -- public data,
so unredacted -- chosen for its structural hazards. tests/tsp_statement*.txt
mirror a real statement's layout with every figure invented.
"""

import datetime as dt
import unittest
from pathlib import Path

from stonksmith.helpers.tsp import (
    CLOSING_BALANCE_LABEL,
    CLOSING_UNITS_LABEL,
    CONTRIBUTIONS_LABEL,
    TSP_FUNDS,
    UNIT_PRICE_LABEL,
    employer_total,
    fund_prices,
    fund_values,
    price_on,
    statement_funds,
    statement_period,
    to_number,
)

HERE = Path(__file__).resolve().parent
PRICES = HERE / "tsp_prices.csv"
STATEMENT = HERE / "tsp_statement.txt"
MULTIFUND = HERE / "tsp_statement_multifund.txt"


def _prices() -> dict[dt.date, dict[str, float]]:
    return fund_prices(text=PRICES.read_text(encoding="utf-8"))


def _statement() -> str:
    return STATEMENT.read_text(encoding="utf-8")


def _multifund() -> str:
    return MULTIFUND.read_text(encoding="utf-8")


class NumberTests(unittest.TestCase):
    def test_reads_a_money_figure(self) -> None:
        self.assertEqual(to_number(text="$1,234.56"), 1234.56)

    def test_reads_a_unit_count(self) -> None:
        self.assertEqual(to_number(text="100.000"), 100.0)

    def test_reads_a_six_decimal_price(self) -> None:
        self.assertEqual(to_number(text="20.000000"), 20.0)

    def test_a_sign_inside_the_dollar_sign_is_kept(self) -> None:
        # TSP writes a negative cash balance "$-25.00", with the minus after
        # the currency symbol rather than before it.
        self.assertEqual(to_number(text="$-25.00"), -25.0)

    def test_a_sign_outside_the_dollar_sign_is_kept(self) -> None:
        self.assertEqual(to_number(text="-$25.00"), -25.0)

    def test_text_with_no_number_is_not_a_number(self) -> None:
        self.assertIsNone(to_number(text="Closing Units"))
        self.assertIsNone(to_number(text=""))


class PriceFileTests(unittest.TestCase):
    def test_the_trailing_separator_line_is_not_a_price_row(self) -> None:
        # The published file ends with ",,,,,,,,,,,,,,,," -- all separators and
        # no date. Unguarded it becomes a date-less entry that every later
        # lookup has to step around.
        prices = _prices()

        self.assertTrue(all(isinstance(day, dt.date) for day in prices))
        self.assertEqual(len(prices), 8)

    def test_a_blank_cell_is_absent_rather_than_zero(self) -> None:
        # The L funds are blank back to 2003 because they did not exist yet.
        # Reading a blank as 0.0 would value an account at nothing on every
        # date before its fund launched -- a plausible-looking number, which is
        # the dangerous kind of wrong.
        oldest = _prices()[dt.date(2003, 5, 31)]

        self.assertNotIn("L 2060", oldest)
        self.assertEqual(oldest["G Fund"], 10.0)

    def test_every_published_fund_is_read(self) -> None:
        self.assertEqual(set(_prices()[dt.date(2026, 8, 5)]), set(TSP_FUNDS))

    def test_the_statement_price_matches_the_public_file(self) -> None:
        # The load-bearing fact for the whole broker: the public feed carries
        # the same number TSP marked the account with.
        self.assertEqual(_prices()[dt.date(2026, 6, 30)]["L 2060"], 24.299)


class PriceLookupTests(unittest.TestCase):
    def test_reads_the_price_on_a_trading_day(self) -> None:
        self.assertEqual(
            price_on(prices=_prices(), fund="L 2060", day=dt.date(2026, 6, 30)),
            (dt.date(2026, 6, 30), 24.299),
        )

    def test_a_non_trading_day_falls_back_and_says_so(self) -> None:
        # Returning the date alongside the price is what lets a caller report
        # how stale a mark is rather than present Friday's number as today's.
        self.assertEqual(
            price_on(prices=_prices(), fund="L 2060", day=dt.date(2026, 8, 2)),
            (dt.date(2026, 7, 31), 24.0756),
        )

    def test_a_date_before_the_fund_existed_has_no_price(self) -> None:
        self.assertIsNone(
            price_on(prices=_prices(), fund="L 2060", day=dt.date(2010, 1, 4))
        )

    def test_an_unknown_fund_has_no_price(self) -> None:
        self.assertIsNone(
            price_on(prices=_prices(), fund="Q Fund", day=dt.date(2026, 6, 30))
        )


class StatementTests(unittest.TestCase):
    def test_reads_the_reporting_period(self) -> None:
        self.assertEqual(
            statement_period(text=_statement()),
            (dt.date(2026, 4, 1), dt.date(2026, 6, 30)),
        )

    def test_a_document_with_no_period_is_not_a_statement(self) -> None:
        self.assertIsNone(statement_period(text="no dates here"))

    def test_reads_the_fund(self) -> None:
        self.assertEqual(statement_funds(text=_statement()), ["L 2060"])

    def test_reads_units_and_price(self) -> None:
        text = _statement()
        self.assertEqual(
            fund_values(text=text, label=CLOSING_UNITS_LABEL, count=1), [100.0]
        )
        self.assertEqual(
            fund_values(text=text, label=UNIT_PRICE_LABEL, count=1), [20.0]
        )

    def test_units_times_price_is_the_closing_balance(self) -> None:
        # The property the whole broker rests on, asserted rather than assumed.
        text = _statement()
        units = fund_values(text=text, label=CLOSING_UNITS_LABEL, count=1)[0]
        price = fund_values(text=text, label=UNIT_PRICE_LABEL, count=1)[0]
        closing = fund_values(text=text, label=CLOSING_BALANCE_LABEL, count=1)[0]

        self.assertAlmostEqual(units * price, closing, places=2)

    def test_reads_the_employer_total(self) -> None:
        # Read, never assumed: whether agency money arrives depends on the
        # member's retirement system, and a default would either invent money
        # that never comes or hide money that does.
        self.assertEqual(employer_total(text=_statement()), 0.0)

    def test_a_zero_employer_total_is_a_value_not_a_missing_one(self) -> None:
        self.assertIsNotNone(employer_total(text=_statement()))

    def test_a_statement_without_the_employer_line_reports_nothing(self) -> None:
        self.assertIsNone(employer_total(text="Closing Balance $1.00"))


class MultiFundStatementTests(unittest.TestCase):
    """A second fund puts every value on the same line as the first.

    Reading only the leading number would silently drop every fund but one --
    an account would lose most of its value with nothing to notice, since the
    remaining fund still reports a perfectly reasonable balance.
    """

    def test_fund_names_are_matched_not_split_on_whitespace(self) -> None:
        # Every fund name contains a space, so splitting "Fund Name L 2060
        # C Fund" naively yields "L", "2060", "C", "Fund".
        self.assertEqual(statement_funds(text=_multifund()), ["L 2060", "C Fund"])

    def test_every_fund_is_read_from_a_shared_row(self) -> None:
        text = _multifund()
        self.assertEqual(
            fund_values(text=text, label=CLOSING_UNITS_LABEL, count=2),
            [100.0, 50.0],
        )
        self.assertEqual(
            fund_values(text=text, label=UNIT_PRICE_LABEL, count=2),
            [20.0, 30.0],
        )

    def test_each_fund_reconciles_on_its_own(self) -> None:
        text = _multifund()
        units = fund_values(text=text, label=CLOSING_UNITS_LABEL, count=2)
        prices = fund_values(text=text, label=UNIT_PRICE_LABEL, count=2)
        closing = fund_values(text=text, label=CLOSING_BALANCE_LABEL, count=2)

        for i, fund in enumerate(iterable=statement_funds(text=text)):
            with self.subTest(fund=fund):
                self.assertAlmostEqual(units[i] * prices[i], closing[i], places=2)

    def test_the_account_summary_is_not_mistaken_for_the_fund_table(self) -> None:
        # The bug this fixture caught. "Closing Balance" appears twice: once in
        # the account summary as a single aggregate ($3,500.00) and once in the
        # per-fund table as one figure per fund. An unscoped search finds the
        # aggregate first -- which reads correctly on a one-fund statement,
        # where the two are the same number, and loses a fund on any other.
        self.assertEqual(
            fund_values(text=_multifund(), label=CLOSING_BALANCE_LABEL, count=2),
            [2000.0, 1500.0],
        )

    def test_contributions_are_read_per_fund(self) -> None:
        self.assertEqual(
            fund_values(text=_multifund(), label=CONTRIBUTIONS_LABEL, count=2),
            [200.0, 100.0],
        )

    def test_a_nonzero_employer_total_is_read_the_same_way(self) -> None:
        # Nothing here is specific to a zero: if agency money ever appears it
        # is picked up with no config change.
        self.assertEqual(employer_total(text=_multifund()), 175.0)


if __name__ == "__main__":
    unittest.main()
