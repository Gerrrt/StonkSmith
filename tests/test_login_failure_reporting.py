"""A run that cannot log in must say why.

From the field: `stonksmith ally -M ally -id 1` with no stored
credential opened a browser, closed it, and printed nothing at all. Every
progress message in this path is INFO, which the default log level hides, and
the three failure exits were silent.
"""

import logging
import unittest
from argparse import Namespace
from unittest.mock import MagicMock

from stonksmith.etc.connection import Connection


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class _NoCreds:
    def get_credentials(self, filter_term: str | None = None) -> list[tuple[str, ...]]:
        return []

    def save_account_data(self, account_name, balance, timestamp) -> None:
        pass

    def shutdown_db(self) -> None:
        pass


class _OneCred:
    def get_credentials(self, filter_term: str | None = None) -> list[tuple[str, ...]]:
        return [("1", "alice", "secret", "plaintext", "manual")]

    def save_account_data(self, account_name, balance, timestamp) -> None:
        pass

    def shutdown_db(self) -> None:
        pass


class LoginFailureReportingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.capture = _CaptureHandler()
        self.logger = logging.getLogger("stonksmith")
        self.logger.addHandler(self.capture)
        # The level a plain run uses, where INFO messages are invisible.
        self.previous = self.logger.level
        self.logger.setLevel(logging.ERROR)

    def tearDown(self) -> None:
        self.logger.removeHandler(self.capture)
        self.logger.setLevel(self.previous)

    def _conn(self, db: object, **args) -> Connection:
        conn = Connection()
        conn.broker = "Ally"
        conn.args = Namespace(
            cred_id=[], username=[], password=[], module_run_markers=False, **args
        )
        conn.db = db
        return conn

    def _logged(self) -> str:
        return " ".join(self.capture.messages)

    def test_missing_credential_id_is_reported(self) -> None:
        conn = self._conn(_NoCreds())
        conn.args.cred_id = ["1"]

        self.assertFalse(conn.login())

        logged = self._logged()
        self.assertIn("No credential in the database with id 1", logged)
        self.assertIn("add creds", logged, "should say how to fix it")

    def test_no_credentials_at_all_is_reported(self) -> None:
        conn = self._conn(_NoCreds())

        self.assertFalse(conn.login())

        self.assertIn("No credentials supplied", self._logged())

    def test_all_attempts_failing_is_reported(self) -> None:
        conn = self._conn(_OneCred())
        conn.args.cred_id = ["1"]
        conn.plaintext_login = MagicMock(return_value=False)

        self.assertFalse(conn.login())

        self.assertIn("Login failed for all 1 credential(s)", self._logged())

    def test_successful_login_reports_nothing(self) -> None:
        conn = self._conn(_OneCred())
        conn.args.cred_id = ["1"]
        conn.plaintext_login = MagicMock(return_value=True)

        self.assertTrue(conn.login())
        self.assertEqual(conn.username, "alice")
        self.assertEqual(self.capture.messages, [])

    def test_broker_flow_does_not_duplicate_a_connection_failure(self) -> None:
        # create_conn_obj() owns reporting its own failure; broker_flow() adding
        # a generic line would print a second, vaguer message for one problem.
        conn = self._conn(_NoCreds())
        conn.create_conn_obj = MagicMock(return_value=False)
        conn.login = MagicMock()

        conn.broker_flow()

        conn.login.assert_not_called()
        self.assertEqual(self.capture.messages, [])

    def test_all_credentials_failing_reports_once(self) -> None:
        conn = self._conn(_OneCred())
        conn.args.cred_id = ["1"]
        conn.plaintext_login = MagicMock(return_value=False)

        conn.broker_flow()

        failures = [m for m in self.capture.messages if "Login failed for all" in m]
        self.assertEqual(len(failures), 1)

    def test_continue_on_success_still_reports_success(self) -> None:
        # The loop runs to the end even after a success, so the outcome has to
        # be tracked; otherwise a successful login reported as a total failure.
        conn = self._conn(_OneCred())
        conn.args.cred_id = ["1"]
        conn.args.continue_on_success = True
        conn.plaintext_login = MagicMock(return_value=True)

        self.assertTrue(conn.login())
        self.assertNotIn("Login failed for all", self._logged())

    def test_id_all_with_empty_database_says_so(self) -> None:
        conn = self._conn(_NoCreds())
        conn.args.cred_id = ["all"]

        conn.login()

        logged = self._logged()
        self.assertIn("No credentials stored in the database", logged)
        self.assertNotIn("with id all", logged, "'all' is not an id")

    def test_broker_flow_does_not_run_modules_when_login_fails(self) -> None:
        conn = self._conn(_NoCreds())
        conn.args.cred_id = ["1"]
        conn.call_modules = MagicMock()
        conn.module = [MagicMock()]

        conn.broker_flow()

        conn.call_modules.assert_not_called()
        # ...and the run explained itself rather than ending in silence.
        self.assertTrue(self.capture.messages)

    def test_broker_flow_runs_modules_on_success(self) -> None:
        conn = self._conn(_OneCred())
        conn.args.cred_id = ["1"]
        conn.plaintext_login = MagicMock(return_value=True)
        conn.call_modules = MagicMock()
        conn.module = [MagicMock()]

        conn.broker_flow()

        conn.call_modules.assert_called_once()


if __name__ == "__main__":
    unittest.main()
