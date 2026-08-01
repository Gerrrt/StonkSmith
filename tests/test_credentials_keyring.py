"""Credential storage must keep secrets in the OS keyring, never in SQLite."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

import keyring
import keyring.backend
from sqlalchemy import text

from etc.infrastructure import create_db_engine


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
    """Load the broker Database the way BrokerLoader does: by file path."""

    path = Path(__file__).resolve().parents[1] / "src/brokers/schwab529plan/database.py"
    spec = importlib.util.spec_from_file_location("schwab529_database", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Database


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


if __name__ == "__main__":
    unittest.main()
