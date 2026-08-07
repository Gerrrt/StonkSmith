"""A run that worked has to say so.

Every message StonkSmith prints about its own progress goes through
StonkSmithAdapter.display(), success() or highlight(), and all three log at
INFO. The default level was ERROR, so none of them survived it: a TSP sync
could read the statement, write the snapshot to the database and update the
Google Sheet while printing nothing but a progress bar. There was no way to
tell that from a run that had done nothing at all -- which is the failure this
whole repository is otherwise built to avoid.

It had been worked around twice instead of fixed, and both workarounds are
still in etc.connection with comments admitting it: one paragraph explaining
that a branch reports at fail level "because the INFO-level progress messages
above are hidden at the default log level", another explaining the same thing
about broker_flow(). Correct messages having to be mis-levelled to be seen is
the symptom; the default is the cause.

--quiet is the old behaviour, kept for unattended runs. --verbose sits ahead of
it so that adding --verbose to a wrapper script that hardcodes --quiet does
what the operator obviously meant.
"""

import logging
import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from etc.cli import gen_cli_args
from etc.infrastructure import set_logging_level
from loaders.brokerloader import BrokerLoader

REPO = Path(__file__).resolve().parents[1]


class _RepoOnlyLoader(BrokerLoader):
    """A loader that ignores ~/.stonksmith/brokers.

    Same seam tests/test_cli_flag_placement.py uses, and for the same reason:
    these tests assert what the parser accepts, so whatever a developer happens
    to have installed under their home directory must not be part of the answer.
    """

    def __init__(self) -> None:
        super().__init__()
        self.stonksmith_path = REPO / "absent"


def _parse(*argv: str) -> Namespace:
    with (
        patch.object(sys, "argv", ["stonksmith", *argv]),
        patch("etc.cli.BrokerLoader", _RepoOnlyLoader),
    ):
        return gen_cli_args()


class _LevelCase(unittest.TestCase):
    """set_logging_level() writes to a process-global logger; put it back."""

    def setUp(self) -> None:
        self.logger = logging.getLogger("stonksmith")
        self._previous = self.logger.level

    def tearDown(self) -> None:
        self.logger.setLevel(self._previous)

    def _level_for(self, **flags: bool) -> int:
        defaults: dict[str, bool] = {"debug": False, "verbose": False, "quiet": False}
        set_logging_level(args=Namespace(**(defaults | flags), log=None))
        return self.logger.level


class DefaultRun(_LevelCase):
    """No flags at all."""

    def test_progress_is_shown(self) -> None:
        # THE regression. At ERROR a successful sync printed nothing.
        self.assertLessEqual(self._level_for(), logging.INFO)

    def test_it_is_not_debug(self) -> None:
        # Showing what a run did is not the same as showing how it works.
        self.assertGreater(self._level_for(), logging.DEBUG)


class QuietRun(_LevelCase):
    """--quiet is the old default, asked for rather than imposed."""

    def test_progress_is_hidden(self) -> None:
        self.assertGreater(self._level_for(quiet=True), logging.INFO)

    def test_failures_still_get_through(self) -> None:
        # A silent run is the point; a silent *failure* never is.
        self.assertLessEqual(self._level_for(quiet=True), logging.ERROR)


class FlagPrecedence(_LevelCase):
    """The combinations, since two of the three flags argue with each other."""

    def test_verbose_beats_quiet(self) -> None:
        # What --verbose is for now: a wrapper script hardcodes --quiet and the
        # operator wants to see what it is doing without editing the script.
        self.assertLessEqual(self._level_for(verbose=True, quiet=True), logging.INFO)

    def test_debug_beats_quiet(self) -> None:
        self.assertEqual(self._level_for(debug=True, quiet=True), logging.DEBUG)

    def test_debug_beats_verbose(self) -> None:
        self.assertEqual(self._level_for(debug=True, verbose=True), logging.DEBUG)


class ListingsNeedNoSpecialCase(_LevelCase):
    """--list-modules and --options exist purely to print something.

    They log at INFO, so under the ERROR default they produced no output and
    set_logging_level() carried a clause promoting the level whenever either was
    passed. That clause is gone: with INFO as the default there is nothing left
    for it to fix, and a special case that is still there once it stops doing
    anything is the kind that gets copied.
    """

    def test_a_listing_prints_without_being_promoted(self) -> None:
        self.assertLessEqual(self._level_for(), logging.INFO)

    def test_a_listing_asked_to_be_quiet_stays_quiet(self) -> None:
        # And the removed clause could not have honoured that: it promoted the
        # level on the presence of the listing flag alone.
        self.assertGreater(self._level_for(quiet=True), logging.INFO)


class QuietFlagPlacement(unittest.TestCase):
    """--quiet has to work on either side of the broker name, like its siblings.

    std_parser is a parent of every broker subparser, so a plain default=False
    there would set quiet=False whenever the flag was absent after the broker
    name -- overwriting a --quiet already parsed before it. SUPPRESS is what
    stops that, and it is easy to add a flag to one list and not the other.
    """

    def test_before_the_broker(self) -> None:
        self.assertTrue(_parse("--quiet", "tsp", "-M", "tsp").quiet)

    def test_after_the_broker(self) -> None:
        self.assertTrue(_parse("tsp", "-M", "tsp", "--quiet").quiet)

    def test_a_pre_broker_quiet_is_not_clobbered_by_the_subparser(self) -> None:
        self.assertTrue(_parse("--quiet", "tsp", "-M", "tsp", "--verbose").quiet)

    def test_absent_leaves_it_off(self) -> None:
        self.assertFalse(_parse("tsp", "-M", "tsp").quiet)

    def test_every_broker_accepts_it(self) -> None:
        for broker in ("ally", "fidelity", "schwab529plan", "snaptrade", "tsp"):
            with self.subTest(broker=broker):
                self.assertTrue(_parse(broker, "-M", "x", "--quiet").quiet)


if __name__ == "__main__":
    unittest.main()
