"""A 529 states its cost under another name, and the brief was not reading it.

The Schwab 529 scraper stores ``principal`` and ``earnings`` -- 1,303.68 against
1,421.93 of value, and 118.25 of earnings, which is the subtraction exactly. It
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
            account=AccountIdentity(account_key="529-1", display_name="Ezekiel"),
            scraped_at="2026-08-12 18:30:00",
            as_of="2026-08-12",
            value=1421.93,
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
            fund_code="14002",
            name="2042-2043 Enrollment Portfolio",
            units=131.0534,
            price=10.85,
            value=1421.93,
            principal=1303.68,
            earnings=118.25,
        )

        row = self._read().holdings[0]

        self.assertEqual(row.cost_basis, 1303.68)

    def test_both_fields_are_still_carried_out_unchanged(self) -> None:
        # Filled, not moved. The sheet has Principal and Earnings columns of its
        # own, and a 529's split is worth reporting as a split.
        self._write(
            symbol="",
            fund_code="14002",
            units=131.0534,
            price=10.85,
            value=1421.93,
            principal=1303.68,
            earnings=118.25,
        )

        row = self._read().holdings[0]

        self.assertEqual(row.principal, 1303.68)
        self.assertEqual(row.earnings, 118.25)

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
        self._write(symbol="O7M8", units=2722.418, price=19.0881, value=51965.79)

        row = self._read().holdings[0]

        self.assertIsNone(row.cost_basis)
        self.assertIsNone(row.principal)

    def test_a_multi_fund_plan_gets_no_cost_basis_at_all(self) -> None:
        # The case an unconditional fallback gets wrong, and the reason the
        # check exists. The parser repeats the account's principal and earnings
        # onto every fund row, so reading either blind gives *each* position the
        # whole account's cost: 1,303.68 against 500.00 of value on one row and
        # 921.93 on the other, for a portfolio that has spent 2,607.36 to hold
        # 1,421.93 and shows a catastrophic loss on money that has made 118.25.
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
            value=1421.93,
            currency="USD",
            holdings=[
                Holding(
                    fund_code="14002",
                    units=46.08,
                    price=10.85,
                    value=500.00,
                    principal=1303.68,
                    earnings=118.25,
                ),
                Holding(
                    fund_code="14003",
                    units=84.97,
                    price=10.85,
                    value=921.93,
                    principal=1303.68,
                    earnings=118.25,
                ),
            ],
            transactions=[],
        )
        db.shutdown_db()

        rows = self._read().holdings

        self.assertEqual([row.cost_basis for row in rows], [None, None])
        # Still carried, because they are what the source said about the
        # account. It is reading them as a *position's* cost that is refused.
        self.assertEqual([row.principal for row in rows], [1303.68, 1303.68])

    def test_a_principal_with_no_earnings_beside_it_is_not_read(self) -> None:
        # Nothing to check the interpretation against, so it is not made. The
        # 529 always reports the pair -- they come off one table row -- so this
        # costs nothing real and refuses a source nobody has looked at yet.
        self._write(
            symbol="",
            fund_code="14002",
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
            fund_code="14002",
            units=131.0534,
            price=10.85,
            value=1421.93,
            principal=1303.68,
            earnings=118.25,
        )

        row = positions(portfolio=self._read(), classes={}, income={}, history={})[0]

        self.assertEqual(row.cost_basis, 1303.68)
        self.assertAlmostEqual(row.gain or 0.0, 118.25, places=2)
        self.assertAlmostEqual(row.growth or 0.0, 0.0907, places=4)
        self.assertAlmostEqual(row.purchase_price or 0.0, 9.9477, places=4)

    def test_the_gain_matches_the_earnings_the_plan_reported(self) -> None:
        # The check that says this is a rename rather than a guess. The plan
        # states earnings itself, and a cost basis taken from principal has to
        # reproduce it -- otherwise the two fields do not mean what this assumes.
        self._write(
            symbol="",
            fund_code="14002",
            units=131.0534,
            price=10.85,
            value=1421.93,
            principal=1303.68,
            earnings=118.25,
        )

        row = self._read().holdings[0]

        self.assertAlmostEqual(
            (row.value or 0.0) - (row.cost_basis or 0.0),
            row.earnings or 0.0,
            places=2,
        )


if __name__ == "__main__":
    unittest.main()
