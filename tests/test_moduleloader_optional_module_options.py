import unittest
from argparse import Namespace
from pathlib import Path
from typing import ClassVar

from etc.logger import stonksmith_logger
from loaders.moduleloader import ModuleLoader
from modules.schwab529plan_module import Schwab529Module

# Anchored to the repo, not the cwd: the old relative path only resolved
# when pytest happened to run from the repository root.
MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "src/modules/schwab529plan_module.py"
)


class _StubDB:
    """Minimal DB stub that satisfies BrokerDbProtocol."""

    def get_credentials(self, filter_term: str | None = None) -> list[tuple[str, ...]]:
        return []

    def save_account_data(
        self, account_name: str | None, balance: str | None, timestamp: str
    ) -> None:
        pass

    def shutdown_db(self) -> None:
        pass


class ModuleLoaderOptionalOptionsTests(unittest.TestCase):
    def test_init_module_succeeds_without_module_option_args(self) -> None:
        args = Namespace(
            broker="schwab529plan",
            module=["schwab529plan"],
        )

        loader = ModuleLoader(
            args=args,
            db=_StubDB(),
            logger=stonksmith_logger,
        )

        module = loader.init_module(MODULE_PATH)

        self.assertIsNotNone(module)

    def test_schwab_module_options_applies_export_override(self) -> None:
        module = Schwab529Module()

        module.options(None, {"EXPORT": "json"})

        self.assertEqual(module.export_format, "json")

    def test_init_module_returns_module_instance(self) -> None:
        args = Namespace(
            broker="schwab529plan",
            module=["schwab529plan"],
        )

        loader = ModuleLoader(
            args=args,
            db=_StubDB(),
            logger=stonksmith_logger,
        )

        module = loader.init_module(MODULE_PATH)

        self.assertIsNotNone(module)
        self.assertEqual(getattr(module, "name", None), "schwab529plan")
        self.assertTrue(callable(getattr(module, "on_login", None)))


class FalsyModuleTests(unittest.TestCase):
    """A module that reports itself empty is still a module."""

    def test_a_module_with_no_length_is_still_prepared(self) -> None:
        """
        prepare() keeps anything init_module() did not refuse.

        The check there used to be truthiness, so a module class defining
        __len__ or __bool__ -- one wrapping a collection of things to sync, and
        holding none this run -- was dropped for being empty. Nothing said so:
        it left prepare() one short, and main.py reports a short list as an
        incomplete run without ever naming which module went missing.

        The same falsy-is-not-missing mistake helpers.normalize documents for a
        zero balance.
        """

        class _EmptyModule:
            name = "empty"
            description = "Reports itself empty"
            supported_brokers: ClassVar[list[str]] = ["schwab529plan"]

            def __len__(self) -> int:
                return 0

            def on_login(self, context: object, connection: object) -> bool:
                return True

        args = Namespace(broker="schwab529plan", module=["empty"])
        loader = ModuleLoader(args=args, db=_StubDB(), logger=stonksmith_logger)

        falsy = _EmptyModule()
        self.assertFalse(falsy, "the fixture has to be falsy for this to test anything")

        loader.list_modules = lambda: {"empty": {"path": MODULE_PATH}}  # type: ignore[method-assign]
        loader.init_module = lambda module_path: falsy  # type: ignore[method-assign]

        self.assertEqual(loader.prepare(), [falsy])


if __name__ == "__main__":
    unittest.main()
