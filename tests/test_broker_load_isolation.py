"""A broker that fails to load must not take the whole tool down with it.

gen_cli_args() executes every discovered broker's broker_args.py to register its
subparser, and it does so before any command is dispatched. The guard was
`except (ImportError, AttributeError, TypeError)`, so a broker raising anything
else -- ValueError, KeyError from a config lookup, FileNotFoundError from reading
a file at import -- escaped argument parsing and killed *every* invocation,
`--version` and `--help` included. ~/.stonksmith/brokers is where work in
progress lives, so a half-finished broker there bricked the tool.

The same unguarded exec_module() sat under database.py and db_navigator.py, which
main.py and stonksmithdb load by path.
"""

import logging
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

from stonksmith.etc.cli import gen_cli_args
from stonksmith.loaders.brokerloader import BrokerLoader

REPO = Path(__file__).resolve().parents[1]

#: A broker package needs only broker.py to be discovered; broker_args.py is what
#: gen_cli_args() runs.
BROKER_PY = "Broker = object\n"


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class _CaptureMixin:
    """Capture stonksmith output at the level a plain run actually uses.

    Not a TestCase: inheriting one from another re-runs every inherited test.
    """

    def setUp(self) -> None:
        self.capture = _CaptureHandler()
        self.logger = logging.getLogger("stonksmith")
        self.logger.addHandler(self.capture)
        # ERROR is what --quiet gives (etc.infrastructure.set_logging_level), so
        # a broker failing to load has to be reported at least this loudly or an
        # unattended run never learns why the broker vanished.
        self.previous = self.logger.level
        self.logger.setLevel(logging.ERROR)

    def tearDown(self) -> None:
        self.logger.removeHandler(self.capture)
        self.logger.setLevel(self.previous)

    def assertReported(self, name: str) -> None:
        joined = "\n".join(self.capture.messages)
        self.assertIn(name, joined, f"nothing named {name!r} was reported:\n{joined}")


def _write_broker(root: Path, name: str, args_py: str) -> None:
    """Lay down a user broker package under <root>/brokers/<name>."""

    package = root / "brokers" / name
    package.mkdir(parents=True)
    (package / "broker.py").write_text(BROKER_PY)
    (package / "broker_args.py").write_text(args_py)


def _loader_for(root: Path) -> type[BrokerLoader]:
    """A BrokerLoader class whose user root is `root` instead of ~/.stonksmith.

    BrokerLoader.__init__ hardcodes ~/.stonksmith, and gen_cli_args() constructs
    its own loader, so substituting the class is the only seam. Same shape as
    tests/test_cli_flag_placement.py's _RepoOnlyLoader -- and it keeps the real
    home out of the suite, which tests/test_suite_does_not_touch_home.py checks.
    """

    class _RootedLoader(BrokerLoader):
        def __init__(self) -> None:
            super().__init__()
            self.stonksmith_path = root

    return _RootedLoader


class BrokenBrokerArgsTests(_CaptureMixin, unittest.TestCase):
    """One rotten broker_args.py, and the CLI carries on without it."""

    def _parse(self, args_py: str, *argv: str) -> Namespace:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_broker(root, "rotten", args_py)

            with (
                patch.object(sys, "argv", ["stonksmith", *argv]),
                patch("stonksmith.etc.cli.BrokerLoader", _loader_for(root)),
            ):
                return gen_cli_args()

    def test_a_broker_raising_on_import_does_not_kill_version(self) -> None:
        # The reproduce case from the issue: ValueError is not one of the three
        # types the old guard caught, so `--version` died with a traceback.
        with self.assertRaises(SystemExit) as caught:
            self._parse('raise ValueError("half-finished broker")\n', "--version")

        self.assertEqual(caught.exception.code, 0)
        self.assertReported("rotten")

    def test_a_broker_raising_on_import_does_not_kill_another_broker(self) -> None:
        args = self._parse(
            'raise ValueError("half-finished broker")\n',
            "fidelity",
            "-M",
            "fidelity",
        )

        self.assertEqual(args.broker, "fidelity")
        self.assertReported("rotten")

    def test_a_broker_args_that_raises_when_called_is_isolated(self) -> None:
        # load_broker() guards the import; this one imports cleanly and blows up
        # inside the call, which only cli.py's own guard can catch.
        args = self._parse(
            "def broker_args(subparsers, std_parser, module_parser):\n"
            '    raise RuntimeError("no subparser for you")\n',
            "fidelity",
            "-M",
            "fidelity",
        )

        self.assertEqual(args.broker, "fidelity")
        self.assertReported("rotten")

    def test_a_broker_args_that_is_not_callable_is_isolated(self) -> None:
        args = self._parse("broker_args = 3\n", "fidelity", "-M", "fidelity")

        self.assertEqual(args.broker, "fidelity")
        self.assertReported("rotten")

    def test_the_healthy_brokers_are_still_registered(self) -> None:
        # --help exits 0 after printing, which is only reachable if every healthy
        # broker registered its subparser around the rotten one.
        with self.assertRaises(SystemExit) as caught:
            self._parse('raise ValueError("half-finished broker")\n', "--help")

        self.assertEqual(caught.exception.code, 0)

    def test_asking_for_the_broken_broker_exits_non_zero(self) -> None:
        # It registered no subparser, so argparse rejects the name: non-zero when
        # the broken broker was the one requested, zero when it was not. The
        # reported line above it names the broker and the real exception.
        with self.assertRaises(SystemExit) as caught:
            self._parse(
                'raise ValueError("half-finished broker")\n',
                "rotten",
                "-M",
                "x",
            )

        self.assertEqual(caught.exception.code, 2)
        self.assertReported("rotten")


class LoadBrokerGuardTests(_CaptureMixin, unittest.TestCase):
    """load_broker() runs broker code, so it owns the blast radius."""

    def _load(self, source: str) -> object | None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "database.py"
            path.write_text(source)
            return BrokerLoader.load_broker(broker_path=str(path))

    def test_a_module_that_raises_on_import_returns_none(self) -> None:
        self.assertIsNone(self._load('raise KeyError("missing config")\n'))
        self.assertReported("KeyError")

    def test_a_module_that_imports_cleanly_is_returned(self) -> None:
        module = self._load("Database = object\n")

        self.assertIsNotNone(module)
        self.assertTrue(hasattr(module, "Database"))
        self.assertEqual(self.capture.messages, [])

    def test_a_path_that_does_not_exist_returns_none(self) -> None:
        self.assertIsNone(
            BrokerLoader.load_broker(broker_path=str(REPO / "absent" / "nope.py")),
        )


class MainSurvivesABrokenDatabaseTests(_CaptureMixin, unittest.TestCase):
    """stonksmith.main.py loads database.py by path with only an `is None` check."""

    def test_a_database_that_raises_on_import_exits_one(self) -> None:
        import stonksmith.main as main_module

        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp)
            (package / "broker.py").write_text(BROKER_PY)
            (package / "database.py").write_text('raise ValueError("rotten db")\n')

            args = Namespace(
                broker="rotten",
                module=["something"],
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
                patch.object(main_module, "BrokerLoader") as broker_loader,
            ):
                loader = broker_loader.return_value
                loader.get_brokers.return_value = {
                    "rotten": {
                        "path": str(package / "broker.py"),
                        "dbpath": str(package / "database.py"),
                    },
                }
                loader.load_broker = BrokerLoader.load_broker

                # Before the guard this raised ValueError out of main().
                self.assertEqual(main_module.main(args=args), 1)

        self.assertReported("rotten db")


if __name__ == "__main__":
    unittest.main()
