"""The SnapTrade broker must explain every way it can fail to connect.

broker_flow() prints nothing of its own when create_conn_obj() or login()
returns False, so a quiet failure here is a run that opens nothing, writes
nothing and exits 0. Both ways this broker can be misconfigured -- no clientId,
no consumer key -- have to produce one line that says what to do about it.

A personal API key is those two values and nothing else: SnapTrade resolves the
user from the key, so there is no userId or userSecret anywhere in this broker.

Nothing here touches the network, the real keyring, or the real config file.
"""

import datetime
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
        self.positions: list[dict[str, Any]] = []
        self.positions_error: Exception | None = None
        self.activities: list[dict[str, Any]] = []
        self.activity_calls: list[dict[str, Any]] = []
        self.page_size = 2
        self.connections = self._Connections(self)
        self.account_information = self._Accounts(self)

    class _Connections:
        def __init__(self, outer: "_FakeClient") -> None:
            self.outer = outer

        def list_brokerage_authorizations(self, **kwargs: Any) -> list[dict[str, Any]]:
            del kwargs
            if self.outer._error is not None:
                raise self.outer._error
            return self.outer._connections

    class _Accounts:
        def __init__(self, outer: "_FakeClient") -> None:
            self.outer = outer

        def list_user_accounts(self, **kwargs: Any) -> list[dict[str, Any]]:
            del kwargs
            return self.outer.accounts

        def get_all_account_positions(self, **kwargs: Any) -> list[dict[str, Any]]:
            del kwargs
            if self.outer.positions_error is not None:
                raise self.outer.positions_error
            return self.outer.positions

        def get_account_activities(self, **kwargs: Any) -> dict[str, Any]:
            # Paginated, like the real endpoint: the records are under "data"
            # and the envelope says how many there are in total.
            self.outer.activity_calls.append(dict(kwargs))
            offset = int(kwargs.get("offset") or 0)
            page = self.outer.activities[offset : offset + self.outer.page_size]
            return {
                "data": page,
                "pagination": {"offset": offset, "total": len(self.outer.activities)},
            }


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

        self._configure(client_id="PERS-TEST")

    def tearDown(self) -> None:
        keyring.set_keyring(self.previous_keyring)
        self.logger.removeHandler(self.capture)
        self.logger.setLevel(self.previous_level)

    def _configure(self, *, client_id: str) -> None:
        """Replace the config getter on the path-loaded module.

        The broker binds the name at import, so patching etc.config would not
        reach it -- and calling the real one would read (and rewrite) the
        developer's own ~/.stonksmith/stonksmith.conf.
        """

        self.module.get_snaptrade_client_id = lambda: client_id

    def _store_consumer_key(self, secret: str = "consumer-secret") -> None:
        self.memory.set_password("stonksmith", "snaptrade:consumerKey", secret)

    def _logged(self) -> str:
        return " ".join(self.capture.messages)

    def test_missing_client_id_is_reported(self) -> None:
        self._configure(client_id="")

        self.assertFalse(self.broker.create_conn_obj())

        logged = self._logged()
        self.assertIn("[SNAPTRADE]", logged)
        self.assertIn("clientId", logged)
        self.assertIn("snaptrade_register.py", logged, "should say how to fix it")

    def test_missing_consumer_key_is_reported(self) -> None:
        self.assertFalse(self.broker.create_conn_obj())

        logged = self._logged()
        self.assertIn("consumer key", logged)
        self.assertIn("snaptrade:consumerKey", logged, "should name the keyring entry")

    def test_a_complete_configuration_builds_a_client(self) -> None:
        self._store_consumer_key()

        self.assertTrue(self.broker.create_conn_obj())

        self.assertIsNotNone(self.broker.client)
        self.assertEqual(self.capture.messages, [], "success should be quiet")

    def test_no_user_identity_is_required(self) -> None:
        # A personal API key is a clientId and a consumerKey and nothing else:
        # SnapTrade resolves the user from the key, so a userId/userSecret pair
        # is neither needed nor obtainable on this tier.
        self._store_consumer_key()

        self.broker.create_conn_obj()

        self.assertFalse(hasattr(self.broker, "user_id"))
        self.assertFalse(hasattr(self.broker, "user_secret"))

    def test_a_rejected_key_names_the_fix(self) -> None:
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


