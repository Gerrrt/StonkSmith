# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""The version is read, not written, and there is one of it.

It used to be written twice: a literal in etc/cli.py beside the one in
pyproject.toml, agreeing by luck and checked by nothing. That is the shape of bug
this project keeps finding, and this instance was quiet in the worst way -- a
`--version` that is wrong reports it with total confidence, and the number is
what somebody correlates a strange database or a strange sheet against.

**Two other copies of "0.1.0" exist in src/ and are deliberately left alone.**
`modules/ally_module.py` and `brokers/tsp/broker.py` carry it inside a
User-Agent, and the comment above the TSP one says why: tsp.gov's WAF answers a
plain requests UA with a 403 and wants a second product/version token, so the
string is shaped like a browser's because it has to be. That file states outright
that "the version is an identifier, not a claim about the build, and does not
need to track releases". Wiring those to the release version would contradict a
measured decision and make a live-verified string vary with the build -- so this
file checks the reported version and pointedly does not check those.

**A third copy lives in README.md and is not left alone.** The README quotes the
`--help` banner, which prints both the version and the codename, so those two
lines restate what pyproject.toml and `CODENAME` already say. Nothing compared
them, and the comment beside `CODENAME` admitted the copy "goes stale silently";
the transcript around them has drifted before. `BannerTests` holds those two
lines and nothing else in that block.
"""

import ast
import tomllib
import unittest
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

import stonksmith.etc.cli as etc_cli
from package_tree import PACKAGE, REPO
from stonksmith.etc.cli import CODENAME, UNKNOWN_VERSION, get_version

PYPROJECT = REPO / "pyproject.toml"
README = REPO / "README.md"


def declared() -> str:
    """The version pyproject.toml declares, which is the single source."""

    with PYPROJECT.open(mode="rb") as f:
        return str(object=tomllib.load(f)["project"]["version"])


class SingleSourceTests(unittest.TestCase):
    def test_the_reported_version_is_the_declared_one(self) -> None:
        # The whole point. These are the two numbers that used to be typed
        # separately, and the only thing that kept them equal was that nobody
        # had changed one yet.
        #
        # A failure here in CI means they have genuinely parted company. A
        # failure locally usually means the venv is behind pyproject.toml, since
        # get_version reads what was installed rather than what is declared --
        # CI runs `uv sync --locked` and so cannot see that state.
        self.assertEqual(
            get_version(),
            declared(),
            "pyproject.toml and the installed distribution disagree about the "
            "version. If this passes in CI, the local venv is behind the file "
            "-- run `uv sync`.",
        )

    def test_the_version_is_read_from_metadata_and_not_from_pyproject(self) -> None:
        # The test above passes either way, because both routes arrive at the
        # same number today -- so on its own it does not say *where* the version
        # came from. Reading pyproject.toml directly would be the tempting
        # shortcut and is wrong: the file says what the next build will declare,
        # the metadata says what is installed and actually running, and it is the
        # running one a bug report needs. Patching the metadata is what tells
        # them apart, because pyproject.toml on disk does not move.
        with patch.object(etc_cli, "installed_version", return_value="7.7.7"):
            self.assertEqual(get_version(), "7.7.7")
            self.assertNotEqual(get_version(), declared())

    def test_an_uninstalled_source_tree_says_so_rather_than_guessing(self) -> None:
        # `python src/stonksmith/main.py` rather than `uv run` has no metadata to read.
        # Every number this could fall back to would be a guess presented as a
        # fact, and a version is only worth printing if it is the one running.
        with patch.object(
            etc_cli, "installed_version", side_effect=PackageNotFoundError("stonksmith")
        ):
            self.assertEqual(get_version(), UNKNOWN_VERSION)

    def test_the_fallback_is_not_a_number(self) -> None:
        # Pins the decision rather than the string: any fallback that looked like
        # a version would be indistinguishable from a real one at the point it
        # matters, which is somebody reading it off a bug report.
        self.assertFalse(
            any(char.isdigit() for char in UNKNOWN_VERSION),
            "a fallback that looks like a version is a guess wearing a fact's clothes",
        )

    def test_the_codename_stays_hand_written(self) -> None:
        # The one part of the banner nothing can derive: there is no metadata
        # field to read a codename out of. It is here so that it is the only
        # thing left to keep in step by hand.
        self.assertTrue(CODENAME)
        self.assertNotIn(declared(), CODENAME)


class BannerTests(unittest.TestCase):
    """The README quotes the banner, so it holds a second copy of both facts.

    Only these two lines are checked, and not the transcript around them. The
    banner interpolates ANSI colour through ``highlight()``, so comparing what
    the package renders would spend most of itself on escape-stripping and would
    end up testing ``highlight`` rather than the duplication. What is duplicated
    is two values; those are what this pins.

    Read against pyproject.toml rather than ``get_version()`` deliberately. The
    README documents the release being prepared, which is what the file declares;
    the installed distribution can be a bump behind it locally, and failing for
    that reason would be reporting a stale venv as a stale README.
    """

    #: The banner's two labels, spelled as README.md has to spell them. `Version`
    #: carries a trailing space so its colon lines up with the one below -- that
    #: alignment is in the f-strings in etc/cli.py, and is part of the string.
    LABELS: tuple[str, ...] = ("Version :", "Codename:")

    def setUp(self) -> None:
        self.lines: list[str] = README.read_text(encoding="utf-8").splitlines()

    def test_the_quoted_version_is_the_declared_one(self) -> None:
        # The number a reader takes the README to be describing. It is the first
        # thing that goes stale on a release, because bumping pyproject.toml is
        # the step everyone remembers and this block is three files away.
        self.assertIn(
            f"Version : {declared()}",
            self.lines,
            f"README.md's banner does not quote version {declared()}. Bump the "
            "line rather than the file -- pyproject.toml is the single source.",
        )

    def test_the_quoted_codename_is_the_one_the_package_holds(self) -> None:
        # The codename is the one part of the banner nothing can derive, so it is
        # the part most likely to be left behind: a minor bump moves it, and
        # until now the only thing that noticed was a person re-reading the file.
        self.assertIn(
            f"Codename: {CODENAME}",
            self.lines,
            f"README.md's banner does not quote the codename {CODENAME!r} that "
            "etc/cli.py holds. The codename moves with the minor version.",
        )

    def test_neither_label_appears_on_a_second_line(self) -> None:
        # The two tests above ask only whether the right line exists, so a stale
        # duplicate further down satisfies both of them -- the correct line is
        # still there, and neither ever asks whether something contradicts it.
        # A second banner pasted into the README is exactly the drift this class
        # is for, so it has to be asked separately rather than assumed away.
        for label in self.LABELS:
            with self.subTest(label=label):
                carrying: list[str] = [
                    line for line in self.lines if line.startswith(label)
                ]

                self.assertEqual(
                    len(carrying),
                    1,
                    f"README.md has {len(carrying)} lines starting {label!r} and "
                    f"should have exactly one: {carrying}. Two of them means the "
                    "checks above can pass while a reader is shown the wrong one.",
                )


def assigned_literal(module: Path, name: str) -> object:
    """
    What a module assigns to a name, read out of its source rather than run.

    Asked of the file and not of the imported module, because the question is
    what the assignment *is* and not what it evaluated to this time. Those differ
    exactly where it matters: a User-Agent wired to get_version() holds the right
    string on an installed tree and the wrong one everywhere else, so comparing
    values would agree with the version being spliced in.
    :param module: The file to read
    :param name: The module-level name to find
    :return: The assigned value
    :rtype: object
    :raises AssertionError: if the name is not assigned at module level
    :raises ValueError: if it is assigned something that is not a literal
    """

    for node in ast.parse(source=module.read_text(encoding="utf-8")).body:
        targets: list[ast.expr] = []

        if isinstance(node, ast.Assign):
            targets = list(node.targets)

        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]

        if any(
            isinstance(target, ast.Name) and target.id == name for target in targets
        ):
            # Raises ValueError on anything that is not a literal -- a call, an
            # f-string, a name -- which is the whole check.
            return ast.literal_eval(node_or_string=node.value)  # type: ignore[arg-type]

    raise AssertionError(f"{module.name} assigns no module-level {name}")


class UserAgentTests(unittest.TestCase):
    """The two copies that are not the release version, and must not become it."""

    #: The files, and the name each keeps its User-Agent under.
    AGENTS: tuple[tuple[Path, str], ...] = (
        (PACKAGE / "brokers" / "tsp" / "broker.py", "PRICE_USER_AGENT"),
        (PACKAGE / "modules" / "ally_module.py", "QUOTE_USER_AGENT"),
    )

    def test_the_user_agents_are_literals_rather_than_derived(self) -> None:
        # brokers/tsp/broker.py records that tsp.gov's WAF refuses
        # "Mozilla/5.0 (compatible; stonksmith)" and accepts a version token, and
        # that the token is an identifier rather than a claim about the build.
        # Deriving it from get_version() would make a string measured against a
        # live host vary with the build, and become "stonksmith/unknown" on an
        # uninstalled tree -- which nothing has ever sent to that WAF.
        #
        # Checked as an assignment rather than as a value. Comparing values
        # cannot see this at all: the token happens to equal the release version
        # today, so a UA built from get_version() would hold the identical string
        # in any installed environment and the test would pass on the change it
        # exists to refuse.
        for module, name in self.AGENTS:
            with self.subTest(name=name):
                try:
                    value = assigned_literal(module=module, name=name)

                except ValueError:
                    self.fail(
                        f"{name} in {module.name} is no longer a literal. If it "
                        "was wired to the release version, that is the change "
                        "this test refuses: the token is a fixed identifier a "
                        "WAF was measured against, not a claim about the build."
                    )

                self.assertIsInstance(value, str)
                self.assertTrue(
                    str(object=value).startswith("Mozilla/5.0 (compatible; stonksmith/")
                )

    def test_the_literal_is_what_the_module_actually_holds(self) -> None:
        # The source check above is only worth having if the assignment it found
        # is the one in effect -- a second assignment further down would make it
        # read the wrong line and pass on a file it had misread.
        from stonksmith.brokers.tsp.broker import PRICE_USER_AGENT
        from stonksmith.modules.ally_module import QUOTE_USER_AGENT

        held: dict[str, str] = {
            "PRICE_USER_AGENT": PRICE_USER_AGENT,
            "QUOTE_USER_AGENT": QUOTE_USER_AGENT,
        }

        for module, name in self.AGENTS:
            with self.subTest(name=name):
                self.assertEqual(assigned_literal(module=module, name=name), held[name])
                self.assertNotIn(UNKNOWN_VERSION, held[name])


if __name__ == "__main__":
    unittest.main()
