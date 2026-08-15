"""A 529 states its cost under another name, and the brief was not reading it.

The Schwab 529 scraper stores ``principal`` and ``earnings`` -- 2,140.00 against
2,300.00 of value, and 160.00 of earnings, which is the subtraction exactly. It
stores no ``cost_basis``, because a plan reports contributions and growth rather
than an average purchase price: that is the split a 529 is *about*.

Everything downstream is computed from ``cost_basis``. So purchase price, gain,
growth, yield on cost and the win/loss flag were all showing a dash on that
holding while the number sat in the column beside them, and the Gain tile read
"across 10 of 13 positions; 3 report no cost basis" when only two of the three
genuinely had nothing to report.

**This is a rename, not a guess.** Principal means what was put in, which is what
a cost basis is. The distinction worth keeping is against the two holdings that
really do report nothing -- a Fidelity 401k that answers with units and price
alone, and a TSP unit count anchored to a quarterly statement -- because for
those, filling anything in would be invention. This fills a field from another
field of the same row, stated by the same source, in the same currency.

**Which is exactly why it cannot be unconditional**, and the first version of it
was. ``helpers.schwab529plan`` says so in its own docstring: principal and
earnings are *table-level totals repeated onto every row*, because the plan's
page never splits them per fund. A 529 holding two funds therefore carries the
whole account's principal on both rows -- and reading it blind would hand each
position the entire account's cost, roughly doubling the basis and inverting the
gain. An account-level number spread across positions, which is the invention
this codebase keeps refusing to commit.

The source hands over the means to tell the two apart. It states earnings as
well, so ``value - principal`` has to reproduce it: true on a row that owns the
whole account, false on a row that is one fund of several. Where it does not
hold the cost stays a dash, which is honest, rather than becoming a number
nobody can check.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_isolation import UserConfigMixin
from keyring_isolation import MemoryKeyringMixin
from stonksmith.etc.brief import positions
from stonksmith.etc.broker_db import BrokerDatabase
from stonksmith.etc.infrastructure import create_db_engine
from stonksmith.etc.portfolio import Portfolio, read_workspace
from stonksmith.etc.records import AccountIdentity, Holding


class ThePlanStatesItsCostAsPrincipal(
    UserConfigMixin, MemoryKeyringMixin, unittest.TestCase
):
    def setUp(self) -> None:
        super().setUp()

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "default").mkdir()

    def _write(self, **holding: object) -> None:
        """
        Record one 529 snapshot.
        :param holding: Whatever this case wants the position to report
        """

        db = BrokerDatabase(
            db_engine=create_db_engine(
                db_path=self.root / "default" / "schwab529plan.db"
            ),
            broker="schwab529plan",
        )
        db.save_snapshot(
            account=AccountIdentity(account_key="529-1", display_name="Sam"),
            scraped_at="2026-08-12 18:30:00",
            as_of="2026-08-12",
            value=2300.00,
            currency="USD",
            holdings=[Holding(**holding)],  # type: ignore[arg-type]
            transactions=[],
        )
        db.shutdown_db()

    def _read(self) -> Portfolio:
        with patch("stonksmith.etc.portfolio.workspace_dir", str(object=self.root)):
            return read_workspace(workspace="default")

    def test_principal_becomes_the_cost_basis(self) -> None:
        # The real row, verbatim: no symbol, a fund code, and the plan's own
        # contributions-against-earnings split.
        self._write(
            symbol="",
            fund_code="70310",
            name="2040-2041 Enrollment Portfolio",
            units=200.0000,
            price=10.85,
            value=2300.00,
            principal=2140.00,
            earnings=160.00,
        )

        row = self._read().holdings[0]

        self.assertEqual(row.cost_basis, 2140.00)

    def test_both_fields_are_still_carried_out_unchanged(self) -> None:
        # Filled, not moved. The sheet has Principal and Earnings columns of its
        # own, and a 529's split is worth reporting as a split.
        self._write(
            symbol="",
            fund_code="70310",
            units=200.0000,
            price=10.85,
            value=2300.00,
            principal=2140.00,
            earnings=160.00,
        )

        row = self._read().holdings[0]

        self.assertEqual(row.principal, 2140.00)
        self.assertEqual(row.earnings, 160.00)

    def test_a_reported_cost_basis_is_not_replaced_by_principal(self) -> None:
        # Never the reverse. A source stating both means them separately, and
        # preferring principal there would overwrite a real average over real
        # lots with a contribution total.
        self._write(
            symbol="VTI",
            units=10.0,
            price=100.0,
            value=1000.0,
            principal=700.0,
            cost_basis=850.0,
        )

        self.assertEqual(self._read().holdings[0].cost_basis, 850.0)

    def test_a_holding_with_neither_still_reports_neither(self) -> None:
        # The 401k and TSP case, which this must not touch. None rather than
        # zero, all the way down: a zero cost reports the position's whole value
        # as profit.
        self._write(symbol="Q4R7", units=2500.000, price=20.0000, value=50000.00)

        row = self._read().holdings[0]

        self.assertIsNone(row.cost_basis)
        self.assertIsNone(row.principal)

    def test_a_multi_fund_plan_gets_no_cost_basis_at_all(self) -> None:
        # The case an unconditional fallback gets wrong, and the reason the
        # check exists. The parser repeats the account's principal and earnings
        # onto every fund row, so reading either blind gives *each* position the
        # whole account's cost: 2,140.00 against 500.00 of value on one row and
        # 1500.00 on the other, for a portfolio that has spent 4,280.00 to hold
        # 2,300.00 and shows a catastrophic loss on money that has made 160.00.
        db = BrokerDatabase(
            db_engine=create_db_engine(
                db_path=self.root / "default" / "schwab529plan.db"
            ),
            broker="schwab529plan",
        )
        db.save_snapshot(
            account=AccountIdentity(account_key="529-2", display_name="Two Funds"),
            scraped_at="2026-08-12 18:30:00",
            as_of="2026-08-12",
            value=2300.00,
            currency="USD",
            holdings=[
                Holding(
                    fund_code="70310",
                    units=69.565,
                    price=10.85,
                    value=500.00,
                    principal=2140.00,
                    earnings=160.00,
                ),
                Holding(
                    fund_code="70311",
                    units=130.435,
                    price=10.85,
                    value=1500.00,
                    principal=2140.00,
                    earnings=160.00,
                ),
            ],
            transactions=[],
        )
        db.shutdown_db()

        rows = self._read().holdings

        self.assertEqual([row.cost_basis for row in rows], [None, None])
        # Still carried, because they are what the source said about the
        # account. It is reading them as a *position's* cost that is refused.
        self.assertEqual([row.principal for row in rows], [2140.00, 2140.00])

    def test_a_row_a_single_cent_out_is_still_read(self) -> None:
        # The page rounds value, principal and earnings independently, so the
        # identity can legitimately land a cent from zero. Nothing is given away
        # by allowing it -- the case being screened for misses by hundreds.
        #
        # **These three numbers are chosen, not illustrative.** In binary
        # floating point 2200.00 - 2040.01 - 159.98 is 0.010000000000019, so the
        # float form this replaced *rejected* a row exactly a cent out -- while a
        # different triple, a cent out by the same amount, sailed through. A
        # boundary that moves with the values is not a boundary, and only a
        # triple that actually lands the wrong side of it can say so. 200.0000
        # x 11.00 is 2200.00 exactly, so the row stays internally honest too.
        self._write(
            symbol="",
            fund_code="70310",
            units=200.0000,
            price=11.00,
            value=2200.00,
            principal=2040.01,
            earnings=159.98,
        )

        self.assertEqual(self._read().holdings[0].cost_basis, 2040.01)

    def test_a_row_two_cents_out_is_not_read(self) -> None:
        # The other side of the same boundary, so "one cent" is a rule rather
        # than a number that happens to work.
        self._write(
            symbol="",
            fund_code="70310",
            units=200.0000,
            price=10.85,
            value=2300.00,
            principal=2140.00,
            earnings=159.98,
        )

        self.assertIsNone(self._read().holdings[0].cost_basis)

    def test_a_principal_with_no_earnings_beside_it_is_not_read(self) -> None:
        # Nothing to check the interpretation against, so it is not made. The
        # 529 always reports the pair -- they come off one table row -- so this
        # costs nothing real and refuses a source nobody has looked at yet.
        self._write(
            symbol="",
            fund_code="70310",
            units=10.0,
            price=10.0,
            value=100.0,
            principal=90.0,
        )

        self.assertIsNone(self._read().holdings[0].cost_basis)

    def test_everything_downstream_follows_from_it(self) -> None:
        # The whole reason this matters. Five fields were dashed on that row
        # while the number sat in the column beside them.
        self._write(
            symbol="",
            fund_code="70310",
            units=200.0000,
            price=10.85,
            value=2300.00,
            principal=2140.00,
            earnings=160.00,
        )

        row = positions(portfolio=self._read(), classes={}, income={}, history={})[0]

        self.assertEqual(row.cost_basis, 2140.00)
        self.assertAlmostEqual(row.gain or 0.0, 160.00, places=2)
        self.assertAlmostEqual(row.growth or 0.0, 0.0748, places=4)
        self.assertAlmostEqual(row.purchase_price or 0.0, 10.7000, places=4)

    def test_the_gain_matches_the_earnings_the_plan_reported(self) -> None:
        # The check that says this is a rename rather than a guess. The plan
        # states earnings itself, and a cost basis taken from principal has to
        # reproduce it -- otherwise the two fields do not mean what this assumes.
        self._write(
            symbol="",
            fund_code="70310",
            units=200.0000,
            price=10.85,
            value=2300.00,
            principal=2140.00,
            earnings=160.00,
        )

        row = self._read().holdings[0]

        self.assertAlmostEqual(
            (row.value or 0.0) - (row.cost_basis or 0.0),
            row.earnings or 0.0,
            places=2,
        )


if __name__ == "__main__":
    unittest.main()
