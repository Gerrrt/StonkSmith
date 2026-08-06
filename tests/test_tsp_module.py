"""Valuing TSP is arithmetic; saying how current the arithmetic is, is the job.

A TSP mark is units x share price, and the two halves are true as of different
days. The price is today's. The unit count is as old as the last statement, and
every contribution since is missing from it -- silently, because the resulting
number looks exactly like a current one.

So the module reports provenance on every mark: which input supplied the units,
what date they were true, and whether that is old enough to have missed a
contribution. A wrong number that announces itself is recoverable; a wrong
number that looks right is the failure this broker exists to avoid.
"""

import datetime as dt
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

from helpers.tsp import fund_prices
from modules.tsp_module import (
    FROM_CONFIG,
    FROM_FLAG,
    FROM_STATEMENT,
    UNITS_STALE_DAYS,
    TspModule,
    read_statement,
    statement_reconciles,
)

HERE = Path(__file__).resolve().parent
PRICES = HERE / "tsp_prices.csv"
STATEMENT = HERE / "tsp_statement.txt"
MULTIFUND = HERE / "tsp_statement_multifund.txt"

TODAY = dt.date(2026, 8, 5)


def _connection() -> MagicMock:
    """A TSP connection carrying the parsed price file."""

    connection = MagicMock()
    connection.client = fund_prices(text=PRICES.read_text(encoding="utf-8"))
    connection.fund = "L 2060"
    connection.username = "public data"
    return connection


def _context(units: float | None = None, as_of: str | None = None) -> MagicMock:
    context = MagicMock()
    context.args = Namespace(units=units, units_as_of=as_of)
    return context


def _said(mock_log) -> str:
    return " ".join(
        str(object=call.kwargs.get("msg", "")) for call in mock_log.call_args_list
    )


class StatementReadTests(unittest.TestCase):
    def test_reads_units_fund_and_period_end(self) -> None:
        self.assertEqual(
            read_statement(path=str(object=STATEMENT)),
            (100.0, "L 2060", dt.date(2026, 6, 30)),
        )

    def test_a_multi_fund_statement_reads_the_first_fund(self) -> None:
        units, fund, _as_of = read_statement(path=str(object=MULTIFUND))

        self.assertEqual((units, fund), (100.0, "L 2060"))

    def test_an_unreadable_file_reports_rather_than_raises(self) -> None:
        # The caller turns this into one actionable line; a traceback out of a
        # module is not that.
        self.assertEqual(
            read_statement(path="/nonexistent/statement.pdf"), (None, "", None)
        )

    def test_a_file_that_is_not_a_statement_reports_nothing(self) -> None:
        self.assertEqual(read_statement(path=str(object=PRICES)), (None, "", None))


class StatementIntegrityTests(unittest.TestCase):
    def test_a_statements_own_numbers_multiply_out(self) -> None:
        self.assertTrue(
            statement_reconciles(text_units=100.0, price=20.0, closing=2000.0)
        )

    def test_a_mismatch_is_caught(self) -> None:
        # Distinguishes "parsed the wrong row" from "could not open the file".
        self.assertFalse(
            statement_reconciles(text_units=100.0, price=20.0, closing=3500.0)
        )


class UnitSourceTests(unittest.TestCase):
    """Which count gets used, and whether the run says where it came from."""

    def test_a_statement_wins_and_carries_its_period_end(self) -> None:
        module = TspModule()
        module.options(
            context=None, module_options={"STATEMENT": str(object=STATEMENT)}
        )

        self.assertEqual(
            module.units_for(context=_context(units=999.0, as_of="2020-01-01")),
            (100.0, "2026-06-30", FROM_STATEMENT),
        )

    def test_the_flag_beats_config(self) -> None:
        with patch(
            "modules.tsp_module.get_tsp_units", return_value=(50.0, "2020-01-01")
        ):
            self.assertEqual(
                TspModule().units_for(
                    context=_context(units=302.0, as_of="2026-06-30")
                ),
                (302.0, "2026-06-30", FROM_FLAG),
            )

    def test_config_is_the_fallback(self) -> None:
        with patch(
            "modules.tsp_module.get_tsp_units", return_value=(100.0, "2026-06-30")
        ):
            self.assertEqual(
                TspModule().units_for(context=_context()),
                (100.0, "2026-06-30", FROM_CONFIG),
            )

    def test_an_unreadable_statement_falls_through_and_says_so(self) -> None:
        module = TspModule()
        module.options(context=None, module_options={"STATEMENT": "/nonexistent.pdf"})
        context = _context(units=7.0, as_of="2026-06-30")

        self.assertEqual(
            module.units_for(context=context), (7.0, "2026-06-30", FROM_FLAG)
        )
        self.assertIn("Could not read a unit count", _said(context.log.fail))


