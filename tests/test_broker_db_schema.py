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

from keyring_isolation import MemoryKeyringMixin
from stonksmith.etc.broker_db import LEGACY_ACCOUNTS_TABLE, BrokerDatabase
from stonksmith.etc.infrastructure import create_db_engine
from stonksmith.etc.records import AccountIdentity, Holding
from stonksmith.etc.secrets import get_secret

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
    ("Beneficiary A", "$1,000.00", "2025-12-01 00:00:00"),
    ("Beneficiary A", "$1,100.00", "2025-12-02 00:00:00"),
    ("Ally - Roth", "-$50.00", "2025-12-02 00:00:00"),
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

    def open_db(self, name: str = "broker.db", broker: str = "ally") -> Any:
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

    def test_shutdown_returns_the_connections_to_the_system(self) -> None:
        """
        shutdown_db() disposes the engine, not only the session.

        Closing the session hands its connection back to the pool, which holds
        it open. Every such connection then survived until the garbage collector
        finalised the engine, and sqlite3 reported it from a context where no
        test was running to fail -- so the suite stayed green while leaking one
        connection per database opened.

        Asserted on the pool rather than on the warning, because the warning is
        raised during finalisation and cannot be attributed to anything by then.
        """

        db = self.open_db()
        db.get_credentials()

        # Closing the session alone -- what shutdown_db() used to do -- moves
        # the connection from checked-out to idle-in-pool. Idle, not closed.
        db.sess.close()
        self.assertEqual(
            db.db_engine.pool.checkedin(), 1, "the leak this test exists for"
        )

        db.shutdown_db()

        # dispose() swaps in a fresh pool, so what the old one held is closed
        # rather than merely idle.
        self.assertEqual(db.db_engine.pool.checkedin(), 0)

    def test_shutdown_twice_is_harmless(self) -> None:
        """
        main.py and portfolio.py dispose the engine themselves, and both still
        do; the second call has to be a no-op rather than an error.
        """

        db = self.open_db()
        db.shutdown_db()
        db.shutdown_db()

        # And the engine is still usable afterwards, which is what makes
        # disposing from inside the database safe at all.
        self.assertIsNotNone(db.get_credentials())

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
        self.assertEqual(names, ["Ally - Roth", "Beneficiary A", "Unknown account"])

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

        self.assertEqual(deltas[("Beneficiary A", "2025-12-02 00:00:00")], 100.0)

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
            account_name="Beneficiary A",
            balance="$1,200.00",
            timestamp="2025-12-04 00:00:00",
        )

        self.assertEqual(
            len(db.get_accounts()), 3, "no new identity should have appeared"
        )

        beneficiary_a = [row for row in db.get_snapshots() if row[1] == "Beneficiary A"]
        self.assertEqual(len(beneficiary_a), 3)


