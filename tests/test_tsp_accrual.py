"""Accounting for the contributions a unit count has not caught up with yet.

A TSP unit count is exact on the day a statement states it and short by one
contribution a month afterwards. That was the broker's one known inaccuracy: it
was bounded, it corrected itself at the next statement, and it was reported --
but it was still wrong, and by a growing amount.

Basic pay is public, published per pay grade and time in service, so a member
who knows their grade, their service date and what fraction of pay they and
their agency contribute has everything needed to say what those missing months
bought. What that produces is an *estimate*, and the tests below are mostly
about the ways it must refuse to produce one rather than about the arithmetic:
an estimate that quietly stands in for a count is worse than no estimate.

Nothing here touches the network or the real config file.
"""

import datetime as dt
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

from helpers.dfas import basic_pay_table
from helpers.tsp import fund_prices, price_on
from modules.tsp_module import ESTIMATED, TspModule, accrue_units, posting_dates

HERE = Path(__file__).resolve().parent
PRICES = HERE / "tsp_prices.csv"
PAY_TABLE = HERE / "dfas_basic_pay_em.html"

#: The fixture's newest price date, so a run reads as if it happened then.
TODAY = dt.date(2026, 8, 5)

#: The last statement's period end, and the fixture's oldest recent price.
ANCHOR = "2026-03-31"

#: An E-7 who crosses ten years of service on 2026-03-15, so a window opened at
#: the end of March is entirely on the far side of the band -- and one opened
#: earlier straddles it.
BASD = dt.date(2016, 3, 14)

MEMBER_PCT = 5.0
AGENCY_PCT = 5.0


def _table() -> dict[str, dict[str, float]]:
    return basic_pay_table(html=PAY_TABLE.read_text(encoding="utf-8"))


def _prices() -> dict[dt.date, dict[str, float]]:
    return fund_prices(text=PRICES.read_text(encoding="utf-8"))


def _connection(
    table: dict[str, dict[str, float]] | None = None,
    grade: str = "E-7",
    basd: dt.date | None = BASD,
    effective: dt.date | None = dt.date(2026, 1, 1),
) -> MagicMock:
    """A TSP connection carrying prices and, unless emptied, a pay table."""

    connection = MagicMock()
    connection.client = _prices()
    connection.fund = "L 2060"
    connection.username = "public data"
    connection.pay_table = _table() if table is None else table
    connection.grade = grade
    connection.basd = basd
    connection.pay_effective = effective
    return connection


def _context(units: float | None = 100.0, as_of: str | None = ANCHOR) -> MagicMock:
    context = MagicMock()
    context.args = Namespace(
        units=units, units_as_of=as_of, balance=None, balance_as_of=None
    )
    return context


def _said(mock_log) -> str:
    return " ".join(
        str(object=call.kwargs.get("msg", "")) for call in mock_log.call_args_list
    )


class PostingDateTests(unittest.TestCase):
    def test_one_date_a_month_over_the_window(self) -> None:
        self.assertEqual(
            posting_dates(
                start=dt.date(2026, 3, 31), end=dt.date(2026, 8, 5), day=None
            ),
            [
                dt.date(2026, 4, 30),
                dt.date(2026, 5, 31),
                dt.date(2026, 6, 30),
                dt.date(2026, 7, 31),
            ],
        )

    def test_the_anchor_date_itself_is_not_counted_again(self) -> None:
        # The unit count was already true on that date, so a contribution that
        # posted the same day is in it. Counting it here is a double count --
        # the one error this whole path exists to avoid.
        dates = posting_dates(
            start=dt.date(2026, 3, 31), end=dt.date(2026, 8, 5), day=None
        )

        self.assertNotIn(dt.date(2026, 3, 31), dates)

    def test_a_configured_day_is_used_instead_of_month_end(self) -> None:
        self.assertEqual(
            posting_dates(start=dt.date(2026, 3, 31), end=dt.date(2026, 6, 5), day=1),
            [dt.date(2026, 4, 1), dt.date(2026, 5, 1), dt.date(2026, 6, 1)],
        )

    def test_a_day_past_the_end_of_a_short_month_is_clamped(self) -> None:
        # Otherwise a member paid on the 31st would silently skip February --
        # and March's 31st has not arrived yet, so the window holds one month.
        self.assertEqual(
            posting_dates(start=dt.date(2026, 1, 31), end=dt.date(2026, 3, 5), day=31),
            [dt.date(2026, 2, 28)],
        )

    def test_a_window_shorter_than_a_month_accrues_nothing(self) -> None:
        self.assertEqual(
            posting_dates(start=dt.date(2026, 8, 1), end=dt.date(2026, 8, 5), day=None),
            [],
        )

    def test_a_window_spanning_a_year_end_keeps_going(self) -> None:
        self.assertEqual(
            posting_dates(
                start=dt.date(2025, 11, 30), end=dt.date(2026, 2, 5), day=None
            ),
            [dt.date(2025, 12, 31), dt.date(2026, 1, 31)],
        )


class AccrualArithmeticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = _table()
        self.prices = _prices()

    def _accrue(self, dates: list[dt.date], basd: dt.date = BASD):
        return accrue_units(
            prices=self.prices,
            fund="L 2060",
            table=self.table,
            grade="E-7",
            basd=basd,
            percent=MEMBER_PCT + AGENCY_PCT,
            dates=dates,
        )

    def test_dollars_are_a_share_of_basic_pay_and_units_are_dollars_over_price(
        self,
    ) -> None:
        accruals, notes = self._accrue(dates=[dt.date(2026, 6, 30)])

        self.assertEqual(notes, [])
        (one,) = accruals
        # E-7 "Over 10" is $5,300.40; 10% of it is $530.04; L 2060 closed at
        # 24.2990 on 2026-06-30.
        self.assertEqual(one.band, "Over 10")
        self.assertEqual(one.basic_pay, 5300.40)
        self.assertAlmostEqual(one.dollars, 530.04, places=6)
        self.assertEqual(one.price, 24.2990)
        self.assertAlmostEqual(one.units, 530.04 / 24.2990, places=9)

    def test_a_posting_date_the_market_was_shut_uses_the_price_before_it(self) -> None:
        # 31 May 2026 is a Sunday; the fixture's newest price on or before it is
        # 29 May. TSP does not revalue on a weekend, so that *is* the price the
        # contribution bought at.
        (one,), _notes = self._accrue(dates=[dt.date(2026, 5, 31)])

        self.assertEqual(one.posted_on, dt.date(2026, 5, 31))
        self.assertEqual(one.price_date, dt.date(2026, 5, 29))
        self.assertEqual(one.price, 24.2845)

    def test_time_in_service_is_recomputed_at_every_posting_date(self) -> None:
        # This member crosses ten years on 2026-03-15. A single lookup for the
        # window would pay them at one rate for both months, which is the sort
        # of error that never looks wrong.
        accruals, _notes = self._accrue(
            dates=[dt.date(2026, 2, 28), dt.date(2026, 4, 30)]
        )
        early, late = accruals

        self.assertEqual((early.band, early.basic_pay), ("Over 8", 5135.70))
        self.assertEqual((late.band, late.basic_pay), ("Over 10", 5300.40))

    def test_a_month_with_no_published_price_is_said_rather_than_skipped(self) -> None:
        # A silent zero is indistinguishable from a month the member genuinely
        # did not contribute, and understates the account by exactly the amount
        # nobody was told about.
        accruals, notes = self._accrue(dates=[dt.date(2019, 1, 31)])

        self.assertEqual(accruals, [])
        self.assertIn("No published L 2060 price", notes[0])

    def test_a_grade_with_no_rate_at_that_band_is_said(self) -> None:
        accruals, notes = accrue_units(
            prices=self.prices,
            fund="L 2060",
            table=self.table,
            grade="E-9",
            basd=dt.date(2025, 1, 1),
            percent=MEMBER_PCT + AGENCY_PCT,
            dates=[dt.date(2026, 6, 30)],
        )

        self.assertEqual(accruals, [])
        self.assertIn("no E-9 rate", notes[0])


class AccrualReportTests(unittest.TestCase):
    """What reaches the run, and every way it declines to guess."""

    def _accrue(self, context: MagicMock, connection: MagicMock) -> float:
        with (
            patch(
                "modules.tsp_module.get_tsp_contributions",
                return_value=(MEMBER_PCT, AGENCY_PCT),
            ),
            patch("modules.tsp_module.get_tsp_contribution_day", return_value=None),
        ):
            return TspModule.accrue(
                context=context,
                connection=connection,
                prices=_prices(),
                fund="L 2060",
                as_of=str(object=context.args.units_as_of or ""),
                today=TODAY,
            )

    def test_four_months_of_contributions_come_back_as_units(self) -> None:
        context = _context()
        accrued = self._accrue(context=context, connection=_connection())

        prices = _prices()
        expected = sum(
            5300.40 * 0.10 / price_on(prices=prices, fund="L 2060", day=when)[1]
            for when in (
                dt.date(2026, 4, 30),
                dt.date(2026, 5, 31),
                dt.date(2026, 6, 30),
                dt.date(2026, 7, 31),
            )
        )

        self.assertAlmostEqual(accrued, expected, places=9)
        self.assertIn("4 month(s)", _said(context.log.success))

    def test_the_run_prints_its_working(self) -> None:
        # A lone "12.04 units" is unauditable. The same number beside the grade,
        # the band, the pay and the price can be checked against an LES.
        context = _context()
        self._accrue(context=context, connection=_connection())

        shown = _said(context.log.display)
        self.assertIn("E-7 Over 10", shown)
        self.assertIn("5,300.40", shown)
        self.assertIn("2026-06-30", shown)

    def test_no_pay_table_accrues_nothing_and_says_nothing(self) -> None:
        # The broker already reported why it has no table; a second line here
        # would name the same problem twice.
        context = _context()
        connection = _connection(table={})
        connection.pay_table = None

        self.assertEqual(self._accrue(context=context, connection=connection), 0.0)
        self.assertEqual(_said(context.log.highlight), "")
        self.assertEqual(_said(context.log.fail), "")

    def test_a_connection_that_never_heard_of_a_pay_table_accrues_nothing(self) -> None:
        # A bare MagicMock answers every getattr with a truthy mock, which is
        # exactly what a duck-typed connection does in the wild -- so the guard
        # has to be on the type, not on the truthiness.
        self.assertEqual(self._accrue(context=_context(), connection=MagicMock()), 0.0)

    def test_no_anchor_date_refuses_rather_than_guessing_a_window(self) -> None:
        # Without a date the unit count was true there is nothing to measure the
        # months since, and any window picked would be invented.
        context = _context(as_of="")

        self.assertEqual(self._accrue(context=context, connection=_connection()), 0.0)
        self.assertIn("units_as_of", _said(context.log.highlight))

    def test_an_unreadable_anchor_date_is_left_to_report(self) -> None:
        # report() already says the date is unreadable, in those words.
        context = _context(as_of="June")

        self.assertEqual(self._accrue(context=context, connection=_connection()), 0.0)

    def test_a_window_before_the_pay_raise_is_flagged_not_hidden(self) -> None:
        # DFAS publishes only the current year, so contributions from before 1
        # January are priced at rates that came in after them. Worth an estimate
        # and worth saying so.
        context = _context(as_of="2025-10-31")
        self._accrue(context=context, connection=_connection())

        self.assertIn("before the pay table took effect", _said(context.log.highlight))

    def test_a_missing_percentage_accrues_nothing(self) -> None:
        context = _context()

        with patch(
            "modules.tsp_module.get_tsp_contributions", return_value=(5.0, None)
        ):
            self.assertEqual(
                TspModule.accrue(
                    context=context,
                    connection=_connection(),
                    prices=_prices(),
                    fund="L 2060",
                    as_of=ANCHOR,
                    today=TODAY,
                ),
                0.0,
            )


