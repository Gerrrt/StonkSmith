"""The derived view, and the reason append-only is not just a slogan.

A dashboard formula addresses a column by position. That is what makes the
append-only rule load-bearing outside the tests: a column added at the end costs
nothing, and a column inserted in the middle silently repoints every formula at
its neighbour. So none of these formulas contains a typed column letter -- every
one is derived from the contract tuples, and these tests check that the derived
letters and the pinned formulas agree.
"""

import datetime as dt
import unittest
from typing import Any
from unittest.mock import MagicMock

from etc.portfolio import ACCOUNT_COLUMNS, HOLDING_COLUMNS, AccountRow, Portfolio
from etc.portfolio_sheet import (
    BANNER,
    BANNER_CELL,
    BY_BROKER_COL,
    BY_SOURCE_COL,
    DASHBOARD_MIN_ROWS,
    STALE_DAYS,
    STALENESS_COL,
    SUMMARY_COL,
    UNREADABLE_COL,
    column_of,
    dashboard_cells,
    write_dashboard,
)
from helpers.sheets import SheetNotOwned

TODAY = dt.date(2026, 8, 8)


def portfolio(**overrides: Any) -> Portfolio:
    """
    A two-account portfolio, read cleanly.
    :param overrides: Fields to replace
    :return: The portfolio
    :rtype: Portfolio
    """

    base: dict[str, Any] = {
        "accounts": (
            AccountRow(
                broker="tsp",
                source="tsp",
                account="C Fund",
                account_key="c",
                value=1000.0,
                as_of="2026-08-07",
                scraped_at="2026-08-08 09:00:00",
            ),
            AccountRow(
                broker="snaptrade",
                source="Schwab",
                account="IRA",
                account_key="ira",
                value=234.5,
                scraped_at="2026-08-08 09:00:01",
            ),
        ),
        "brokers_read": ("snaptrade", "tsp"),
    }
    base.update(overrides)

    return Portfolio(**base)


