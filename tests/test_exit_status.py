"""A run that did nothing must not exit 0.

Every StonkSmith run used to exit 0 unless the *arguments* were wrong. The
outcome was discarded at four layers: broker_flow() consumed the
create_conn_obj()/login() booleans, __call__ swallowed every exception,
start_run() never called future.result(), and main() ignored what came back.
So a run that could not log in, crashed, scraped nothing, or wrote nothing all
reported success -- invisible to cron, which is the only audience that reads an
exit code.

The contract these tests pin: **False means "I did nothing"; anything else,
including None, means "I did my work."** None is what every module and broker
written before this returns, which is what keeps ~/.stonksmith/modules and
~/.stonksmith/brokers working untouched.
"""

import asyncio
import logging
import unittest
from argparse import Namespace
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from etc.api_connection import ApiConnection
from etc.connection import Connection
from etc.runner import start_run


class _StubDb:
    """Minimal DB stub that satisfies BrokerDbProtocol."""

    def get_credentials(self, filter_term: str | None = None) -> list[tuple[str, ...]]:
        return []

    def save_account_data(
        self, account_name: str | None, balance: str | None, timestamp: str
    ) -> None:
        pass

    def shutdown_db(self) -> None:
        pass


class _Module:
    """A module returning whatever it was told to."""

    def __init__(self, name: str = "stub", result: Any = None) -> None:
        self.name = name
        self.result = result
        self.ran = False

    def on_login(self, context: Any, connection: Any) -> Any:
        self.ran = True
        return self.result


class _RaisingModule:
    name = "boom"

    def __init__(self) -> None:
        self.ran = False

    def on_login(self, context: Any, connection: Any) -> Any:
        self.ran = True
        raise RuntimeError("boom")


def _args(**overrides: Any) -> Namespace:
    defaults: dict[str, Any] = {
        "module_run_markers": False,
        "username": [],
        "password": [],
        "cred_id": [],
    }
    defaults.update(overrides)
    return Namespace(**defaults)


def _conn(modules: list[Any], **arg_overrides: Any) -> Connection:
    conn = Connection()
    conn.args = _args(**arg_overrides)
    conn.db = _StubDb()
    conn.module = modules
    return conn


class LoggerLevelMixin:
    """Restore the global logger level.

    main() calls set_logging_level(), which sets the process-global 'stonksmith'
    logger level from the flags it was given. This file sorts alphabetically
    before several that capture INFO-level output, so leaking a level they did
    not choose silently blinds them.
    """

    def setUp(self) -> None:
        self._logger = logging.getLogger("stonksmith")
        self._level = self._logger.level

    def tearDown(self) -> None:
        self._logger.setLevel(self._level)


class CallModulesOutcomeTests(unittest.TestCase):
    def test_a_module_returning_none_is_success(self) -> None:
        # THE backward-compatibility guarantee: None is the original signature,
        # and every module under ~/.stonksmith/modules still returns it.
        module = _Module(result=None)

        self.assertTrue(_conn([module]).call_modules())
        self.assertTrue(module.ran)

    def test_a_module_returning_true_is_success(self) -> None:
        self.assertTrue(_conn([_Module(result=True)]).call_modules())

    def test_a_module_returning_false_fails_the_run(self) -> None:
        self.assertFalse(_conn([_Module(result=False)]).call_modules())

    def test_a_falsey_non_false_return_is_still_success(self) -> None:
        # Only the exact value False means failure; a module returning a count
        # of 0 is reporting success. Documented in modules/example.py.
        self.assertTrue(_conn([_Module(result=0)]).call_modules())

    def test_a_raising_module_fails_the_run(self) -> None:
        self.assertFalse(_conn([_RaisingModule()]).call_modules())

    def test_a_failing_module_does_not_stop_the_others(self) -> None:
        # Failure is recorded, not short-circuited.
        second = _Module(name="second", result=None)
        conn = _conn([_Module(name="first", result=False), second])

        self.assertFalse(conn.call_modules())
        self.assertTrue(second.ran, "the second module must still run")

    def test_a_missing_database_fails_the_run(self) -> None:
        # Nothing ran and nothing was said about it: a failed run, not a
        # successful empty one.
        conn = _conn([_Module()])
        conn.db = None

        self.assertFalse(conn.call_modules())

    def test_the_marker_no_longer_claims_a_crashed_module_completed(self) -> None:
        conn = _conn([_RaisingModule()], module_run_markers=True)
        logger = logging.getLogger("stonksmith")
        messages: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                messages.append(record.getMessage())

        handler = _Capture()
        logger.addHandler(handler)
        previous = logger.level
        logger.setLevel(logging.INFO)
        try:
            conn.call_modules()
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous)

        joined = " ".join(messages)
        self.assertIn("Gave up on", joined)
        self.assertNotIn("[+] Completed", joined)


