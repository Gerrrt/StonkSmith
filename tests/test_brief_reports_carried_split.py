"""The page says how much of its headline was actually read this morning.

The other half of tests/test_brief_delta_uses_carry_axis.py. That one pins that a
carried account is counted; this one pins that the reader is told it was.

Counting them is what makes the total right. Saying so is what makes the total
honest, and the two are separate claims that can be broken independently -- the
number can be correct on a page that presents it as five fresh readings when it
is one reading and four carries. A reader who takes "+$1,500" for a portfolio
move, when it is one broker's move and four accounts nobody checked, has been
misled by a page that was arithmetically perfect.

Rendered beside the headline rather than in a footnote, and pinned here at the
level of the HTML rather than the dataclass, because a field that is computed and
never displayed is the failure this is guarding against.
"""

import datetime as dt
import unittest

from config_isolation import UserConfigMixin
from stonksmith.etc.brief import build_brief
from stonksmith.etc.brief_html import render
from stonksmith.etc.portfolio import CARRIED, OBSERVED, NetWorthRow, Portfolio

NOW: dt.datetime = dt.datetime(2026, 8, 14, 6, 30, tzinfo=dt.UTC)


def _row(broker: str, key: str, value: float, basis: str) -> NetWorthRow:
    """
    One account on the newest date, read or carried onto it.
    :param broker: The broker
    :param key: Its account key
    :param value: What the account was worth
    :param basis: OBSERVED or CARRIED
    :return: The series row
    :rtype: NetWorthRow
    """

    return NetWorthRow(
        broker=broker,
        source=broker,
        account=f"{broker} account",
        account_key=key,
        date="2026-08-13",
        value=value,
        basis=basis,
        observed_on="2026-08-13",
        scraped_at="2026-08-13T18:30:00",
    )


class TheSplitReachesThePage(UserConfigMixin, unittest.TestCase):
    def setUp(self) -> None:
        # UserConfigMixin's setUp is what points the config at a throwaway file.
        # Skipping the super() call leaves every getter reading the developer's
        # real config, which tests/test_suite_does_not_touch_home.py fails the
        # whole suite for.
        super().setUp()

        self.portfolio = Portfolio(
            net_worth=(
                _row(broker="tsp", key="t1", value=91500.0, basis=OBSERVED),
                _row(broker="ally", key="a1", value=41000.0, basis=CARRIED),
                _row(broker="schwab529plan", key="s1", value=8000.0, basis=CARRIED),
            )
        )
        self.brief = build_brief(
            portfolio=self.portfolio, baseline=None, today=dt.date(2026, 8, 14)
        )

    def test_the_counts_are_split(self) -> None:
        self.assertEqual(self.brief.observed, 1)
        self.assertEqual(self.brief.carried, 2)

    def test_the_page_names_both_numbers(self) -> None:
        page: str = render(brief=self.brief, now=NOW)

        # Both numbers and the word, rather than a substring of the sentence.
        # The wording is free to be rewritten; what must survive is that a reader
        # is told how many of the three accounts were actually read.
        self.assertIn("1 of 3 accounts were read", page)
        self.assertIn("2 carried", page)

    def test_a_fully_observed_morning_says_so_plainly(self) -> None:
        # The counterpart, so the carried sentence cannot be hardcoded. A morning
        # where every broker ran should not carry a caveat it has not earned --
        # a warning that appears every day is one that stops being read.
        every = Portfolio(
            net_worth=(
                _row(broker="tsp", key="t1", value=91500.0, basis=OBSERVED),
                _row(broker="ally", key="a1", value=41000.0, basis=OBSERVED),
            )
        )
        page: str = render(
            brief=build_brief(
                portfolio=every, baseline=None, today=dt.date(2026, 8, 14)
            ),
            now=NOW,
        )

        self.assertIn("All 2 accounts were read", page)
        self.assertNotIn("carried an older value", page)


if __name__ == "__main__":
    unittest.main()
