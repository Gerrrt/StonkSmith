"""What the portfolio is meant to hold, how far it sits from that, and on
how few things it rests.

The allocation table said what the money was in. It could not say whether that
was the intention, and it could not say that a table looking evenly split had
most of its money in one fund. Three additions, and each is a measurement rather
than a recommendation.

**A target is stated, never inferred.** No source knows what anybody is aiming
at, so this reads the same kind of hand-kept table the asset classes already
come from. What the brief then reports is a distance -- held against intended.
What to do about a gap is a decision this tool has no business making, and the
column says "off target" rather than anything resembling an instruction.

**A class that is targeted and not held is the entry most worth seeing.** It
would be dropped by a breakdown built only from what is held: nothing bought yet
reads as nothing to report, when it is the whole of the gap.

**Concentration answers what the class view structurally cannot.** A portfolio
split 85/15 across two classes can still have two thirds of its money in a
single fund in a single account. The two shares are computed against *different*
denominators on purpose -- positions against the position total, accounts against
the account total -- because uninvested cash sits in an account balance and in no
holding, and one denominator for both would understate whichever it was not.
"""

import datetime as dt
import re
import unittest

from config_isolation import UserConfigMixin
from stonksmith.etc.brief import (
    Allocation,
    allocation_breakdown,
    build_brief,
    concentration,
)
from stonksmith.etc.brief_html import render
from stonksmith.etc.config import get_allocation_targets, get_drift_band
from stonksmith.etc.portfolio import (
    OBSERVED,
    AccountRow,
    HoldingRow,
    NetWorthRow,
    Portfolio,
)

TODAY: dt.date = dt.date(2026, 8, 14)
NOW: dt.datetime = dt.datetime(2026, 8, 14, 6, 30, tzinfo=dt.UTC)

CLASSES: dict[str, str] = {"AAA": "Growth", "BBB": "Steady"}


def _held(symbol: str, account: str, key: str, value: float) -> HoldingRow:
    """
    One position.
    :param symbol: Its ticker
    :param account: The account's display name
    :param key: The account key
    :param value: What it is worth
    :return: The row
    :rtype: HoldingRow
    """

    return HoldingRow(
        broker="b",
        source="src",
        account=account,
        account_key=key,
        symbol=symbol,
        units=1.0,
        value=value,
    )


class ATargetIsReadAsPeopleWriteOne(UserConfigMixin, unittest.TestCase):
    def _reload(self, body: str) -> tuple[dict[str, float], list[str]]:
        self.config_body = body
        self.tearDown()
        self.setUp()

        return get_allocation_targets()

    def test_nothing_configured_is_no_targets_and_no_complaints(self) -> None:
        self.assertEqual(get_allocation_targets(), ({}, []))

    def test_percentages_are_read_with_or_without_the_sign(self) -> None:
        targets, refused = self._reload(
            "[ALLOCATION]\ntargets =\n\tGrowth = 85\n\tSteady = 15%\n"
        )

        self.assertEqual(targets, {"Growth": 85.0, "Steady": 15.0})
        self.assertEqual(refused, [])

    def test_a_share_outside_nought_to_a_hundred_is_refused(self) -> None:
        # Not clamped. A target of 150 is a typo, and clamping it to 100 would
        # keep a number nobody meant and compute a gap against it.
        _targets, refused = self._reload("[ALLOCATION]\ntargets =\n\tGrowth = 150\n")

        self.assertEqual(len(refused), 1)
        self.assertIn("between 0 and 100", refused[0])

    def test_something_that_is_not_a_percentage_is_named(self) -> None:
        _targets, refused = self._reload(
            "[ALLOCATION]\ntargets =\n\tGrowth = most of it\n"
        )

        self.assertIn("not a percentage", refused[0])

    def test_the_band_defaults_and_survives_a_bad_value(self) -> None:
        self.assertEqual(get_drift_band(), 5.0)

        self.config_body = "[ALLOCATION]\ndrift_band = wide\n"
        self.tearDown()
        self.setUp()

        self.assertEqual(get_drift_band(), 5.0)


