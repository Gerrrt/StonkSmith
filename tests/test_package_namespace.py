"""The wheel ships one importable name, and it is `stonksmith`.

The build used to say:

    [tool.hatch.build.targets.wheel]
    include = [ "src" ]
    sources = [ "src" ]

`sources` strips a path prefix; it does not declare a package root. So every child
of src/ installed at the top level of site-packages -- `etc`, `helpers`, `modules`,
`loaders`, `brokers`, `main`. Six of the most generic importable names there are,
any of which can shadow, or be shadowed by, an unrelated distribution in the same
environment, resolved by sys.path order at import time.

tests/test_dependency_hygiene.py is the test written about exactly that hazard and
it cannot see this instance of it. It walks importlib.metadata's `dist.files`, and
an editable install's RECORD lists only `_editable_impl_stonksmith.pth` -- the
project's own top-level names never appear. That blind spot is why the collision
lasted as long as it did, and it is the reason these assertions read pyproject.toml
directly instead.

Nothing here builds a wheel: that is slow, and the declaration is what actually
decides the layout. What a built wheel contains is checked by hand at release time.
"""

import tomllib
import unittest
from typing import Any

from package_tree import PACKAGE, REPO

PYPROJECT = REPO / "pyproject.toml"

#: The names the package used to install at the top level. A .py file under
#: src/stonksmith/ importing one of these would mean part of the tree never got
#: moved -- and it would keep working locally, because the compat shim aliases
#: exactly these names while a file is being loaded by path.
LEGACY_ROOTS = ("etc", "helpers", "loaders", "modules", "brokers", "main")


def _names_a_legacy_root(statement: str) -> bool:
    """Is this line an import of one of the old top-level names?

    Prefix matching on the whole statement, so `from etcetera import x` and
    `import mainly` do not count -- the same false positives a word-boundary
    pattern would have picked up during the migration itself.
    """

    return any(
        statement.startswith(
            (f"from {root} ", f"from {root}.", f"import {root} ", f"import {root}.")
        )
        or statement == f"import {root}"
        for root in LEGACY_ROOTS
    )


def config() -> dict[str, Any]:
    with PYPROJECT.open(mode="rb") as f:
        return tomllib.load(f)


class WheelLayoutTests(unittest.TestCase):
    def test_the_wheel_declares_exactly_one_package(self) -> None:
        wheel = config()["tool"]["hatch"]["build"]["targets"]["wheel"]

        self.assertEqual(
            wheel.get("packages"),
            ["src/stonksmith"],
            "the wheel must name the package directory, not the source root",
        )

    def test_the_keys_that_flattened_the_tree_are_gone(self) -> None:
        # Not covered by the assertion above: `packages` can be correct while a
        # leftover `sources` still strips the prefix off everything else.
        wheel = config()["tool"]["hatch"]["build"]["targets"]["wheel"]

        for key in ("sources", "include"):
            with self.subTest(key=key):
                self.assertNotIn(
                    key,
                    wheel,
                    f"{key} is what put six top-level names in site-packages",
                )

    def test_every_console_script_points_into_the_package(self) -> None:
        # These resolve at first invocation, not at install, so a stale entry
        # point is a traceback for the user rather than a failed `uv sync`.
        for name, target in config()["project"]["scripts"].items():
            with self.subTest(script=name):
                self.assertTrue(
                    target.startswith("stonksmith."),
                    f"{name} = {target!r} does not name a module in the package",
                )


class ConfiguredPathTests(unittest.TestCase):
    """Settings that name a file: they fail quietly when the file moves."""

    def test_the_coverage_omit_paths_exist(self) -> None:
        # modules/example.py is never executed -- it exists to be read and
        # copied. Left out of `omit` its ~28 uncovered lines rejoin the
        # denominator, and CI's floor of 87 has under a point of headroom over
        # the measured number, so this surfaces as "coverage regressed" rather
        # than as the stale path it is.
        for path in config()["tool"]["coverage"]["run"]["omit"]:
            with self.subTest(path=path):
                self.assertTrue((REPO / path).is_file(), f"{path} does not exist")

    def test_the_per_file_ignore_paths_exist(self) -> None:
        # A per-file-ignore whose path stopped matching is silent in the other
        # direction: the ignore simply stops applying and the file starts
        # failing lint for reasons that look unrelated to a move.
        ignores = config()["tool"]["ruff"]["lint"]["per-file-ignores"]

        for pattern in ignores:
            if any(char in pattern for char in "*?["):
                continue

            with self.subTest(pattern=pattern):
                self.assertTrue((REPO / pattern).exists(), f"{pattern} does not exist")


class SourceTreeTests(unittest.TestCase):
    def test_no_shipped_file_imports_a_pre_namespace_name(self) -> None:
        # The standing version of the grep this migration was driven by. It has
        # to be a test rather than a one-time check because the shim makes the
        # old names work again while a file is loaded by path -- so a shipped
        # module left on them would run correctly here and fail only once
        # installed from a wheel.
        offenders: list[str] = [
            f"{path.relative_to(REPO)}:{number}: {statement}"
            for path in sorted(PACKAGE.rglob("*.py"))
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if _names_a_legacy_root(statement := line.strip())
        ]

        self.assertEqual(
            offenders,
            [],
            "these import a name the package no longer installs:\n"
            + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
