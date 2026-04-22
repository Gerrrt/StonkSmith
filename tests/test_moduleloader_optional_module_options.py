import sys
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etc.logger import stonksmith_logger
from loaders.moduleloader import ModuleLoader
from modules.schwab529plan_module import Schwab529Module


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

        module = loader.init_module(Path("src/modules/schwab529plan_module.py"))

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

        module = loader.init_module(Path("src/modules/schwab529plan_module.py"))

        self.assertIsNotNone(module)
        self.assertEqual(getattr(module, "name", None), "schwab529plan")
        self.assertTrue(callable(getattr(module, "on_login", None)))


if __name__ == "__main__":
    unittest.main()
