# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""The schema, and what happens to a database that predates it.

Real users have real history in the pre-history ``accounts`` table: one row per
account per run, with the balance stored as the text the page printed. Opening
such a database has to carry all of it forward, because it is the only record of
what those accounts were worth, and it has to do so exactly once no matter how
many times the database is opened.

The rename-before-create ordering is the part most likely to regress silently.
``metadata.create_all`` leaves an existing table alone, so if the legacy
``accounts`` is not moved out of the way first, the new schema is never created
and every write afterwards fails against four columns that mean something else.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from sqlalchemy import text

from etc.broker_db import LEGACY_ACCOUNTS_TABLE, BrokerDatabase
from etc.infrastructure import create_db_engine
from keyring_isolation import MemoryKeyringMixin

LEGACY_SCHEMA = """
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    account_name TEXT,
    balance TEXT,
    last_updated TEXT
);
CREATE TABLE credentials (
    id INTEGER PRIMARY KEY,
    username TEXT,
    keyring_key TEXT,
    type TEXT,
    pillaged_from TEXT
);
"""

#: Deliberately awkward: a repeated account, a negative, an unreadable balance
#: and a row with no name at all. All four exist in databases in the wild.
LEGACY_ROWS: tuple[tuple[str | None, str, str], ...] = (
    ("Ezekiel", "$1,000.00", "2025-12-01 00:00:00"),
    ("Ezekiel", "$1,100.00", "2025-12-02 00:00:00"),
    ("Fidelity - Roth", "-$50.00", "2025-12-02 00:00:00"),
    (None, "--", "2025-12-03 00:00:00"),
)


class _DbTestCase(MemoryKeyringMixin, unittest.TestCase):
    """A throwaway database directory per test, never under $HOME."""

    def setUp(self) -> None:
        super().setUp()
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._dir.name)
        self.opened: list[BrokerDatabase] = []

    def tearDown(self) -> None:
        for db in self.opened:
            db.shutdown_db()
        self._dir.cleanup()
        super().tearDown()

    def open_db(self, name: str = "broker.db", broker: str = "fidelity") -> Any:
        db = BrokerDatabase(create_db_engine(db_path=self.tmp / name), broker)
        self.opened.append(db)
        return db

    def write_legacy(self, name: str = "broker.db") -> Path:
        path: Path = self.tmp / name
        con = sqlite3.connect(path)
        try:
            con.executescript(LEGACY_SCHEMA)
            con.executemany(
                "INSERT INTO accounts (account_name, balance, last_updated) "
                "VALUES (?, ?, ?)",
                LEGACY_ROWS,
            )
            con.commit()
        finally:
            con.close()

        return path

    def table_names(self, name: str = "broker.db") -> set[str]:
        con = sqlite3.connect(self.tmp / name)
        try:
            return {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            con.close()


class FreshDatabaseTests(_DbTestCase):
    """A database created from nothing."""

    def test_every_table_is_created(self) -> None:
        self.open_db()

        self.assertLessEqual(
            {"accounts", "account_snapshots", "holdings", "transactions"},
            self.table_names(),
        )

    def test_no_legacy_table_is_invented(self) -> None:
        self.open_db()

        self.assertNotIn(LEGACY_ACCOUNTS_TABLE, self.table_names())

    def test_accounts_holds_identity_not_balances(self) -> None:
        db = self.open_db()

        with db.db_engine.connect() as conn:
            columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info(accounts)"))
            }

        self.assertLessEqual(
            {
                "broker",
                "source",
                "account_key",
                "external_id",
                "display_name",
                "beneficiary",
                "kind",
                "first_seen",
                "last_seen",
            },
            columns,
        )
        self.assertNotIn(
            "balance", columns, "balance belongs to a snapshot, not an identity"
        )


class LegacySaveAccountDataTests(_DbTestCase):
    """The pre-history write path still works, and lands in the new tables."""

    def test_a_balance_becomes_an_identity_and_a_snapshot(self) -> None:
        db = self.open_db()

        db.save_account_data(
            account_name="ROTH IRA (123456789)",
            balance="$1,234.56",
            timestamp="2026-01-01 00:00:00",
        )

        self.assertEqual(len(db.get_accounts()), 1)

        snapshots = db.get_snapshots()
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0][4], 1234.56, "the balance must be a number")

    def test_the_raw_text_survives_beside_the_number(self) -> None:
        db = self.open_db()

        db.save_account_data(
            account_name="ROTH IRA",
            balance="$1,234.56",
            timestamp="2026-01-01 00:00:00",
        )

        with db.db_engine.connect() as conn:
            raw = conn.execute(text("SELECT raw_value FROM account_snapshots")).scalar()

        self.assertEqual(raw, "$1,234.56")

    def test_an_unnamed_account_gets_the_same_fallback_as_before(self) -> None:
        # The fallback has to match, or a user's unnamed history forks in two.
        db = self.open_db()

        db.save_account_data(
            account_name=None, balance="$1.00", timestamp="2026-01-01 00:00:00"
        )

        self.assertEqual(db.get_accounts()[0][2], "Unknown account")

    def test_get_account_data_keeps_its_pre_history_shape(self) -> None:
        # Navigators and any third-party caller unpack these four in this order.
        db = self.open_db()

        db.save_account_data(
            account_name="ROTH IRA",
            balance="$1,234.56",
            timestamp="2026-01-01 00:00:00",
        )

        rows = db.get_account_data()
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 4)
        self.assertEqual(rows[0][1], "ROTH IRA")
        self.assertEqual(rows[0][2], "$1,234.56")
        self.assertEqual(rows[0][3], "2026-01-01 00:00:00")


