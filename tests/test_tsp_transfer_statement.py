# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""A statement spanning an interfund transfer, which reads exactly backwards.

Found by running the parser against a real annual statement. Its activity table
looks like this -- these four rows are the live ones, everything else in
tests/tsp_statement_transfer.txt is invented around them:

    Fund Name        All Funds Total  L 2050  L 2060
    Closing Balance  $7,810.84        $0.00   $7,810.84
    Closing Units    315.789
    Unit Price (NAV) 24.734400

Two things there had never been seen before, because neither existing fixture
has them, and each is a separate defect.

**The leading column is not a fund.** "All Funds Total" carries no fund name, so
statement_funds() reports two funds while every value row carries three figures.
Reading from the left assigned the account total to L 2050 and dropped L 2060
entirely -- reporting the emptied fund as holding everything and the fund
actually held as holding nothing. An exact inversion, in an ordinary-looking
row.

**The unit row is short.** Nothing is printed for the fund that was emptied, so
one figure sits under a two-fund header and position cannot say whose it is. It
was paired with funds[0]: the right unit count under the wrong fund's name.

What that produced live was a mark of $7,790.83 where the truth was $7,790.82 --
off by a cent, from units that were right and a label that was not. The fund
guard then refused it, correctly, and advised setting the configured fund to
L 2050, which would have priced L 2060's units with L 2050's price and been
wrong by ninety percent in the other direction.

The balances are what resolve it: they are printed per fund, and one of them is
zero. That is an answer on the page rather than a guess, and it is confirmed
against the statement's own arithmetic before being used.
"""

import tempfile
import unittest
from pathlib import Path

from helpers.tsp import (
    CLOSING_BALANCE_LABEL,
    fund_values,
    leading_columns,
    sole_position,
    statement_funds,
)
from modules.tsp_module import read_statement, statement_reconciles

HERE = Path(__file__).resolve().parent
TRANSFER = HERE / "tsp_statement_transfer.txt"
SINGLE = HERE / "tsp_statement.txt"
MULTI = HERE / "tsp_statement_multifund.txt"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class _EditedStatement(unittest.TestCase):
    """Write a doctored statement somewhere that is neither $HOME nor the repo."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def written(self, text: str) -> str:
        path = Path(self._dir.name) / "statement.txt"
        path.write_text(text, encoding="utf-8")
        return str(object=path)


class AggregateColumn(unittest.TestCase):
    """The account-wide total has to be recognised as not a fund."""

    def test_it_is_counted_on_a_statement_that_has_one(self) -> None:
        self.assertEqual(leading_columns(text=_text(TRANSFER)), 1)

    def test_and_not_on_one_that_does_not(self) -> None:
        self.assertEqual(leading_columns(text=_text(SINGLE)), 0)
        self.assertEqual(leading_columns(text=_text(MULTI)), 0)

    def test_the_balances_land_on_the_right_funds(self) -> None:
        # THE inversion. Before this, L 2050 read $7,810.84 and L 2060 $0.00 --
        # the emptied fund holding everything, the held fund holding nothing.
        text = _text(TRANSFER)
        funds = statement_funds(text=text)

        balances = fund_values(text=text, label=CLOSING_BALANCE_LABEL, count=len(funds))

        self.assertEqual(
            dict(zip(funds, balances, strict=True)),
            {
                "L 2050": 0.0,
                "L 2060": 7810.84,
            },
        )

    def test_no_fund_is_dropped_off_the_end(self) -> None:
        text = _text(TRANSFER)
        funds = statement_funds(text=text)

        balances = fund_values(text=text, label=CLOSING_BALANCE_LABEL, count=len(funds))

        self.assertEqual(len(balances), len(funds))


class UnalignedRow(_EditedStatement):
    """A row matching neither shape is handed over whole, not trimmed.

    Trimming to the first `count` values would be this PR's own bug pointed the
    other way: the transfer statement's extra column is on the *left*, so
    taking the leftmost values is precisely what read it backwards. An
    over-long row means the table is not the shape the header describes, and
    there is nothing on the page saying which end the extras belong to.
    """

    #: A percentage after the balances. AMOUNT matches bare numbers, so "100%"
    #: parses as a fourth figure on a three-column row.
    LONG = "Closing Balance $7,810.84 $0.00 $7,810.84 100%"

    def test_the_extra_value_is_not_trimmed_away(self) -> None:
        text = _text(TRANSFER).replace(
            "Closing Balance $7,810.84 $0.00 $7,810.84", self.LONG
        )

        values = fund_values(text=text, label=CLOSING_BALANCE_LABEL, count=2)

        self.assertEqual(values, [7810.84, 0.0, 7810.84, 100.0])

    def test_and_the_fund_it_would_have_named_is_refused(self) -> None:
        text = _text(TRANSFER).replace(
            "Closing Balance $7,810.84 $0.00 $7,810.84", self.LONG
        )

        self.assertIsNone(sole_position(text=text))

    def test_so_the_statement_yields_no_units(self) -> None:
        text = _text(TRANSFER).replace(
            "Closing Balance $7,810.84 $0.00 $7,810.84", self.LONG
        )

        units, fund, _period = read_statement(path=self.written(text=text))

        self.assertIsNone(units)
        self.assertEqual(fund, "")


