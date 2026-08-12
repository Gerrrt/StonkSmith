"""Credential storage must keep secrets in the OS keyring, never in SQLite."""

import tempfile
import unittest
from pathlib import Path

import keyring
import keyring.backend
from sqlalchemy import text

from stonksmith.etc.infrastructure import create_db_engine
from stonksmith.loaders.brokerloader import BrokerLoader


class _MemoryKeyring(keyring.backend.KeyringBackend):
    """In-memory keyring so tests never touch the real credential store."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.store.pop((service, username), None)


def _load_database_class() -> type:
    """
    Resolve the broker Database the way main.py does.

    Through the loader rather than by loading a file: schwab529plan no longer
    ships a database.py, and neither do the other four. Asking the loader is
    what production does, so this exercises the same answer rather than a path
    that happens to exist.
    """

    resolved = BrokerLoader().database_class(name="schwab529plan")
    assert resolved is not None
    return resolved


class CredentialKeyringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous = keyring.get_keyring()
        self.memory = _MemoryKeyring()
        keyring.set_keyring(self.memory)
        self.Database = _load_database_class()
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        keyring.set_keyring(self.previous)

    def test_secret_is_stored_in_keyring_and_not_in_sqlite(self) -> None:
        engine = create_db_engine(db_path=self.tmp / "fresh.db")
        db = self.Database(engine, "schwab529plan")

        db.add_credential(username="alice", secret="hunter2")

        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM credentials")).fetchall()

        self.assertNotIn("hunter2", str(rows))
        self.assertEqual(db.get_credential_refs()[0][2], "schwab529plan:alice")
        self.assertEqual(db.get_credentials()[0][2], "hunter2")
        db.shutdown_db()

    def test_refs_never_expose_the_secret(self) -> None:
        engine = create_db_engine(db_path=self.tmp / "refs.db")
        db = self.Database(engine, "schwab529plan")
        db.add_credential(username="alice", secret="hunter2")

        self.assertNotIn("hunter2", str(db.get_credential_refs()))
        db.shutdown_db()

    def test_delete_removes_row_and_keyring_entry(self) -> None:
        engine = create_db_engine(db_path=self.tmp / "delete.db")
        db = self.Database(engine, "schwab529plan")
        db.add_credential(username="alice", secret="hunter2")

        self.assertTrue(db.delete_credential(cred_id=1))
        self.assertEqual(db.get_credentials(), [])
        self.assertEqual(self.memory.store, {})
        db.shutdown_db()

    def test_legacy_plaintext_column_is_migrated_into_the_keyring(self) -> None:
        engine = create_db_engine(db_path=self.tmp / "legacy.db")
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE credentials (id INTEGER PRIMARY KEY, username TEXT, "
                    "password TEXT, type TEXT, pillaged_from TEXT)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO credentials "
                    "VALUES (1,'bob','s3cret','plaintext','manual')"
                )
            )
            conn.commit()

        db = self.Database(engine, "schwab529plan")

        with engine.connect() as conn:
            username, password, key = conn.execute(
                text("SELECT username, password, keyring_key FROM credentials")
            ).fetchone()

        self.assertEqual(username, "bob")
        self.assertIsNone(password, "plaintext password must be cleared in place")
        self.assertEqual(key, "schwab529plan:bob")
        self.assertEqual(db.get_credentials()[0][2], "s3cret")
        db.shutdown_db()

    def test_missing_keyring_entry_yields_empty_secret(self) -> None:
        engine = create_db_engine(db_path=self.tmp / "missing.db")
        db = self.Database(engine, "schwab529plan")
        db.add_credential(username="alice", secret="hunter2")

        self.memory.store.clear()

        self.assertEqual(db.get_credentials()[0][2], "")
        db.shutdown_db()

    def test_an_empty_filter_matches_nothing_rather_than_every_credential(self) -> None:
        # Connection.query_db_creds spells "no filter" as the literal "all", so
        # every other value is a filter. `--cred-id ""` used to be dropped on
        # the floor by `if filter_term:`, which handed back every credential --
        # with secrets resolved -- and looked like a filter that matched all.
        engine = create_db_engine(db_path=self.tmp / "empty_filter.db")
        db = self.Database(engine, "schwab529plan")
        db.add_credential(username="alice", secret="hunter2")
        db.add_credential(username="bob", secret="s3cret")

        self.assertEqual(len(db.get_credential_refs()), 2, "both are stored")

        self.assertEqual(db.get_credential_refs(filter_term=""), [])
        self.assertEqual(db.get_credentials(filter_term=""), [])

        # An id that does exist still narrows, and "1" is a str here because
        # that is what argparse hands over.
        self.assertEqual(len(db.get_credentials(filter_term="1")), 1)
        db.shutdown_db()


if __name__ == "__main__":
    unittest.main()
