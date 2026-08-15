"""An account you can see but cannot scrape, valued without inventing anything.

Some accounts have no API, no scrapeable page and no export -- a plan portal
that shows a balance and a fund and offers nothing else. Leaving one out makes
every total short by its value while looking complete, which is the failure this
project keeps designing against and, unlike a broker that breaks, one that never
announces itself.

**What is stored is a unit count, never a balance**, and that is the whole
design rather than a detail. The [TSP] config comment states the rule in one
line: a balance is true for one day, so storing it would leave a value that
silently rots. Units move only when money does, so an account nobody is funding
has a count that stays exactly right while a published price does the moving.

A hardcoded balance would be correct the morning it was typed and wrong every
morning after -- and because it feeds the net worth series it would draw a flat
line through one slice of the portfolio while looking entirely like data. That
is what these cases exist to prevent, so the parsing ones are about refusing
input that would produce a plausible wrong number, and the module ones are about
what a mark is allowed to say when the price is missing.
"""

import datetime as dt
import unittest
from argparse import Namespace
from typing import Any
from unittest.mock import MagicMock, patch

from config_isolation import UserConfigMixin
from stonksmith.etc.config import ManualHolding, get_manual_accounts
from stonksmith.modules.manual_module import StonkSmithModule


class TheConfigParsesWhatTheCommentPromises(UserConfigMixin, unittest.TestCase):
    config_body: str = (
        "[MANUAL]\n"
        "accounts =\n"
        "    Sam Custodial | SPYM | 2.000000 | 2026-08-10 | 150.00\n"
        "    No Cost Known | VOO | 2.5 | 2026-08-01\n"
    )

    def test_it_reads_five_fields(self) -> None:
        accounts, refused = get_manual_accounts()

        self.assertEqual(refused, [])
        self.assertEqual(
            accounts[0],
            ManualHolding(
                name="Sam Custodial",
                symbol="SPYM",
                units=2.000000,
                units_as_of="2026-08-10",
                cost_basis=150.00,
            ),
        )

    def test_the_fifth_field_is_optional(self) -> None:
        # Most portals that cannot be scraped cannot be asked what was paid
        # either, and None rather than 0.0 is what makes the brief render a dash
        # instead of reporting a position that gained its entire value.
        accounts, _ = get_manual_accounts()

        self.assertEqual(accounts[1].units, 2.5)
        self.assertIsNone(accounts[1].cost_basis)


class ALineThatCannotBeReadIsNamed(UserConfigMixin, unittest.TestCase):
    """Refused rather than dropped, because nothing else will ever correct it."""

    config_body: str = (
        "[MANUAL]\n"
        "accounts =\n"
        "    Good Account | SPYM | 1.5 | 2026-08-10\n"
        "    Too Few Fields | SPYM | 1.5\n"
        "    Not A Number | SPYM | one and a half | 2026-08-10\n"
        "    Blank Symbol |  | 1.5 | 2026-08-10\n"
        "    Negative | SPYM | -1.5 | 2026-08-10\n"
        "    Negative Cost | SPYM | 1.5 | 2026-08-10 | -20\n"
    )

    def setUp(self) -> None:
        super().setUp()
        self.accounts, self.refused = get_manual_accounts()

    def test_the_good_line_survives(self) -> None:
        self.assertEqual([held.name for held in self.accounts], ["Good Account"])

    def test_every_bad_line_is_reported(self) -> None:
        # Named rather than counted, and reported rather than skipped: a
        # mistyped account is otherwise indistinguishable from an account
        # nobody added, and this is hand-typed configuration that no source
        # will ever correct.
        self.assertEqual(len(self.refused), 5)

    def test_a_negative_unit_count_is_refused(self) -> None:
        # Nothing in this format can express a short position, so a minus sign
        # is a typo -- and one that would subtract from the portfolio while
        # looking like a holding.
        self.assertIn("Negative | SPYM | -1.5 | 2026-08-10", self.refused)

    def test_a_negative_cost_is_refused(self) -> None:
        # It would report a gain larger than the position is worth.
        self.assertIn("Negative Cost | SPYM | 1.5 | 2026-08-10 | -20", self.refused)


