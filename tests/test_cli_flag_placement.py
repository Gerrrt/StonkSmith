"""--verbose and --debug must work on either side of the broker name.

`stonksmith fidelity -M fidelity --verbose` is the natural thing to type and it
used to be a usage error: --verbose and --debug were top-level only, while -M,
-u, -p and -id are subcommand flags, so the required ordering was the opposite
of what most of the flags wanted.

The subtle half is the default. std_parser is a parent of every broker
subparser, so a plain `default=False` there would set verbose=False whenever the
flag was absent *after* the broker name -- overwriting a --verbose already
parsed before it. SUPPRESS leaves the attribute alone unless the flag is really
given, which is what makes the pre-broker position keep working.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from etc.cli import gen_cli_args
from loaders.brokerloader import BrokerLoader

REPO = Path(__file__).resolve().parents[1]


class _RepoOnlyLoader(BrokerLoader):
    """A loader that ignores ~/.stonksmith/brokers.

    gen_cli_args() builds a BrokerLoader to register one subparser per broker,
    and BrokerLoader scans the user's home as well as the repo. Without this,
    a half-finished broker under ~/.stonksmith/brokers -- one whose
    broker_args.py raises on import, say -- would fail these tests on the
    developer's machine over something entirely unrelated to CLI parsing.
    Same seam tests/test_broker_discovery.py uses.
    """

    def __init__(self) -> None:
        super().__init__()
        self.stonksmith_path = REPO / "absent"


def _parse(*argv: str):
    with (
        patch.object(sys, "argv", ["stonksmith", *argv]),
        patch("etc.cli.BrokerLoader", _RepoOnlyLoader),
    ):
        return gen_cli_args()


class VerboseFlagPlacementTests(unittest.TestCase):
    def test_verbose_before_the_broker(self) -> None:
        self.assertTrue(_parse("--verbose", "snaptrade", "-M", "snaptrade").verbose)

    def test_verbose_after_the_broker(self) -> None:
        # The case that used to be "unrecognized arguments: --verbose".
        self.assertTrue(_parse("snaptrade", "-M", "snaptrade", "--verbose").verbose)

    def test_debug_before_the_broker(self) -> None:
        self.assertTrue(_parse("--debug", "snaptrade", "-M", "snaptrade").debug)

    def test_debug_after_the_broker(self) -> None:
        self.assertTrue(_parse("snaptrade", "-M", "snaptrade", "--debug").debug)

    def test_neither_flag_leaves_both_off(self) -> None:
        args = _parse("snaptrade", "-M", "snaptrade")

        self.assertFalse(args.verbose)
        self.assertFalse(args.debug)

    def test_a_pre_broker_flag_is_not_clobbered_by_the_subparser(self) -> None:
        # THE regression this design guards. With default=False on std_parser
        # the subparser would overwrite the top-level True with False, silently
        # turning off a --verbose the operator did pass.
        self.assertTrue(_parse("--verbose", "snaptrade", "-M", "snaptrade").verbose)
        self.assertTrue(_parse("--debug", "snaptrade", "-M", "snaptrade").debug)

    def test_both_flags_can_be_split_across_positions(self) -> None:
        args = _parse("--verbose", "snaptrade", "-M", "snaptrade", "--debug")

        self.assertTrue(args.verbose)
        self.assertTrue(args.debug)

    def test_every_broker_accepts_them(self) -> None:
        # std_parser is a parent of every broker subparser, so this holds for
        # any broker added later too.
        for broker in ("ally", "fidelity", "schwab529plan", "snaptrade", "tsp"):
            with self.subTest(broker=broker):
                self.assertTrue(_parse(broker, "-M", "x", "--verbose").verbose)


if __name__ == "__main__":
    unittest.main()
