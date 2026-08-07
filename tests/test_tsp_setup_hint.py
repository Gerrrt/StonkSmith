# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""The message a first TSP run actually hits, and where it sends the reader.

A live run stopped at "No TSP fund configured" and followed the hint, which
said to set fund and units in the config "or pass --prices". So the run passed
--prices -- and got an argparse error, because --prices takes a path to a
downloaded price file and has nothing to do with naming a fund.

That is the failure mode worth a test: a hint that is not wrong about any one
fact, but offers as an alternative something that cannot possibly resolve the
condition it is printed for. Following it costs a round trip and teaches the
reader nothing.
"""

import importlib.util
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def _tsp_broker():
    spec = importlib.util.spec_from_file_location(
        "tsp_broker", SRC / "brokers/tsp/broker.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SetupHint(unittest.TestCase):
    """What it must say, and the one thing it must not."""

    def setUp(self) -> None:
        self.hint = _tsp_broker().SETUP_HINT

    def test_it_does_not_offer_prices_as_a_way_to_name_a_fund(self) -> None:
        """The live run followed exactly this and hit a usage error."""
        self.assertNotIn("--prices", self.hint)

    def test_it_names_the_file_to_edit(self) -> None:
        self.assertIn("stonksmith.conf", self.hint)

    def test_it_names_the_section_and_the_key(self) -> None:
        self.assertIn("[TSP]", self.hint)
        self.assertIn("fund", self.hint)

    def test_it_shows_what_a_fund_name_looks_like(self) -> None:
        """ "C Fund" is not guessable from "fund"; it is a column heading."""
        self.assertIn("C Fund", self.hint)

    def test_it_lists_every_way_units_can_arrive(self) -> None:
        """Units are not config-only, and a hint that implied so would mislead."""
        for route in ("--units", "--balance", "STATEMENT"):
            self.assertIn(route, self.hint)


if __name__ == "__main__":
    unittest.main()
