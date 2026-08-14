"""An account is its positions plus its cash, not the total SnapTrade cached.

Two findings, measured against the live API, and this file exists so neither can
come back.

**The cached total is a day stale.** StonkSmith read balances from
``list_user_accounts``, which SnapTrade's own documentation describes as serving
"Daily data regardless of the customer's plan… cached and refreshed once a day".
The consequence was exact rather than approximate: on 2026-08-14 the live balance
for Garrett IRA was 6710.00 and for Mekenna IRA 674.38, and those are precisely
the position values StonkSmith had recorded for them the day before, to the cent.
Every balance in the workspace was one sync behind, and the net worth series with
it. The delta survived that -- both ends shifted equally -- but the level did not.

**Positions are not the whole account either.** ``get_all_account_positions``
returns securities and never mentions cash, which is routinely negative. One
brokerage account here holds $2,986.31 of a fund against cash of -$744.28, from
an overdraft transfer out; SnapTrade's own total says $2,242.03 and summing the
positions says $2,986.31. Neither endpoint alone is the account.

So the value is computed as positions plus cash, and the fallbacks below are the
interesting part: each is a case where computing it would be *wrong* rather than
merely unavailable, and each would be wrong quietly.
"""

import unittest
from typing import Any
from unittest.mock import MagicMock

from stonksmith.etc.records import Holding
from stonksmith.modules.snaptrade_module import SnapTradeModule

#: The account that prompted this: one fund, and a margin loan against it.
ROW: dict[str, str] = {
    "Id": "76fe65df",
    "Account": "Garrett Brokerage",
    "Brokerage": "Schwab",
    "Currency": "USD",
    # What list_user_accounts cached, which is what this used to store.
    "Amount": "2242.03",
    "Balance": "$2,242.03",
    "SyncedAt": "2026-08-14",
}

HOLDINGS: list[Holding] = [Holding(symbol="SWPPX", units=148.499, value=2986.31)]


def _context() -> Any:
    context = MagicMock()
    context.args.no_positions = False
    return context


class TheValueIsPositionsPlusCash(unittest.TestCase):
    def setUp(self) -> None:
        self.module = SnapTradeModule()

    def test_a_margin_loan_is_subtracted(self) -> None:
        # 2,986.31 - 744.28 = 2,242.03, which is what SnapTrade's own total says
        # once it catches up. Summing the positions alone overstates this account
        # by the size of the debt.
        value = self.module.account_value(
            row=ROW,
            holdings=HOLDINGS,
            positions_read=True,
            cash=-744.28,
            context=_context(),
        )

        self.assertAlmostEqual(value or 0.0, 2242.03, places=2)

    def test_uninvested_cash_is_added(self) -> None:
        value = self.module.account_value(
            row=ROW,
            holdings=HOLDINGS,
            positions_read=True,
            cash=13.69,
            context=_context(),
        )

        self.assertAlmostEqual(value or 0.0, 3000.00, places=2)

    def test_a_fully_invested_account_equals_its_positions(self) -> None:
        value = self.module.account_value(
            row=ROW,
            holdings=HOLDINGS,
            positions_read=True,
            cash=0.0,
            context=_context(),
        )

        self.assertAlmostEqual(value or 0.0, 2986.31, places=2)


class TheCachedTotalIsTheFallback(unittest.TestCase):
    """Three ways back to it, each a case where computing would be wrong."""

    def setUp(self) -> None:
        self.module = SnapTradeModule()

    def test_positions_that_could_not_be_read_fall_back(self) -> None:
        # A failed fetch and an empty account look identical afterwards, which is
        # why positions() reports whether it read as well as what. Computing from
        # an unread list prices a brokerage account at its cash alone -- on this
        # account, at minus seven hundred dollars.
        value = self.module.account_value(
            row=ROW,
            holdings=[],
            positions_read=False,
            cash=-744.28,
            context=_context(),
        )

        self.assertAlmostEqual(value or 0.0, 2242.03, places=2)

    def test_an_account_reporting_no_positions_falls_back(self) -> None:
        # A brokerage that pre-aggregates -- a Schwab-held 529 -- gives a balance
        # and nothing to sum. Positions plus cash would be zero, and a zero is a
        # number rather than an error: the series would carry it for thirty days.
        value = self.module.account_value(
            row=ROW,
            holdings=[],
            positions_read=True,
            cash=0.0,
            context=_context(),
        )

        self.assertAlmostEqual(value or 0.0, 2242.03, places=2)

    def test_cash_that_could_not_be_read_falls_back(self) -> None:
        # The securities alone omit a margin loan, which overstates the account
        # by the size of the debt. A stale total is better than a confident wrong
        # one.
        value = self.module.account_value(
            row=ROW,
            holdings=HOLDINGS,
            positions_read=True,
            cash=None,
            context=_context(),
        )

        self.assertAlmostEqual(value or 0.0, 2242.03, places=2)


class CashIsReadInTheAccountsOwnCurrency(unittest.TestCase):
    def setUp(self) -> None:
        self.module = SnapTradeModule()
        self.connection = MagicMock()

    def test_it_takes_the_matching_currency(self) -> None:
        # SnapTrade returns one entry per currency, because some brokerages hold
        # several in one account. Summing across them adds a dollar to a euro.
        self.connection.fetch_balance.return_value = [
            {"currency": {"code": "CAD"}, "cash": 999.0},
            {"currency": {"code": "USD"}, "cash": -744.28},
        ]

        found = self.module.cash(
            connection=self.connection, row=ROW, context=_context()
        )

        self.assertAlmostEqual(found or 0.0, -744.28, places=2)

    def test_a_currency_the_account_does_not_hold_reads_as_unknown(self) -> None:
        self.connection.fetch_balance.return_value = [
            {"currency": {"code": "CAD"}, "cash": 999.0}
        ]

        self.assertIsNone(
            self.module.cash(connection=self.connection, row=ROW, context=_context())
        )

    def test_a_failed_call_reads_as_unknown_rather_than_zero(self) -> None:
        # None and 0.0 mean different things here and the fallback depends on
        # telling them apart: zero cash makes an account worth its positions,
        # while "not read" must leave the cached total in place rather than
        # quietly writing off a margin loan.
        self.connection.fetch_balance.side_effect = RuntimeError("503")

        self.assertIsNone(
            self.module.cash(connection=self.connection, row=ROW, context=_context())
        )


class PositionsReportWhetherTheyWereRead(unittest.TestCase):
    def setUp(self) -> None:
        self.module = SnapTradeModule()
        self.connection = MagicMock()

    def test_an_empty_account_is_read_and_empty(self) -> None:
        self.connection.fetch_positions.return_value = []

        holdings, read = self.module.positions(
            connection=self.connection, row=ROW, context=_context()
        )

        self.assertEqual(holdings, [])
        self.assertTrue(read, "an account with no positions was reported as unread")

    def test_a_failed_fetch_is_not_read(self) -> None:
        self.connection.fetch_positions.side_effect = RuntimeError("503")

        holdings, read = self.module.positions(
            connection=self.connection, row=ROW, context=_context()
        )

        self.assertEqual(holdings, [])
        self.assertFalse(read, "a failed fetch was reported as a read empty account")

    def test_no_positions_flag_is_not_read(self) -> None:
        context = _context()
        context.args.no_positions = True

        _holdings, read = self.module.positions(
            connection=self.connection, row=ROW, context=context
        )

        self.assertFalse(read)


if __name__ == "__main__":
    unittest.main()