class MarkWithAnEstimateTests(unittest.TestCase):
    """The estimate has to stay visible everywhere the value goes."""

    def _run(self, context: MagicMock, connection: MagicMock) -> bool:
        with (
            patch("modules.tsp_module.sync"),
            patch("modules.tsp_module.SnapshotDbProtocol", MagicMock),
            patch("modules.tsp_module.get_tsp_units", return_value=(None, "")),
            patch(
                "modules.tsp_module.get_tsp_contributions",
                return_value=(MEMBER_PCT, AGENCY_PCT),
            ),
            patch("modules.tsp_module.get_tsp_contribution_day", return_value=None),
            patch("modules.tsp_module.dt", _FrozenDate),
        ):
            return TspModule().on_login(context=context, connection=connection)

    def test_the_value_is_the_anchor_plus_the_estimate(self) -> None:
        context = _context()
        context.db = MagicMock()

        self.assertTrue(self._run(context=context, connection=_connection()))

        saved = context.db.save_snapshot.call_args.kwargs
        holdings = saved["holdings"]
        self.assertEqual(len(holdings), 2)
        self.assertAlmostEqual(
            saved["value"], sum(one.value for one in holdings), places=6
        )
        self.assertAlmostEqual(
            saved["value"], (100.0 + holdings[1].units) * 24.7344, places=6
        )

    def test_the_estimate_is_its_own_holding_and_says_so(self) -> None:
        # Two rows that sum to the account's value keep "how much of this is a
        # guess" answerable from the database, not only from a log line.
        context = _context()
        context.db = MagicMock()

        self._run(context=context, connection=_connection())

        anchored, estimated = context.db.save_snapshot.call_args.kwargs["holdings"]
        self.assertEqual(anchored.units, 100.0)
        self.assertEqual(anchored.raw_value, ANCHOR)
        self.assertIn("estimated contributions", estimated.name)
        self.assertEqual(estimated.raw_value, ESTIMATED)
        self.assertEqual(estimated.price, anchored.price)

    def test_the_mark_line_separates_the_two_counts(self) -> None:
        context = _context()
        context.db = MagicMock()

        self._run(context=context, connection=_connection())

        said = _said(context.log.success)
        self.assertIn("anchored", said)
        self.assertIn("estimated", said)

    def test_without_an_accrual_the_run_writes_exactly_what_it_always_did(self) -> None:
        # The backward compatibility guarantee: nothing configured, nothing
        # added, one holding, the same line.
        context = _context()
        context.db = MagicMock()
        connection = _connection()
        connection.pay_table = None

        self._run(context=context, connection=connection)

        saved = context.db.save_snapshot.call_args.kwargs
        self.assertEqual(len(saved["holdings"]), 1)
        self.assertAlmostEqual(saved["value"], 100.0 * 24.7344, places=6)
        self.assertNotIn("anchored", _said(context.log.success))


class _FrozenDatetime(dt.datetime):
    """dt.datetime.now() pinned to the fixture's newest price date."""

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return dt.datetime(TODAY.year, TODAY.month, TODAY.day, tzinfo=tz)


class _FrozenDate:
    """Stands in for the module's ``dt``, so "today" is the fixture's last day."""

    date = dt.date
    datetime = _FrozenDatetime
    timedelta = dt.timedelta
    UTC = dt.UTC


if __name__ == "__main__":
    unittest.main()
