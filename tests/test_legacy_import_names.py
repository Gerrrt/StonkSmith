"""A user's broker or module written before the namespace still loads.

``~/.stonksmith/brokers`` and ``~/.stonksmith/modules`` hold the user's own files,
loaded by path, written against the names this package used to install at the top
level -- ``from etc.context import Context``. Moving the tree under
``stonksmith/`` breaks all of them, so ``loaders._legacy_names`` aliases the old
names back for exactly as long as one of those files is executing.

**This whole file is deleted when the shim is, at 1.0**, along with
``src/stonksmith/loaders/_legacy_names.py`` and the two ``with`` blocks that use
it. It is the thing that says whether the shim still has a job.

Three of these tests exist because the obvious implementation passes the other
four. ``sys.modules["etc"] = stonksmith.etc`` satisfies "it loads" while handing
the file a second, distinct copy of every submodule. Dropping the ``__spec__``
restore corrupts the real package invisibly. And asserting only that a
``DeprecationWarning`` was raised passes on a shim that raises it *instead of*
loading the broker -- see ``test_a_deprecation_error_filter_still_loads``.
"""

import logging
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

import stonksmith.etc.connection
import stonksmith.etc.context
from package_tree import SRC
from stonksmith.loaders._legacy_names import LEGACY_ROOTS, _AliasFinder
from stonksmith.loaders.brokerloader import BrokerLoader
from stonksmith.loaders.moduleloader import ModuleLoader

#: A user broker that predates the rename. `Broker = Context` is not meaningful
#: as a broker; it is how the test gets hold of the class the file imported, to
#: compare identities with the one StonkSmith itself uses.
LEGACY_BROKER = (
    "from etc.context import Context\n"
    "from etc.connection import Connection\n"
    "\n"
    "Broker = Context\n"
    "AlsoConnection = Connection\n"
)

