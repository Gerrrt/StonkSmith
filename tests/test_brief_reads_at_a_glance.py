"""Three ways the page made a reader work for something it already knew.

None of these was a wrong number. Each was a correct number presented so that
checking it took effort the page could have spent instead.

**The table forced its own scrollbar.** ``main`` was capped at a reading column's
width on a page that is mostly an eleven-column money table, so the rightmost
columns -- gain, growth, win/loss -- sat behind a horizontal scroll on a full-size
screen. The pinned invariant is a relationship rather than a pair of literals:
the table's minimum width has to fit inside the page's maximum, or a scrollbar
is guaranteed by arithmetic before anything renders.

**The holdings count did not match the rows under it.** It said thirteen; twelve
were listed. Both were right -- a cash sweep of eight cents is a real holding and
is filtered out of the table -- and the reconciliation was in a note beneath the
table rather than beside the figure that raised the question. A reader who counts
rows finds the discrepancy before they find the explanation.

**The chart had no scale on either axis.** It showed that something rose, without
saying from what, to what, or over how long, which is a shape rather than a
chart. The labels have to live in HTML around the SVG: it is drawn with
``preserveAspectRatio="none"`` so it can stretch to the page, and anything inside
it stretches too, so a value written as ``<text>`` comes out smeared by however
wide the reader's window happens to be.
"""

import datetime as dt
import re
import unittest

from config_isolation import UserConfigMixin
from stonksmith.etc.brief import build_brief
from stonksmith.etc.brief_html import STYLE, render, sparkline
from stonksmith.etc.portfolio import (
    OBSERVED,
    AccountRow,
    HoldingRow,
    NetWorthRow,
    Portfolio,
)

TODAY: dt.date = dt.date(2026, 8, 14)
NOW: dt.datetime = dt.datetime(2026, 8, 14, 6, 30, tzinfo=dt.UTC)


def _rem(css: str, prop: str, selector: str) -> float:
    """
    One rem-valued property out of the stylesheet.
    :param css: The stylesheet
    :param prop: The property, e.g. "max-width"
    :param selector: The rule it sits in, e.g. "main"
    :return: The value in rem
    :rtype: float
    """

    rule = re.search(
        pattern=re.escape(selector)
        + r"\s*\{[^}]*?"
        + re.escape(prop)
        + r":\s*([\d.]+)rem",
        string=css,
        flags=re.S,
    )
    assert rule is not None, f"no {prop} on {selector}"

    return float(rule.group(1))


class TheTableFitsThePageItIsOn(unittest.TestCase):
    def test_the_table_minimum_fits_inside_the_page_maximum(self) -> None:
        # The invariant, rather than the two numbers that currently satisfy it.
        # If the table's floor ever exceeds the page's ceiling, every desktop
        # reader gets a horizontal scrollbar -- and it is decided here, in
        # arithmetic, before a single row is rendered.
        page: float = _rem(css=STYLE, prop="max-width", selector="main")
        table: float = _rem(css=STYLE, prop="min-width", selector=".scroll table")

        self.assertLessEqual(
            table,
            page,
            f"the table's {table}rem minimum cannot fit the page's {page}rem",
        )

    def test_the_narrow_screen_still_scrolls_inside_its_own_box(self) -> None:
        # This must survive the widening. A phone cannot be widened into, and
        # the alternative to a box that scrolls is a *page* that scrolls
        # sideways, which is worse: it takes the headline with it.
        self.assertIn("overflow-x: auto", STYLE)
        self.assertRegex(STYLE, r"\.scroll\s*\{[^}]*overflow-x:\s*auto")


