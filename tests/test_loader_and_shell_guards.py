"""Regression tests for loader, shell, and credential-pairing guards."""

import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import stonksmith.etc.config as etc_config
from stonksmith.etc.config import process_secret
from stonksmith.etc.connection import Connection
from stonksmith.etc.logger import stonksmith_logger
from stonksmith.loaders.moduleloader import ModuleLoader

_config_home: tempfile.TemporaryDirectory | None = None
_config_patch = None


def setUpModule() -> None:
    """
    Keep this module off the developer's real config file.

    process_secret() reaches get_config(), which backfills options missing from
    the shipped defaults and writes the merged result back whenever the user
    file exists -- so an unisolated test rewrites ~/.stonksmith/stonksmith.conf.
    Point the path at an empty temp dir instead; a path that does not exist is
    read as "nothing configured" and is never written to.
    """

    global _config_home, _config_patch

    _config_home = tempfile.TemporaryDirectory()
    _config_patch = patch.object(
        etc_config, "user_cfg_path", Path(_config_home.name) / "stonksmith.conf"
    )
    _config_patch.start()

    # The merged config is cached in a process global, so patching the path
    # without dropping the cache would leave whatever an earlier test module
    # loaded -- and would leak this module's config to the next one.
    etc_config.reset_config_cache()


def tearDownModule() -> None:
    etc_config.reset_config_cache()

    if _config_patch is not None:
        _config_patch.stop()

    if _config_home is not None:
        _config_home.cleanup()


class _StubDB:
    def get_credentials(self, filter_term: str | None = None) -> list[tuple[str, ...]]:
        return []

    def save_account_data(
        self, account_name: str | None, balance: str | None, timestamp: str
    ) -> None:
        pass

    def shutdown_db(self) -> None:
        pass


class ModuleLoaderPrepareTests(unittest.TestCase):
    """prepare() used to return after the first module, silently dropping -M."""

    def test_prepare_returns_every_requested_module(self) -> None:
        args = Namespace(broker="schwab529plan", module=["schwab529plan"])
        loader = ModuleLoader(args=args, db=_StubDB(), logger=stonksmith_logger)

        prepared = loader.prepare()

        self.assertIsInstance(prepared, list)
        self.assertEqual(len(prepared), 1)
        self.assertEqual(getattr(prepared[0], "name", None), "schwab529plan")

    def test_unknown_module_does_not_abort_the_known_one(self) -> None:
        args = Namespace(
            broker="schwab529plan", module=["does-not-exist", "schwab529plan"]
        )
        loader = ModuleLoader(args=args, db=_StubDB(), logger=stonksmith_logger)

        prepared = loader.prepare()

        self.assertEqual(len(prepared), 1, "a bad name must not drop the good one")

    def test_prepare_returns_empty_list_when_nothing_requested(self) -> None:
        args = Namespace(broker="schwab529plan", module=[])
        loader = ModuleLoader(args=args, db=_StubDB(), logger=stonksmith_logger)

        self.assertEqual(loader.prepare(), [])


class StonkSmithDBGuardTests(unittest.TestCase):
    """do_broker indexed brokers[...]['nvpath'] without checking it existed."""

    @patch("stonksmith.etc.stonksmithdb.BrokerLoader")
    def test_incomplete_broker_reports_instead_of_raising(
        self, mock_loader: MagicMock
    ) -> None:
        from stonksmith.etc.stonksmithdb import StonkSmithDBMenu

        # A broker package with broker.py but no database.py/db_navigator.py:
        # 'path' only, no nvpath/dbpath.
        mock_loader.return_value.get_brokers.return_value = {
            "lonely": {"path": "/tmp/lonely/broker.py"}
        }

        menu = StonkSmithDBMenu.__new__(StonkSmithDBMenu)
        menu.brokers = {"lonely": {"path": "/tmp/lonely/broker.py"}}
        menu.workspace = "default"

        with patch("builtins.print") as mock_print:
            menu.do_broker(broker="lonely")

        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("incomplete", printed)

    def test_exit_is_a_command_method_returning_true(self) -> None:
        from stonksmith.etc.stonksmithdb import StonkSmithDBMenu

        # do_exit used to be a module-level function, so cmd.Cmd never saw it.
        self.assertTrue(callable(getattr(StonkSmithDBMenu, "do_exit", None)))

        menu = StonkSmithDBMenu.__new__(StonkSmithDBMenu)
        with patch("builtins.print"):
            self.assertTrue(menu.do_exit(line=""))


class ProcessSecretTests(unittest.TestCase):
    """process_secret raised TypeError whenever it was reached."""

    def test_secret_is_masked_and_never_returned_verbatim(self) -> None:
        masked = process_secret(text="hunter2")

        self.assertNotIn("hunter2", masked)
        self.assertTrue(masked.startswith("*"))

    def test_empty_secret_is_empty_string(self) -> None:
        self.assertEqual(process_secret(text=""), "")
        self.assertEqual(process_secret(text=None), "")


class CredentialPairingTests(unittest.TestCase):
    """Uneven -u/-p lists used to drop attempts with no warning."""

    def test_mismatched_credential_counts_are_reported(self) -> None:
        conn = Connection()
        conn.args = Namespace(
            username=["a", "b", "c"],
            password=["only-one"],
            cred_id=[],
            continue_on_success=False,
        )
        conn.db = _StubDB()

        conn.logger = MagicMock()
        conn.plaintext_login = MagicMock(return_value=False)

        conn.login()

        messages = " ".join(str(c) for c in conn.logger.fail.call_args_list)
        self.assertIn("mismatch", messages.lower())


class CallCmdArgsTests(unittest.TestCase):
    """call_cmd_args dispatched to any method whose name matched a CLI flag."""

    def test_arbitrary_flag_does_not_invoke_same_named_method(self) -> None:
        conn = Connection()
        conn.args = Namespace(login=True)
        conn.login = MagicMock(return_value=True)

        conn.call_cmd_args()

        conn.login.assert_not_called()

    def test_declared_action_is_dispatched(self) -> None:
        conn = Connection()
        conn.args = Namespace(account=True)
        conn.cmd_actions = ("account",)
        conn.account = MagicMock()

        conn.call_cmd_args()

        conn.account.assert_called_once()


if __name__ == "__main__":
    unittest.main()