class HoldingUnitsDateMigrationTests(_DbTestCase):
    """The units date gets a column, and the databases in the wild get it too.

    create_all never alters an existing table, so a column added to the Python
    schema does not reach a file anyone already has. That would not be quiet
    about it -- save_snapshot names every column unconditionally, so the next
    sync would die on "table holdings has no column named units_as_of" -- but it
    would die after a login and a scrape, and Ally needs a fresh sign-in every
    run. Hence a migration, and hence these.

    Nothing tested any ALTER in this project before this class. The one that
    already existed, in migrate_plaintext_secrets, went unexercised because the
    legacy fixture below has no ``password`` column for it to find.
    """

    def older_database(
        self, broker: str, raw_value: str | None, name: str = "broker.db"
    ) -> Path:
        """
        A database shaped the way one written before this column was.

        Built by opening a current one and dropping the column again, rather
        than by hand-writing the old CREATE TABLE. A literal would be a second
        copy of the schema that drifts the day anything else is added, and the
        thing under test is the migration, not my typing.
        :param broker: The broker the database belongs to
        :param raw_value: What to leave in the holding's raw_value
        :param name: The database file name
        :return: The path to it
        :rtype: Path
        """

        db = BrokerDatabase(create_db_engine(db_path=self.tmp / name), broker)
        db.save_snapshot(
            account=AccountIdentity(
                account_key="TSP L 2060", display_name="TSP L 2060"
            ),
            scraped_at="2026-08-08 09:00:00",
            as_of="2026-08-07",
            value=2473.44,
            holdings=[
                Holding(
                    fund_code="L 2060",
                    units=100.0,
                    price=24.7344,
                    value=2473.44,
                    raw_value=raw_value,
                )
            ],
        )
        db.shutdown_db()

        con = sqlite3.connect(self.tmp / name)
        try:
            con.execute("ALTER TABLE holdings DROP COLUMN units_as_of")
            con.commit()
        finally:
            con.close()

        return self.tmp / name

    def holding(self, name: str = "broker.db") -> tuple[Any, ...]:
        con = sqlite3.connect(self.tmp / name)
        try:
            return con.execute("SELECT units_as_of, raw_value FROM holdings").fetchone()
        finally:
            con.close()

    def columns(self, name: str = "broker.db") -> list[str]:
        con = sqlite3.connect(self.tmp / name)
        try:
            return [row[1] for row in con.execute("PRAGMA table_info(holdings)")]
        finally:
            con.close()

    def test_an_older_database_gains_the_column(self) -> None:
        self.older_database(broker="tsp", raw_value="2026-06-30")
        self.assertNotIn("units_as_of", self.columns())

        self.open_db(broker="tsp")

        self.assertIn("units_as_of", self.columns())

    def test_a_write_against_an_older_database_no_longer_fails(self) -> None:
        # The one that proves the migration is not decorative. Without it this
        # raises OperationalError, because the insert names every column.
        self.older_database(broker="tsp", raw_value="2026-06-30")
        db = self.open_db(broker="tsp")

        db.save_snapshot(
            account=AccountIdentity(account_key="TSP C", display_name="TSP C"),
            scraped_at="2026-08-09 09:00:00",
            value=100.0,
            holdings=[Holding(fund_code="C", units=1.0, units_as_of="2026-06-30")],
        )

        self.assertEqual(len(db.get_current_holdings()), 2)

    def test_a_stranded_units_date_moves_into_its_own_column(self) -> None:
        self.older_database(broker="tsp", raw_value="2026-06-30")

        self.open_db(broker="tsp")

        self.assertEqual(self.holding()[0], "2026-06-30")

    def test_the_original_text_is_kept_beside_it(self) -> None:
        # Same reasoning as the legacy accounts table being renamed rather than
        # dropped: a migration that has to guess should not destroy its input.
        self.older_database(broker="tsp", raw_value="2026-06-30")

        self.open_db(broker="tsp")

        self.assertEqual(self.holding()[1], "2026-06-30")

    def test_a_value_that_is_not_a_date_is_left_where_it_is(self) -> None:
        # What every other broker keeps in raw_value. Reading one of these as a
        # date would put a date column full of nonsense on the sheet.
        self.older_database(broker="ally", raw_value="$1,500.00")

        self.open_db(broker="ally")

        self.assertIsNone(self.holding()[0])
        self.assertEqual(self.holding()[1], "$1,500.00")

    def test_a_broker_that_never_stored_a_date_there_is_not_searched(self) -> None:
        # The 529 parser puts the value text here too. Even when one happens to
        # parse, it is not a units date and must not become one.
        self.older_database(broker="schwab529plan", raw_value="2026-06-30")

        self.open_db(broker="schwab529plan")

        self.assertIsNone(self.holding()[0])

    def test_a_holding_with_no_raw_value_survives_the_migration(self) -> None:
        self.older_database(broker="tsp", raw_value=None)

        self.open_db(broker="tsp")

        self.assertIsNone(self.holding()[0])

    def test_opening_the_same_database_twice_changes_nothing(self) -> None:
        self.older_database(broker="tsp", raw_value="2026-06-30")

        first = self.open_db(broker="tsp")
        first.shutdown_db()
        before: tuple[Any, ...] = self.holding()

        self.open_db(broker="tsp")

        self.assertEqual(self.holding(), before)

    def test_a_hand_set_date_is_not_clobbered_by_a_later_open(self) -> None:
        self.older_database(broker="tsp", raw_value="2026-06-30")
        self.open_db(broker="tsp").shutdown_db()

        con = sqlite3.connect(self.tmp / "broker.db")
        try:
            con.execute("UPDATE holdings SET units_as_of = '2026-03-31'")
            con.commit()
        finally:
            con.close()

        self.open_db(broker="tsp")

        self.assertEqual(self.holding()[0], "2026-03-31")

    def test_a_fresh_database_migrates_nothing(self) -> None:
        db = self.open_db(broker="tsp")

        self.assertIn("units_as_of", self.columns())
        self.assertEqual(db.migrate_holding_dates(), 0)

    def test_a_migrated_schema_matches_a_fresh_one(self) -> None:
        # The column goes last in the table definition for this reason: ALTER
        # can only append, so a migrated file and a new one would otherwise
        # disagree about column order forever.
        self.older_database(broker="tsp", raw_value="2026-06-30")
        self.open_db(broker="tsp")
        self.open_db(name="fresh.db", broker="tsp")

        self.assertEqual(self.columns(), self.columns(name="fresh.db"))


