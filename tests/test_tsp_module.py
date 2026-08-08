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
    FROM_BALANCE,
    FROM_CONFIG,
    FROM_FLAG,
    FROM_STATEMENT,
    UNITS_STALE_DAYS,
    TspModule,
    pdf_text,
    read_statement,
    statement_reconciles,
    units_from_balance,
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


def _context(
    units: float | None = None,
    as_of: str | None = None,
    balance: float | None = None,
    balance_as_of: str | None = None,
) -> MagicMock:
    context = MagicMock()
    context.args = Namespace(
        units=units, units_as_of=as_of, balance=balance, balance_as_of=balance_as_of
    )
    return context


def _prices() -> dict:
    return fund_prices(text=PRICES.read_text(encoding="utf-8"))


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


class _Page:
    """Stands in for a pypdf page: extracts text, nothing, or an exception."""

    def __init__(self, text: str | None = "", error: Exception | None = None) -> None:
        self.text: str | None = text
        self.error: Exception | None = error

    def extract_text(self) -> str | None:
        if self.error is not None:
            raise self.error

        return self.text


class PdfPageTests(unittest.TestCase):
    """A statement is several pages and the units live on one of them."""

    def test_pages_are_joined_in_order(self) -> None:
        self.assertEqual(
            pdf_text(pages=[_Page(text="one"), _Page(text="two")]), "one\ntwo"
        )

    def test_a_page_with_no_text_does_not_sink_the_document(self) -> None:
        # extract_text is annotated -> str, but a None would reach str.join and
        # turn a readable statement into an unreadable one.
        self.assertIn(
            "Closing Units",
            pdf_text(pages=[_Page(text=None), _Page(text="Closing Units 100.0")]),
        )

    def test_a_page_that_raises_costs_only_that_page(self) -> None:
        pages = [
            _Page(error=ValueError("malformed content stream")),
            _Page(text="Closing Units 100.0"),
        ]

        self.assertIn("Closing Units", pdf_text(pages=pages))

    def test_no_readable_page_at_all_yields_nothing_to_parse(self) -> None:
        self.assertEqual(pdf_text(pages=[_Page(text=None)]).strip(), "")


class BalanceInversionTests(unittest.TestCase):
    """The site states a balance and a date, and never states units."""

    def test_a_balance_divides_back_into_the_units_that_made_it(self) -> None:
        # 100 units of L 2060 closed at 24.7344 on 2026-08-05, so a balance of
        # 100 x that has to invert to exactly 100 units back.
        solved = units_from_balance(
            prices=_prices(),
            fund="L 2060",
            balance=100.0 * 24.7344,
            day=dt.date(2026, 8, 5),
        )

        assert solved is not None
        units, price_date, price = solved
        self.assertAlmostEqual(units, 100.0, places=6)
        self.assertEqual((price_date, price), (dt.date(2026, 8, 5), 24.7344))

    def test_a_non_business_day_uses_the_price_the_balance_was_struck_at(self) -> None:
        # TSP does not revalue on a weekend or holiday, so a balance dated then
        # was computed with the previous business day's price -- which is the
        # one that inverts it correctly.
        solved = units_from_balance(
            prices=_prices(), fund="L 2060", balance=1000.0, day=dt.date(2026, 7, 2)
        )

        assert solved is not None
        self.assertEqual(solved[1], dt.date(2026, 6, 30))

    def test_a_fund_with_no_price_cannot_be_inverted(self) -> None:
        self.assertIsNone(
            units_from_balance(
                prices=_prices(),
                fund="Q Fund",
                balance=1000.0,
                day=dt.date(2026, 8, 5),
            )
        )

    def test_a_date_before_the_file_begins_cannot_be_inverted(self) -> None:
        self.assertIsNone(
            units_from_balance(
                prices=_prices(),
                fund="L 2060",
                balance=1000.0,
                day=dt.date(1999, 1, 1),
            )
        )


