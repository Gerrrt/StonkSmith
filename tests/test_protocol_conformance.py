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

from package_tree import MODULES as MODULES_DIR
from package_tree import REPO
from stonksmith.etc.context import BrokerProtocol, ModuleProtocol
from stonksmith.loaders.brokerloader import BrokerLoader

#: Not collected by globbing what exists: a glob that silently stopped matching
#: would leave this file asserting nothing, which is the failure mode
#: test_broker_discovery.py was written about.
#:
#: Written down, and then checked against the directory -- both halves, which is
#: the shape test_broker_discovery.py already uses for the broker packages and
#: this file had only half of. Without the check a name missing from these tuples
#: is simply never conformance-tested, and two were: `manual` and
#: `manual_module.py` had been shipping unchecked because nothing compared the
#: lists to what is on disk. Removing the fidelity broker is what surfaced it --
#: deleting `modules/fidelity_module.py` broke no test, because an allowlist
#: cannot notice something leaving it.
SHIPPED_BROKERS = ("ally", "manual", "schwab529plan", "snaptrade", "tsp")
SHIPPED_MODULES = (
    "ally_module.py",
    "manual_module.py",
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


#: Exempt from the listing check below. `example.py` is the annotated template
#: rather than a module anybody runs -- it is excluded from coverage and from
#: some lint rules for the same reason -- and `__init__.py` is packaging.
NOT_MODULES = ("__init__.py", "example.py")


class ShippedListsMatchTheTreeTests(unittest.TestCase):
    """The written-down lists have to be what is actually on disk.

    The tuples above exist so a stopped glob cannot leave this file asserting
    nothing. That is the right trade and it has a cost the other half pays for:
    a list nothing compares to the tree is a list that can quietly disagree with
    it, and then a broker or module ships with its conformance never checked.
    """

    def test_every_broker_package_is_listed(self) -> None:
        found = sorted(
            p.name
            for p in (MODULES_DIR.parent / "brokers").iterdir()
            if p.is_dir() and not p.name.startswith((".", "_"))
        )

        self.assertEqual(
            found,
            sorted(SHIPPED_BROKERS),
            "brokers/ and SHIPPED_BROKERS disagree. A broker missing from the "
            "tuple is never checked against BrokerProtocol by this file.",
        )

    def test_every_module_is_listed(self) -> None:
        found = sorted(
            p.name for p in MODULES_DIR.glob("*.py") if p.name not in NOT_MODULES
        )

        self.assertEqual(
            found,
            sorted(SHIPPED_MODULES),
            "modules/ and SHIPPED_MODULES disagree. A module missing from the "
            "tuple is never checked against ModuleProtocol by this file.",
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
