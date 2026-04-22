import logging
import sys
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etc.connection import Connection
from etc.context import Context


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class _RecordingModule:
    name = "recording"

    def __init__(self) -> None:
        self.context: Context | None = None
        self.connection: Connection | None = None

    def on_login(self, context: Context, connection: Connection) -> None:
        self.context = context
        self.connection = connection


class _FailingModule:
    name = "failing"

    def on_login(self, context: Context, connection: Connection) -> None:
        raise RuntimeError("boom")


class _StubDB:
    """Minimal DB stub that satisfies BrokerDbProtocol."""

    def get_credentials(self, filter_term: str | None = None) -> list[tuple[str, ...]]:
        return []

    def save_account_data(
        self, account_name: str | None, balance: str | None, timestamp: str
    ) -> None:
        pass

    def shutdown_db(self) -> None:
        pass


class ConnectionModuleContextTests(unittest.TestCase):
    def test_call_modules_includes_active_and_cli_credentials(self) -> None:
        conn = Connection()
        conn.args = Namespace(
            module_run_markers=False,
            username=["cli-user"],
            password=["cli-pass"],
        )
        conn.db = _StubDB()
        conn.username = "active-user"
        conn.password = "active-pass"

        module = _RecordingModule()
        conn.module = [module]

        conn.call_modules()

        self.assertIsNotNone(module.context)
        assert module.context is not None
        self.assertEqual(module.context.active_username, "active-user")
        self.assertEqual(module.context.active_password, "active-pass")
        self.assertEqual(module.context.cli_usernames, ["cli-user"])
        self.assertEqual(module.context.cli_passwords, ["cli-pass"])

    def test_call_modules_logs_module_exception(self) -> None:
        conn = Connection()
        conn.args = Namespace(
            module_run_markers=False,
            username=["cli-user"],
            password=["cli-pass"],
        )
        conn.db = _StubDB()
        conn.username = "active-user"
        conn.password = "active-pass"

        capture = _CaptureHandler()
        conn.logger.logger.addHandler(capture)

        try:
            conn.module = [_FailingModule()]
            conn.call_modules()
        finally:
            conn.logger.logger.removeHandler(capture)

        self.assertTrue(any("Module failing failed" in msg for msg in capture.messages))


if __name__ == "__main__":
    unittest.main()
