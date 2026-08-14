"""A brief with no baseline says so, rather than reporting a quiet morning.

"Nothing moved" and "nothing could be compared" render almost identically and
mean opposite things. The first is a fact about the portfolio. The second is a
fact about the brief, and on the morning it is true the reader has been given no
information at all -- while being shown a page that looks exactly like the one
they get on a day when genuinely nothing happened.

Three ways to arrive there, which is why this is its own file: the very first
run, a baseline file that was deleted, and one written by a version whose fields
do not mean what this one would read them as. All three answer None, and None has
to produce a page that admits it rather than a delta computed from zeros -- which
would report the entire portfolio as having arrived overnight.

The delta-from-zero failure is the specific thing being guarded. It is not a
crash and not a blank screen; it is a plausible, enormous, green number.
"""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from config_isolation import UserConfigMixin
from stonksmith.etc.brief import (
    BASELINE_VERSION,
    BriefState,
    build_brief,
    read_baseline,
)
from stonksmith.etc.brief_html import render
from stonksmith.etc.portfolio import OBSERVED, NetWorthRow, Portfolio

NOW: dt.datetime = dt.datetime(2026, 8, 14, 6, 30, tzinfo=dt.UTC)

PORTFOLIO: Portfolio = Portfolio(
    net_worth=(
        NetWorthRow(
            broker="tsp",
            source="tsp",
            account="TSP C Fund",
            account_key="t1",
            date="2026-08-13",
            value=91500.0,
            basis=OBSERVED,
            observed_on="2026-08-13",
        ),
    )
)


class AFirstBriefInventsNoChange(UserConfigMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()

        self.brief = build_brief(
            portfolio=PORTFOLIO, baseline=None, today=dt.date(2026, 8, 14)
        )

    def test_it_is_marked_as_a_first_brief(self) -> None:
        self.assertIs(self.brief.state, BriefState.FIRST)

    def test_the_delta_is_not_the_whole_portfolio(self) -> None:
        # The failure in one assertion. Treating an absent baseline as zero makes
        # every account look like it arrived last night, which is a number rather
        # than a message and so cannot be told apart from a real one.
        self.assertEqual(self.brief.delta, 0.0)
        self.assertIsNone(self.brief.pct)

    def test_no_movers_are_reported(self) -> None:
        # Empty because nothing can be compared, not because nothing moved. The
        # page has to distinguish those, which the next test checks.
        self.assertEqual(self.brief.account_movers, ())
        self.assertEqual(self.brief.holding_movers, ())

    def test_the_page_says_why_it_is_empty(self) -> None:
        page: str = render(brief=self.brief, now=NOW)

        self.assertIn("first brief", page)
        self.assertIn("nothing to compare against yet", page)

    def test_the_total_is_still_reported(self) -> None:
        # A first brief reports no *change*, and still reports what is held. A
        # page showing nothing at all reads as a broken install rather than as a
        # first run.
        self.assertEqual(self.brief.total, 91500.0)


class AnUnusableBaselineIsNoBaseline(unittest.TestCase):
    def setUp(self) -> None:
        self._home = tempfile.TemporaryDirectory()
        self.path = Path(self._home.name) / "brief_baseline.json"

    def tearDown(self) -> None:
        self._home.cleanup()

    def test_a_missing_file_reads_as_none(self) -> None:
        self.assertIsNone(read_baseline(path=self.path))

    def test_a_truncated_file_reads_as_none(self) -> None:
        # A write interrupted by a laptop closing mid-brief. Half a JSON object
        # parses as nothing, and the alternative to None is a delta computed
        # against whichever fields happened to survive.
        self.path.write_text(
            data='{"version": 1, "taken_on": "2026-08', encoding="utf-8"
        )

        self.assertIsNone(read_baseline(path=self.path))

    def test_a_future_version_reads_as_none(self) -> None:
        # The reason the version is written down. A baseline whose fields mean
        # something else is not one this code can subtract against, and reading
        # it anyway produces a confident wrong answer rather than a first brief.
        self.path.write_text(
            data=json.dumps(
                {"version": BASELINE_VERSION + 1, "taken_on": "2026-08-13"}
            ),
            encoding="utf-8",
        )

        self.assertIsNone(read_baseline(path=self.path))

    def test_a_json_document_of_the_wrong_shape_reads_as_none(self) -> None:
        self.path.write_text(data="[1, 2, 3]", encoding="utf-8")

        self.assertIsNone(read_baseline(path=self.path))


if __name__ == "__main__":
    unittest.main()