class TheGapIsMeasuredInPoints(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = allocation_breakdown(
            rows=(
                _held(symbol="AAA", account="One", key="a1", value=880.0),
                _held(symbol="BBB", account="Two", key="a2", value=120.0),
            ),
            classes=CLASSES,
            baseline={},
            targets={"Growth": 85.0, "Steady": 15.0},
        )
        self.by = {entry.label: entry for entry in self.rows}

    def test_the_target_travels_with_the_class(self) -> None:
        self.assertEqual(self.by["Growth"].target, 85.0)

    def test_the_gap_is_points_not_a_percentage_of_a_percentage(self) -> None:
        # 88% held against an 85% target is three points over, and three and a
        # half percent of itself over. The two numbers invite opposite
        # conclusions about one position.
        self.assertAlmostEqual(self.by["Growth"].off or 0.0, 3.0, places=6)
        self.assertAlmostEqual(self.by["Steady"].off or 0.0, -3.0, places=6)

    def test_a_class_with_no_target_has_no_gap(self) -> None:
        # None rather than zero: a class nobody set a target for is not a class
        # sitting exactly on one, and rendering them alike would show every
        # unlisted holding as perfectly on plan.
        rows = allocation_breakdown(
            rows=(_held(symbol="AAA", account="One", key="a1", value=100.0),),
            classes=CLASSES,
            baseline={},
            targets={},
        )

        self.assertIsNone(rows[0].target)
        self.assertIsNone(rows[0].off)

    def test_a_target_with_nothing_held_still_appears(self) -> None:
        # The entry most worth seeing, and the one a breakdown built only from
        # holdings drops. Nothing bought yet is the whole of the gap.
        rows = allocation_breakdown(
            rows=(_held(symbol="AAA", account="One", key="a1", value=100.0),),
            classes=CLASSES,
            baseline={},
            targets={"Growth": 60.0, "Steady": 40.0},
        )
        by = {entry.label: entry for entry in rows}

        self.assertIn("Steady", by)
        self.assertEqual(by["Steady"].value, 0.0)
        self.assertAlmostEqual(by["Steady"].off or 0.0, -40.0, places=6)


class TheBandDecidesWhatIsWorthSaying(UserConfigMixin, unittest.TestCase):
    def _page(self, growth: float, steady: float, band: float) -> str:
        held = (
            _held(symbol="AAA", account="One", key="a1", value=growth),
            _held(symbol="BBB", account="Two", key="a2", value=steady),
        )
        portfolio = Portfolio(
            accounts=(
                AccountRow(
                    broker="b",
                    source="src",
                    account="One",
                    account_key="a1",
                    value=growth,
                    as_of="2026-08-14",
                ),
                AccountRow(
                    broker="b",
                    source="src",
                    account="Two",
                    account_key="a2",
                    value=steady,
                    as_of="2026-08-14",
                ),
            ),
            holdings=held,
            net_worth=(
                NetWorthRow(
                    broker="b",
                    source="src",
                    account="One",
                    account_key="a1",
                    date="2026-08-14",
                    value=growth + steady,
                    basis=OBSERVED,
                    observed_on="2026-08-14",
                ),
            ),
        )

        self.config_body = (
            "[ALLOCATION]\n"
            "asset_classes =\n\tAAA = Growth\n\tBBB = Steady\n"
            "targets =\n\tGrowth = 85\n\tSteady = 15\n"
            f"drift_band = {band}\n"
        )
        self.tearDown()
        self.setUp()

        return render(
            brief=build_brief(portfolio=portfolio, baseline=None, today=TODAY),
            now=NOW,
        )

    def test_inside_the_band_the_gap_is_stated_and_not_flagged(self) -> None:
        page: str = self._page(growth=880.0, steady=120.0, band=5.0)

        self.assertIn("+3.0 pp", page)
        self.assertNotIn("OFF", page)

    def test_outside_the_band_it_is_flagged(self) -> None:
        page: str = self._page(growth=950.0, steady=50.0, band=5.0)

        self.assertIn("OFF", page)

    def test_the_flag_is_a_word_and_not_only_a_colour(self) -> None:
        # A page where colour is the only difference between "on plan" and "off
        # plan" is unreadable to about one man in twelve, and this deliberately
        # is not one.
        page: str = self._page(growth=950.0, steady=50.0, band=5.0)
        marked = re.search(pattern=r'<b class="wl">([^<]+)</b>', string=page)

        assert marked is not None
        self.assertEqual(marked.group(1), "OFF")


class ConcentrationSaysWhatTheClassesCannot(unittest.TestCase):
    def setUp(self) -> None:
        self.focus = concentration(
            rows=(
                _held(symbol="AAA", account="Big", key="a1", value=670.0),
                _held(symbol="BBB", account="Small", key="a2", value=330.0),
            ),
            accounts=(
                AccountRow(
                    broker="b",
                    source="src",
                    account="Big",
                    account_key="a1",
                    value=680.0,
                    as_of="2026-08-14",
                ),
                AccountRow(
                    broker="b",
                    source="src",
                    account="Small",
                    account_key="a2",
                    value=330.0,
                    as_of="2026-08-14",
                ),
            ),
        )

    def test_the_largest_position_is_named_with_its_account(self) -> None:
        # A ticker alone is ambiguous: the same fund is routinely held in
        # several accounts, and which one carries the concentration matters.
        self.assertEqual(self.focus.holding, "AAA in Big")
        self.assertAlmostEqual(self.focus.holding_share, 0.67, places=4)

    def test_the_largest_account_is_ranked_separately(self) -> None:
        # Separately, because a position can be modest while the account
        # holding it is not.
        self.assertEqual(self.focus.account, "Big")

    def test_the_two_shares_use_different_denominators(self) -> None:
        # 670 of 1,000 in positions is 67.0%; 680 of 1,010 in accounts is
        # 67.33%. They differ by the uninvested cash that sits in a balance and
        # in no holding, and one denominator for both would understate
        # whichever it was not.
        self.assertNotAlmostEqual(
            self.focus.holding_share, self.focus.account_share, places=4
        )
        self.assertAlmostEqual(self.focus.account_share, 680.0 / 1010.0, places=6)

    def test_nothing_held_ranks_nothing(self) -> None:
        empty = concentration(rows=(), accounts=())

        self.assertEqual(empty.holding, "")
        self.assertEqual(empty.account_share, 0.0)


class TheAllocationEntryStandsAlone(unittest.TestCase):
    def test_an_entry_with_no_target_carries_none_rather_than_zero(self) -> None:
        self.assertIsNone(Allocation(label="Growth").target)
        self.assertIsNone(Allocation(label="Growth").off)


if __name__ == "__main__":
    unittest.main()
