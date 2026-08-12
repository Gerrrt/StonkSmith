# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""The shipped brokers and modules satisfy the protocols main.py casts them to.

main.py gets its broker class out of a file loaded by path, so nothing static
can confirm the shape and the annotation is a cast. A cast is a claim, and an
unchecked claim is worth nothing: BrokerProtocol could gain a member no broker
has, or a broker could drop `name`, and ty would still pass because the cast
says otherwise. This is the check that makes the claim real, and it runs against
the actual brokers/ and modules/ trees rather than a fixture.

Both protocols are runtime_checkable for exactly this, which is also why they
carry only attributes every implementation genuinely has -- see ModuleProtocol
on why the login handlers are not among them.
"""

import importlib.util
import inspect
import unittest
from pathlib import Path
from types import ModuleType

from etc.context import BrokerProtocol, ModuleProtocol
from loaders.brokerloader import BrokerLoader

REPO = Path(__file__).resolve().parents[1]
MODULES_DIR = REPO / "src" / "modules"

#: Not collected by globbing what exists: a glob that silently stopped matching
#: would leave this file asserting nothing, which is the failure mode
#: test_broker_discovery.py was written about.
SHIPPED_BROKERS = ("ally", "fidelity", "schwab529plan", "snaptrade", "tsp")
SHIPPED_MODULES = (
    "ally_module.py",
    "fidelity_module.py",
    "schwab529plan_module.py",
    "snaptrade_module.py",
    "tsp_module.py",
)


def _loader() -> BrokerLoader:
    """A loader that cannot see whatever is installed under the real ~."""

    loader = BrokerLoader()
    loader.stonksmith_path = REPO / "absent"
    return loader


def _load(path: Path) -> ModuleType:
    """
    Load a module file the way ModuleLoader does.

    Raises rather than asserting: python -O strips assert, and a stripped
    precondition here would surface as an AttributeError on None several lines
    later, naming neither the file nor the reason.
    """

    spec = importlib.util.spec_from_file_location("conformance_probe", path)
    if spec is None or spec.loader is None:
        msg = f"{path} produced no loadable spec"
        raise RuntimeError(msg)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BrokerConformanceTests(unittest.TestCase):
    """Every shipped broker is what main.py says it is."""

    def test_each_broker_satisfies_the_protocol(self) -> None:
        loader = _loader()
        brokers = loader.get_brokers()

        for name in SHIPPED_BROKERS:
            with self.subTest(broker=name):
                self.assertIn(name, brokers)

                module = loader.load_broker(broker_path=brokers[name]["path"])
                self.assertIsNotNone(module, "broker failed to load")

                # The same two-step main.py does: a 'Broker' alias, falling back
                # to the capitalised directory name.
                broker_class = getattr(module, "Broker", None) or getattr(
                    module, name.capitalize(), None
                )
                self.assertIsNotNone(broker_class, "no Broker alias or named class")

                self.assertIsInstance(broker_class(), BrokerProtocol)

    def test_a_broker_is_callable_with_the_runner_signature(self) -> None:
        """
        runner.start_run() submits the broker itself to a thread pool, so its
        __call__ is the contract -- not a method the broker happens to expose.
        """

        loader = _loader()
        brokers = loader.get_brokers()

        for name in SHIPPED_BROKERS:
            with self.subTest(broker=name):
                module = loader.load_broker(broker_path=brokers[name]["path"])
                # Both checked before use, as in the test above, and separately
                # so the failure says which of the two went wrong: a broker that
                # would not load reads very differently from one that loaded and
                # published no class.
                self.assertIsNotNone(module, "broker failed to load")

                broker_class = getattr(module, "Broker", None) or getattr(
                    module, name.capitalize(), None
                )
                self.assertIsNotNone(broker_class, "no Broker alias or named class")

                signature = inspect.signature(broker_class.__call__)

                # self is bound out; args, db and host are what start_run passes.
                self.assertEqual(
                    [p for p in signature.parameters if p != "self"],
                    ["args", "db", "host"],
                )


class ModuleConformanceTests(unittest.TestCase):
    """Every shipped module declares what ModuleLoader reads about it."""

    def test_each_module_satisfies_the_protocol(self) -> None:
        for filename in SHIPPED_MODULES:
            with self.subTest(module=filename):
                path = MODULES_DIR / filename
                self.assertTrue(path.is_file(), f"{filename} is gone")

                loaded = _load(path)
                candidates = [
                    obj
                    for _, obj in inspect.getmembers(loaded, inspect.isclass)
                    if obj.__module__ == loaded.__name__
                    and all(
                        hasattr(obj, marker)
                        for marker in ("name", "description", "supported_brokers")
                    )
                ]

                self.assertTrue(candidates, "no module class found")

                for candidate in candidates:
                    self.assertIsInstance(candidate(), ModuleProtocol)


if __name__ == "__main__":
    unittest.main()