class OneFileCannotPriceTwoFunds(UserConfigMixin, unittest.TestCase):
    """--prices names one payload, and a payload carries one symbol's closes."""

    config_body: str = (
        "[MANUAL]\n"
        "accounts =\n"
        "    Sam Custodial | SPYM | 1.65 | 2026-08-10\n"
        "    Something Else | VOO | 2.5 | 2026-08-01\n"
    )

    def _broker(self, prices: str = "") -> Any:
        from stonksmith.brokers.manual.broker import Manual

        broker = Manual()
        broker.args = Namespace(prices=prices)
        broker.logger = MagicMock()
        # A readable file, so the only reason this run can fail is the refusal.
        # Naming a path that does not exist makes create_conn_obj return False
        # because nothing loaded -- which passes the assertion below with the
        # refusal deleted, and was how this test first passed for the wrong
        # reason.
        broker.read_local = MagicMock(return_value={dt.date(2026, 8, 14): 91.0})

        return broker

    def test_two_symbols_with_one_file_is_refused(self) -> None:
        # Without this the loop reads the same payload for each symbol and marks
        # a fund at another fund's price -- wrong by however far the two have
        # diverged, and written to the database without a word of complaint.
        broker = self._broker(prices="/tmp/spym.json")

        self.assertFalse(
            broker.create_conn_obj(),
            "a single price file was accepted for two symbols, so one fund is "
            "about to be marked at the other's price",
        )
        self.assertEqual(
            broker.prices, {}, "one file's closes were loaded against a symbol"
        )

    def test_the_refusal_names_both_symbols(self) -> None:
        # Refused rather than warned about: a warning scrolls past and the wrong
        # number stays. Naming them is what makes the message actionable.
        broker = self._broker(prices="/tmp/spym.json")
        broker.create_conn_obj()

        said = " ".join(str(call) for call in broker.logger.fail.call_args_list)

        self.assertIn("SPYM", said)
        self.assertIn("VOO", said)

    def test_without_the_flag_each_symbol_is_fetched(self) -> None:
        # The ordinary path is unaffected: one request per distinct symbol.
        broker = self._broker()
        broker.fetch_quotes = MagicMock(return_value={dt.date(2026, 8, 14): 91.0})

        self.assertTrue(broker.create_conn_obj())
        self.assertEqual(
            sorted(
                call.kwargs["symbol"] for call in broker.fetch_quotes.call_args_list
            ),
            ["SPYM", "VOO"],
        )


class OneFileIsFineForOneFund(UserConfigMixin, unittest.TestCase):
    """The flag's actual use, which the refusal must not have taken away."""

    config_body: str = (
        "[MANUAL]\naccounts =\n    Sam Custodial | SPYM | 1.65 | 2026-08-10\n"
    )

    def test_a_single_symbol_reads_the_file(self) -> None:
        # The refusal is conditional rather than a removal: valuing one
        # configured account against a payload saved earlier is exactly what
        # --prices is for, and is the offline path when the feed is unreachable.
        from stonksmith.brokers.manual.broker import Manual

        broker = Manual()
        broker.args = Namespace(prices="/tmp/spym.json")
        broker.logger = MagicMock()
        broker.read_local = MagicMock(return_value={dt.date(2026, 8, 14): 91.0})

        self.assertTrue(broker.create_conn_obj())
        self.assertEqual(list(broker.prices), ["SPYM"])


