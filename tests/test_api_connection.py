"""An API-backed broker must run without credentials, and fail loudly.

Connection.login() is written for the scraper shape: with no -u and no -id it
reports "No credentials supplied" and returns False, and broker_flow() then
returns without logging anything of its own. A broker whose key lives in the
keyring has nothing to supply, so inheriting that check turns every run into a
no-op that prints nothing and exits 0.

These tests pin the shape itself -- no broker, no SDK, no config, no keyring.
"""

import logging
import unittest
from argparse import Namespace
from unittest.mock import MagicMock

from etc.api_connection import ApiConnection


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class _Db:
    """A database that fails the test if credentials are ever consulted."""

    def __init__(self) -> None:
        self.credentials_read = False

    def get_credentials(self, filter_term: str | None = None) -> list[tuple[str, ...]]:
        self.credentials_read = True
        return []

    def save_account_data(self, account_name, balance, timestamp) -> None:
        pass

    def shutdown_db(self) -> None:
        pass


class _Working(ApiConnection):
    """The minimum a real API broker implements."""

    session_label = "test session"

    def __init__(self) -> None:
        super().__init__()
        self.broker = "Testly"
        self.name = "Testly"
        self.verified = False

    def create_conn_obj(self) -> bool:
        self.client = object()
        return True

    def verify_access(self) -> bool:
        self.verified = True
        return True


class _Rejected(_Working):
    """Key present, API says no."""

    def verify_access(self) -> bool:
        self.logger.fail(msg="SnapTrade rejected the stored key (401).")
        return False


class _CaptureMixin:
    """Capture stonksmith log output at the level a plain run actually uses.

    Not a TestCase: inheriting one from another re-runs every inherited test.
    """

    def setUp(self) -> None:
        self.capture = _CaptureHandler()
        self.logger = logging.getLogger("stonksmith")
        self.logger.addHandler(self.capture)
        # ERROR is the default (see etc.infrastructure.set_logging_level), and
        # it is the level that matters: anything a broker needs an operator to
        # see on an ordinary run has to survive it.
        self.previous = self.logger.level
        self.logger.setLevel(logging.ERROR)

    def tearDown(self) -> None:
        self.logger.removeHandler(self.capture)
        self.logger.setLevel(self.previous)

    def _args(self, **overrides) -> Namespace:
        """The argument shape every broker sees, with nothing supplied."""

        defaults: dict[str, object] = {
            "cred_id": [],
            "username": [],
            "password": [],
            "module_run_markers": False,
        }
        defaults.update(overrides)

        return Namespace(**defaults)

    def _logged(self) -> str:
        return " ".join(self.capture.messages)


class ApiConnectionTests(_CaptureMixin, unittest.TestCase):
    def test_login_succeeds_with_no_credentials(self) -> None:
        broker = _Working()
        broker.args = self._args()
        broker.db = _Db()

        self.assertTrue(broker.login())
        self.assertTrue(broker.verified, "login() must prove the key works")

    def test_login_never_consults_the_credentials_table(self) -> None:
        # Direct regression against inheriting Connection.login(): that path
        # queries the database and then fails the run when it finds nothing.
        broker = _Working()
        broker.args = self._args(cred_id=["all"])
        db = _Db()
        broker.db = db

        broker.login()

        self.assertFalse(db.credentials_read)
        self.assertNotIn("No credentials supplied", self._logged())

    def test_login_fails_when_the_key_is_rejected(self) -> None:
        broker = _Rejected()
        broker.args = self._args()
        broker.db = _Db()

        self.assertFalse(broker.login())
        self.assertIn("rejected the stored key", self._logged())

    def test_command_line_credentials_are_announced_as_ignored(self) -> None:
        # Informational, not a failure: the run still works, it just used the
        # stored key. So this one is INFO and only shows under --verbose, while
        # everything that stops a run is ERROR and always shows.
        self.logger.setLevel(logging.INFO)

        broker = _Working()
        broker.args = self._args(username=["alice"], password=["hunter2"])
        broker.db = _Db()

        broker.login()

        self.assertIn("ignored", self._logged())

    def test_a_password_alone_is_still_announced_as_ignored(self) -> None:
        # -p is the easiest of the three to pass on its own, and checking only
        # the two that carry an identity would let it be dropped in silence.
        self.logger.setLevel(logging.INFO)

        broker = _Working()
        broker.args = self._args(password=["hunter2"])
        broker.db = _Db()

        broker.login()

        self.assertIn("ignored", self._logged())

    def test_a_credential_id_alone_is_announced_as_ignored(self) -> None:
        self.logger.setLevel(logging.INFO)

        broker = _Working()
        broker.args = self._args(cred_id=["1"])
        broker.db = _Db()

        broker.login()

        self.assertIn("ignored", self._logged())

    def test_nothing_is_announced_when_no_credentials_were_passed(self) -> None:
        self.logger.setLevel(logging.INFO)

        broker = _Working()
        broker.args = self._args()
        broker.db = _Db()

        broker.login()

        self.assertNotIn("ignored", self._logged())

    def test_username_is_never_empty(self) -> None:
        # call_modules() logs "for unknown user" on every line when it is, and
        # hands the empty value to the module through Context.
        broker = _Working()
        broker.args = self._args()
        broker.db = _Db()

        broker.login()

        self.assertEqual(broker.username, "test session")

    def test_the_base_create_conn_obj_refuses_and_says_so(self) -> None:
        # A subclass that forgets to build a client must be loud, not silent.
        broker = ApiConnection()
        broker.broker = "Forgetful"
        broker.args = self._args()
        broker.db = _Db()

        self.assertFalse(broker.create_conn_obj())
        self.assertIn("does not implement create_conn_obj", self._logged())

    def test_teardown_drops_the_client(self) -> None:
        broker = _Working()
        broker.create_conn_obj()

        broker.teardown()

        self.assertIsNone(broker.client)


class ApiConnectionFlowTests(_CaptureMixin, unittest.TestCase):
    """broker_flow() end to end -- the case that would otherwise be silent."""

    def test_modules_run_with_zero_credentials(self) -> None:
        broker = _Working()
        broker.args = self._args()
        broker.db = _Db()
        broker.module = [MagicMock()]
        broker.call_modules = MagicMock()

        broker.broker_flow()

        broker.call_modules.assert_called_once()

    def test_a_rejected_key_stops_the_run_and_explains(self) -> None:
        broker = _Rejected()
        broker.args = self._args()
        broker.db = _Db()
        broker.module = [MagicMock()]
        broker.call_modules = MagicMock()

        broker.broker_flow()

        broker.call_modules.assert_not_called()
        self.assertTrue(self.capture.messages, "the run must not end in silence")

    def test_a_broker_that_cannot_connect_never_verifies(self) -> None:
        broker = _Working()
        broker.args = self._args()
        broker.db = _Db()
        broker.create_conn_obj = MagicMock(return_value=False)
        broker.module = [MagicMock()]
        broker.call_modules = MagicMock()

        broker.broker_flow()

        self.assertFalse(broker.verified)
        broker.call_modules.assert_not_called()


if __name__ == "__main__":
    unittest.main()
