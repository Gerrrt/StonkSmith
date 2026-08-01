"""Guard against two distributions claiming the same import name.

playwright-sm shipped its own top-level ``playwright_stealth/`` package, which
overwrote the real playwright-stealth. Both wrote the same files, so whichever
installed last won -- macOS resolved one, Linux CI the other, and the type check
and test suite disagreed across platforms for days.
"""

import importlib.metadata as md
import unittest
from collections import defaultdict

# PEP 420 namespace packages are legitimately shared across distributions.
KNOWN_NAMESPACE_PACKAGES: frozenset[str] = frozenset({"jaraco"})


def _top_level_owners() -> dict[str, set[str]]:
    """
    Map each importable top-level name to the distributions that install it.

    Covers both packages (``foo/__init__.py``) and single-file modules
    (``foo.py``). Skipping the latter would miss a real collision: two
    distributions both shipping ``foo.py`` make ``import foo`` just as
    last-install-wins as two shipping ``foo/``.
    """

    owners: dict[str, set[str]] = defaultdict(set)

    for dist in md.distributions():
        name = dist.metadata["Name"]
        if not name:
            continue

        for entry in dist.files or []:
            path = str(entry)
            if (
                path.startswith("..")
                or ".dist-info" in path
                or ".data/" in path
                or path.startswith(("__pycache__", "__editable__"))
            ):
                continue

            if "/" in path:
                owners[path.split("/")[0]].add(name)

            elif path.endswith(".py"):
                owners[path.removesuffix(".py")].add(name)

    return owners


class DependencyHygieneTests(unittest.TestCase):
    def test_no_two_distributions_claim_the_same_import_name(self) -> None:
        collisions = {
            top: sorted(dists)
            for top, dists in _top_level_owners().items()
            if len(dists) > 1 and top not in KNOWN_NAMESPACE_PACKAGES
        }

        self.assertEqual(
            collisions,
            {},
            "Two distributions install the same top-level package; whichever "
            "installs last wins, and that order varies by platform. Drop one, "
            "or add it to KNOWN_NAMESPACE_PACKAGES if it is a real PEP 420 "
            "namespace package.",
        )

    def test_playwright_stealth_resolves_to_the_real_distribution(self) -> None:
        # The specific symptom of the collision: Stealth exists in
        # playwright-stealth 2.x and not in playwright-sm's bundled copy.
        from playwright_stealth import Stealth

        self.assertTrue(callable(Stealth))


if __name__ == "__main__":
    unittest.main()
