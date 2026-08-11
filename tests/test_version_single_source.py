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
"""

import tomllib
import unittest
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

import etc.cli
from etc.cli import CODENAME, UNKNOWN_VERSION, get_version

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def declared() -> str:
    """The version pyproject.toml declares, which is the single source."""

    with open(file=PYPROJECT, mode="rb") as f:
        return str(object=tomllib.load(f)["project"]["version"])


class SingleSourceTests(unittest.TestCase):
    def test_the_reported_version_is_the_declared_one(self) -> None:
        # The whole point. These are the two numbers that used to be typed
        # separately, and the only thing that kept them equal was that nobody
        # had changed one yet.
        self.assertEqual(get_version(), declared())

    def test_a_bumped_pyproject_and_a_stale_install_disagree_here(self) -> None:
        # Not a restatement of the test above: that one compares the two numbers,
        # this one says what a difference between them means. get_version reads
        # installed metadata, so bumping pyproject.toml without reinstalling
        # leaves `--version` reporting the old number -- true, but not the code
        # that is running. CI runs `uv sync --locked`, so the two agree there and
        # a failure here is a local venv behind the file. Fix: `uv sync`.
        self.assertEqual(
            get_version(),
            declared(),
            "pyproject.toml and the installed distribution disagree about the "
            "version. The venv is behind the file -- run `uv sync`.",
        )

    def test_an_uninstalled_source_tree_says_so_rather_than_guessing(self) -> None:
        # `python src/main.py` rather than `uv run` has no metadata to read.
        # Every number this could fall back to would be a guess presented as a
        # fact, and a version is only worth printing if it is the one running.
        with patch.object(
            etc.cli, "installed_version", side_effect=PackageNotFoundError("stonksmith")
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


class UserAgentTests(unittest.TestCase):
    """The two copies that are not the release version, and must not become it."""

    def test_the_user_agents_do_not_track_the_reported_version(self) -> None:
        # brokers/tsp/broker.py records that tsp.gov's WAF refuses
        # "Mozilla/5.0 (compatible; stonksmith)" and accepts a version token, and
        # that the token is an identifier rather than a claim about the build.
        # Deriving it from get_version() would make a string measured against a
        # live host vary with the build -- and become "stonksmith/unknown" on an
        # uninstalled tree, which nothing has ever sent to that WAF.
        from brokers.tsp.broker import PRICE_USER_AGENT
        from modules.ally_module import QUOTE_USER_AGENT

        for agent in (PRICE_USER_AGENT, QUOTE_USER_AGENT):
            with self.subTest(agent=agent):
                self.assertTrue(
                    agent.startswith("Mozilla/5.0 (compatible; stonksmith/")
                )
                self.assertNotIn(UNKNOWN_VERSION, agent)

    def test_they_are_fixed_strings_rather_than_reads(self) -> None:
        # If one were wired to get_version(), patching it would move the UA. This
        # is what stops a tidy-up from quietly changing what two live hosts see.
        from brokers.tsp.broker import PRICE_USER_AGENT

        with patch.object(etc.cli, "installed_version", return_value="9.9.9"):
            from brokers.tsp.broker import PRICE_USER_AGENT as after

            self.assertEqual(PRICE_USER_AGENT, after)
            self.assertNotIn("9.9.9", after)


if __name__ == "__main__":
    unittest.main()
