"""Discovery must be exercised against the real src/brokers tree.

Nothing did, so the glob that found brokers was untested: it could have stopped
matching and the whole suite would still have passed. The pair-of-entries layout
(brokers/fidelity.py beside brokers/fidelity/) was invisible for the same reason --
BrokerLoader resolved the file, `import brokers.fidelity` resolved the package, and
no test ever made the two meet.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from loaders.brokerloader import BrokerLoader

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

EXPECTED_KEYS = {"path", "dbpath", "nvpath", "argspath"}
SHIPPED = ("ally", "fidelity", "schwab529plan", "snaptrade", "tsp")


def _fresh_loader(user_root: Path | None = None) -> BrokerLoader:
    """A loader with its second search root pointed somewhere harmless.

    BrokerLoader.__init__ hardcodes ~/.stonksmith, so without this the suite would
    be affected by whatever the developer happens to have installed there.
    """

    loader = BrokerLoader()
    loader.stonksmith_path = user_root if user_root is not None else REPO / "absent"
    return loader


class ShippedBrokerDiscoveryTests(unittest.TestCase):
    def test_the_bundled_brokers_are_found(self) -> None:
        brokers = _fresh_loader().get_brokers()

        for name in SHIPPED:
            self.assertIn(name, brokers)

    def test_every_entry_matches_the_published_contract(self) -> None:
        for name, info in _fresh_loader().get_brokers().items():
            with self.subTest(broker=name):
                self.assertLessEqual(set(info), EXPECTED_KEYS)
                self.assertIn("path", info)

                for key, value in info.items():
                    self.assertIsInstance(value, str, f"{key} must be a str")
                    self.assertTrue(Path(value).is_file(), f"{key} -> {value}")

    def test_the_key_is_the_directory_name(self) -> None:
        # The key doubles as the CLI lookup, Database's second argument, and the
        # <name>.db filename stem.
        for name, info in _fresh_loader().get_brokers().items():
            with self.subTest(broker=name):
                self.assertEqual(Path(info["path"]).parent.name, name)
                self.assertEqual(Path(info["path"]).name, "broker.py")

    def test_every_broker_exposes_a_broker_alias(self) -> None:
        # main.py reads this off the path-loaded module.
        for name, info in _fresh_loader().get_brokers().items():
            with self.subTest(broker=name):
                module = BrokerLoader.load_broker(broker_path=info["path"])

                self.assertIsNotNone(module)
                self.assertIsInstance(
                    getattr(module, "Broker", None), type, "missing Broker alias"
                )

    def test_the_shipped_brokers_are_complete(self) -> None:
        # stonksmithdb calls a broker "incomplete" without nvpath and dbpath.
        brokers = _fresh_loader().get_brokers()

        for name in SHIPPED:
            info = brokers[name]
            with self.subTest(broker=name):
                self.assertTrue({"nvpath", "dbpath"} <= set(info))

                db_mod = BrokerLoader.load_broker(broker_path=info["dbpath"])
                nav_mod = BrokerLoader.load_broker(broker_path=info["nvpath"])
                args_mod = BrokerLoader.load_broker(broker_path=info["argspath"])

                self.assertIsInstance(getattr(db_mod, "Database", None), type)
                self.assertIsInstance(getattr(nav_mod, "DatabaseNavigator", None), type)
                self.assertTrue(callable(getattr(args_mod, "broker_args", None)))

    def test_no_flat_module_shadows_a_broker_package(self) -> None:
        # The bug this layout closed: brokers/fidelity.py beside brokers/fidelity/
        # made `import brokers.fidelity` and BrokerLoader resolve different objects.
        strays = sorted(p.name for p in (SRC / "brokers").glob("[!_]*.py"))

        self.assertEqual(
            strays,
            [],
            "A broker is a directory containing broker.py. A flat "
            "brokers/<name>.py is shadowed by the package of the same name.",
        )

    def test_the_package_export_matches_the_path_loaded_class(self) -> None:
        # Not assertIs: load_broker never registers in sys.modules, so the
        # path-loaded class is a distinct object from the imported one.
        from brokers.ally import Ally
        from brokers.fidelity import Fidelity
        from brokers.schwab529plan import Schwab529plan
        from brokers.snaptrade import SnapTradeBroker
        from brokers.tsp import Tsp

        brokers = _fresh_loader().get_brokers()

        for name, exported in (
            ("ally", Ally),
            ("fidelity", Fidelity),
            ("schwab529plan", Schwab529plan),
            ("snaptrade", SnapTradeBroker),
            ("tsp", Tsp),
        ):
            with self.subTest(broker=name):
                module = BrokerLoader.load_broker(broker_path=brokers[name]["path"])

                self.assertIsNotNone(module)
                self.assertEqual(module.Broker.__qualname__, exported.__qualname__)

    def test_an_unknown_package_attribute_still_raises(self) -> None:
        import brokers.fidelity

        with self.assertRaises(AttributeError):
            _ = brokers.fidelity.NoSuchThing


class DiscoveryRulesTests(unittest.TestCase):
    def test_a_flat_py_file_is_not_a_broker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brokers"
            root.mkdir()
            (root / "legacy.py").write_text("class Legacy: pass\n")

            self.assertNotIn("legacy", _fresh_loader(Path(tmp)).get_brokers())

    def test_a_directory_without_broker_py_is_not_a_broker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brokers"
            (root / "halfbroker").mkdir(parents=True)
            (root / "halfbroker" / "database.py").write_text("")

            self.assertNotIn("halfbroker", _fresh_loader(Path(tmp)).get_brokers())

    def test_underscore_directories_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brokers"
            (root / "__pycache__").mkdir(parents=True)
            (root / "__pycache__" / "broker.py").write_text("")

            self.assertNotIn("__pycache__", _fresh_loader(Path(tmp)).get_brokers())

    def test_a_user_broker_is_discovered_with_only_broker_py(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brokers"
            (root / "mybroker").mkdir(parents=True)
            (root / "mybroker" / "broker.py").write_text(
                "class MyBroker: pass\n\nBroker = MyBroker\n"
            )

            info = _fresh_loader(Path(tmp)).get_brokers()["mybroker"]

            self.assertEqual(set(info), {"path"})

            module = BrokerLoader.load_broker(broker_path=info["path"])
            self.assertIsNotNone(module)
            self.assertEqual(module.Broker.__name__, "MyBroker")

    def test_src_wins_over_a_user_broker_of_the_same_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brokers"
            (root / "fidelity").mkdir(parents=True)
            (root / "fidelity" / "broker.py").write_text("Broker = object\n")

            path = _fresh_loader(Path(tmp)).get_brokers()["fidelity"]["path"]

            self.assertTrue(Path(path).is_relative_to(SRC))

    def test_a_missing_search_root_is_not_fatal(self) -> None:
        brokers = _fresh_loader(REPO / "definitely-absent").get_brokers()

        self.assertIn("fidelity", brokers)

    def test_the_second_call_is_cached(self) -> None:
        loader = _fresh_loader()

        self.assertIs(loader.get_brokers(), loader.get_brokers())


class LazyExportTests(unittest.TestCase):
    """The sheet writer is imported on every run; it must stay cheap.

    ModuleLoader metadata-scans every file in modules/ on every run of every
    broker, and each of those now imports etc.portfolio_sheet -- which is what
    the five per-broker savers used to be, an every-run import that must not
    drag a transport in behind it. An eager class export in a broker's
    __init__.py pulls the whole transport along: playwright for Fidelity, the
    SnapTrade SDK for SnapTrade, on runs that never touch that broker.
    """

    def _import_in_subprocess(self, module: str, heavy: str) -> str:
        # A subprocess is required: sys.modules in-process is already polluted
        # by the tests that load these brokers by path.
        code = f"import sys; import {module}; print({heavy!r} in sys.modules)"
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=dict(os.environ, PYTHONPATH=str(SRC)),
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_the_sheet_writer_does_not_drag_in_playwright(self) -> None:
        self.assertIn(
            "False",
            self._import_in_subprocess("etc.portfolio_sheet", "playwright_stealth"),
        )

    def test_the_sheet_writer_does_not_drag_in_the_snaptrade_sdk(self) -> None:
        self.assertIn(
            "False",
            self._import_in_subprocess("etc.portfolio_sheet", "snaptrade_client"),
        )

    def test_the_sheet_writer_does_not_open_a_broker_package(self) -> None:
        # It reads every broker database directly as a BrokerDatabase rather
        # than through each broker's Database subclass, precisely so that a
        # read does not import five broker packages and their optional deps.
        self.assertIn(
            "False",
            self._import_in_subprocess("etc.portfolio_sheet", "brokers.fidelity"),
        )


if __name__ == "__main__":
    unittest.main()