class BrokerFlowOutcomeTests(unittest.TestCase):
    def test_a_failed_connection_fails_the_run(self) -> None:
        conn = _conn([_Module()])
        conn.create_conn_obj = MagicMock(return_value=False)  # type: ignore[method-assign]
        conn.call_modules = MagicMock()  # type: ignore[method-assign]

        self.assertFalse(conn.broker_flow())
        conn.call_modules.assert_not_called()

    def test_a_failed_login_fails_the_run(self) -> None:
        conn = _conn([_Module()])
        conn.login = MagicMock(return_value=False)  # type: ignore[method-assign]
        conn.call_modules = MagicMock()  # type: ignore[method-assign]

        self.assertFalse(conn.broker_flow())
        conn.call_modules.assert_not_called()

    def test_a_working_run_succeeds(self) -> None:
        conn = _conn([_Module(result=None)])
        conn.login = MagicMock(return_value=True)  # type: ignore[method-assign]

        self.assertTrue(conn.broker_flow())

    def test_call_returns_true_on_the_happy_path(self) -> None:
        conn = _conn([_Module(result=None)])
        conn.login = MagicMock(return_value=True)  # type: ignore[method-assign]

        self.assertTrue(conn(args=conn.args, db=_StubDb(), host=None))

    def test_call_returns_false_when_broker_flow_raises_and_still_tears_down(
        self,
    ) -> None:
        conn = _conn([_Module()])
        conn.broker_flow = MagicMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        conn.teardown = MagicMock()  # type: ignore[method-assign]

        self.assertFalse(conn(args=conn.args, db=_StubDb(), host=None))
        conn.teardown.assert_called_once()

    def test_a_broker_whose_flow_returns_none_still_succeeds(self) -> None:
        # An out-of-tree broker under ~/.stonksmith/brokers may still declare
        # broker_flow() -> None, where None has always meant "finished".
        conn = _conn([_Module()])
        conn.broker_flow = MagicMock(return_value=None)  # type: ignore[method-assign]

        self.assertTrue(conn(args=conn.args, db=_StubDb(), host=None))


class _ApiBroker(ApiConnection):
    def __init__(self, verified: bool = True, connected: bool = True) -> None:
        super().__init__()
        self.broker = "Testly"
        self.name = "Testly"
        self._verified = verified
        self._connected = connected

    def create_conn_obj(self) -> bool:
        if not self._connected:
            self.logger.fail(msg="no client")
        return self._connected

    def verify_access(self) -> bool:
        if not self._verified:
            self.logger.fail(msg="rejected")
        return self._verified


class ApiConnectionOutcomeTests(unittest.TestCase):
    """The second broker shape inherits the fix; prove it did not regress."""

    def test_a_rejected_key_fails_the_run(self) -> None:
        # This is the SnapTrade case that exits 0 today.
        broker = _ApiBroker(verified=False)
        broker.module = [_Module()]

        self.assertFalse(broker(args=_args(), db=_StubDb(), host=None))

    def test_a_client_that_cannot_be_built_fails_the_run(self) -> None:
        broker = _ApiBroker(connected=False)
        broker.module = [_Module()]

        self.assertFalse(broker(args=_args(), db=_StubDb(), host=None))

    def test_a_working_api_broker_succeeds_with_no_credentials(self) -> None:
        broker = _ApiBroker()
        broker.module = [_Module(result=None)]

        self.assertTrue(broker(args=_args(), db=_StubDb(), host=None))


