# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""The account series, and the four ways a series over uneven scrapes lies.

The plumbing is settled elsewhere -- a row shape, a tab, an append-only column
tuple, all pinned by tests/test_portfolio_contract.py. What is tested here is
the part that is not plumbing.

Brokers do not scrape on the same day. Ally needs a manual sign-in and may go a
week, TSP runs unattended, SnapTrade runs whenever. So the obvious construction
-- group the stored snapshots by date and total them -- puts one broker's money
on a date only that broker ran on, and draws a portfolio that repeatedly
collapses and recovers. Every number in it is real. The chart is still a lie,
and it looks entirely like data, which is what makes it worse than no chart.

Carrying each account's last known value forward fixes that and introduces three
more ways to be wrong, each of which is a test below: a carried value that does
not admit it, a carry that crosses a gap it has no business crossing, and an
account back-filled at zero for dates before it existed. The first is a chart
asserting a precision it does not have; the third is the row-shape rule -- a
value the source never gave stays empty rather than becoming 0 -- broken with a
number invented on top.
"""

import unittest

from etc.portfolio import (
    CARRIED,
    CARRY_DAYS,
    OBSERVED,
    AccountRow,
    NetWorthRow,
    net_worth_history,
)


def observation(
    broker: str = "tsp",
    key: str = "TSP",
    value: float | None = 100.0,
    as_of: str | None = "2026-01-01",
    scraped_at: str = "2026-01-01 12:00:00",
    currency: str = "USD",
    account: str | None = None,
) -> AccountRow:
    """One snapshot, as read_history hands it over."""

    return AccountRow(
        broker=broker,
        source=broker,
        # Defaults to the key, which is the ordinary case. Passed separately
        # only where a test needs the display name to differ from identity.
        account=key if account is None else account,
        account_key=key,
        value=value,
        currency=currency,
        as_of=as_of,
        scraped_at=scraped_at,
    )


def totals(series: list[NetWorthRow]) -> dict[str, float]:
    """What each date in a series adds up to."""

    summed: dict[str, float] = {}

    for row in series:
        summed[row.date] = summed.get(row.date, 0.0) + (row.value or 0.0)

    return summed


def on(series: list[NetWorthRow], date: str) -> list[NetWorthRow]:
    """Every row standing on one date."""

    return [row for row in series if row.date == date]


class UnevenScrapeTests(unittest.TestCase):
    """The failure the whole shape exists to prevent."""

    def test_a_date_only_one_broker_ran_on_still_counts_both(self) -> None:
        # The headline. Ally reads on the 1st and the 8th; TSP reads on the 3rd.
        # Group by date and total, and the 3rd holds TSP's money alone -- a
        # portfolio that lost two thirds of itself and got it back, on nothing
        # but scrape timing.
        series = net_worth_history(
            observations=[
                observation(broker="ally", key="A", value=200.0, as_of="2026-01-01"),
                observation(broker="ally", key="A", value=210.0, as_of="2026-01-08"),
                observation(broker="tsp", key="T", value=100.0, as_of="2026-01-03"),
                observation(broker="tsp", key="T", value=105.0, as_of="2026-01-08"),
            ]
        )

        self.assertEqual(
            totals(series=series),
            {"2026-01-01": 200.0, "2026-01-03": 300.0, "2026-01-08": 315.0},
        )

    def test_every_date_after_the_first_sums_the_same_accounts(self) -> None:
        # The property behind that number, stated directly: once an account is
        # in the series it is on every later date, so no date is short an
        # account and no chart point is comparing different portfolios.
        series = net_worth_history(
            observations=[
                observation(broker="ally", key="A", as_of="2026-01-01"),
                observation(broker="tsp", key="T", as_of="2026-01-01"),
                observation(broker="ally", key="A", as_of="2026-01-05"),
                observation(broker="tsp", key="T", as_of="2026-01-09"),
            ]
        )

        counted: set[int] = {
            len(on(series=series, date=date)) for date in totals(series=series)
        }

        self.assertEqual(counted, {2})

    def test_two_brokers_sharing_an_account_key_stay_two_accounts(self) -> None:
        # Identity is per-broker: account_key is unique inside one database and
        # means nothing outside it. Merging on the key alone would fold two real
        # accounts into one series and halve the portfolio.
        series = net_worth_history(
            observations=[
                observation(broker="ally", key="Invest", value=10.0),
                observation(broker="fidelity", key="Invest", value=20.0),
            ]
        )

        self.assertEqual(len(series), 2)
        self.assertEqual(totals(series=series), {"2026-01-01": 30.0})


class CarriedValuesSaySoTests(unittest.TestCase):
    """A number that was not read today has to admit it."""

    def test_a_carried_row_is_marked_carried_and_keeps_its_own_date(self) -> None:
        series = net_worth_history(
            observations=[
                observation(broker="ally", key="A", value=200.0, as_of="2026-01-01"),
                observation(broker="tsp", key="T", value=100.0, as_of="2026-01-03"),
            ]
        )

        carried = on(series=series, date="2026-01-03")[0]

        self.assertEqual(carried.account_key, "A")
        self.assertEqual(carried.basis, CARRIED)
        self.assertEqual(carried.date, "2026-01-03")

        # And it says how far the carry reached, which is the difference between
        # crossing a weekend and crossing a quarter.
        self.assertEqual(carried.observed_on, "2026-01-01")

    def test_an_observed_row_is_marked_observed_and_dates_agree(self) -> None:
        series = net_worth_history(observations=[observation(as_of="2026-01-01")])

        self.assertEqual(series[0].basis, OBSERVED)
        self.assertEqual(series[0].observed_on, series[0].date)

    def test_every_row_says_one_or_the_other(self) -> None:
        # Never blank. A blank cell means "the source said nothing" everywhere
        # else in this contract, and this column is computed rather than
        # reported -- so it always has an answer.
        series = net_worth_history(
            observations=[
                observation(broker="ally", key="A", as_of="2026-01-01"),
                observation(broker="tsp", key="T", as_of="2026-01-04"),
            ]
        )

        self.assertTrue(series)
        self.assertTrue(all(row.basis in {OBSERVED, CARRIED} for row in series))


class HorizonTests(unittest.TestCase):
    """How far a carry may reach before the account drops out instead."""

    def test_a_gap_inside_the_horizon_is_carried(self) -> None:
        series = net_worth_history(
            observations=[
                observation(broker="ally", key="A", value=200.0, as_of="2026-01-01"),
                observation(broker="tsp", key="T", value=100.0, as_of="2026-01-20"),
            ]
        )

        self.assertEqual(totals(series=series)["2026-01-20"], 300.0)

    def test_a_gap_past_the_horizon_drops_the_account_out(self) -> None:
        # Nineteen days on from an account last read on the 1st is still that
        # account; a year on is a stale number wearing today's date. The line
        # is CARRY_DAYS, and past it the account leaves the series rather than
        # persisting -- so the total gets smaller rather than staying wrong.
        series = net_worth_history(
            observations=[
                observation(broker="ally", key="A", value=200.0, as_of="2026-01-01"),
                observation(broker="tsp", key="T", value=100.0, as_of="2026-06-01"),
            ]
        )

        self.assertEqual(totals(series=series)["2026-06-01"], 100.0)
        self.assertEqual([row.account_key for row in on(series, "2026-06-01")], ["T"])

    def test_the_horizon_is_exactly_carry_days_and_inclusive(self) -> None:
        # Pinned rather than left to arithmetic: an off-by-one here silently
        # changes which accounts are in a total.
        edge = net_worth_history(
            observations=[
                observation(broker="ally", key="A", as_of="2026-01-01"),
                observation(broker="tsp", key="T", as_of="2026-01-31"),
            ]
        )
        past = net_worth_history(
            observations=[
                observation(broker="ally", key="A", as_of="2026-01-01"),
                observation(broker="tsp", key="T", as_of="2026-02-01"),
            ]
        )

        self.assertEqual(CARRY_DAYS, 30)
        self.assertEqual(len(on(series=edge, date="2026-01-31")), 2)
        self.assertEqual(len(on(series=past, date="2026-02-01")), 1)

    def test_the_horizon_is_not_the_dashboards_week(self) -> None:
        # STALE_DAYS is seven and answers "should a human look at this". This
        # answers "may this still be counted", and seven is wrong for it: Ally
        # routinely goes longer than a week, so a week-long horizon would drop a
        # live account and restore it a run later -- the collapse this shape
        # exists to prevent, reintroduced by the fix for it.
        series = net_worth_history(
            observations=[
                observation(broker="ally", key="A", value=200.0, as_of="2026-01-01"),
                observation(broker="tsp", key="T", value=100.0, as_of="2026-01-12"),
            ]
        )

        self.assertEqual(totals(series=series)["2026-01-12"], 300.0)


class AbsentIsNotZeroTests(unittest.TestCase):
    """An account that did not exist yet, and one that reported no number."""

    def test_an_account_gets_no_row_before_its_first_reading(self) -> None:
        # Not a zero row. Zero and absent are different, and an account opened
        # in March did not spend February being worth nothing.
        series = net_worth_history(
            observations=[
                observation(broker="ally", key="A", value=200.0, as_of="2026-01-01"),
                observation(broker="tsp", key="T", value=100.0, as_of="2026-03-01"),
            ]
        )

        self.assertEqual([row.account_key for row in on(series, "2026-01-01")], ["A"])
        self.assertEqual(totals(series=series)["2026-01-01"], 200.0)

    def test_a_snapshot_with_no_value_does_not_become_a_carried_value(self) -> None:
        # A NULL value is the source declining to say, which is not a reading.
        # It cannot be carried, and it must not reset a carry that is running:
        # the account keeps the last number anything actually knew.
        series = net_worth_history(
            observations=[
                observation(broker="ally", key="A", value=200.0, as_of="2026-01-01"),
                observation(broker="ally", key="A", value=None, as_of="2026-01-05"),
                observation(broker="tsp", key="T", value=100.0, as_of="2026-01-05"),
            ]
        )

        carried = [row for row in on(series, "2026-01-05") if row.account_key == "A"]

        self.assertEqual([row.value for row in carried], [200.0])
        self.assertEqual(carried[0].observed_on, "2026-01-01")

    def test_a_date_whose_only_event_was_a_silence_is_not_a_point(self) -> None:
        # A point on which every account is carried is a chart of nothing,
        # drawn to look like a chart of something.
        series = net_worth_history(
            observations=[
                observation(value=100.0, as_of="2026-01-01"),
                observation(value=None, as_of="2026-01-05"),
            ]
        )

        self.assertEqual(sorted(totals(series=series)), ["2026-01-01"])

    def test_an_account_that_only_ever_reported_nothing_is_absent(self) -> None:
        series = net_worth_history(
            observations=[
                observation(broker="ally", key="A", value=None, as_of="2026-01-01"),
                observation(broker="tsp", key="T", value=100.0, as_of="2026-01-01"),
            ]
        )

        self.assertEqual([row.account_key for row in series], ["T"])

    def test_no_observations_at_all_is_an_empty_series(self) -> None:
        self.assertEqual(net_worth_history(observations=[]), [])


class DateTests(unittest.TestCase):
    """Which date a snapshot is evidence about."""

    def test_the_sources_own_date_wins_over_the_run_clock(self) -> None:
        # The distinction "As Of" and "Scraped At" already settle. A value read
        # on the 5th that the source says is for the 1st belongs on the 1st.
        series = net_worth_history(
            observations=[
                observation(as_of="2026-01-01", scraped_at="2026-01-05 09:00:00")
            ]
        )

        self.assertEqual(series[0].date, "2026-01-01")
        self.assertEqual(series[0].as_of, "2026-01-01")
        self.assertEqual(series[0].scraped_at, "2026-01-05 09:00:00")

    def test_a_source_that_gave_no_date_falls_back_to_the_run(self) -> None:
        series = net_worth_history(
            observations=[observation(as_of=None, scraped_at="2026-01-05 09:00:00")]
        )

        self.assertEqual(series[0].date, "2026-01-05")

        # And the fallback is visible: "Observed On" has a date because it must,
        # while "As Of" stays empty because the source really did say nothing.
        self.assertEqual(series[0].observed_on, "2026-01-05")
        self.assertIsNone(series[0].as_of)

    def test_an_unreadable_as_of_costs_its_date_not_its_row(self) -> None:
        # _iso keeps text it could not parse, deliberately. A series cannot
        # place a point on "whenever" -- and sorted as text it would land above
        # every real date -- so the row falls back to the run's date rather than
        # being dropped. The value was observed; just not on a day anyone can name.
        series = net_worth_history(
            observations=[
                observation(as_of="whenever", scraped_at="2026-01-05 09:00:00")
            ]
        )

        self.assertEqual(series[0].date, "2026-01-05")
        self.assertEqual(series[0].as_of, "whenever")

    def test_a_source_date_in_another_format_is_read_not_guessed_at(self) -> None:
        # The 529 scraper stores "12/30/2025". Two formats in one column sort
        # wrong, which is why the view normalizes on the way out.
        series = net_worth_history(
            observations=[
                observation(as_of="12/30/2025", scraped_at="2026-01-05 09:00:00")
            ]
        )

        self.assertEqual(series[0].date, "2025-12-30")

    def test_the_last_reading_of_a_day_is_the_one_that_counts(self) -> None:
        # Two runs on one date is ordinary -- a failed scrape followed by a
        # successful one. The later reading wins, which is the rule
        # get_current_accounts already applies across all dates.
        series = net_worth_history(
            observations=[
                observation(value=100.0, as_of="2026-01-01"),
                observation(value=150.0, as_of="2026-01-01"),
            ]
        )

        self.assertEqual([row.value for row in series], [150.0])


class CurrencyTests(unittest.TestCase):
    """Nothing here knows a rate, and nothing here pretends to."""

    def test_each_row_carries_the_currency_of_the_reading_it_carries(self) -> None:
        series = net_worth_history(
            observations=[
                observation(broker="ally", key="A", value=200.0, currency="CAD"),
                observation(broker="tsp", key="T", value=100.0, currency="USD"),
            ]
        )

        self.assertEqual(
            {row.account_key: row.currency for row in series},
            {"A": "CAD", "T": "USD"},
        )

    def test_a_carry_does_not_convert_anything(self) -> None:
        series = net_worth_history(
            observations=[
                observation(
                    broker="ally",
                    key="A",
                    value=200.0,
                    currency="CAD",
                    as_of="2026-01-01",
                ),
                observation(broker="tsp", key="T", value=100.0, as_of="2026-01-03"),
            ]
        )

        carried = [row for row in on(series, "2026-01-03") if row.account_key == "A"]

        self.assertEqual(carried[0].currency, "CAD")
        self.assertEqual(carried[0].value, 200.0)


class OrderTests(unittest.TestCase):
    """A series is read in the direction it was lived."""

    def test_rows_group_by_account_and_run_forward_in_time(self) -> None:
        # Not newest-first like Transactions. That one is a log, where the last
        # thing that happened is what you came to read.
        series = net_worth_history(
            observations=[
                observation(broker="tsp", key="T", as_of="2026-01-05"),
                observation(broker="ally", key="A", as_of="2026-01-01"),
            ]
        )

        self.assertEqual(
            [(row.account_key, row.date) for row in series],
            [
                ("A", "2026-01-01"),
                ("A", "2026-01-05"),
                ("T", "2026-01-05"),
            ],
        )

    def test_an_account_renamed_mid_history_stays_one_block(self) -> None:
        # Every row carries the display name of the reading it carries, and a
        # display name is explicitly not identity -- it changes. Ordering the
        # finished rows on it puts a renamed account in two blocks of the tab,
        # each internally in order and neither one the account, with its series
        # apparently starting twice. So the order is decided once per account,
        # on the name it goes by now.
        series = net_worth_history(
            observations=[
                observation(broker="ally", key="A", account="Zed", as_of="2026-01-01"),
                observation(
                    broker="ally", key="A", account="Aardvark", as_of="2026-01-05"
                ),
                observation(broker="tsp", key="M", account="Middle"),
            ]
        )

        self.assertEqual(
            [(row.account_key, row.date) for row in series],
            [
                ("A", "2026-01-01"),
                ("A", "2026-01-05"),
                ("M", "2026-01-01"),
                ("M", "2026-01-05"),
            ],
        )

        # And the block sorts by the name it goes by now, not the one it had:
        # "Aardvark" is where a reader looks for it today.
        self.assertEqual([row.account for row in series][:2], ["Zed", "Aardvark"])

    def test_two_accounts_displaying_the_same_still_order_deterministically(
        self,
    ) -> None:
        # Identity breaks the tie, so the tab does not depend on which broker
        # happened to be read first.
        one = net_worth_history(
            observations=[
                observation(broker="ally", key="B", account="Invest"),
                observation(broker="fidelity", key="A", account="Invest"),
            ]
        )
        other = net_worth_history(
            observations=[
                observation(broker="fidelity", key="A", account="Invest"),
                observation(broker="ally", key="B", account="Invest"),
            ]
        )

        self.assertEqual(
            [(row.broker, row.account_key) for row in one],
            [(row.broker, row.account_key) for row in other],
        )


if __name__ == "__main__":
    unittest.main()
