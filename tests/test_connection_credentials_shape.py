import sys
import unittest
from argparse import Namespace
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etc.connection import Connection
from etc.logger import StonkSmithAdapter


class _StubLogger:
    def __init__(self) -> None:
        self.debug_messages: list[str] = []
        self.error_messages: list[str] = []
        self.highlight_messages: list[str] = []

    def debug(self, msg: str) -> None:
        self.debug_messages.append(msg)

    def error(self, msg: str) -> None:
        self.error_messages.append(msg)

    def highlight(self, msg: str) -> None:
        self.highlight_messages.append(msg)


class _StubDB:
    def __init__(self, rows: list[tuple[str, ...]]) -> None:
        self._rows = rows

    def get_credentials(self, filter_term: str | None = None) -> list[tuple[str, ...]]:
        return self._rows

    def save_account_data(
        self, account_name: str | None, balance: str | None, timestamp: str
    ) -> None:
        pass

    def shutdown_db(self) -> None:
        pass


class ConnectionCredentialShapeTests(unittest.TestCase):
    def _build_connection(
        self, rows: list[tuple[str, ...]]
    ) -> tuple[Connection, _StubLogger]:
        conn = Connection()
        logger = _StubLogger()
        conn.logger = cast(StonkSmithAdapter, logger)
        conn.db = _StubDB(rows)
        conn.args = Namespace(cred_id=["all"])
        return conn, logger

    def test_query_db_creds_truncates_extra_columns(self) -> None:
        conn, logger = self._build_connection(
            [("1", "alice", "secret", "plaintext", "manual", "extra")]
        )

        usernames, owned, secrets, types, metadata = conn.query_db_creds()

        self.assertEqual(usernames, ["alice"])
        self.assertEqual(owned, [False])
        self.assertEqual(secrets, ["secret"])
        self.assertEqual(types, ["plaintext"])
        self.assertEqual(metadata, [None])
        self.assertTrue(
            any(
                "unexpected extra values" in message
                for message in logger.highlight_messages
            )
        )

    def test_query_db_creds_skips_malformed_short_rows(self) -> None:
        conn, logger = self._build_connection([("1", "alice", "secret")])

        usernames, owned, secrets, types, metadata = conn.query_db_creds()

        self.assertEqual(usernames, [])
        self.assertEqual(owned, [])
        self.assertEqual(secrets, [])
        self.assertEqual(types, [])
        self.assertEqual(metadata, [])
        self.assertTrue(
            any(
                "Skipping malformed credential row" in message
                for message in logger.error_messages
            )
        )


if __name__ == "__main__":
    unittest.main()
