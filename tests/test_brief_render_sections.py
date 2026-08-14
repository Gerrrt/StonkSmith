"""Each section of the page draws what it has, and nothing when it has none.

Seven sections, and the interesting cases are all the empty ones. A card headed
"Allocation" containing one 100% slice called "(unclassified)", or one headed
"Not fresh" with no rows under it, is worse than no card: it takes up the space a
reader scans and answers nothing, and after a week of them nobody scrolls that
far. The config comment for asset_classes makes this argument for the sheet's
allocation block, and it applies unchanged here.

The sparkline gets the same treatment for a sharper reason. Two points are the
fewest that can make a line; drawn from one, the chart is a single dot on a flat
axis -- which reads as a portfolio that has not moved rather than as one nobody
has measured twice. That is a claim about the money made out of a shortage of
data, which is the class of mistake this whole project is arranged against.
"""

import datetime as dt
import unittest

from config_isolation import UserConfigMixin
from stonksmith.etc.brief import Allocation, Brief, BriefState, Movement, Position
from stonksmith.etc.brief_html import money, percent, render, signed, sparkline
from stonksmith.etc.portfolio import CARRIED, OBSERVED

NOW: dt.datetime = dt.datetime(2026, 8, 14, 6, 30, tzinfo=dt.UTC)


class TheSparkline(unittest.TestCase):
    def test_one_point_draws_nothing(self) -> None:
        self.assertEqual(sparkline(points=[("2026-08-13", 100.0, True)]), "")

    def test_no_points_draw_nothing(self) -> None:
        self.assertEqual(sparkline(points=[]), "")

    def test_two_points_draw_a_line(self) -> None:
        svg: str = sparkline(
            points=[("2026-08-12", 100.0, True), ("2026-08-13", 200.0, True)]
        )

        self.assertIn("<polyline", svg)
        self.assertIn("<svg", svg)

    def test_a_flat_series_does_not_divide_by_its_range(self) -> None:
        # A portfolio that has not moved has no range to scale into, and the
        # obvious implementation puts every point at infinity -- an SVG that
        # renders as nothing at all on the one morning it is easiest not to
        # notice, because a flat line and a missing line look alike.
        svg: str = sparkline(
            points=[("2026-08-12", 100.0, True), ("2026-08-13", 100.0, True)]
        )

        self.assertIn("<polyline", svg)
        self.assertNotIn("inf", svg.lower())
        self.assertNotIn("nan", svg.lower())

    def test_only_observed_points_get_a_dot(self) -> None:
        # A stretch of carried dates is a straight segment drawn between two
        # readings. Marking where the readings are is what stops the line from
        # claiming to be a measurement along its whole length.
        svg: str = sparkline(
            points=[
                ("2026-08-11", 100.0, True),
                ("2026-08-12", 150.0, False),
                ("2026-08-13", 200.0, True),
            ]
        )

        self.assertEqual(svg.count("<circle"), 2)


class TheNumberFormatting(unittest.TestCase):
    def test_an_absent_value_is_a_dash(self) -> None:
        # Not "$0.00". A source that reported nothing is not one that reported
        # zero, and the screen a person reads is the last place that distinction
        # can survive.
        self.assertEqual(money(value=None), "—")

    def test_a_value_is_grouped_and_two_decimal_places(self) -> None:
        self.assertEqual(money(value=1234.5), "$1,234.50")

    def test_a_non_dollar_currency_is_named_rather_than_symbolised(self) -> None:
        self.assertEqual(money(value=10.0, currency="EUR"), "EUR 10.00")

    def test_direction_is_carried_by_an_arrow_not_only_colour(self) -> None:
        # About one man in twelve cannot read a red-green dashboard, and every
        # number on this page is either a rise or a fall.
        self.assertTrue(signed(value=10.0).startswith("▲"))
        self.assertTrue(signed(value=-10.0).startswith("▼"))
        self.assertTrue(signed(value=0.0).startswith("±"))

    def test_a_fall_is_rendered_as_a_positive_amount(self) -> None:
        # The arrow says down; a leading minus as well would read as "minus
        # negative three hundred" on a quick scan.
        self.assertEqual(signed(value=-300.0), "▼ $300.00")

    def test_no_denominator_renders_as_nothing(self) -> None:
        self.assertEqual(percent(value=None), "")


def _brief(**fields: object) -> Brief:
    """
    A brief with one account read, overridden per case.
    :param fields: What to set on it
    :return: The brief
    :rtype: Brief
    """

    # Merged into the defaults rather than passed alongside them, so a case may
    # override `state` as easily as it adds an `allocation`.
    return Brief(
        **{
            "state": BriefState.FRESH,
            "as_of": "2026-08-13",
            "since": "2026-08-12",
            "total": 1000.0,
            "delta": 10.0,
            "observed": 1,
            **fields,
        }  # type: ignore[arg-type]
    )


