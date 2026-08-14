"""The brief's total sums the carry axis, so a quiet broker is not a fall.

The failure this pins is the one net_worth_history was written to prevent, one
consumer further along. Brokers do not scrape on the same day: TSP runs
unattended every weekday, Ally needs a manual sign-in and routinely goes a week.
So on most nights the newest date on the axis carries a reading for one broker
and a value carried forward for the others.

Total only what was read on that date and the portfolio appears to lose every
account that did not run -- forty-one thousand dollars, overnight, in a headline
number rendered in green and red beside a percentage. It would look entirely like
data. The next morning Ally scrapes and it all comes back, so the chart recovers
and nothing anywhere reports an error.

The temptation is specific and it reads as rigour: carried values are not real
readings, so exclude them and report only what was measured. That is right about
a *reading* and wrong about a *total*, and this file is here because the two are
easy to conflate. A carried value is the last thing anybody knew that account to
be worth, and leaving it out does not make the total more honest -- it makes it
a total of a different portfolio.

What keeps it honest instead is saying so, which is what the observed/carried
split on the headline is for; tests/test_brief_reports_carried_split.py pins that
half.
"""

import datetime as dt
import unittest

from config_isolation import UserConfigMixin
from stonksmith.etc.brief import build_brief, totals_by_date
from stonksmith.etc.portfolio import (
    AccountRow,
    Portfolio,
    net_worth_history,
)

#: Two brokers on the cadence the docs describe. TSP ran on both dates; Ally ran
#: on the first and not the second, which is the ordinary weeknight rather than
#: an outage.
OBSERVATIONS: tuple[AccountRow, ...] = (
    AccountRow(
        broker="tsp",
        source="tsp",
        account="TSP C Fund",
        account_key="t1",
        value=90000.0,
        as_of="2026-08-12",
        scraped_at="2026-08-12T18:30:00",
    ),
    AccountRow(
        broker="ally",
        source="ally",
        account="Ally Invest",
        account_key="a1",
        value=41000.0,
        as_of="2026-08-12",
        scraped_at="2026-08-12T18:31:00",
    ),
    AccountRow(
        broker="tsp",
        source="tsp",
        account="TSP C Fund",
        account_key="t1",
        value=91500.0,
        as_of="2026-08-13",
        scraped_at="2026-08-13T18:30:00",
    ),
)

TSP_ONLY: float = 91500.0
WHOLE_PORTFOLIO: float = 132500.0


class TheTotalCountsEveryAccount(unittest.TestCase):
    def setUp(self) -> None:
        self.series = net_worth_history(observations=OBSERVATIONS)
        self.totals = totals_by_date(rows=self.series)

    def test_the_newest_date_carries_the_broker_that_did_not_run(self) -> None:
        # The whole claim, in one number. Reverting to a total of the observed
        # rows alone returns 91500.0 here -- a portfolio that lost Ally's entire
        # balance on a night when nothing happened to it.
        self.assertEqual(
            self.totals["2026-08-13"],
            WHOLE_PORTFOLIO,
            "the newest date totalled only the broker that scraped, so a night "
            "Ally did not run reads as Ally going to zero",
        )

    def test_both_dates_total_the_same_accounts(self) -> None:
        # Not an assertion that the value is unchanged -- TSP moved -- but that
        # the *composition* is. A delta between two dates only means anything
        # when both sum the same set of accounts, which is the property the
        # carry exists to provide and the one a subtraction silently depends on.
        self.assertEqual(
            self.totals["2026-08-13"] - self.totals["2026-08-12"],
            TSP_ONLY - 90000.0,
            "the difference between the two dates is not TSP's move alone, so "
            "the axis is not comparing like with like",
        )

    def test_an_account_below_the_carry_horizon_is_absent_not_zero(self) -> None:
        # The other half of the rule. Past CARRY_DAYS the account leaves the
        # series rather than persisting at a stale number, and the total on that
        # date is a smaller portfolio rather than the same one at zero.
        stretched = (
            *OBSERVATIONS,
            AccountRow(
                broker="tsp",
                source="tsp",
                account="TSP C Fund",
                account_key="t1",
                value=93000.0,
                as_of="2026-10-01",
                scraped_at="2026-10-01T18:30:00",
            ),
        )
        totals = totals_by_date(rows=net_worth_history(observations=stretched))

        self.assertEqual(
            totals["2026-10-01"],
            93000.0,
            "Ally was carried more than thirty days past its last reading, so "
            "the total is standing on a number nobody has checked since August",
        )


class TheBriefReportsThatTotal(UserConfigMixin, unittest.TestCase):
    def test_the_headline_is_the_carried_total(self) -> None:
        # Through build_brief rather than only through totals_by_date, so the
        # assembly cannot quietly total something else on its way to the page.
        brief = build_brief(
            portfolio=Portfolio(net_worth=tuple(net_worth_history(OBSERVATIONS))),
            baseline=None,
            today=dt.date(2026, 8, 14),
        )

        self.assertEqual(brief.as_of, "2026-08-13")
        self.assertEqual(brief.total, WHOLE_PORTFOLIO)


if __name__ == "__main__":
    unittest.main()
