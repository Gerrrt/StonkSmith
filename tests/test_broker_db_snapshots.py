# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Writing a run: a value, the positions behind it, and the movements.

Three properties matter here, and each has a way of failing quietly:

* **Atomicity.** The engine is built with isolation_level="AUTOCOMMIT", under
  which every statement commits as it runs and `with conn.begin():` rolls
  nothing back. A snapshot that kept three of its six holdings would look
  exactly like an account that holds three funds.
* **Idempotence.** Re-running a scrape must not double the history. A snapshot
  is keyed on (account, scraped_at) and holdings are replaced wholesale.
* **Not over-deduplicating.** Two identical $50 contributions on the same day
  are indistinguishable field by field, and collapsing them loses half the
  money permanently.
"""

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sqlalchemy import text

from etc.broker_db import BrokerDatabase, natural_keys
from etc.infrastructure import create_db_engine
from etc.records import AccountIdentity, Holding, Transaction
from keyring_isolation import MemoryKeyringMixin

EZEKIEL = AccountIdentity(
    account_key="Ezekiel",
    display_name="Ezekiel",
    beneficiary="Ezekiel A",
    kind="529",
    external_id="ACC-1",
)

#: A scraped 529 fund row: a fund code, contributions and growth, no ticker.
FUND = Holding(
    fund_code="SWX",
    name="Index 2030",
    units=10.5,
    price=117.58,
    value=1234.56,
    principal=1000.0,
    earnings=234.56,
)

#: An API position: a ticker and a cost basis, no principal or earnings.
POSITION = Holding(
    symbol="VTI",
    name="Vanguard Total Market",
    units=3.0,
    price=250.0,
    value=750.0,
    cost_basis=600.0,
)

CONTRIBUTION = Transaction(
    processed_on="12/30/2025",
    traded_on="12/29/2025",
    tx_type="Contribution",
    value=50.0,
    raw="$50.00",
)


class _SnapshotTestCase(MemoryKeyringMixin, unittest.TestCase):
    """A throwaway database per test, never under $HOME."""

    def setUp(self) -> None:
        super().setUp()
        self._dir = tempfile.TemporaryDirectory()
        self.db = BrokerDatabase(
            create_db_engine(db_path=Path(self._dir.name) / "broker.db"),
            "schwab529plan",
        )

    def tearDown(self) -> None:
        self.db.shutdown_db()
        self._dir.cleanup()
        super().tearDown()

    def count(self, table: str) -> int:
        with self.db.db_engine.connect() as conn:
            return int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())

    def save(self, **overrides: Any) -> int:
        kwargs: dict[str, Any] = {
            "account": EZEKIEL,
            "scraped_at": "2026-01-01 00:00:00",
            "value": 1234.56,
            "raw_value": "$1,234.56",
            "as_of": "2025-12-31",
        }
        kwargs.update(overrides)
        return self.db.save_snapshot(**kwargs)


class WriteTests(_SnapshotTestCase):
    """One call writes identity, value, positions and movements."""

    def test_a_snapshot_links_to_its_account_and_holdings(self) -> None:
        snapshot_id = self.save(holdings=[FUND, POSITION])

        self.assertEqual(self.count("accounts"), 1)
        self.assertEqual(self.count("account_snapshots"), 1)
        self.assertEqual(len(self.db.get_holdings(snapshot_id=snapshot_id)), 2)

    def test_the_source_as_of_date_is_kept_apart_from_the_run_time(self) -> None:
        # A daily change is only meaningful against the date the value is for.
        self.save()

        snapshot = self.db.get_snapshots()[0]
        self.assertEqual(snapshot[2], "2025-12-31", "as_of")
        self.assertEqual(snapshot[3], "2026-01-01 00:00:00", "scraped_at")

    def test_both_holding_shapes_persist_without_borrowing_each_other_columns(
        self,
    ) -> None:
        self.save(holdings=[FUND, POSITION])

        with self.db.db_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT symbol, fund_code, principal, earnings, cost_basis "
                    "FROM holdings ORDER BY position"
                )
            ).fetchall()

        fund, position = rows
        self.assertEqual((fund[0], fund[1]), (None, "SWX"))
        self.assertEqual((fund[2], fund[3], fund[4]), (1000.0, 234.56, None))
        self.assertEqual((position[0], position[1]), ("VTI", None))
        self.assertEqual((position[2], position[3], position[4]), (None, None, 600.0))

    def test_an_account_with_no_positions_still_gets_a_snapshot(self) -> None:
        # A pre-aggregated 529 returns zero positions through SnapTrade. That is
        # a fact about the account, not a failed scrape.
        self.save(holdings=[])

        self.assertEqual(self.count("account_snapshots"), 1)
        self.assertEqual(self.count("holdings"), 0)

    def test_a_value_that_could_not_be_read_is_null_not_zero(self) -> None:
        self.save(value=None, raw_value="--")

        self.assertIsNone(self.db.get_snapshots()[0][4])

    def test_metadata_a_later_run_omits_is_not_blanked_out(self) -> None:
        # Sources drop fields. Overwriting a known beneficiary with the None a
        # quieter page produced would lose what the database already had.
        self.save()
        self.db.save_snapshot(
            account=AccountIdentity(account_key="Ezekiel", display_name="Ezekiel"),
            scraped_at="2026-01-02 00:00:00",
            value=1300.0,
        )

        account = self.db.get_accounts()[0]
        self.assertEqual(account[3], "Ezekiel A", "beneficiary")
        self.assertEqual(account[4], "529", "kind")


class IdempotenceTests(_SnapshotTestCase):
    """Re-running a scrape must not double anything."""

    def test_the_same_run_written_twice_is_one_snapshot(self) -> None:
        self.save(transactions=[CONTRIBUTION])
        self.save(transactions=[CONTRIBUTION])

        self.assertEqual(self.count("account_snapshots"), 1)
        self.assertEqual(self.count("transactions"), 1)

    def test_holdings_are_replaced_wholesale_not_appended(self) -> None:
        # A re-run that finds fewer positions must not leave the ones it no
        # longer sees lying around looking current.
        snapshot_id = self.save(holdings=[FUND, POSITION])
        self.save(holdings=[FUND])

        self.assertEqual(len(self.db.get_holdings(snapshot_id=snapshot_id)), 1)

    def test_a_later_run_adds_a_snapshot_without_re_adding_transactions(self) -> None:
        self.save(transactions=[CONTRIBUTION])
        self.save(scraped_at="2026-01-02 00:00:00", transactions=[CONTRIBUTION])

        self.assertEqual(self.count("account_snapshots"), 2)
        self.assertEqual(self.count("transactions"), 1)

    def test_a_re_scrape_contributes_only_what_is_new(self) -> None:
        later = Transaction(
            processed_on="12/31/2025",
            traded_on="12/31/2025",
            tx_type="Dividend",
            value=7.25,
            raw="$7.25",
        )

        self.save(transactions=[CONTRIBUTION])
        self.save(scraped_at="2026-01-02 00:00:00", transactions=[CONTRIBUTION, later])

        self.assertEqual(self.count("transactions"), 2)


class DuplicateTransactionTests(_SnapshotTestCase):
    """Identical movements are still two movements."""

    def test_two_identical_rows_in_one_batch_both_persist(self) -> None:
        self.save(transactions=[CONTRIBUTION, CONTRIBUTION])

        self.assertEqual(
            self.count("transactions"),
            2,
            "collapsing same-day duplicates loses half the money permanently",
        )

    def test_re_scraping_them_still_yields_exactly_two(self) -> None:
        self.save(transactions=[CONTRIBUTION, CONTRIBUTION])
        self.save(
            scraped_at="2026-01-02 00:00:00",
            transactions=[CONTRIBUTION, CONTRIBUTION],
        )

        self.assertEqual(self.count("transactions"), 2)

    def test_the_ordinal_only_separates_genuine_repeats(self) -> None:
        keys = natural_keys(rows=[CONTRIBUTION, CONTRIBUTION])

        self.assertNotEqual(keys[0], keys[1])
        self.assertEqual(keys, natural_keys(rows=[CONTRIBUTION, CONTRIBUTION]))

    def test_a_source_supplied_id_is_used_directly(self) -> None:
        # SnapTrade gives every activity an id. There is nothing to derive, and
        # deriving one anyway would break when it reorders its window.
        rows = [
            Transaction(external_id="abc", tx_type="BUY", value=1.0),
            Transaction(external_id="abc", tx_type="BUY", value=1.0),
        ]

        self.assertEqual(natural_keys(rows=rows), ["id:abc", "id:abc"])

        self.save(transactions=rows)
        self.assertEqual(self.count("transactions"), 1)


class AtomicityTests(_SnapshotTestCase):
    """Half a scrape must not reach the database."""

    def test_a_failure_partway_through_leaves_nothing_behind(self) -> None:
        # The engine runs in AUTOCOMMIT, where a plain conn.begin() rolls
        # nothing back. Without the SERIALIZABLE override in _write(), the
        # account and snapshot below would survive this raise.
        with (
            patch.object(
                BrokerDatabase,
                "_insert_transactions",
                side_effect=RuntimeError("network died mid-write"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.save(holdings=[FUND], transactions=[CONTRIBUTION])

        self.assertEqual(self.count("accounts"), 0)
        self.assertEqual(self.count("account_snapshots"), 0)
        self.assertEqual(self.count("holdings"), 0)
        self.assertEqual(self.count("transactions"), 0)

    def test_an_earlier_good_snapshot_is_not_rolled_back_too(self) -> None:
        self.save()

        with (
            patch.object(
                BrokerDatabase,
                "_insert_transactions",
                side_effect=RuntimeError("boom"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.save(scraped_at="2026-01-02 00:00:00", transactions=[CONTRIBUTION])

        self.assertEqual(self.count("account_snapshots"), 1)


class ReadTests(_SnapshotTestCase):
    """What the navigator and the savers read back."""

    def test_the_delta_between_consecutive_snapshots(self) -> None:
        self.save(value=1000.0)
        self.save(scraped_at="2026-01-02 00:00:00", value=1100.0)

        newest = self.db.get_daily_change()[0]
        self.assertEqual(newest[3], 1100.0)
        self.assertEqual(newest[4], 1000.0)
        self.assertEqual(newest[5], 100.0)

    def test_the_first_snapshot_has_no_delta_rather_than_a_zero_one(self) -> None:
        self.save(value=1000.0)

        self.assertIsNone(self.db.get_daily_change()[0][5])

    def test_latest_snapshots_returns_one_row_per_account(self) -> None:
        self.save(value=1000.0)
        self.save(scraped_at="2026-01-02 00:00:00", value=1100.0)
        self.db.save_snapshot(
            account=AccountIdentity(account_key="Other", display_name="Other"),
            scraped_at="2026-01-02 00:00:00",
            value=5.0,
        )

        latest = self.db.get_latest_snapshots()
        self.assertEqual(len(latest), 2)
        self.assertEqual({row[3] for row in latest}, {1100.0, 5.0})

    def test_holdings_default_to_the_newest_snapshot(self) -> None:
        self.save(holdings=[FUND])
        self.save(scraped_at="2026-01-02 00:00:00", holdings=[POSITION])

        current = self.db.get_holdings()
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0][1], "VTI")

    def test_save_transactions_works_without_a_snapshot(self) -> None:
        stored = self.db.save_transactions(
            account=EZEKIEL,
            timestamp="2026-01-01 00:00:00",
            rows=[CONTRIBUTION],
        )

        self.assertEqual(stored, 1)
        self.assertEqual(self.count("account_snapshots"), 0)


if __name__ == "__main__":
    unittest.main()