class TheSectionsAppearOnlyWhenEarned(UserConfigMixin, unittest.TestCase):
    def test_a_healthy_morning_carries_no_banner(self) -> None:
        # A warning that appears every day is one that stops being read, which
        # would make it useless on the morning it says something.
        self.assertNotIn("⚠", render(brief=_brief(), now=NOW))

    def test_a_stalled_morning_says_so_at_the_top(self) -> None:
        page: str = render(brief=_brief(state=BriefState.NO_NEW_SCRAPE), now=NOW)

        self.assertIn("No new scrape since 2026-08-12", page)
        self.assertIn("not counted as read", page)

    def test_a_degraded_morning_names_what_is_missing(self) -> None:
        page: str = render(
            brief=_brief(
                state=BriefState.DEGRADED,
                unreadable=(("ally", "file is not a database"),),
            ),
            now=NOW,
        )

        self.assertIn("short by at least one broker", page)
        self.assertIn("file is not a database", page)

    def test_no_allocation_section_when_nothing_is_classified(self) -> None:
        self.assertNotIn("Allocation", render(brief=_brief(), now=NOW))

    def test_the_allocation_section_shows_drift_in_points(self) -> None:
        # Percentage points, not a percentage of a percentage: a class going
        # from 20% to 22% has drifted two points and risen ten percent of
        # itself, and the two invite opposite conclusions about one move.
        page: str = render(
            brief=_brief(
                allocation=(
                    Allocation(label="US Stock", value=800.0, share=0.8, was=0.75),
                )
            ),
            now=NOW,
        )

        self.assertIn("US Stock", page)
        self.assertIn("+5.0 pp", page)

    def test_a_class_with_no_baseline_shows_a_dash_not_a_drift(self) -> None:
        page: str = render(
            brief=_brief(
                allocation=(Allocation(label="Bond", value=200.0, share=0.2, was=None),)
            ),
            now=NOW,
        )

        self.assertIn("Bond", page)

        # The rendered cell, not the absence of "pp" anywhere on the page --
        # which was the first thing tried here and matches the "-apple-system"
        # in the font stack. A substring assertion has to name something only
        # the case under test could produce.
        self.assertIn('<td class="num">—</td>', page)

    def test_no_stale_section_when_everything_is_fresh(self) -> None:
        self.assertNotIn("Not fresh", render(brief=_brief(), now=NOW))

    def test_the_stale_section_quotes_the_reason_verbatim(self) -> None:
        page: str = render(
            brief=_brief(
                stale=(("ally / Ally Invest", "as of 2026-07-01, 44 days old"),)
            ),
            now=NOW,
        )

        self.assertIn("Not fresh", page)
        self.assertIn("as of 2026-07-01, 44 days old", page)

    def test_a_carried_mover_is_marked_on_its_own_row(self) -> None:
        # On the row rather than in a legend. A reader scanning four movers
        # should not have to hold "the third one is carried" in their head.
        page: str = render(
            brief=_brief(
                account_movers=(
                    Movement(
                        label="Ally Invest",
                        broker="ally",
                        before=900.0,
                        after=1000.0,
                        delta=100.0,
                        pct=0.111,
                        basis=CARRIED,
                    ),
                )
            ),
            now=NOW,
        )

        self.assertIn("carried", page)

    def test_an_observed_mover_carries_no_pill(self) -> None:
        page: str = render(
            brief=_brief(
                account_movers=(
                    Movement(
                        label="TSP",
                        broker="tsp",
                        before=900.0,
                        after=1000.0,
                        delta=100.0,
                        basis=OBSERVED,
                    ),
                )
            ),
            now=NOW,
        )

        self.assertNotIn('class="carried"', page)

    def test_a_units_change_is_noted_and_an_unchanged_count_is_not(self) -> None:
        # The line between a position the market repriced and one that was
        # bought. A "0 units" note on every repriced row would bury the handful
        # that are events.
        #
        # On the holdings row rather than in a movers list, which is where this
        # lived until the full table replaced that section. The note is the one
        # thing the list said that the table does not, so it moved rather than
        # going away -- and this test moved with it rather than being deleted.
        bought: str = render(
            brief=_brief(
                positions=(
                    Position(
                        symbol="VTI",
                        broker="ally",
                        account="Ally Invest",
                        value=1000.0,
                        units_delta=2.0,
                    ),
                )
            ),
            now=NOW,
        )
        repriced: str = render(
            brief=_brief(
                positions=(
                    Position(
                        symbol="VTI",
                        broker="ally",
                        account="Ally Invest",
                        value=1000.0,
                        units_delta=None,
                    ),
                )
            ),
            now=NOW,
        )

        self.assertIn("+2.0000 units", bought)

        # "Shares" is a column header on this table, so the assertion names the
        # note's own wording rather than the word "units" anywhere on the page.
        self.assertNotIn("units", repriced)


if __name__ == "__main__":
    unittest.main()
