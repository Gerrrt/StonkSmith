"""A user file on the pre-namespace names is refused by name, and only it.

Before the package had a namespace it installed ``etc``, ``helpers``,
``modules``, ``loaders`` and ``brokers`` straight into site-packages, and
people's own brokers and modules were written against those --
``from etc.context import Context``. Moving the tree under ``stonksmith/`` broke
every one of them, so from 0.1.0 until 1.0 a shim aliased the old names back for
exactly as long as one of those files was executing.

**The shim is gone, and this file is what says so.** It replaces
``tests/test_legacy_import_names.py``, which asserted the opposite and was
deleted with the code it covered.

That swap is the point. Deleting a shim and deleting its tests leaves the new
behaviour asserted by nothing: the suite goes green because nothing is looking,
which is the same state the tree would be in if the removal had gone wrong. So
what 1.0 actually promises is written down here instead --

* a user file on the old names **fails to load**, rather than loading with a
  warning;
* the failure **names the file and the missing module**, because the operator has
  to be able to find it. ``ModuleNotFoundError: No module named 'etc'`` on its
  own describes a Python that is broken, not a broker that needs two imports
  changed;
* and it **takes nothing else down with it**. ``load_broker`` wraps
  ``exec_module`` in a blanket ``except Exception`` precisely so one unloadable
  file under ``~/.stonksmith/brokers`` is skipped rather than ending the run --
  which, for ``gen_cli_args()``, would be every invocation of the tool including
  ``--version`` and ``--help``.

The third is the one worth having a test for. The first two are visible the
moment anybody tries it; a broker that quietly takes down ``--help`` for every
*other* broker is not.

Both exec sites are covered. ``BrokerLoader.load_broker()`` and
``ModuleLoader._is_valid_spec()`` are different call paths, and each had its own
``with`` block for that reason.
"""

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from stonksmith.loaders.brokerloader import BrokerLoader
from stonksmith.loaders.moduleloader import ModuleLoader

#: A user broker written before the rename. Two imports, both of names the
#: package stopped installing at 0.1.0.
LEGACY_BROKER = (
    "from etc.context import Context\n"
    "from etc.connection import Connection\n"
    "\n"
    "Broker = Context\n"
    "AlsoConnection = Connection\n"
)

#: The same file after the two-line change the deprecation notice asked for.
#: Here so the refusal above is shown to be about the import names rather than
#: about anything else in the file.
PORTED_BROKER = (
    "from stonksmith.etc.context import Context\n"
    "from stonksmith.etc.connection import Connection\n"
    "\n"
    "Broker = Context\n"
    "AlsoConnection = Connection\n"
)

#: A user module on the old names, carrying the four attributes
#: ModuleLoader.module_is_sane() requires plus a login handler.
LEGACY_MODULE = (
    "from etc.context import Context\n"
    "\n"
    "\n"
    "class LegacyModule:\n"
    "    name = 'Legacy'\n"
    "    description = 'Written before the namespace'\n"
    "    supported_brokers = ['schwab529plan']\n"
    "\n"
    "    def options(self, context, module_options):\n"
    "        pass\n"
    "\n"
    "    def on_login(self, context, connection):\n"
    "        return True\n"
)


class _QuietLogs:
    """Keep the expected failure report off the test output.

    Every test here provokes a load failure on purpose, and load_broker reports
    those at ERROR. Silencing the logger is not hiding the assertion -- the
    tests below read the report through assertLogs rather than off the screen.
    """

    def setUp(self) -> None:
        self.logger = logging.getLogger("stonksmith")
        self.previous = self.logger.level
        self.logger.setLevel(logging.CRITICAL)

    def tearDown(self) -> None:
        self.logger.setLevel(self.previous)


def _write(root: Path, relative: str, body: str) -> Path:
    """Lay a file down under a throwaway root, creating its parents."""

    path: Path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _load_broker(body: str, name: str = "legacy") -> object:
    """Load a user broker whose source is ``body``, as BrokerLoader would."""

    with tempfile.TemporaryDirectory() as tmp:
        path = _write(Path(tmp), f"brokers/{name}/broker.py", body)
        return BrokerLoader.load_broker(broker_path=str(path))


class LegacyBrokerIsRefusedTests(_QuietLogs, unittest.TestCase):
    def test_a_broker_on_the_old_names_no_longer_loads(self) -> None:
        self.assertIsNone(_load_broker(LEGACY_BROKER))

    def test_the_same_broker_loads_once_its_imports_are_ported(self) -> None:
        # What makes the assertion above about the import names rather than
        # about anything else in the file. Without this the test would still
        # pass on a loader that had stopped loading user brokers entirely.
        self.assertIsNotNone(_load_broker(PORTED_BROKER))

    def test_the_report_names_the_file_and_the_missing_module(self) -> None:
        # `No module named 'etc'` alone reads as a broken Python rather than as
        # a broker that needs two imports changed.
        self.logger.setLevel(logging.NOTSET)

        with self.assertLogs(logger="stonksmith", level=logging.ERROR) as caught:
            _load_broker(LEGACY_BROKER, name="antique")

        report = "\n".join(caught.output)
        self.assertIn("antique", report)
        self.assertIn("ModuleNotFoundError", report)
        self.assertIn("etc", report)

    def test_one_unloadable_broker_does_not_cost_the_others(self) -> None:
        # The claim that matters, and the only one not obvious the first time
        # somebody tries it. load_broker's blanket `except Exception` exists so
        # a half-finished file under ~/.stonksmith/brokers is skipped rather
        # than ending the run -- which for gen_cli_args() is every invocation of
        # the tool, including --version and --help.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = _write(root, "brokers/stale/broker.py", LEGACY_BROKER)
            ported = _write(root, "brokers/ported/broker.py", PORTED_BROKER)

            self.assertIsNone(BrokerLoader.load_broker(broker_path=str(stale)))
            self.assertIsNotNone(BrokerLoader.load_broker(broker_path=str(ported)))


class LegacyModuleIsRefusedTests(_QuietLogs, unittest.TestCase):
    def test_a_module_on_the_old_names_no_longer_loads(self) -> None:
        # The other exec site. init_module() and get_module_info() both run
        # through _is_valid_spec(), but that is a different call path from
        # BrokerLoader.load_broker() and one test does not cover both -- which
        # is why the shim needed a `with` block in each.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "modules/legacy_module.py", LEGACY_MODULE)

            loader = ModuleLoader.__new__(ModuleLoader)
            loader._cache = None
            loader.logger = MagicMock()

            info = loader.get_module_info(
                module_path=root / "modules" / "legacy_module.py"
            )

        # Reported and skipped rather than raised, same as the broker side:
        # get_module_info() catches ImportError so one unreadable file does not
        # end the metadata scan that runs on every invocation.
        self.assertIsNone(info)

        reported = str(loader.logger.highlight.call_args)
        self.assertIn("legacy_module.py", reported)
        self.assertIn("etc", reported)


if __name__ == "__main__":
    unittest.main()