def cells(updates: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Flatten a batch_update payload into range -> first value.
    :param updates: What was handed to batch_update
    :return: One entry per range
    :rtype: dict[str, Any]
    """

    return {update["range"]: update["values"] for update in updates}


class FormulaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.formulas, self.literals = dashboard_cells(
            portfolio=portfolio(), today=TODAY
        )
        self.by_range = cells(updates=self.formulas)

    def test_the_total_sums_by_currency_not_over_everything(self) -> None:
        # Portfolio.total refuses to add a dollar to a euro. The sheet must not
        # do quietly what the code declines to do loudly.
        self.assertEqual(
            self.by_range["B3"],
            [['=SUMIF(Accounts!$H$3:$H,"USD",Accounts!$G$3:$G)']],
        )

    def test_accounts_are_counted_on_the_key_not_the_display_name(self) -> None:
        # account_key is written unwrapped and can never be blank; a display
        # name goes through _cell and can. Counting identity cannot undercount.
        self.assertEqual(self.by_range["B5"], [["=COUNTA(Accounts!$D$3:$D)"]])
        self.assertEqual(self.by_range["B6"], [["=COUNTA(Holdings!$D$3:$D)"]])

    def test_the_gap_between_balances_and_positions_is_shown(self) -> None:
        # Uninvested cash sits in a balance and in no position: the reason there
        # are two row shapes at all. Negative means double-counting.
        self.assertEqual(self.by_range["B8"], [["=B3-B7"]])

    def test_that_gap_points_at_its_neighbours_by_label_not_by_row(self) -> None:
        # The one formula that refers to its own tab. Typed, it would keep
        # naming rows 3 and 7 after somebody reordered the summary -- and keep
        # producing a number while doing it. So the labels move it.
        labels = [row[0] for row in cells(updates=self.literals)["A3:A14"]]
        total: int = labels.index("Total (USD)") + 3
        held: int = labels.index("Holdings total (USD)") + 3

        self.assertEqual(self.by_range["B8"], [[f"=B{total}-B{held}"]])

    def test_movements_are_counted_on_the_key_that_cannot_be_blank(self) -> None:
        # Same reasoning as the two counts above: Account Key is written
        # unwrapped, while Type and Description are both routinely empty
        # depending on which source the movement came from.
        self.assertEqual(self.by_range["B13"], [["=COUNTA(Transactions!$D$3:$D)"]])

    def test_the_newest_movement_is_sorted_as_text_not_maxed(self) -> None:
        # Safe only because etc.portfolio normalizes Processed On to ISO on the
        # way out of the database. It is stored as the source wrote it, and the
        # 529 scraper writes "12/30/2025", which sorts above "01/15/2026".
        newest: str = self.by_range["B14"][0][0]

        self.assertIn("Transactions!$L$3:$L", newest)
        self.assertIn("SORT(", newest)
        self.assertNotIn("MAX(", newest)
        self.assertIn(",1,FALSE)", newest)

    def test_scrape_times_are_sorted_as_text_not_maxed(self) -> None:
        # Scraped At is text under RAW, and MAX over text returns 0. The stored
        # format sorts lexicographically exactly as it sorts chronologically.
        newest: str = self.by_range["B10"][0][0]
        self.assertIn("SORT(", newest)
        self.assertNotIn("MAX(", newest)
        self.assertIn(",1,FALSE)", newest)
        self.assertIn(",1,TRUE)", self.by_range["B11"][0][0])

    def test_each_band_starts_in_its_own_column(self) -> None:
        # A QUERY that would spill into an occupied cell returns #REF! and shows
        # nothing at all, so the bands cannot share a column.
        starts = [
            SUMMARY_COL,
            BY_BROKER_COL,
            BY_SOURCE_COL,
            STALENESS_COL,
            UNREADABLE_COL,
        ]
        self.assertEqual(len(set(starts)), len(starts))

    def test_the_query_bands_are_positional_and_match_the_contract(self) -> None:
        by_broker: str = self.by_range[f"{BY_BROKER_COL}2"][0][0]

        self.assertIn("Accounts!$A$3:$J", by_broker)
        self.assertIn("select Col1, sum(Col7)", by_broker)
        self.assertIn("where Col8 = 'USD'", by_broker)
        self.assertIn("group by Col1", by_broker)

        # The point: those Col numbers are the contract's own indices.
        self.assertEqual(list(ACCOUNT_COLUMNS).index("Broker") + 1, 1)
        self.assertEqual(list(ACCOUNT_COLUMNS).index("Value") + 1, 7)
        self.assertEqual(list(ACCOUNT_COLUMNS).index("Currency") + 1, 8)

    def test_the_source_band_groups_on_source(self) -> None:
        by_source: str = self.by_range[f"{BY_SOURCE_COL}2"][0][0]

        self.assertIn("select Col2, sum(Col7)", by_source)
        self.assertEqual(list(ACCOUNT_COLUMNS).index("Source") + 1, 2)

    def test_the_staleness_cutoff_is_baked_and_deterministic(self) -> None:
        # Baked rather than TEXT(TODAY()-7,...) inside a concatenated query, so
        # the formula is pinnable and free of TEXT's locale-dependent format.
        stale: str = self.by_range[f"{STALENESS_COL}2"][0][0]
        cutoff: str = (TODAY - dt.timedelta(days=STALE_DAYS)).isoformat()

        self.assertEqual(cutoff, "2026-08-01")
        self.assertIn(f"Col9 < '{cutoff}'", stale)
        self.assertIn("Col9 is null or", stale)

    def test_every_band_that_can_error_is_wrapped(self) -> None:
        # FILTER and QUERY return #N/A over an empty range; SUMIF and COUNTA
        # return 0. So a workspace with nothing in it renders empty rather than
        # filling the tab with errors, and the wrapping goes exactly where it is
        # needed rather than everywhere.
        formulas, _ = dashboard_cells(portfolio=Portfolio(), today=TODAY)

        for update in formulas:
            formula: str = update["values"][0][0]

            if "FILTER(" in formula or "QUERY(" in formula:
                self.assertIn("IFERROR", formula, formula)

    def test_no_formula_contains_a_typed_column_letter(self) -> None:
        # Every reference comes from column_of, so the letters below are what
        # the contract currently resolves to rather than what someone typed.
        self.assertEqual(column_of(columns=ACCOUNT_COLUMNS, name="Value"), "G")
        self.assertEqual(column_of(columns=ACCOUNT_COLUMNS, name="Currency"), "H")
        self.assertEqual(column_of(columns=HOLDING_COLUMNS, name="Value"), "I")

        for update in self.formulas:
            self.assertTrue(update["values"][0][0].startswith("="))


class LiteralTests(unittest.TestCase):
    def setUp(self) -> None:
        self.formulas, self.literals = dashboard_cells(
            portfolio=portfolio(), today=TODAY
        )
        self.by_range = cells(updates=self.literals)

    def test_the_banner_is_a_literal(self) -> None:
        self.assertEqual(self.by_range[BANNER_CELL], [[BANNER]])

    def test_the_labels_name_every_summary_row(self) -> None:
        labels = [row[0] for row in self.by_range["A3:A14"]]

        self.assertEqual(labels[0], "Total (USD)")
        self.assertEqual(labels[1], "Total as read")
        self.assertEqual(labels[-1], "Newest movement")

    def test_the_total_as_read_is_the_number_python_computed(self) -> None:
        # The cross-check: Python over the databases beside Sheets over the
        # cells. They disagree only if the write was truncated or a row failed
        # to land, which is otherwise invisible.
        self.assertEqual(self.by_range["B4"], [[1234.5]])
        self.assertIsInstance(self.by_range["B4"][0][0], float)

    def test_the_total_as_read_is_not_in_the_formula_batch(self) -> None:
        self.assertNotIn("B4", cells(updates=self.formulas))

    def test_brokers_read_are_named(self) -> None:
        self.assertEqual(self.by_range["B12"], [["snaptrade, tsp"]])

    def test_an_unreadable_broker_appears_with_its_reason(self) -> None:
        # A total short by a whole broker is the failure this project keeps
        # finding. The dashboard is the only place it shows.
        _, literals = dashboard_cells(
            portfolio=portfolio(unreadable=(("ally", "OSError: no such file"),)),
            today=TODAY,
        )
        rows = cells(updates=literals)[f"{UNREADABLE_COL}2:P3"]

        self.assertEqual(rows[0], ["Not read", "Why"])
        self.assertEqual(rows[1], ["ally", "OSError: no such file"])

    def test_reading_everything_is_stated_rather_than_left_blank(self) -> None:
        # An empty region is indistinguishable from a write that failed.
        rows = self.by_range[f"{UNREADABLE_COL}2:P3"]

        self.assertEqual(rows[-1], ["everything read", ""])

    def test_a_failure_reason_is_never_entered_as_a_formula(self) -> None:
        # Exception text beginning with "=" under USER_ENTERED stops being text.
        _, literals = dashboard_cells(
            portfolio=portfolio(unreadable=(("ally", "=broken"),)), today=TODAY
        )

        self.assertNotIn("=broken", str(object=cells(updates=self.formulas)))
        self.assertIn("=broken", str(object=cells(updates=literals)))


class WriteDashboardTests(unittest.TestCase):
    def _tab(self) -> MagicMock:
        tab = MagicMock()
        tab.acell.return_value = MagicMock(value=BANNER)
        tab.row_count = 1000
        tab.col_count = 26
        return tab

    def test_the_two_halves_go_up_with_different_input_options(self) -> None:
        tab = self._tab()

        write_dashboard(worksheet=tab, portfolio=portfolio(), today=TODAY)

        options = [
            call.kwargs["value_input_option"]
            for call in tab.batch_update.call_args_list
        ]
        self.assertEqual(options, ["RAW", "USER_ENTERED"])

    def test_a_small_portfolio_gets_the_floor(self) -> None:
        tab = self._tab()
        tab.row_count = 10

        write_dashboard(worksheet=tab, portfolio=portfolio(), today=TODAY)

        tab.add_rows.assert_called_once_with(DASHBOARD_MIN_ROWS - 10)

    def test_the_grid_grows_with_the_portfolio_not_to_a_fixed_height(self) -> None:
        # The bands spill downward, one row per account. A grid too short does
        # not shorten the band -- Sheets refuses the whole array with #REF!, so
        # the staleness panel disappears exactly when there is most to see. A
        # fixed 40 rows broke silently somewhere past the 38th account.
        many = tuple(
            AccountRow(broker="tsp", source="tsp", account=f"A{n}", account_key=f"a{n}")
            for n in range(60)
        )
        tab = self._tab()
        tab.row_count = 40

        write_dashboard(worksheet=tab, portfolio=portfolio(accounts=many), today=TODAY)

        # Room for the header row plus one result row per account.
        tab.add_rows.assert_called_once_with(62 - 40)

    def test_unreadable_brokers_are_counted_in_the_height_too(self) -> None:
        tab = self._tab()
        tab.row_count = 10

        write_dashboard(
            worksheet=tab,
            portfolio=portfolio(unreadable=tuple((f"b{n}", "boom") for n in range(50))),
            today=TODAY,
        )

        tab.add_rows.assert_called_once_with(52 - 10)

    def test_a_dashboard_that_is_not_ours_is_refused_before_it_is_cleared(self) -> None:
        tab = self._tab()
        tab.acell.return_value = MagicMock(value="my own summary")

        with self.assertRaises(SheetNotOwned):
            write_dashboard(worksheet=tab, portfolio=portfolio(), today=TODAY)

        tab.clear.assert_not_called()
        tab.batch_update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