#: The four attributes ModuleLoader.module_is_sane() requires, plus a login
#: handler, on a module using the old import names.
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
    """Swallow the shim's own ERROR-level deprecation notice.

    The shim logs as well as warns, because DeprecationWarning is invisible under
    Python's default filters. That is deliberate, and it would otherwise print
    over the test output.
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


def _load_broker(body: str) -> object:
    """Load a user broker whose source is ``body``, as BrokerLoader would."""

    with tempfile.TemporaryDirectory() as tmp:
        path = _write(Path(tmp), "brokers/legacy/broker.py", body)
        return BrokerLoader.load_broker(broker_path=str(path))


class LegacyBrokerTests(_QuietLogs, unittest.TestCase):
    def test_a_broker_written_against_the_old_names_still_loads(self) -> None:
        # Both halves matter. Asserting only the warning would pass on a shim
        # that raises the warning instead of loading the file, which is exactly
        # what happens when it is not suppressed at the emit site.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            module = _load_broker(LEGACY_BROKER)

        self.assertIsNotNone(module, "the broker did not load")

        deprecations = [
            str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        self.assertTrue(deprecations, "no DeprecationWarning was raised")
        self.assertTrue(
            any("etc.context" in message for message in deprecations),
            f"nothing named the legacy module: {deprecations}",
        )

    def test_the_class_it_imports_is_the_one_stonksmith_uses(self) -> None:
        # The test that fails under `sys.modules["etc"] = stonksmith.etc`: that
        # aliases the package, so `from etc.context import Context` re-executes
        # context.py and yields a second class. isinstance across the boundary
        # is then False and `except` clauses stop catching.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            module = _load_broker(LEGACY_BROKER)

        self.assertIs(module.Broker, stonksmith.etc.context.Context)

    def test_the_real_package_is_not_corrupted_by_an_alias(self) -> None:
        # module_from_spec() stamps the alias's spec onto the module the loader
        # returns. Without the restore in _AliasLoader.exec_module,
        # stonksmith.etc.context.__spec__.name reads "etc.context" afterwards,
        # for the rest of the process.
        #
        # Assert the value, not that it did not change. Comparing before against
        # after is what this test did first, and it passed with the restore
        # deleted: an earlier test in this class had already corrupted the spec,
        # so both sides were equally wrong. Nothing here may depend on whether
        # some other test loaded a legacy broker first.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            _load_broker(LEGACY_BROKER)

        self.assertEqual(stonksmith.etc.__spec__.name, "stonksmith.etc")
        self.assertEqual(
            stonksmith.etc.context.__spec__.name,
            "stonksmith.etc.context",
            "the alias's spec was left stamped on the real module",
        )
        self.assertEqual(
            stonksmith.etc.connection.__spec__.name, "stonksmith.etc.connection"
        )

    def test_a_deprecation_error_filter_still_loads_the_broker(self) -> None:
        # The suite runs under filterwarnings = ["error"], and a user may export
        # PYTHONWARNINGS=error. Unsuppressed, the warning raises inside
        # exec_module(), load_broker()'s blanket `except Exception` catches it,
        # and the broker is reported as having failed to load. The shim would
        # then be the cause of the breakage it exists to prevent.
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            module = _load_broker(LEGACY_BROKER)

        self.assertIsNotNone(module, "a warnings filter must not lose the broker")
        self.assertIs(module.Broker, stonksmith.etc.context.Context)

    def test_a_name_with_no_counterpart_still_raises_the_ordinary_error(
        self,
    ) -> None:
        # The message must name what the file wrote, not what the shim tried.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            module = _load_broker("from etc.no_such_module import Thing\n")

        self.assertIsNone(module, "a broken import must still fail")


class ScopeTests(_QuietLogs, unittest.TestCase):
    def test_the_alias_does_not_survive_the_load(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            _load_broker(LEGACY_BROKER)

        leaked = sorted(
            name for name in sys.modules if name.partition(".")[0] in LEGACY_ROOTS
        )
        self.assertEqual(leaked, [], "the legacy names outlived the load")

        self.assertEqual(
            [f for f in sys.meta_path if isinstance(f, _AliasFinder)],
            [],
            "the finder was left installed",
        )

    def test_the_legacy_names_are_not_importable_in_a_fresh_process(self) -> None:
        # In-process this cannot be trusted: sys.modules is already populated by
        # every other test that loads a broker by path. A subprocess is the only
        # honest check, and it is what tells us the wheel does not ship `etc`.
        import subprocess

        result = subprocess.run(
            [sys.executable, "-c", "import etc"],
            env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, "`import etc` must not resolve")
        self.assertIn("No module named 'etc'", result.stderr)


class LegacyModuleTests(_QuietLogs, unittest.TestCase):
    def test_a_module_written_against_the_old_names_still_loads(self) -> None:
        # The other exec site. init_module() and get_module_info() both run
        # through _is_valid_spec(), but that is a different call path from
        # BrokerLoader.load_broker() and one test does not cover both.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "modules/legacy_module.py", LEGACY_MODULE)

            loader = ModuleLoader.__new__(ModuleLoader)
            loader._cache = None
            loader.logger = logging.getLogger("stonksmith")

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                info = loader.get_module_info(
                    module_path=root / "modules" / "legacy_module.py"
                )

        self.assertIsNotNone(info, "the module did not load")
        self.assertIn("Legacy", info)

        self.assertTrue(
            [w for w in caught if issubclass(w.category, DeprecationWarning)],
            "loading a legacy module raised no DeprecationWarning",
        )


class ShippedFilesTests(_QuietLogs, unittest.TestCase):
    def test_the_shipped_brokers_do_not_use_the_shim(self) -> None:
        # The standing proof that the rename actually landed in src/, and the
        # reason both exec sites can wrap unconditionally rather than checking
        # whether the file being loaded is one of ours.
        loader = BrokerLoader()
        loader.stonksmith_path = Path(tempfile.gettempdir()) / "definitely-absent"

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for info in loader.get_brokers().values():
                self.assertIsNotNone(BrokerLoader.load_broker(broker_path=info["path"]))

        deprecations = [
            str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        self.assertEqual(
            deprecations,
            [],
            "a shipped broker is still importing a pre-namespace name",
        )


if __name__ == "__main__":
    unittest.main()