class TheMarkIsACountTimesAPublishedPrice(unittest.TestCase):
    def setUp(self) -> None:
        self.held = ManualHolding(
            name="Sam Custodial",
            symbol="SPYM",
            units=2.000000,
            units_as_of="2026-08-10",
            cost_basis=150.00,
        )

        self.db = MagicMock()
        self.context = MagicMock()
        self.context.db = self.db

        self.connection = MagicMock()
        self.connection.accounts = [self.held]
        self.connection.priced.return_value = (dt.date(2026, 8, 14), 91.365)

    def _run(self) -> bool | None:
        # The protocol is patched to MagicMock so the isinstance narrowing
        # admits the fake, which is what tests/test_tsp_module.py does for the
        # same check. A MagicMock has every attribute and still fails
        # isinstance against a runtime_checkable Protocol carrying non-method
        # members, so without this the module reports a contract violation and
        # writes nothing -- and every assertion below reads as a bug in the
        # module rather than in the fake.
        with patch("stonksmith.modules.manual_module.SnapshotDbProtocol", MagicMock):
            return StonkSmithModule().on_login(
                context=self.context, connection=self.connection
            )

    def test_it_writes_units_times_price(self) -> None:
        self._run()

        written = self.db.save_snapshot.call_args.kwargs

        self.assertAlmostEqual(written["value"], 182.73, places=2)

    def test_the_as_of_is_the_price_date_not_the_clock(self) -> None:
        # The same answer every other view gives to "what date is this value
        # for". It is what makes a manual account age visibly beside scraped
        # ones -- a stale price shows up in `stale` exactly as a stale scrape
        # does, rather than looking fresh because the run happened today.
        self._run()

        self.assertEqual(self.db.save_snapshot.call_args.kwargs["as_of"], "2026-08-14")

    def test_the_unit_date_rides_separately_from_the_price_date(self) -> None:
        # Two facts about one mark, days or months apart: the price is today's
        # and the count is as old as the last time anybody typed it. Folding
        # them together is what would hide how much room a missed contribution
        # has to be wrong in.
        self._run()

        holding = self.db.save_snapshot.call_args.kwargs["holdings"][0]

        self.assertEqual(holding.units_as_of, "2026-08-10")
        self.assertEqual(holding.price, 91.365)

    def test_the_cost_basis_reaches_the_holding(self) -> None:
        self._run()

        self.assertEqual(
            self.db.save_snapshot.call_args.kwargs["holdings"][0].cost_basis, 150.00
        )

    def test_it_records_no_transactions(self) -> None:
        # A movement is a fact about money changing hands and this module
        # observes none -- it prices a count. Writing the deposits that produced
        # that count would be inventing a log out of a configuration line, and
        # the brief would then report them as new movements.
        self._run()

        self.assertEqual(self.db.save_snapshot.call_args.kwargs["transactions"], [])


class AnAccountWithNoPriceIsSkippedNotZeroed(unittest.TestCase):
    def setUp(self) -> None:
        self.db = MagicMock()
        self.context = MagicMock()
        self.context.db = self.db

        self.connection = MagicMock()
        self.connection.accounts = [
            ManualHolding(
                name="Sam Custodial",
                symbol="SPYM",
                units=1.65,
                units_as_of="2026-08-10",
            )
        ]
        self.connection.priced.return_value = None

    def _run(self) -> bool | None:
        with patch("stonksmith.modules.manual_module.SnapshotDbProtocol", MagicMock):
            return StonkSmithModule().on_login(
                context=self.context, connection=self.connection
            )

    def test_nothing_is_written(self) -> None:
        # The one failure that would look like a number rather than an error.
        # An account written at zero drags a real balance to nothing in the net
        # worth series, and the series carries it forward for thirty days.
        self._run()

        self.db.save_snapshot.assert_not_called()

    def test_the_run_fails(self) -> None:
        # False is what makes a scheduled run exit non-zero. A manual broker
        # that silently records nothing is worse than one that fails: the
        # account stops appearing and a total short by it looks like a total.
        self.assertIs(self._run(), False)


if __name__ == "__main__":
    unittest.main()