class AsPageRowsTests(unittest.TestCase):
    """Activities arrive wrapped in a pagination envelope; accounts do not.

    Handing the envelope to as_rows iterates its two keys instead of the
    records, which yields two meaningless rows rather than an error -- so the
    two shapes need two functions.
    """

    def setUp(self) -> None:
        self.module = _load_broker_module()

    def test_the_records_come_out_of_the_data_key(self) -> None:
        class _Response:
            def __init__(self) -> None:
                self.body = {
                    "data": [{"id": "a"}, {"id": "b"}],
                    "pagination": {"total": 2},
                }

        rows, pagination = self.module.as_page_rows(_Response())

        self.assertEqual(rows, [{"id": "a"}, {"id": "b"}])
        self.assertEqual(pagination, {"total": 2})

    def test_an_already_unwrapped_list_is_tolerated(self) -> None:
        rows, pagination = self.module.as_page_rows([{"id": "a"}])

        self.assertEqual(rows, [{"id": "a"}])
        self.assertEqual(pagination, {})

    def test_an_empty_page_is_not_an_error(self) -> None:
        rows, _ = self.module.as_page_rows({"data": [], "pagination": {"total": 0}})

        self.assertEqual(rows, [])


class FetchPositionsTests(unittest.TestCase):
    """Per-account positions, including the account that has none."""

    def setUp(self) -> None:
        module = _load_broker_module()
        self.broker = module.SnapTradeBroker()
        self.client = _FakeClient()
        self.broker.client = self.client

    def test_positions_come_back_as_plain_dictionaries(self) -> None:
        self.client.positions = [{"units": 3, "price": 250}]

        self.assertEqual(
            self.broker.fetch_positions(account_id="acct-1"),
            [{"units": 3, "price": 250}],
        )

    def test_an_account_with_no_positions_returns_nothing_rather_than_failing(
        self,
    ) -> None:
        # A brokerage that pre-aggregates -- a Schwab-held 529 -- reports a
        # balance and zero positions. That is a fact about the account.
        self.assertEqual(self.broker.fetch_positions(account_id="acct-1"), [])


class FetchActivitiesTests(unittest.TestCase):
    """Transactions are paginated, and stopping early loses history silently."""

    def setUp(self) -> None:
        module = _load_broker_module()
        self.broker = module.SnapTradeBroker()
        self.client = _FakeClient()
        self.broker.client = self.client

    def _fetch(self) -> list[dict[str, Any]]:
        return self.broker.fetch_activities(
            account_id="acct-1",
            start_date=datetime.date(2025, 10, 1),
            end_date=datetime.date(2025, 12, 31),
        )

    def test_every_page_is_followed(self) -> None:
        self.client.activities = [{"id": str(object=n)} for n in range(5)]
        self.client.page_size = 2

        self.assertEqual(
            [row["id"] for row in self._fetch()], ["0", "1", "2", "3", "4"]
        )

    def test_the_offset_advances_between_pages(self) -> None:
        self.client.activities = [{"id": str(object=n)} for n in range(5)]
        self.client.page_size = 2

        self._fetch()

        self.assertEqual(
            [call["offset"] for call in self.client.activity_calls], [0, 2, 4]
        )

    def test_a_single_page_makes_a_single_call(self) -> None:
        self.client.activities = [{"id": "0"}]

        self._fetch()

        self.assertEqual(len(self.client.activity_calls), 1)

    def test_no_activities_is_one_call_and_no_rows(self) -> None:
        self.assertEqual(self._fetch(), [])
        self.assertEqual(len(self.client.activity_calls), 1)

    def test_the_window_is_passed_through(self) -> None:
        self._fetch()

        call = self.client.activity_calls[0]
        self.assertEqual(call["start_date"], datetime.date(2025, 10, 1))
        self.assertEqual(call["end_date"], datetime.date(2025, 12, 31))

    def test_a_pagination_block_that_never_ends_is_capped(self) -> None:
        # An infinite loop against a paid API is worse than a short read.
        class _Endless:
            def get_account_activities(self, **kwargs: Any) -> dict[str, Any]:
                del kwargs
                return {"data": [{"id": "x"}], "pagination": {"total": 10**9}}

        self.broker.client = type("C", (), {"account_information": _Endless()})()

        rows = self.broker.fetch_activities(
            account_id="acct-1",
            start_date=datetime.date(2025, 10, 1),
            end_date=datetime.date(2025, 12, 31),
            page_limit=3,
        )

        self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
