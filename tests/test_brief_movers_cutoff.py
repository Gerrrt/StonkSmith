"""Which movers earn a row, and what the page owes the ones that do not.

The cutoff is a ranking -- the largest by dollar, capped at ``[BRIEF] movers`` --
and it was chosen against two alternatives that both looked reasonable.

A **dollar floor** keeps a rounding wiggle on the largest account off the page
and hides a four percent day on the smallest one. On a book where a single 401k
is two thirds of the money, one floor cannot be right for both ends of it. A
**percentage floor** inverts that, and makes a cash account holding twelve
dollars the loudest row every morning; it also has nothing to say about an
account that arrived since the baseline, whose ``pct`` is None because there is
no denominator. A ranking has no threshold to be wrong about, shows the same
number of rows every day, and stays right as the portfolio grows.

What a ranking costs is that it can drop a real mover, and this file exists
mostly for that. A list that ends at eight without comment reports the eighth as
the smallest thing that moved -- the reader cannot tell a quiet morning from a
truncated one. That is the quiet-truncation failure this project already names
about ``get_transactions``, whose five-hundred-row limit is exactly why that read
cannot back a sheet.

So the count of what was dropped is computed in build_brief and rendered. The
render half is pinned in tests/test_brief_render_sections.py; this pins the half
that computes it, which a render test cannot -- it builds a Brief directly and
would pass with the wiring removed.
"""

import datetime as dt
import unittest

from config_isolation import UserConfigMixin
from stonksmith.etc.brief import Baseline, Movement, build_brief, significant
from stonksmith.etc.portfolio import OBSERVED, NetWorthRow, Portfolio

TODAY: dt.date = dt.date(2026, 8, 14)

#: Ten accounts, each moving by a different amount, largest last so nothing here
#: depends on the order they were built in.
MOVES: tuple[int, ...] = tuple(range(1, 11))


def _portfolio() -> Portfolio:
    """Ten accounts that each moved, on two dates of one axis."""

    rows: list[NetWorthRow] = []

    for index in MOVES:
        for date, value in (
            ("2026-08-12", 1000.0),
            ("2026-08-13", 1000.0 + index * 10),
        ):
            rows.append(
                NetWorthRow(
                    broker="snaptrade",
                    source="snaptrade",
                    account=f"Account {index:02d}",
                    account_key=f"a{index}",
                    date=date,
                    value=value,
                    basis=OBSERVED,
                    observed_on=date,
                )
            )

    return Portfolio(net_worth=tuple(rows))


BASELINE: Baseline = Baseline(taken_on="2026-08-12", totals={"USD": 10_000.0})


class TheCutoffIsTheLargestByDollar(unittest.TestCase):
    def test_it_keeps_the_order_it_was_given(self) -> None:
        # account_movements sorts by absolute dollar move before this sees them,
        # so the cutoff is a truncation and never a re-sort. Re-sorting here
        # would be a second opinion about ranking, in a function whose whole
        # job is to stop at a number.
        moves = [
            Movement(label="a", broker="x", delta=-500.0),
            Movement(label="b", broker="x", delta=100.0),
        ]

        self.assertEqual(
            [row.label for row in significant(moves=moves, limit=8)], ["a", "b"]
        )

    def test_a_fall_ranks_by_its_size_not_its_sign(self) -> None:
        # Absolute, because a reader at half past six wants what moved the
        # portfolio, and a four hundred dollar drop moved it more than a fifty
        # dollar rise.
        from stonksmith.etc.brief import account_movements

        ranked = account_movements(
            rows=(
                NetWorthRow(
                    broker="b",
                    source="b",
                    account="Fell",
                    account_key="f",
                    date="2026-08-12",
                    value=1000.0,
                    basis=OBSERVED,
                ),
                NetWorthRow(
                    broker="b",
                    source="b",
                    account="Fell",
                    account_key="f",
                    date="2026-08-13",
                    value=600.0,
                    basis=OBSERVED,
                ),
                NetWorthRow(
                    broker="b",
                    source="b",
                    account="Rose",
                    account_key="r",
                    date="2026-08-12",
                    value=1000.0,
                    basis=OBSERVED,
                ),
                NetWorthRow(
                    broker="b",
                    source="b",
                    account="Rose",
                    account_key="r",
                    date="2026-08-13",
                    value=1050.0,
                    basis=OBSERVED,
                ),
            ),
            since="2026-08-12",
            until="2026-08-13",
        )

        self.assertEqual([row.label for row in ranked], ["Fell", "Rose"])

    def test_fewer_movers_than_the_cap_are_all_kept(self) -> None:
        moves = [Movement(label=str(n), broker="x", delta=float(n)) for n in range(3)]

        self.assertEqual(len(significant(moves=moves, limit=8)), 3)


class WhatTheCapLeftOutIsCounted(UserConfigMixin, unittest.TestCase):
    """The half a render test cannot reach, because it builds a Brief directly."""

    def test_eight_are_shown_and_the_rest_counted(self) -> None:
        brief = build_brief(
            portfolio=_portfolio(), baseline=BASELINE, today=TODAY, limit=8
        )

        self.assertEqual(len(brief.account_movers), 8)
        self.assertEqual(brief.account_movers_dropped, 2)

    def test_the_largest_movers_are_the_ones_kept(self) -> None:
        # Accounts 10 and 09 moved most; 01 and 02 moved least and are the two
        # that should fall off.
        brief = build_brief(
            portfolio=_portfolio(), baseline=BASELINE, today=TODAY, limit=8
        )
        shown = [row.label for row in brief.account_movers]

        self.assertEqual(shown[0], "Account 10")
        self.assertNotIn("Account 01", shown)
        self.assertNotIn("Account 02", shown)

    def test_nothing_is_dropped_when_everything_fits(self) -> None:
        # The count must be zero rather than negative when the cap is generous,
        # or the page reports a phantom "-2 more accounts moved".
        brief = build_brief(
            portfolio=_portfolio(), baseline=BASELINE, today=TODAY, limit=50
        )

        self.assertEqual(len(brief.account_movers), 10)
        self.assertEqual(brief.account_movers_dropped, 0)

    def test_a_first_brief_drops_nothing(self) -> None:
        # No baseline means no comparison, so there are no movers to cap and
        # nothing to have left out. A count above zero here would put "N more
        # accounts moved" on a page that has just said it cannot compare.
        brief = build_brief(portfolio=_portfolio(), baseline=None, today=TODAY, limit=8)

        self.assertEqual(brief.account_movers, ())
        self.assertEqual(brief.account_movers_dropped, 0)


if __name__ == "__main__":
    unittest.main()