class TheCountMatchesTheRowsBeneathIt(UserConfigMixin, unittest.TestCase):
    def _page(self, floor: float) -> str:
        """
        Render a two-holding account with the given display floor.
        :param floor: Positions worth less than this are not listed
        :return: The rendered page
        :rtype: str
        """

        held = (
            HoldingRow(
                broker="b",
                source="Fidelity",
                account="An Account",
                account_key="f1",
                symbol="FSKAX",
                units=10.0,
                value=1922.62,
            ),
            HoldingRow(
                broker="b",
                source="Fidelity",
                account="An Account",
                account_key="f1",
                symbol="FCASH",
                units=0.08,
                value=0.08,
            ),
        )
        portfolio = Portfolio(
            accounts=(
                AccountRow(
                    broker="b",
                    source="Fidelity",
                    account="An Account",
                    account_key="f1",
                    value=1922.70,
                    as_of="2026-08-14",
                ),
            ),
            holdings=held,
            net_worth=(
                NetWorthRow(
                    broker="b",
                    source="Fidelity",
                    account="An Account",
                    account_key="f1",
                    date="2026-08-14",
                    value=1922.70,
                    basis=OBSERVED,
                    observed_on="2026-08-14",
                ),
            ),
        )

        return render(
            brief=build_brief(
                portfolio=portfolio, baseline=None, today=TODAY, floor=floor
            ),
            now=NOW,
        )

    def test_a_hidden_position_is_reconciled_beside_the_count(self) -> None:
        # Not in a note under the table. The reader meets "2 holdings" and one
        # row in the same glance, and the sentence that resolves it has to be in
        # that glance too.
        self.assertIn("2 holdings, 1 shown below", self._page(floor=1.00))

    def test_nothing_hidden_says_nothing_about_showing(self) -> None:
        # The qualifier appears only when it is needed. A page that explains an
        # absent discrepancy teaches the reader to skip the explanation.
        page: str = self._page(floor=0.0)

        self.assertIn("2 holdings", page)
        self.assertNotIn("shown below", page)


class TheChartSaysWhatItIsDrawnAgainst(unittest.TestCase):
    SERIES: tuple[tuple[str, float, bool], ...] = (
        ("2026-08-02", 1381.30, True),
        ("2026-08-07", 74171.57, True),
        ("2026-08-14", 77287.81, True),
    )

    def setUp(self) -> None:
        self.svg = sparkline(points=self.SERIES)

        # What a sighted reader actually sees: the markup with the <svg> taken
        # out. Asserting against the whole string would be satisfied by the
        # aria-label alone -- it carries the same figures -- so a test written
        # that way passes with every visible label deleted, which is exactly
        # what the first draft of this file did.
        self.visible: str = re.sub(
            pattern=r"<svg\b.*?</svg>", repl="", string=self.svg, flags=re.S
        )

    def test_the_value_range_is_stated(self) -> None:
        # Whole dollars: the label exists to give the line an order of
        # magnitude, and a chart spanning tens of thousands is not clarified by
        # two more digits.
        self.assertIn("$77,288", self.visible)
        self.assertIn("$1,381", self.visible)

    def test_the_date_range_is_stated(self) -> None:
        self.assertIn("2026-08-02", self.visible)
        self.assertIn("2026-08-14", self.visible)

    def test_the_labels_are_outside_the_stretched_svg(self) -> None:
        # The load-bearing one. The chart is drawn preserveAspectRatio="none" so
        # it can fill the page width, which stretches its contents with it --
        # a value in a <text> element comes out horizontally smeared by however
        # wide the window is. So the labels are HTML siblings, and there is no
        # <text> in the SVG at all.
        inside = re.search(pattern=r"<svg\b.*?</svg>", string=self.svg, flags=re.S)

        assert inside is not None
        self.assertIn('preserveAspectRatio="none"', inside.group(0))
        self.assertNotIn("<text", inside.group(0))

        # The aria-label is exempt and has to be: it is an attribute rather than
        # rendered geometry, so the stretch cannot reach it, and the test below
        # requires the range to be in there. What must not appear is a drawn
        # element -- which is why this checks for <text> and not for the figure.
        drawn: str = re.sub(
            pattern=r'aria-label="[^"]*"', repl="", string=inside.group(0)
        )

        self.assertNotIn("$77,288", drawn)
        self.assertNotIn("2026-08-02", drawn)

    def test_the_screen_reader_gets_the_same_range(self) -> None:
        # The label is the whole chart to somebody who cannot see it, and "value
        # over 3 readings" was as uninformative there as an unlabelled axis is
        # on screen.
        self.assertRegex(self.svg, r'aria-label="[^"]*\$1,381[^"]*\$77,288')

    def test_a_series_too_short_to_have_a_shape_draws_nothing(self) -> None:
        # Unchanged by the labels: one reading is not a flat portfolio, it is a
        # portfolio nobody has measured twice, and an axis on a single dot would
        # dress that up rather than say it.
        self.assertEqual(sparkline(points=self.SERIES[:1]), "")


if __name__ == "__main__":
    unittest.main()