class StalenessReportTests(unittest.TestCase):
    """The number looks identical either way; only the report differs."""

    def test_an_old_unit_count_warns_that_contributions_are_missing(self) -> None:
        context = _context()
        old = (TODAY - dt.timedelta(days=UNITS_STALE_DAYS + 30)).isoformat()

        TspModule.report(context=context, as_of=old, source=FROM_CONFIG, today=TODAY)

        said = _said(context.log.highlight)
        self.assertIn(old, said)
        self.assertIn("short by one or more", said)

    def test_a_fresh_unit_count_does_not_cry_wolf(self) -> None:
        context = _context()
        recent = (TODAY - dt.timedelta(days=3)).isoformat()

        TspModule.report(
            context=context, as_of=recent, source=FROM_STATEMENT, today=TODAY
        )

        self.assertEqual(_said(context.log.highlight), "")
        self.assertIn(recent, _said(context.log.display))

    def test_no_as_of_date_is_reported_as_unknowable_not_assumed_fresh(self) -> None:
        context = _context()

        TspModule.report(context=context, as_of="", source=FROM_CONFIG, today=TODAY)

        self.assertIn("cannot be stated", _said(context.log.highlight))

    def test_an_unparseable_as_of_date_says_what_was_expected(self) -> None:
        context = _context()

        TspModule.report(context=context, as_of="June", source=FROM_CONFIG, today=TODAY)

        self.assertIn("YYYY-MM-DD", _said(context.log.highlight))


class MarkTests(unittest.TestCase):
    def _run(self, context: MagicMock, module: TspModule | None = None) -> bool:
        with patch("modules.tsp_module.Saver") as saver:
            saver.return_value.save_accounts.return_value = None
            return (module or TspModule()).on_login(
                context=context, connection=_connection()
            )

    def test_units_times_the_published_price_reach_the_database(self) -> None:
        context = _context(units=100.0, as_of="2026-06-30")
        context.db = MagicMock()

        with patch("modules.tsp_module.SnapshotDbProtocol", MagicMock):
            self.assertTrue(self._run(context=context))

        saved = context.db.save_snapshot.call_args.kwargs
        # L 2060 closed at 24.7344 on the fixture's newest date.
        self.assertAlmostEqual(saved["value"], 100.0 * 24.7344, places=4)

    def test_the_mark_is_dated_by_the_price_not_the_run(self) -> None:
        # They differ on a weekend or before the day's price publishes, and
        # collapsing them would date a Friday price as Sunday's.
        context = _context(units=100.0, as_of="2026-06-30")
        context.db = MagicMock()

        with patch("modules.tsp_module.SnapshotDbProtocol", MagicMock):
            self._run(context=context)

        saved = context.db.save_snapshot.call_args.kwargs
        self.assertEqual(saved["as_of"], "2026-08-05")
        self.assertNotEqual(saved["as_of"], saved["scraped_at"])

    def test_the_holding_records_units_and_price_separately(self) -> None:
        # A stored mark stays self-describing: the value can be re-derived, and
        # a wrong unit count is visible rather than baked into a total.
        context = _context(units=100.0, as_of="2026-06-30")
        context.db = MagicMock()

        with patch("modules.tsp_module.SnapshotDbProtocol", MagicMock):
            self._run(context=context)

        holding = context.db.save_snapshot.call_args.kwargs["holdings"][0]
        self.assertEqual(holding.units, 100.0)
        self.assertEqual(holding.price, 24.7344)
        self.assertEqual(holding.fund_code, "L 2060")

    def test_no_unit_count_refuses_rather_than_valuing_at_zero(self) -> None:
        # Zero units would multiply out to $0.00 -- a number, which reads as an
        # answer rather than as the missing input it is.
        context = _context()
        context.db = MagicMock()

        with patch("modules.tsp_module.get_tsp_units", return_value=(None, "")):
            self.assertFalse(self._run(context=context))

        self.assertIn("No unit count to value", _said(context.log.fail))
        context.db.save_snapshot.assert_not_called()

    def test_a_connection_with_no_prices_is_reported(self) -> None:
        context = _context(units=100.0, as_of="2026-06-30")
        connection = MagicMock()
        connection.client = None
        connection.fund = "L 2060"

        self.assertFalse(TspModule().on_login(context=context, connection=connection))
        self.assertIn("share price file", _said(context.log.fail))

    def test_a_fund_with_no_published_price_is_reported_not_valued(self) -> None:
        context = _context(units=100.0, as_of="2026-06-30")
        context.db = MagicMock()
        connection = _connection()
        connection.fund = "Q Fund"

        with patch("modules.tsp_module.Saver"):
            self.assertFalse(
                TspModule().on_login(context=context, connection=connection)
            )

        self.assertIn("No published price", _said(context.log.fail))


if __name__ == "__main__":
    unittest.main()