class PeriodSurvives(_EditedStatement):
    """The period is a property of the statement, not of its fund table.

    It used to be read after the fund checks, so every path that gave up before
    reaching them reported no period -- not because the statement stated none,
    but because nobody had looked yet.
    """

    def test_a_statement_with_no_activity_table_still_dates_itself(self) -> None:
        text = "Account Summary 04-01-2026 to 06-30-2026\n"

        _units, _fund, period = read_statement(path=self.written(text=text))

        self.assertEqual(str(object=period), "2026-06-30")

    def test_and_so_does_one_whose_unit_row_is_missing(self) -> None:
        text = _text(TRANSFER).replace("Closing Units 315.789", "")

        _units, _fund, period = read_statement(path=self.written(text=text))

        self.assertEqual(str(object=period), "2026-06-30")

    def test_a_file_that_would_not_open_dates_nothing(self) -> None:
        # Nothing was read, so there is nothing to have found. Distinct from
        # having looked and found no period.
        self.assertEqual(read_statement(path="/nonexistent.pdf"), (None, "", None))


class SolePosition(unittest.TestCase):
    """Naming the fund a short row belongs to, from the balances."""

    def test_the_fund_still_holding_money_is_found(self) -> None:
        self.assertEqual(sole_position(text=_text(TRANSFER)), ("L 2060", 7810.84))

    def test_two_live_funds_are_refused_rather_than_picked_between(self) -> None:
        # Both funds hold money, so a lone figure genuinely is ambiguous and
        # there is nothing on the page that resolves it.
        self.assertIsNone(sole_position(text=_text(MULTI)))

    def test_a_statement_with_no_funds_at_all_is_refused(self) -> None:
        self.assertIsNone(sole_position(text="Activity Detail by Fund\n"))


class ReadStatement(_EditedStatement):
    """What the module actually asks for."""

    def test_the_units_come_back_under_the_fund_that_holds_them(self) -> None:
        units, fund, _period = read_statement(path=str(object=TRANSFER))

        self.assertEqual(units, 315.789)
        self.assertEqual(fund, "L 2060")

    def test_not_under_the_fund_that_was_emptied(self) -> None:
        # The whole bug in one line: the label used to say L 2050.
        _units, fund, _period = read_statement(path=str(object=TRANSFER))

        self.assertNotEqual(fund, "L 2050")

    def test_the_period_end_still_parses(self) -> None:
        _units, _fund, period = read_statement(path=str(object=TRANSFER))

        self.assertEqual(str(object=period), "2026-06-30")

    def test_an_aligned_statement_is_unchanged(self) -> None:
        self.assertEqual(read_statement(path=str(object=SINGLE))[:2], (100.0, "L 2060"))

    def test_and_so_is_a_two_fund_one(self) -> None:
        self.assertEqual(read_statement(path=str(object=MULTI))[:2], (100.0, "L 2060"))

    def test_an_unresolvable_short_row_names_no_fund_at_all(self) -> None:
        # Rather than naming the wrong one. Two live funds and one unit figure:
        # nothing on the page says which, so nothing is claimed.
        unresolvable = _text(MULTI).replace(
            "Closing Units 100.000 50.000", "Closing Units 100.000"
        )

        units, fund, _period = read_statement(path=self.written(text=unresolvable))

        self.assertIsNone(units)
        self.assertEqual(fund, "")

    def test_a_short_row_that_does_not_reconcile_is_refused(self) -> None:
        # The balances name a fund, but the arithmetic on the page disagrees --
        # so the three figures are not describing the same position and the
        # parse cannot be trusted to have found the right rows.
        wrong = _text(TRANSFER).replace(
            "Closing Units 315.789", "Closing Units 999.999"
        )

        units, fund, _period = read_statement(path=self.written(text=wrong))

        self.assertIsNone(units)
        self.assertEqual(fund, "")


class Reconciliation(unittest.TestCase):
    """The tolerance has to come from the printing, not from a round number."""

    def test_the_real_statement_reconciles(self) -> None:
        # 315.789 x 24.734400 = 7810.8514, printed as 7810.84. Off by 1.1
        # cents, and right: the unit count is printed to three decimals, so at
        # this price it stands for over a cent of balance either way. A flat
        # cent of tolerance called this broken.
        self.assertTrue(
            statement_reconciles(text_units=315.789, price=24.7344, closing=7810.84)
        )

    def test_a_genuinely_wrong_row_still_fails(self) -> None:
        self.assertFalse(
            statement_reconciles(text_units=315.789, price=24.7344, closing=14794.59)
        )

    def test_the_tolerance_scales_with_the_price(self) -> None:
        # A cent of drift is within the printing at $24 a unit and nowhere near
        # it at $0.01, so a fixed tolerance is wrong in one direction or the
        # other whatever number is picked.
        self.assertFalse(
            statement_reconciles(text_units=100.0, price=0.01, closing=1.02)
        )

    def test_the_round_fixture_figures_still_reconcile(self) -> None:
        self.assertTrue(
            statement_reconciles(text_units=100.0, price=20.0, closing=2000.0)
        )


if __name__ == "__main__":
    unittest.main()
