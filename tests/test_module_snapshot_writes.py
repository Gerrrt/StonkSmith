# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Modules write history when the database keeps it, and balances when it does not.

Two audiences share this code path. A database shipped with StonkSmith keeps
snapshots, holdings and transactions. A database written against the older
contract -- including any under ~/.stonksmith/modules that a user wrote
themselves -- knows only save_account_data, and must keep working exactly as it
did rather than crashing on a method it never promised.

The Schwab529 transaction case is the one worth stating plainly: the known
rendering of the dashboard puts one transaction table on the page with nothing
naming the account a row belongs to. Attribution therefore takes the strongest
marker the markup offers -- a row that names its account, failing that a table
per account paired by position, failing that a page showing a single account --
and when none of those holds, nothing is stored and the run says so. Attaching
the movements all to the first account invents history for it and copying them
to each invents history for every account; both look completely plausible
afterwards, which is what makes them worse than an empty table and a message.
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
        self.highlights: list[str] = []

    def __getattr__(self, name: str) -> Any:
        del name
        return lambda **_kwargs: None

    def fail(self, msg: str, **_kwargs: Any) -> None:
        self.failures.append(msg)

    def highlight(self, msg: str, **_kwargs: Any) -> None:
        self.highlights.append(msg)


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

    def attribute(
        self,
        transactions: list[dict[str, Any]],
        balances: list[dict[str, Any]],
        log: _CapturingLog,
    ) -> dict[int, list[Transaction]]:
        return Schwab529Module.attribute_transactions(
            transactions=transactions,
            balances=balances,
            context=MagicMock(log=log),
            beneficiaries=self.BENEFICIARIES,
        )

    def test_one_account_takes_the_transactions(self) -> None:
        log = _CapturingLog()

        attributed = self.attribute(self.TRANSACTIONS, self.BALANCES[:1], log)

        self.assertEqual(list(attributed), [0])
        self.assertEqual(len(attributed[0]), 1)
        self.assertIsInstance(attributed[0][0], Transaction)
        self.assertEqual(log.failures, [], "an attributable table is not a problem")

    def test_several_accounts_naming_none_store_none_and_say_so(self) -> None:
        # Attaching them all to the first invents history for it; copying them
        # to each invents history for every account. Both look plausible
        # afterwards, which is what makes them worse than storing nothing.
        log = _CapturingLog()

        attributed = self.attribute(self.TRANSACTIONS, self.BALANCES, log)

        self.assertEqual(attributed, {})
        self.assertEqual(len(log.failures), 1)
        self.assertIn("does not say which account", log.failures[0])
        self.assertIn("None were stored", log.failures[0])

    def test_no_transactions_is_not_reported_as_a_problem(self) -> None:
        log = _CapturingLog()

        attributed = self.attribute([], self.BALANCES, log)

        self.assertEqual(attributed, {})
        self.assertEqual(log.failures, [])

    def test_a_row_naming_its_account_goes_to_that_account(self) -> None:
        log = _CapturingLog()
        rows: list[dict[str, Any]] = [
            {**self.TRANSACTIONS[0], "Account": "Naomi"},
            {**self.TRANSACTIONS[0], "Account": "Ezekiel"},
        ]

        attributed = self.attribute(rows, self.BALANCES, log)

        self.assertEqual(sorted(attributed), [0, 1])
        self.assertEqual(len(attributed[0]), 1)
        self.assertEqual(len(attributed[1]), 1)
        self.assertEqual(log.failures, [])

    def test_a_masked_account_number_matches_the_account_it_belongs_to(self) -> None:
        # Schwab masks account numbers. "...5678" and "1000-5678" are not two
        # different accounts, and a four-digit tail is what a human matches on.
        log = _CapturingLog()
        beneficiaries: list[dict[str, Any]] = [
            {"Name": "Ezekiel", "Account": "1000-1234"},
            {"Name": "Naomi", "Account": "1000-5678"},
        ]

        attributed = Schwab529Module.attribute_transactions(
            transactions=[{**self.TRANSACTIONS[0], "Account": "XXXX-5678"}],
            balances=self.BALANCES,
            context=MagicMock(log=log),
            beneficiaries=beneficiaries,
        )

        self.assertEqual(list(attributed), [1])
        self.assertEqual(log.failures, [])

    def test_a_section_heading_attributes_the_rows_beneath_it(self) -> None:
        log = _CapturingLog()
        rows: list[dict[str, Any]] = [
            {**self.TRANSACTIONS[0], "Section": "Contributions for Ezekiel"},
            {**self.TRANSACTIONS[0], "Section": "Contributions for Naomi"},
        ]

        attributed = self.attribute(rows, self.BALANCES, log)

        self.assertEqual(sorted(attributed), [0, 1])

    def test_rows_that_match_are_stored_and_the_rest_are_reported(self) -> None:
        # The matched rows are correct. Discarding them as well would lose real
        # history to protect nothing.
        log = _CapturingLog()
        rows: list[dict[str, Any]] = [
            {**self.TRANSACTIONS[0], "Account": "Ezekiel"},
            {**self.TRANSACTIONS[0], "Account": "Someone Else"},
        ]

        attributed = self.attribute(rows, self.BALANCES, log)

        self.assertEqual(list(attributed), [0])
        self.assertEqual(len(attributed[0]), 1)
        self.assertEqual(len(log.failures), 1)
        self.assertIn("1 of 2", log.failures[0])
        self.assertIn("Someone Else", log.failures[0])

    def test_a_hint_matching_two_accounts_is_not_an_attribution(self) -> None:
        log = _CapturingLog()
        beneficiaries: list[dict[str, Any]] = [
            {"Name": "Smith", "Account": "ACC-1"},
            {"Name": "Smith", "Account": "ACC-2"},
        ]

        attributed = Schwab529Module.attribute_transactions(
            transactions=[{**self.TRANSACTIONS[0], "Account": "Smith"}],
            balances=self.BALANCES,
            context=MagicMock(log=log),
            beneficiaries=beneficiaries,
        )

        self.assertEqual(attributed, {})
        self.assertEqual(len(log.failures), 1)

    def test_one_table_per_account_pairs_by_position(self) -> None:
        # The same rule holdings_for already applies to the fund tables, which
        # the page renders the same way.
        log = _CapturingLog()
        rows: list[dict[str, Any]] = [
            {**self.TRANSACTIONS[0], "Table": 0},
            {**self.TRANSACTIONS[0], "Table": 1},
            {**self.TRANSACTIONS[0], "Table": 1},
        ]

        attributed = self.attribute(rows, self.BALANCES, log)

        self.assertEqual(sorted(attributed), [0, 1])
        self.assertEqual(len(attributed[0]), 1)
        self.assertEqual(len(attributed[1]), 2)
        self.assertEqual(log.failures, [], "an inference the page supports")
        self.assertTrue(
            any("split into 2 tables" in msg for msg in log.highlights),
            "an inference has to say it was one",
        )

    def test_tables_that_do_not_match_the_account_count_store_nothing(self) -> None:
        log = _CapturingLog()
        rows: list[dict[str, Any]] = [
            {**self.TRANSACTIONS[0], "Table": 0},
            {**self.TRANSACTIONS[0], "Table": 1},
            {**self.TRANSACTIONS[0], "Table": 2},
        ]

        attributed = self.attribute(rows, self.BALANCES, log)

        self.assertEqual(attributed, {})
        self.assertIn("None were stored", log.failures[0])

    def test_one_caption_over_one_table_does_not_take_everyones_history(
        self,
    ) -> None:
        # A single table covering both beneficiaries, captioned with one of
        # their names, is the exact invention this refuses to make.
        log = _CapturingLog()
        rows: list[dict[str, Any]] = [
            {**self.TRANSACTIONS[0], "Table": 0, "Title": "Ezekiel"},
            {**self.TRANSACTIONS[0], "Table": 0, "Title": "Ezekiel"},
        ]

        attributed = self.attribute(rows, self.BALANCES, log)

        self.assertEqual(attributed, {})
        self.assertIn("None were stored", log.failures[0])

    def test_a_caption_per_table_is_trusted(self) -> None:
        log = _CapturingLog()
        rows: list[dict[str, Any]] = [
            {**self.TRANSACTIONS[0], "Table": 0, "Title": "Ezekiel"},
            {**self.TRANSACTIONS[0], "Table": 1, "Title": "Naomi"},
        ]

        attributed = self.attribute(rows, self.BALANCES, log)

        self.assertEqual(sorted(attributed), [0, 1])
        self.assertEqual(log.failures, [])

    def test_the_markup_is_not_walked_when_attribution_succeeds(self) -> None:
        # Describing the markup walks every row of every table. It answers a
        # question only the failing paths ask, so the runs that work must not
        # pay for it.
        calls: list[int] = []

        def structure() -> list[dict[str, Any]]:
            calls.append(1)
            return []

        for balances in (self.BALANCES[:1], self.BALANCES):
            Schwab529Module.attribute_transactions(
                transactions=[{**self.TRANSACTIONS[0], "Account": "Ezekiel"}]
                if len(balances) > 1
                else self.TRANSACTIONS,
                balances=balances,
                context=MagicMock(log=_CapturingLog()),
                beneficiaries=self.BENEFICIARIES,
                structure=structure,
            )

        self.assertEqual(calls, [], "the clean paths never read the markup")

    def test_the_markup_is_described_when_nothing_can_be_attributed(self) -> None:
        # Issue #36's blocking question is what the live page renders. A run
        # that cannot attribute prints the shape so the next one can.
        log = _CapturingLog()

        Schwab529Module.attribute_transactions(
            transactions=self.TRANSACTIONS,
            balances=self.BALANCES,
            context=MagicMock(log=log),
            beneficiaries=self.BENEFICIARIES,
            structure=lambda: [
                {
                    "Table": 0,
                    "Caption": None,
                    "Headers": ["Processed", "Traded"],
                    "Rows": 1,
                    "Widths": [6],
                    "Attributes": ["class"],
                }
            ],
        )

        printed = " ".join(log.highlights)
        self.assertIn("headers=['Processed', 'Traded']", printed)
        self.assertIn("cells-per-row=[6]", printed)
        self.assertIn("attributes=['class']", printed)
        self.assertNotIn("$50.00", printed, "values do not belong in a diagnostic")

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
