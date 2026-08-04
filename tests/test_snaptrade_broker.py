"""The SnapTrade broker must explain every way it can fail to connect.

broker_flow() prints nothing of its own when create_conn_obj() or login()
returns False, so a quiet failure here is a run that opens nothing, writes
nothing and exits 0. Each of the four ways this broker can be misconfigured --
no clientId, no userId, no consumer key, no user secret -- has to produce one
line that says what to do about it.

Nothing here touches the network, the real keyring, or the real config file.
"""

import importlib.util
import logging
import unittest
from argparse import Namespace
from pathlib import Path
from typing import Any

import keyring
import keyring.backend

BROKER_FILE = (
    Path(__file__).resolve().parents[1] / "src" / "brokers" / "snaptrade" / "broker.py"
)


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class _MemoryKeyring(keyring.backend.KeyringBackend):
    """In-memory keyring so tests never touch the real credential store.

    CI forces keyring.backends.null.Keyring, which returns None for everything.
    A test asserting a *successful* read would pass locally and fail there
    without this.
    """

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


def _load_broker_module() -> Any:
    """Load broker.py by path, the way BrokerLoader does."""

    spec = importlib.util.spec_from_file_location("snaptrade_broker", BROKER_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Rejected(Exception):
    """Stands in for the SDK's ApiException, which carries .status."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


class _FakeClient:
    """Answers the two calls the broker makes, with no network."""

    def __init__(
        self,
        connections: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._connections = connections or []
        self._error = error
        self.accounts: list[dict[str, Any]] = []
        self.connections = self._Connections(self)
        self.account_information = self._Accounts(self)

    class _Connections:
        def __init__(self, outer: _FakeClient) -> None:
            self.outer = outer

        def list_brokerage_authorizations(self, **kwargs: Any) -> list[dict[str, Any]]:
            del kwargs
            if self.outer._error is not None:
                raise self.outer._error
            return self.outer._connections

    class _Accounts:
        def __init__(self, outer: _FakeClient) -> None:
            self.outer = outer

        def list_user_accounts(self, **kwargs: Any) -> list[dict[str, Any]]:
            del kwargs
            return self.outer.accounts


def _connection(
    conn_id: str, *, name: str = "Schwab", disabled: bool = False
) -> dict[str, Any]:
    return {
        "id": conn_id,
        "disabled": disabled,
        "disabled_date": "2026-07-01" if disabled else None,
        "brokerage": {"name": name, "slug": name.upper()},
    }


class SnapTradeBrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_broker_module()

        self.previous_keyring = keyring.get_keyring()
        self.memory = _MemoryKeyring()
        keyring.set_keyring(self.memory)

        self.capture = _CaptureHandler()
        self.logger = logging.getLogger("stonksmith")
        self.logger.addHandler(self.capture)
        self.previous_level = self.logger.level
        # Everything asserted here has to survive the default level.
        self.logger.setLevel(logging.ERROR)

        self.broker = self.module.SnapTradeBroker()
        self.broker.args = Namespace(cred_id=[], username=[], password=[])

        self._configure(client_id="PERS-TEST", user_id="garrett")

    def tearDown(self) -> None:
        keyring.set_keyring(self.previous_keyring)
        self.logger.removeHandler(self.capture)
        self.logger.setLevel(self.previous_level)

    def _configure(self, *, client_id: str, user_id: str) -> None:
        """Replace the config getters on the path-loaded module.

        The broker binds these names at import, so patching etc.config would
        not reach them -- and calling the real ones would read (and rewrite)
        the developer's own ~/.stonksmith/stonksmith.conf.
        """

        self.module.get_snaptrade_client_id = lambda: client_id
        self.module.get_snaptrade_user_id = lambda: user_id

    def _store(self, account: str, secret: str) -> None:
        self.memory.set_password("stonksmith", f"snaptrade:{account}", secret)

    def _store_both(self) -> None:
        self._store("consumerKey", "consumer-secret")
        self._store("garrett", "user-secret")

    def _logged(self) -> str:
        return " ".join(self.capture.messages)

    def test_missing_client_id_is_reported(self) -> None:
        self._configure(client_id="", user_id="garrett")

        self.assertFalse(self.broker.create_conn_obj())

        logged = self._logged()
        self.assertIn("[SNAPTRADE]", logged)
        self.assertIn("clientId", logged)
        self.assertIn("snaptrade_register.py", logged, "should say how to fix it")

    def test_missing_user_id_is_reported(self) -> None:
        self._configure(client_id="PERS-TEST", user_id="")

        self.assertFalse(self.broker.create_conn_obj())
        self.assertIn("userId", self._logged())

    def test_both_missing_identifiers_are_named_together(self) -> None:
        self._configure(client_id="", user_id="")

        self.broker.create_conn_obj()

        logged = self._logged()
        self.assertIn("clientId and userId are not set", logged)

    def test_a_single_missing_identifier_reads_as_singular(self) -> None:
        self._configure(client_id="PERS-TEST", user_id="")

        self.broker.create_conn_obj()

        self.assertIn("userId is not set", self._logged())

    def test_missing_consumer_key_is_reported(self) -> None:
        self._store("garrett", "user-secret")

        self.assertFalse(self.broker.create_conn_obj())

        logged = self._logged()
        self.assertIn("consumer key", logged)
        self.assertIn("snaptrade:consumerKey", logged, "should name the keyring entry")

    def test_missing_user_secret_is_reported(self) -> None:
        self._store("consumerKey", "consumer-secret")

        self.assertFalse(self.broker.create_conn_obj())

        logged = self._logged()
        self.assertIn("user secret", logged)
        self.assertIn("garrett", logged, "should name the user it looked for")

    def test_a_complete_configuration_builds_a_client(self) -> None:
        self._store_both()

        self.assertTrue(self.broker.create_conn_obj())

        self.assertIsNotNone(self.broker.client)
        self.assertEqual(self.broker.user_secret, "user-secret")
        self.assertEqual(self.capture.messages, [], "success should be quiet")

    def test_a_rejected_key_names_the_user_and_the_fix(self) -> None:
        self.broker.user_id = "garrett"
        self.broker.client = _FakeClient(error=_Rejected(401))

        self.assertFalse(self.broker.verify_access())

        logged = self._logged()
        self.assertIn("rejected the stored key", logged)
        self.assertIn("401", logged)
        self.assertIn("snaptrade_register.py", logged)

    def test_a_transport_error_is_reported_plainly(self) -> None:
        self.broker.client = _FakeClient(error=RuntimeError("connection reset"))

        self.assertFalse(self.broker.verify_access())

        logged = self._logged()
        self.assertIn("Could not reach SnapTrade", logged)
        self.assertNotIn("rejected the stored key", logged)

    def test_no_connections_is_a_failure_with_a_next_step(self) -> None:
        self.broker.client = _FakeClient(connections=[])

        self.assertFalse(self.broker.verify_access())
        self.assertIn("no brokerage connections", self._logged())

    def test_connections_are_indexed_by_id(self) -> None:
        self.broker.client = _FakeClient(
            connections=[_connection("aaa"), _connection("bbb", name="Fidelity")]
        )

        self.assertTrue(self.broker.verify_access())

        self.assertEqual(set(self.broker.connections), {"aaa", "bbb"})
        self.assertEqual(self.capture.messages, [])

    def test_a_disabled_connection_warns_but_does_not_stop_the_run(self) -> None:
        # SnapTrade keeps serving a disabled connection's last cached balance
        # instead of erroring, so this has to be said out loud.
        self.broker.client = _FakeClient(
            connections=[
                _connection("aaa", name="Schwab"),
                _connection("bbb", name="Fidelity", disabled=True),
            ]
        )

        self.assertTrue(self.broker.verify_access(), "healthy connections still sync")

        logged = self._logged()
        self.assertIn("Disabled SnapTrade connection", logged)
        self.assertIn("Fidelity", logged)
        self.assertNotIn("Schwab", logged, "only the disabled one is named")

    def test_fetch_accounts_returns_plain_dictionaries(self) -> None:
        client = _FakeClient(connections=[_connection("aaa")])
        client.accounts = [{"id": "1", "name": "Garrett IRA"}]
        self.broker.client = client

        accounts = self.broker.fetch_accounts()

        self.assertEqual(accounts, [{"id": "1", "name": "Garrett IRA"}])
        self.assertIsInstance(accounts[0], dict)


class AsRowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_broker_module()

    def test_a_response_wrapper_is_unwrapped(self) -> None:
        class _Response:
            def __init__(self) -> None:
                self.body = [{"id": "1"}, {"id": "2"}]

        self.assertEqual(self.module.as_rows(_Response()), [{"id": "1"}, {"id": "2"}])

    def test_a_plain_list_passes_through(self) -> None:
        self.assertEqual(self.module.as_rows([{"id": "1"}]), [{"id": "1"}])


if __name__ == "__main__":
    unittest.main()