class _FakeBroker:
    name = "Fake"

    def __init__(self, result: Any = True, raises: bool = False) -> None:
        self.result = result
        self.raises = raises

    def __call__(self, args: Any, db: Any, host: Any = None) -> Any:
        if self.raises:
            raise RuntimeError("broker exploded")
        return self.result


class StartRunOutcomeTests(unittest.TestCase):
    def _run(self, broker: _FakeBroker) -> bool:
        return asyncio.run(
            start_run(broker_obj=broker, db=_StubDb(), args=_args())  # type: ignore[arg-type]
        )

    def test_a_successful_broker_passes_through(self) -> None:
        self.assertTrue(self._run(_FakeBroker(result=True)))

    def test_a_failed_broker_passes_through(self) -> None:
        self.assertFalse(self._run(_FakeBroker(result=False)))

    def test_a_broker_returning_none_is_success(self) -> None:
        self.assertTrue(self._run(_FakeBroker(result=None)))

    def test_a_raising_broker_fails_without_propagating(self) -> None:
        # future.result() was never called, so this vanished entirely.
        self.assertFalse(self._run(_FakeBroker(raises=True)))


def _async_returning(value: bool):
    async def _run(**kwargs: Any) -> bool:
        del kwargs
        return value

    return _run


def _async_interrupt():
    async def _run(**kwargs: Any) -> bool:
        del kwargs
        raise KeyboardInterrupt

    return _run


class MainExitCodeTests(LoggerLevelMixin, unittest.TestCase):
    """main()'s return value is the process exit status (pyproject console script)."""

    #: Distinguishes "use the default" from "pass module=None", which is the
    #: `stonksmith <broker>` with no -M case and a different code path.
    _DEFAULT = object()

    def _main(
        self,
        run: Any,
        *,
        requested: Any = _DEFAULT,
        prepared: int = 1,
    ) -> int:
        import main as main_module

        broker_module = SimpleNamespace(Broker=MagicMock(), Database=MagicMock())
        loader = MagicMock()
        loader.prepare.return_value = [MagicMock() for _ in range(prepared)]

        args = Namespace(
            broker="fidelity",
            module=["fidelity"] if requested is self._DEFAULT else requested,
            list_modules=False,
            show_module_options=False,
            log=None,
            verbose=False,
            debug=False,
        )

        with (
            patch.object(main_module, "setup_tool"),
            patch.object(main_module, "set_logging_level"),
            patch.object(main_module, "get_workspace", return_value="default"),
            patch.object(main_module, "create_db_engine", return_value=MagicMock()),
            patch.object(main_module, "ModuleLoader", return_value=loader),
            patch.object(main_module, "start_run", run),
            patch.object(main_module, "BrokerLoader") as broker_loader,
        ):
            broker_loader.return_value.get_brokers.return_value = {
                "fidelity": {"path": "b.py", "dbpath": "d.py"}
            }
            broker_loader.return_value.load_broker.return_value = broker_module

            return main_module.main(args=args)

    def test_a_successful_run_exits_zero(self) -> None:
        self.assertEqual(self._main(_async_returning(True)), 0)

    def test_a_failed_run_exits_one(self) -> None:
        # The whole point: this exits 0 before the fix.
        self.assertEqual(self._main(_async_returning(False)), 1)

    def test_an_interrupted_run_exits_130(self) -> None:
        # 128 + SIGINT, so a scheduler can page on 1 and shrug at a human Ctrl-C.
        self.assertEqual(self._main(_async_interrupt()), 130)

    def test_a_partial_module_load_exits_one(self) -> None:
        # Asked for two, got one: a silent half-run under cron.
        self.assertEqual(
            self._main(_async_returning(True), requested=["a", "b"], prepared=1),
            1,
        )

    def test_a_full_module_load_still_exits_zero(self) -> None:
        self.assertEqual(
            self._main(_async_returning(True), requested=["a", "b"], prepared=2),
            0,
        )

    def test_no_modules_loaded_exits_one(self) -> None:
        self.assertEqual(self._main(_async_returning(True), prepared=0), 1)

    def test_no_module_requested_exits_one(self) -> None:
        # `stonksmith fidelity` with no -M. Already exited 1, but silently --
        # it now says why.
        self.assertEqual(self._main(_async_returning(True), requested=None), 1)


if __name__ == "__main__":
    unittest.main()