class LegacyMigrationTests(_DbTestCase):
    """Opening a database written before account history existed."""

    def test_the_original_table_is_kept_not_dropped(self) -> None:
        # It is the user's only undo if a balance format was misread.
        self.write_legacy()
        self.open_db()

        self.assertIn(LEGACY_ACCOUNTS_TABLE, self.table_names())

        con = sqlite3.connect(self.tmp / "broker.db")
        try:
            kept = con.execute(
                f"SELECT COUNT(*) FROM {LEGACY_ACCOUNTS_TABLE}"
            ).fetchone()
        finally:
            con.close()

        self.assertEqual(kept[0], len(LEGACY_ROWS))

    def test_every_legacy_row_becomes_a_snapshot(self) -> None:
        self.write_legacy()
        db = self.open_db()

        self.assertEqual(len(db.get_snapshots()), len(LEGACY_ROWS))

    def test_repeated_names_collapse_into_one_identity(self) -> None:
        self.write_legacy()
        db = self.open_db()

        names = sorted(row[2] for row in db.get_accounts())
        self.assertEqual(names, ["Ezekiel", "Fidelity - Roth", "Unknown account"])

    def test_text_balances_become_numbers(self) -> None:
        self.write_legacy()
        db = self.open_db()

        by_time = {row[3]: row[4] for row in db.get_snapshots()}

        self.assertEqual(by_time["2025-12-01 00:00:00"], 1000.0)
        self.assertEqual(by_time["2025-12-02 00:00:00"], 1100.0)

    def test_a_negative_balance_keeps_its_sign(self) -> None:
        self.write_legacy()
        db = self.open_db()

        values = [row[4] for row in db.get_snapshots()]
        self.assertIn(-50.0, values)

    def test_an_unreadable_balance_becomes_null_not_zero(self) -> None:
        # A NULL says "no number here". A zero would be a claim about the money.
        self.write_legacy()
        db = self.open_db()

        unreadable = [row for row in db.get_snapshots() if row[1] == "Unknown account"]
        self.assertEqual(len(unreadable), 1)
        self.assertIsNone(unreadable[0][4])

        with db.db_engine.connect() as conn:
            raw = conn.execute(
                text("SELECT raw_value FROM account_snapshots WHERE value IS NULL")
            ).scalar()

        self.assertEqual(raw, "--", "the original text still has to be there")

    def test_migrated_history_supports_a_delta(self) -> None:
        # The whole point: two consecutive snapshots now subtract.
        self.write_legacy()
        db = self.open_db()

        deltas = {(row[0], row[2]): row[5] for row in db.get_daily_change()}

        self.assertEqual(deltas[("Ezekiel", "2025-12-02 00:00:00")], 100.0)

    def test_opening_the_same_database_twice_changes_nothing(self) -> None:
        self.write_legacy()

        first = self.open_db()
        before = first.get_snapshots()
        first.shutdown_db()
        self.opened.remove(first)

        second = self.open_db()

        self.assertEqual(
            len(second.get_snapshots()),
            len(before),
            "a second open must not replay the legacy rows again",
        )
        self.assertEqual(len(second.get_accounts()), 3)

    def test_a_database_already_on_the_new_schema_is_left_alone(self) -> None:
        db = self.open_db()
        db.save_account_data(
            account_name="ROTH IRA", balance="$1.00", timestamp="2026-01-01 00:00:00"
        )
        db.shutdown_db()
        self.opened.remove(db)

        again = self.open_db()

        self.assertEqual(len(again.get_snapshots()), 1)
        self.assertNotIn(LEGACY_ACCOUNTS_TABLE, self.table_names())

    def test_a_write_after_migration_continues_the_same_history(self) -> None:
        # This is what the account_key choice buys: the string save_account_data
        # always passed is the identity, so post-upgrade rows join up with
        # pre-upgrade ones instead of forking a second account.
        self.write_legacy()
        db = self.open_db()

        db.save_account_data(
            account_name="Ezekiel",
            balance="$1,200.00",
            timestamp="2025-12-04 00:00:00",
        )

        self.assertEqual(
            len(db.get_accounts()), 3, "no new identity should have appeared"
        )

        ezekiel = [row for row in db.get_snapshots() if row[1] == "Ezekiel"]
        self.assertEqual(len(ezekiel), 3)


if __name__ == "__main__":
    unittest.main()
