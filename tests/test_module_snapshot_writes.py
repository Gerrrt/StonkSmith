# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Modules write history when the database keeps it, and balances when it does not.

Two audiences share this code path. A database shipped with StonkSmith keeps
snapshots, holdings and transactions. A database written against the older
contract -- including any under ~/.stonksmith/modules that a user wrote
themselves -- knows only save_account_data, and must keep working exactly as it
did rather than crashing on a method it never promised.

The Schwab529 transaction case is the one worth stating plainly: the dashboard
renders a single transaction table for the whole page with nothing naming the
account a row belongs to. With one account there is one answer; with several
there is no honest one, so nothing is stored and the run says so.
"""

import unittest
from typing import Any, ClassVar
from unittest.mock import MagicMock

from etc.context import Context, SnapshotDbProtocol
from etc.records import AccountIdentity, Holding, Transaction
from modules.fidelity_module import FidelityModule
from modules.schwab529plan_module import Schwab529Module


class _LegacyDb:
    """A database written against the pre-history contract, and nothing more."""

    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    def get_credentials(self, filter_term: str | None = None) -> list[tuple[str, ...]]:
        del filter_term
        return []

    def save_account_data(
        self, account_name: str | None, balance: str | None, timestamp: str
    ) -> None:
        self.saved.append(
            {"name": account_name, "balance": balance, "timestamp": timestamp}
        )

    def shutdown_db(self) -> None:
        return None


class _SnapshotDb(_LegacyDb):
    """A database that keeps history."""

    def __init__(self) -> None:
        super().__init__()
        self.snapshots: list[dict[str, Any]] = []

    def save_snapshot(
        self,
        account: AccountIdentity,
        scraped_at: str,
        value: float | None,
        currency: str = "USD",
        as_of: str | None = None,
        raw_value: str | None = None,
        holdings: Any = (),
        transactions: Any = (),
    ) -> int:
        self.snapshots.append(
            {
                "account": account,
                "scraped_at": scraped_at,
                "value": value,
                "currency": currency,
                "as_of": as_of,
                "raw_value": raw_value,
                "holdings": list(holdings),
                "transactions": list(transactions),
            }
        )
        return len(self.snapshots)

    def save_transactions(
        self, account: AccountIdentity, timestamp: str, rows: Any
    ) -> int:
        del account, timestamp
        return len(list(rows))


class _CapturingLog:
    """Records what a module reported, at the level it reported it."""

    def __init__(self) -> None:
        self.failures: list[str] = []

    def __getattr__(self, name: str) -> Any:
        del name
        return lambda **_kwargs: None

    def fail(self, msg: str, **_kwargs: Any) -> None:
        self.failures.append(msg)


def _context(db: Any) -> Any:
    context = MagicMock(spec=Context)
    context.db = db
    context.log = _CapturingLog()
    context.args = MagicMock(history_days=0, no_positions=True)
    return context


class ProtocolDiscriminationTests(unittest.TestCase):
    """Which contract a database satisfies decides which path runs."""

    def test_a_legacy_database_is_not_mistaken_for_a_snapshot_one(self) -> None:
        self.assertFalse(isinstance(_LegacyDb(), SnapshotDbProtocol))

    def test_a_snapshot_database_is_recognised(self) -> None:
        self.assertTrue(isinstance(_SnapshotDb(), SnapshotDbProtocol))


class FidelityWriteTests(unittest.TestCase):
    """The simplest module: a balance, a number, and its history."""

    ACCOUNTS: ClassVar[list[dict[str, str]]] = [
        {
            "Account": "ROTH IRA (123456789)",
            "Balance": "$1,234.56",
            "Name": "ROTH IRA",
            "Number": "123456789",
        }
    ]

    def _run(self, db: Any) -> bool:
        module = FidelityModule()
        context = _context(db)
        connection = MagicMock()
        connection.username = "someone"

        module.scrape_accounts = lambda page, context: list(self.ACCOUNTS)  # type: ignore[method-assign]

        return module.on_login(context=context, connection=connection)

    def test_a_snapshot_database_receives_a_number_not_a_string(self) -> None:
        db = _SnapshotDb()

        self.assertTrue(self._run(db))
        self.assertEqual(len(db.snapshots), 1)
        self.assertEqual(db.snapshots[0]["value"], 1234.56)
        self.assertEqual(db.snapshots[0]["raw_value"], "$1,234.56")
        self.assertEqual(db.saved, [], "the legacy path must not also run")

    def test_the_account_number_is_recorded_without_becoming_the_identity(self) -> None:
        # The composite label is what previous runs stored. Keying on the number
        # instead would fork every existing user's history at the upgrade.
        db = _SnapshotDb()
        self._run(db)

        identity = db.snapshots[0]["account"]
        self.assertEqual(identity.account_key, "ROTH IRA (123456789)")
        self.assertEqual(identity.external_id, "123456789")

    def test_the_display_name_keeps_the_number_that_disambiguates_it(self) -> None:
        # Several Fidelity accounts can share a nickname.
        db = _SnapshotDb()
        self._run(db)

        self.assertEqual(
            db.snapshots[0]["account"].display_name, "ROTH IRA (123456789)"
        )

    def test_a_legacy_database_still_gets_its_balances(self) -> None:
        db = _LegacyDb()

        self.assertTrue(self._run(db))
        self.assertEqual(
            db.saved,
            [
                {
                    "name": "ROTH IRA (123456789)",
                    "balance": "$1,234.56",
                    "timestamp": db.saved[0]["timestamp"],
                }
            ],
        )


class Schwab529WriteTests(unittest.TestCase):
    """Beneficiaries, holdings and transactions, not just a balance."""

    BENEFICIARIES: ClassVar[list[dict[str, Any]]] = [
        {"Title": "Beneficiary:", "Name": "Ezekiel", "Account": "ACC-1"},
        {"Title": "Beneficiary:", "Name": "Naomi", "Account": "ACC-2"},
    ]
    BALANCES: ClassVar[list[dict[str, Any]]] = [
        {"Title": "Balance:", "Amount": "$1,234.56", "Date": "as of 12/31/2025"},
        {"Title": "Balance:", "Amount": "$2,000.00", "Date": "as of 12/31/2025"},
    ]
    INVESTMENTS: ClassVar[list[dict[str, Any]]] = [
        {
            "Table": 0,
            "Fund Code": "SWX01",
            "Fund": "Index 2030",
            "Units": "10.5",
            "Price": "$117.58",
            "Value": "$1,234.56",
            "Total Assets": "$1,234.56",
            "Principal": "$1,000.00",
            "Earnings": "$234.56",
        },
        {
            "Table": 1,
            "Fund Code": "SWX02",
            "Fund": "Index 2035",
            "Units": "10",
            "Price": "$200.00",
            "Value": "$2,000.00",
            "Total Assets": "$2,000.00",
            "Principal": "$1,800.00",
            "Earnings": "$200.00",
        },
    ]
    TRANSACTIONS: ClassVar[list[dict[str, Any]]] = [
        {
            "Processed": "12/30/2025",
            "Traded": "12/29/2025",
            "Type": "Contribution",
            "Units": "1",
            "Price": "$50.00",
            "Value": "$50.00",
        },
    ]

    def holdings(self, index: int) -> list[Holding]:
        return Schwab529Module.holdings_for(investments=self.INVESTMENTS, index=index)

    def test_holdings_are_paired_with_the_account_whose_table_they_came_from(
        self,
    ) -> None:
        self.assertEqual([h.fund_code for h in self.holdings(0)], ["SWX01"])
        self.assertEqual([h.fund_code for h in self.holdings(1)], ["SWX02"])

    def test_a_holding_carries_numbers_not_scraped_text(self) -> None:
        holding = self.holdings(0)[0]

        self.assertEqual(holding.units, 10.5)
        self.assertEqual(holding.price, 117.58)
        self.assertEqual(holding.value, 1234.56)
        self.assertEqual(holding.principal, 1000.0)
        self.assertEqual(holding.earnings, 234.56)

    def test_a_holding_keeps_the_text_it_was_read_from(self) -> None:
        self.assertEqual(self.holdings(0)[0].raw_value, "$1,234.56")

    def test_one_account_takes_the_transactions(self) -> None:
        log = _CapturingLog()

        rows = Schwab529Module.attribute_transactions(
            transactions=self.TRANSACTIONS,
            balances=self.BALANCES[:1],
            context=MagicMock(log=log),
        )

        self.assertEqual(len(rows), 1)
        self.assertIsInstance(rows[0], Transaction)
        self.assertEqual(log.failures, [], "an attributable table is not a problem")

    def test_several_accounts_store_none_and_say_so(self) -> None:
        # Attaching them all to the first invents history for it; copying them
        # to each invents history for every account. Both look plausible
        # afterwards, which is what makes them worse than storing nothing.
        log = _CapturingLog()

        rows = Schwab529Module.attribute_transactions(
            transactions=self.TRANSACTIONS,
            balances=self.BALANCES,
            context=MagicMock(log=log),
        )

        self.assertEqual(rows, [])
        self.assertEqual(len(log.failures), 1)
        self.assertIn("does not say which account", log.failures[0])
        self.assertIn("None were stored", log.failures[0])

    def test_no_transactions_is_not_reported_as_a_problem(self) -> None:
        log = _CapturingLog()

        rows = Schwab529Module.attribute_transactions(
            transactions=[], balances=self.BALANCES, context=MagicMock(log=log)
        )

        self.assertEqual(rows, [])
        self.assertEqual(log.failures, [])

    def test_the_beneficiary_is_stored_rather_than_folded_into_a_name(self) -> None:
        from helpers.schwab529plan import beneficiary_field

        self.assertEqual(
            beneficiary_field(beneficiaries=self.BENEFICIARIES, index=1, key="Name"),
            "Naomi",
        )
        self.assertEqual(
            beneficiary_field(beneficiaries=self.BENEFICIARIES, index=1, key="Account"),
            "ACC-2",
        )

    def test_an_unpaired_balance_gets_no_beneficiary_rather_than_the_wrong_one(
        self,
    ) -> None:
        from helpers.schwab529plan import beneficiary_field

        self.assertIsNone(
            beneficiary_field(beneficiaries=self.BENEFICIARIES, index=5, key="Name")
        )


if __name__ == "__main__":
    unittest.main()