class BalanceFlagTests(unittest.TestCase):
    """Reading a balance off the site has to beat waiting for a statement."""

    def _solve(self, context: MagicMock) -> tuple[float | None, str, str]:
        return TspModule().units_for(context=context, prices=_prices(), fund="L 2060")

    def test_a_balance_becomes_a_unit_count_dated_to_the_balance(self) -> None:
        units, as_of, source = self._solve(
            context=_context(balance=100.0 * 24.7344, balance_as_of="2026-08-05")
        )

        assert units is not None
        self.assertAlmostEqual(units, 100.0, places=6)
        self.assertEqual((as_of, source), ("2026-08-05", FROM_BALANCE))

    def test_the_units_are_dated_by_the_balance_not_the_price(self) -> None:
        # Nothing moves units over a weekend, so a Saturday balance struck at
        # Friday's price still states Saturday's unit count. Dating it to the
        # price would report the count as older than it is.
        _units, as_of, _source = self._solve(
            context=_context(balance=1000.0, balance_as_of="2026-07-02")
        )

        self.assertEqual(as_of, "2026-07-02")

    def test_the_derived_count_is_printed_ready_to_store(self) -> None:
        # The balance is true for one day; the units it implies stay true until
        # the next transaction. Without this the next run is stale again.
        context = _context(balance=100.0 * 24.7344, balance_as_of="2026-08-05")

        self._solve(context=context)

        self.assertIn("[TSP] units =", _said(context.log.display))

    def test_a_balance_beats_a_typed_unit_count(self) -> None:
        _units, _as_of, source = self._solve(
            context=_context(
                units=999.0,
                as_of="2020-01-01",
                balance=100.0 * 24.7344,
                balance_as_of="2026-08-05",
            )
        )

        self.assertEqual(source, FROM_BALANCE)

    def test_a_balance_with_no_date_refuses_and_falls_through(self) -> None:
        # The same dollars buy a different number of units on a different day.
        context = _context(balance=7810.84, units=50.0, as_of="2026-06-30")

        self.assertEqual(self._solve(context=context), (50.0, "2026-06-30", FROM_FLAG))
        self.assertIn("needs --balance-as-of", _said(context.log.fail))

    def test_an_unreadable_balance_date_says_what_was_expected(self) -> None:
        context = _context(balance=7810.84, balance_as_of="August")

        with patch("modules.tsp_module.get_tsp_units", return_value=(None, "")):
            self._solve(context=context)

        self.assertIn("YYYY-MM-DD", _said(context.log.fail))

    def test_a_price_file_too_old_to_convert_against_refuses(self) -> None:
        # price_on falls back to the newest price on or before the date, which
        # is right across a weekend and wrong across a stale file: dividing a
        # current balance by an old price invents a unit count.
        context = _context(balance=7810.84, balance_as_of="2026-08-30")

        with patch("modules.tsp_module.get_tsp_units", return_value=(None, "")):
            units, _as_of, _source = self._solve(context=context)

        self.assertIsNone(units)
        self.assertIn("too wide a gap", _said(context.log.fail))

    def test_a_balance_with_no_price_file_falls_through(self) -> None:
        context = _context(
            balance=7810.84, balance_as_of="2026-08-05", units=50.0, as_of="2026-06-30"
        )

        self.assertEqual(
            TspModule().units_for(context=context), (50.0, "2026-06-30", FROM_FLAG)
        )
        self.assertIn("share price file", _said(context.log.fail))

    def test_a_statement_still_outranks_a_balance(self) -> None:
        module = TspModule()
        module.options(
            context=None, module_options={"STATEMENT": str(object=STATEMENT)}
        )

        _units, _as_of, source = module.units_for(
            context=_context(balance=7810.84, balance_as_of="2026-08-05"),
            prices=_prices(),
            fund="L 2060",
        )

        self.assertEqual(source, FROM_STATEMENT)


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

    def test_a_statement_with_no_readable_period_says_so_in_words(self) -> None:
        # Real units, no date for them. "as of None" reads like a bug rather
        # than like the missing date it is, on the one line whose whole job is
        # to say how current the number is.
        module = TspModule()
        module.options(context=None, module_options={"STATEMENT": "statement.pdf"})
        context = _context()

        with patch(
            "modules.tsp_module.read_statement", return_value=(100.0, "L 2060", None)
        ):
            self.assertEqual(
                module.units_for(context=context), (100.0, "", FROM_STATEMENT)
            )

        said = _said(context.log.success)
        self.assertIn("an unstated date", said)
        self.assertNotIn("None", said)

    def test_an_unreadable_statement_falls_through_and_says_so(self) -> None:
        module = TspModule()
        module.options(context=None, module_options={"STATEMENT": "/nonexistent.pdf"})
        context = _context(units=7.0, as_of="2026-06-30")

        self.assertEqual(
            module.units_for(context=context), (7.0, "2026-06-30", FROM_FLAG)
        )
        # Names both reasons a statement yields no unit count: unreadable, or
        # read fine but covering two live funds with nothing saying which the
        # closing units belong to. From here they are indistinguishable, and
        # claiming the first sends a run to check a file that is not the
        # problem.
        said = _said(context.log.fail)
        self.assertIn("Could not take a unit count", said)
        self.assertIn("not a TSP statement", said)
        self.assertIn("more than one fund", said)


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