class PlaintextSecretMigrationTests(_DbTestCase):
    """The other silent ALTER, which had no test at all until now.

    LEGACY_SCHEMA above gives ``credentials`` a keyring_key and no password, so
    migrate_plaintext_secrets returned 0 on every run of this suite and its
    ALTER never executed. This is a database that actually predates the keyring.
    """

    PRE_KEYRING = """
    CREATE TABLE credentials (
        id INTEGER PRIMARY KEY,
        username TEXT,
        password TEXT,
        type TEXT,
        pillaged_from TEXT
    );
    """

    #: Rows to leave behind when the question is what survives in the file
    #: rather than what SELECT returns.
    #:
    #: Ten, and the number is measured rather than picked. Whether the cleared
    #: plaintext survives is a function of page layout, not of chance: with one
    #: credential SQLite rewrites that page in place and the old bytes go with
    #: it, so a one-row fixture asserts something already true and would pass
    #: with the VACUUM reverted. Across 15 runs per size, 1 row survived 0/15
    #: and 5 rows 0/15, while 2, 3, 10, 20 and 50 all survived 15/15. Ten is the
    #: smallest round number reliably on the surviving side.
    CREDENTIALS_LEFT_BEHIND = 10

    def write_pre_keyring(self, name: str = "broker.db", count: int = 1) -> None:
        con = sqlite3.connect(self.tmp / name)
        try:
            con.executescript(self.PRE_KEYRING)
            con.executemany(
                "INSERT INTO credentials (username, password, type, pillaged_from) "
                "VALUES (?, 'hunter2', 'plaintext', 'manual')",
                [(f"someone{i}" if count > 1 else "someone",) for i in range(count)],
            )
            con.commit()
        finally:
            con.close()

    def credential(self, name: str = "broker.db") -> tuple[Any, ...]:
        con = sqlite3.connect(self.tmp / name)
        try:
            return con.execute(
                "SELECT password, keyring_key FROM credentials"
            ).fetchone()
        finally:
            con.close()

    def test_the_keyring_key_column_is_added(self) -> None:
        self.write_pre_keyring()

        self.open_db()

        self.assertIsNotNone(self.credential()[1])

    def test_the_secret_leaves_the_database_for_the_keyring(self) -> None:
        self.write_pre_keyring()

        self.open_db()

        password, key = self.credential()
        self.assertIsNone(password, "the plaintext must not survive")
        self.assertEqual(get_secret(key=key), "hunter2")

    def test_a_second_open_migrates_nothing(self) -> None:
        self.write_pre_keyring()
        db = self.open_db()

        self.assertEqual(db.migrate_plaintext_secrets(), 0)

    def test_the_cleared_plaintext_does_not_survive_in_the_file(self) -> None:
        """The one claim SQL cannot make, so this reads the bytes.

        ``test_the_secret_leaves_the_database_for_the_keyring`` above asserts
        the password column is NULL, and that is true the instant the UPDATE
        lands whether or not the old bytes are still in the file -- freed pages
        are not reachable from SELECT. So the assertion that the plaintext is
        *gone* has to be made against the file itself, and it is the reason
        migrate_plaintext_secrets ends in a VACUUM.
        """

        self.write_pre_keyring(count=self.CREDENTIALS_LEFT_BEHIND)

        self.open_db()

        self.assertNotIn(
            b"hunter2",
            (self.tmp / "broker.db").read_bytes(),
            "the cleared plaintext is still readable in the database file",
        )

    def test_nothing_is_vacuumed_when_nothing_migrated(self) -> None:
        """A VACUUM on every open would rewrite every database, every run.

        migrate_plaintext_secrets() is called from __init__, so the guard on
        ``migrated`` is what keeps a whole-file rewrite off the common path. A
        VACUUM leaves the free list empty; a database opened twice has had no
        second migration and so must still be carrying whatever free pages its
        ordinary writes left.
        """

        self.write_pre_keyring(count=self.CREDENTIALS_LEFT_BEHIND)
        self.open_db()

        con = sqlite3.connect(self.tmp / "broker.db")
        try:
            con.execute("CREATE TABLE scratch (blob TEXT)")
            con.executemany(
                "INSERT INTO scratch (blob) VALUES (?)", [("x" * 400,)] * 200
            )
            con.execute("DROP TABLE scratch")
            con.commit()
            freed: int = con.execute("PRAGMA freelist_count").fetchone()[0]
        finally:
            con.close()

        self.assertGreater(freed, 0, "the fixture did not free any pages")

        self.open_db(name="broker.db")

        con = sqlite3.connect(self.tmp / "broker.db")
        try:
            after: int = con.execute("PRAGMA freelist_count").fetchone()[0]
        finally:
            con.close()

        self.assertEqual(after, freed, "opening the database vacuumed it")


if __name__ == "__main__":
    unittest.main()
