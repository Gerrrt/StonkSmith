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

#: Every codename released so far, keyed by the minor series it named. Recovered
#: from the tags rather than written from memory -- `git show
#: v0.3.0:src/stonksmith/etc/cli.py` prints the literal that shipped, and until
#: this map existed that was the only record of any of them.
#:
#: It exists because a rule about *movement* needs two values and there was only
#: ever one. The comment beside `CODENAME` says a codename "is not derivable from
#: anything -- there is nothing to read it out of"; that was true of the current
#: name and quietly also true of every name before it, so "it moves with the
#: minor version" could not be checked by anything even in principle.
CODENAMES: dict[str, str] = {
    "0.1": "Forrest Gump",
    "0.2": "Ferris Bueller",
    "0.3": "Fox Mulder",
    "0.4": "Ford Prefect",
    "0.5": "Ford Prefect",
}

#: The minor series that shipped without moving the codename. 0.5 reused 0.4's
#: "Ford Prefect", and it is recorded rather than repaired: 0.5.0 is on PyPI
#: under that name, and a version number is spent whether or not what went under
#: it was right.
#:
#: Adding to this set is the deliberate act the gate below exists to force. It is
#: not an escape hatch for a release in flight -- an entry has to describe a
#: reuse that actually happened, and `test_no_skip_is_a_stale_suppression`
#: fails on one that does not, so the set cannot quietly accumulate permissions
#: for reuses nobody has made yet.
SKIPPED_THE_MOVE: frozenset[str] = frozenset({"0.5"})

#: The letter every codename has begun with. Forrest Gump, Ferris Bueller, Fox
#: Mulder and Ford Prefect are four for four, which is past the point where it
#: reads as coincidence -- but four names are also few enough that the pattern
#: lived entirely in whoever picked the last one, and the person picking the next
#: one is not guaranteed to be them.
#:
#: Pinned as the letter rather than as "they all agree with each other". The
#: weaker rule is satisfied by the whole set moving to G, which is not the
#: convention -- it is a different convention that happens to be self-consistent,
#: and it would pass on the release that abandoned this one.
CODENAME_INITIAL: str = "F"


def minor_series(version: str) -> str:
    """The minor series a version belongs to: ``1.2.3`` -> ``"1.2"``."""

    major, minor, *_ = version.split(".")

    return f"{major}.{minor}"


def series_order(series: str) -> tuple[int, ...]:
    """Sort key for a series, so 0.10 follows 0.9 rather than 0.1."""

    return tuple(int(part) for part in series.split("."))


def reused_codenames() -> dict[str, list[str]]:
    """Every codename naming more than one series, each in release order."""

    by_name: dict[str, list[str]] = {}

    for series, name in CODENAMES.items():
        by_name.setdefault(name, []).append(series)

    return {
        name: sorted(series, key=series_order)
        for name, series in by_name.items()
        if len(series) > 1
    }


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


class CodenameConventionTests(unittest.TestCase):
    """ "It moves with the minor version" was a comment, and comments do not run.

    0.5.0 is the proof and the reason this class exists. It shipped reusing
    0.4.0's "Ford Prefect" with every gate green, because no gate was ever
    looking: `BannerTests` compares the README's copy against `CODENAME`, so
    those two agree with each other whatever `CODENAME` says, and nothing
    compared `CODENAME` against the release before it. The rule was written down
    in the one place that cannot enforce it -- in a comment beside the value it
    governs -- and the release went out before anybody re-read the comment.

    That is this project's recurring shape, reached from a new direction. The
    version was two copies agreeing by luck until something compared them; the
    codename was one copy with a rule about it that nothing could evaluate,
    because evaluating it needs the previous value and the previous value was
    only ever in the tags.
    """

    def test_the_current_minor_has_a_codename_recorded(self) -> None:
        # The check that fires on the release that forgets. A minor bump with no
        # entry here is exactly what 0.5.0 was, and it is the moment the omission
        # is still free to fix -- once tagged, the name is on PyPI.
        series: str = minor_series(declared())

        self.assertIn(
            series,
            CODENAMES,
            f"pyproject.toml declares {declared()} and CODENAMES has no entry "
            f"for the {series} series. A minor bump moves the codename: add the "
            "new name here and to etc/cli.py, or record the series in "
            "SKIPPED_THE_MOVE and say why.",
        )

    def test_the_package_holds_the_recorded_codename(self) -> None:
        # What makes the map authoritative rather than decorative. Without this
        # the history could say one thing while the banner printed another, and
        # the gate below would be checking a record of nothing.
        series: str = minor_series(declared())

        self.assertEqual(
            CODENAMES.get(series),
            CODENAME,
            f"etc/cli.py holds {CODENAME!r} but CODENAMES records "
            f"{CODENAMES.get(series)!r} for the {series} series. These are the "
            "same fact and one of them has moved.",
        )

    def test_every_minor_moves_the_codename(self) -> None:
        # The convention itself, finally executable. Reuse is caught wherever it
        # happens rather than only between neighbours: going back to a name from
        # two series ago is the same defect as not moving at all, and a check
        # that only compared adjacent pairs would wave it through.
        for name, series in reused_codenames().items():
            first, *repeats = series

            for repeat in repeats:
                with self.subTest(codename=name, series=repeat):
                    self.assertIn(
                        repeat,
                        SKIPPED_THE_MOVE,
                        f"the {repeat} series reuses {name!r}, already used by "
                        f"{first}. The codename moves with the minor version. If "
                        "a release genuinely meant to keep the previous name, "
                        "add the series to SKIPPED_THE_MOVE with a reason.",
                    )

    def test_every_codename_starts_with_the_same_letter(self) -> None:
        # The other half of the convention, and the half with no natural moment
        # to be noticed. A codename that has moved is visibly a new name, so the
        # gate above fires on the release that forgets; a name that moved but
        # broke the pattern looks correct from every angle except this one.
        #
        # Checked over the whole history rather than over CODENAME alone. The
        # current name is held equal to its recorded entry above, so covering the
        # record covers it -- and a name added for some other series would
        # otherwise never be looked at again.
        for series, name in sorted(
            CODENAMES.items(), key=lambda kv: series_order(kv[0])
        ):
            with self.subTest(series=series, codename=name):
                self.assertTrue(
                    name.startswith(CODENAME_INITIAL),
                    f"the {series} codename {name!r} does not start with "
                    f"{CODENAME_INITIAL!r}. Every release so far has been named "
                    "for a fictional character whose name begins with that "
                    "letter; breaking it is a decision rather than a slip, so "
                    "move CODENAME_INITIAL and say why.",
                )

    def test_no_skip_is_a_stale_suppression(self) -> None:
        # The half that keeps the exception list honest. Without it an entry
        # added for a release that was then given a fresh name would sit here
        # permitting a reuse nobody has made -- a silenced alarm on a door that
        # was subsequently locked, which is worse than no alarm because it reads
        # as a decision somebody made about the current state.
        actually_reused: set[str] = {
            series for repeats in reused_codenames().values() for series in repeats[1:]
        }

        for series in sorted(SKIPPED_THE_MOVE, key=series_order):
            with self.subTest(series=series):
                self.assertIn(
                    series,
                    actually_reused,
                    f"SKIPPED_THE_MOVE names the {series} series, but its "
                    "codename is not a reuse of an earlier one. The entry is "
                    "suppressing nothing and should go -- left in place it would "
                    "permit a future reuse in that series without comment.",
                )


if __name__ == "__main__":
    unittest.main()
