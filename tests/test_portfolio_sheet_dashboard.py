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

from etc.portfolio import (
    ACCOUNT_COLUMNS,
    HOLDING_COLUMNS,
    ISO_DATE_PATTERN,
    AccountRow,
    HoldingRow,
    Portfolio,
)
from etc.portfolio_sheet import (
    ALLOCATION_WIDTH,
    BANNER,
    BANNER_CELL,
    BY_BROKER_COL,
    BY_KIND_COL,
    BY_POSITION_COL,
    BY_SOURCE_COL,
    DASHBOARD_MIN_ROWS,
    FIRST_DATA_ROW,
    HEADER_ROW,
    STALE_DAYS,
    STALENESS_COL,
    SUMMARY_COL,
    SUMMARY_LABELS,
    UNREADABLE_COL,
    _block_updates,
    column_index,
    column_letter,
    column_of,
    dashboard_cells,
    summary_cell,
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

    def test_the_newest_movement_only_considers_things_shaped_like_dates(
        self,
    ) -> None:
        # The one summary cell that cannot filter on <>"". Processed On keeps a
        # date it could not parse, on purpose, and sorted as text a single
        # "whenever" outranks every real date and is reported as the latest
        # movement. The two scrape cells above are exempt: StonkSmith writes
        # those itself and they are always timestamps.
        newest: str = self.by_range["B14"][0][0]

        self.assertIn("REGEXMATCH(", newest)
        self.assertIn(ISO_DATE_PATTERN, newest)
        self.assertNotIn('Transactions!$L$3:$L<>""', newest)

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

    def test_the_grid_is_wide_enough_for_the_allocation_blocks(self) -> None:
        # The blocks are written ranges, not spilled arrays, so a grid too
        # narrow does not refuse them -- it drops the columns off the end and
        # leaves a breakdown with no numbers beside its names.
        tab = self._tab()

        # As wide as the dashboard needed before the blocks existed, so the
        # growth this asserts is exactly the room they take.
        tab.col_count = column_index(letter=UNREADABLE_COL) + 1

        write_dashboard(worksheet=tab, portfolio=allocating(), today=TODAY)

        tab.add_cols.assert_called_once_with(
            column_index(letter=BY_POSITION_COL) + ALLOCATION_WIDTH - 1 - tab.col_count
        )

    def test_a_long_position_list_makes_the_grid_taller(self) -> None:
        # One row per distinct symbol, plus cash, plus the check row. Counted
        # for the same reason the accounts are: a breakdown truncated to fit
        # still looks like a breakdown, which is worse than one that refuses.
        many = tuple(
            HoldingRow(
                broker="tsp",
                source="tsp",
                account="C Fund",
                account_key="c",
                symbol=f"S{n}",
                value=1.0,
            )
            for n in range(60)
        )
        tab = self._tab()
        tab.row_count = 40

        write_dashboard(
            worksheet=tab,
            portfolio=portfolio(
                accounts=(
                    AccountRow(
                        broker="tsp",
                        source="tsp",
                        account="C Fund",
                        account_key="c",
                        value=100.0,
                    ),
                ),
                holdings=many,
            ),
            today=TODAY,
        )

        # 60 symbols + cash + "Slices sum to", below the header row.
        tab.add_rows.assert_called_once_with(HEADER_ROW + 62 - 40)


def allocating(**overrides: Any) -> Portfolio:
    """
    A portfolio holding cash: 1600 in balances, 1100 of it in positions.
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
                kind="INVESTMENT",
                value=1000.0,
            ),
            AccountRow(
                broker="schwab529plan",
                source="Schwab",
                account="Plan",
                account_key="p",
                kind="529",
                value=500.0,
            ),
            AccountRow(
                broker="snaptrade",
                source="Ally",
                account="Loose",
                account_key="l",
                value=100.0,
            ),
        ),
        "holdings": (
            HoldingRow(
                broker="tsp",
                source="tsp",
                account="C Fund",
                account_key="c",
                symbol="C",
                value=700.0,
            ),
            HoldingRow(
                broker="schwab529plan",
                source="Schwab",
                account="Plan",
                account_key="p",
                symbol="",
                value=400.0,
            ),
        ),
        "brokers_read": ("schwab529plan", "snaptrade", "tsp"),
    }
    base.update(overrides)

    return Portfolio(**base)


class AllocationTests(unittest.TestCase):
    """
    The breakdown, and the cash it has to account for.

    Holdings do not sum to the portfolio: uninvested money sits in a balance and
    in no position. A share computed over the holdings subtotal therefore leaves
    the cash out silently, overstates every slice, and still adds to 100% -- the
    failure this project keeps finding, where the run reported success because
    from its side nothing went wrong. These tests pin the base the shares divide
    by, the slice that names the cash, and what happens when the gap goes the
    way it cannot.
    """

    def setUp(self) -> None:
        formulas, literals = dashboard_cells(portfolio=allocating(), today=TODAY)
        self.formulas = cells(updates=formulas)
        self.literals = cells(updates=literals)

    def _column(self, block: str, offset: int) -> str:
        """
        A block's nth column letter.
        :param block: The block's start column
        :param offset: 0 for names, 1 for values, 2 for shares
        :return: The column letter
        :rtype: str
        """

        return column_letter(index=column_index(letter=block) + offset)

    def _cells(self, block: str, offset: int) -> list[Any]:
        """
        Every cell in one of a block's columns, header excluded.
        :param block: The block's start column
        :param offset: 0 for names, 1 for values, 2 for shares
        :return: The column's cells, top to bottom
        :rtype: list[Any]
        """

        letter: str = self._column(block=block, offset=offset)
        written: dict[str, Any] = {**self.formulas, **self.literals}

        for name, values in written.items():
            if name.startswith(f"{letter}{FIRST_DATA_ROW}:"):
                return [row[0] for row in values]

        raise AssertionError(f"nothing written down column {letter}")

    def test_shares_divide_by_the_portfolio_not_by_the_holdings_subtotal(
        self,
    ) -> None:
        # The whole point. Holdings total is 1100 of a 1600 portfolio; dividing
        # by it would render a 31%-cash portfolio as fully invested, with every
        # slice overstated and the numbers still adding to 100%.
        labels = [row[0] for row in self.literals["A3:A14"]]
        total: str = f"B{labels.index('Total (USD)') + FIRST_DATA_ROW}"
        held: str = f"B{labels.index('Holdings total (USD)') + FIRST_DATA_ROW}"

        # Every slice, but not the check row below them, which sums the column.
        for share in self._cells(block=BY_POSITION_COL, offset=2)[:-1]:
            self.assertIn(total, share)
            self.assertNotIn(held, share)

    def test_the_base_the_shares_are_of_is_written_in_the_header(self) -> None:
        # Stated, not inferred. A percentage whose base is unnamed is the thing
        # that made the untrustworthy version look correct.
        for block in (BY_KIND_COL, BY_POSITION_COL):
            right: str = self._column(block=block, offset=ALLOCATION_WIDTH - 1)
            header = self.literals[f"{block}{HEADER_ROW}:{right}{HEADER_ROW}"][0]

            self.assertEqual(header[1:], ["Value (USD)", "Share of total (USD)"])

    def test_cash_is_a_named_slice_of_the_position_breakdown(self) -> None:
        names = self._cells(block=BY_POSITION_COL, offset=0)

        self.assertIn("Cash and uninvested", names)

    def test_the_cash_slice_is_the_gap_the_summary_already_publishes(self) -> None:
        # Pointed at, not recomputed. A second subtraction could drift from the
        # first, and two cells on one tab disagreeing about how much cash there
        # is would be worse than not drawing the slice.
        labels = [row[0] for row in self.literals["A3:A14"]]
        gap: int = labels.index("In accounts, not in positions") + FIRST_DATA_ROW
        names = self._cells(block=BY_POSITION_COL, offset=0)
        values = self._cells(block=BY_POSITION_COL, offset=1)

        self.assertEqual(values[names.index("Cash and uninvested")], f"=B{gap}")

    def test_that_reference_follows_the_label_rather_than_a_typed_row(self) -> None:
        # summary_cell derives it from SUMMARY_LABELS, so a reordered summary
        # moves the reference instead of leaving it pointing at a stale row and
        # still producing a number.
        gap: int = list(SUMMARY_LABELS).index("In accounts, not in positions")

        self.assertEqual(
            summary_cell(label="In accounts, not in positions"),
            f"B{gap + FIRST_DATA_ROW}",
        )

    def test_no_allocation_formula_types_a_column_letter(self) -> None:
        # The module's standing rule. A formula addressing a column by position
        # is repointed at its neighbour by any insertion, so every letter here
        # has to come from the contract tuples.
        kind: str = column_of(columns=ACCOUNT_COLUMNS, name="Kind")
        value: str = column_of(columns=ACCOUNT_COLUMNS, name="Value")
        currency: str = column_of(columns=ACCOUNT_COLUMNS, name="Currency")

        self.assertEqual(
            self._cells(block=BY_KIND_COL, offset=1)[0],
            f"=SUMIFS(Accounts!${value}$3:${value},Accounts!${kind}$3:${kind},"
            f'"INVESTMENT",Accounts!${currency}$3:${currency},"USD")',
        )

        symbol: str = column_of(columns=HOLDING_COLUMNS, name="Symbol")
        held: str = column_of(columns=HOLDING_COLUMNS, name="Value")
        held_currency: str = column_of(columns=HOLDING_COLUMNS, name="Currency")

        self.assertEqual(
            self._cells(block=BY_POSITION_COL, offset=1)[0],
            f"=SUMIFS(Holdings!${held}$3:${held},Holdings!${symbol}$3:${symbol},"
            f'"C",Holdings!${held_currency}$3:${held_currency},"USD")',
        )

    def test_account_kinds_add_up_to_the_whole_portfolio(self) -> None:
        # Balances include the cash, so this block has no gap to name. That is
        # what makes account kind the honest breakdown to build first: it needs
        # no data this project does not already have.
        names = self._cells(block=BY_KIND_COL, offset=0)

        self.assertEqual(names, ["INVESTMENT", "529", "(no kind)", "Slices sum to"])

    def test_a_slice_the_source_did_not_name_is_stated_not_dropped(self) -> None:
        # A position with no ticker is still money. Omitting it is how a set of
        # shares stops adding up while every row on screen still looks right.
        self.assertIn("(no kind)", self._cells(block=BY_KIND_COL, offset=0))
        self.assertIn("(no symbol)", self._cells(block=BY_POSITION_COL, offset=0))

    def test_the_unnamed_slice_matches_the_empty_cell_it_was_written_as(
        self,
    ) -> None:
        # The label is for the reader; the criterion has to be what _cell wrote,
        # which for a missing symbol is the empty string.
        names = self._cells(block=BY_POSITION_COL, offset=0)
        values = self._cells(block=BY_POSITION_COL, offset=1)

        self.assertIn('""', values[names.index("(no symbol)")])
        self.assertNotIn("(no symbol)", values[names.index("(no symbol)")])

    def test_each_block_closes_with_what_its_slices_actually_add_to(self) -> None:
        # The sheet's own arithmetic over the cells it wrote, beside Python's
        # over the databases. A share sum that is not 1 is a wrong base, and
        # this is where it says so without anybody adding a column up by hand.
        for block in (BY_KIND_COL, BY_POSITION_COL):
            names = self._cells(block=block, offset=0)
            shares = self._cells(block=block, offset=2)
            last: int = FIRST_DATA_ROW + len(names) - 2
            letter: str = self._column(block=block, offset=2)

            self.assertEqual(names[-1], "Slices sum to")
            self.assertEqual(
                shares[-1], f"=SUM({letter}{FIRST_DATA_ROW}:{letter}{last})"
            )

    def test_a_negative_gap_refuses_to_draw_rather_than_rendering(self) -> None:
        # A negative gap means a position is counted twice, and the slice it
        # implies cannot exist -- a negative wedge, with every other share
        # overstated to make room for it.
        doubled = allocating(
            holdings=(
                HoldingRow(
                    broker="tsp",
                    source="tsp",
                    account="C Fund",
                    account_key="c",
                    symbol="C",
                    value=2000.0,
                ),
            )
        )
        formulas, literals = dashboard_cells(portfolio=doubled, today=TODAY)
        self.formulas, self.literals = cells(updates=formulas), cells(updates=literals)

        self.assertEqual(
            self._cells(block=BY_POSITION_COL, offset=0), ["Allocation not drawn"]
        )
        self.assertIn("400.00", self._cells(block=BY_POSITION_COL, offset=1)[0])

    def test_the_refusal_is_stated_rather_than_left_blank(self) -> None:
        # An empty region is indistinguishable from a write that failed, which
        # is the same reason the unreadable panel says "everything read".
        doubled = allocating(
            holdings=(
                HoldingRow(
                    broker="tsp",
                    source="tsp",
                    account="C Fund",
                    account_key="c",
                    symbol="C",
                    value=2000.0,
                ),
            )
        )
        formulas, literals = dashboard_cells(portfolio=doubled, today=TODAY)
        self.formulas, self.literals = cells(updates=formulas), cells(updates=literals)
        said: str = self._cells(block=BY_POSITION_COL, offset=1)[0]

        self.assertIn("counted twice", said)
        self.assertFalse(said.startswith("="))

        # And the kind block, which cannot have the problem, still draws.
        self.assertIn("INVESTMENT", self._cells(block=BY_KIND_COL, offset=0))

    def test_float_noise_is_not_mistaken_for_double_counting(self) -> None:
        # 0.1 + 0.2 - 0.3 is -5.5e-17. Refusing on that would replace a correct
        # breakdown with an accusation.
        noisy = allocating(
            accounts=(
                AccountRow(
                    broker="tsp",
                    source="tsp",
                    account="C Fund",
                    account_key="c",
                    value=0.1 + 0.2,
                ),
            ),
            holdings=(
                HoldingRow(
                    broker="tsp",
                    source="tsp",
                    account="C Fund",
                    account_key="c",
                    symbol="C",
                    value=0.3,
                ),
            ),
        )
        formulas, literals = dashboard_cells(portfolio=noisy, today=TODAY)
        self.formulas, self.literals = cells(updates=formulas), cells(updates=literals)

        self.assertIn(
            "Cash and uninvested", self._cells(block=BY_POSITION_COL, offset=0)
        )

    def test_a_slice_named_with_a_quote_cannot_break_out_of_its_criterion(
        self,
    ) -> None:
        # Slice names come from brokers, not from this module.
        quoted = allocating(
            holdings=(
                HoldingRow(
                    broker="tsp",
                    source="tsp",
                    account="C Fund",
                    account_key="c",
                    symbol='A"B',
                    value=100.0,
                ),
            )
        )
        formulas, literals = dashboard_cells(portfolio=quoted, today=TODAY)
        self.formulas, self.literals = cells(updates=formulas), cells(updates=literals)

        self.assertIn('"A""B"', self._cells(block=BY_POSITION_COL, offset=1)[0])

    def test_another_currency_is_left_out_rather_than_added_at_no_rate(
        self,
    ) -> None:
        # Portfolio.total refuses to add a dollar to a euro, and the summary's
        # "Other currencies present" is what names the omission. A breakdown
        # that folded them in would be doing quietly what the code declines to
        # do loudly.
        mixed = allocating(
            holdings=(
                HoldingRow(
                    broker="tsp",
                    source="tsp",
                    account="C Fund",
                    account_key="c",
                    symbol="EUR",
                    value=900.0,
                    currency="EUR",
                ),
                HoldingRow(
                    broker="tsp",
                    source="tsp",
                    account="C Fund",
                    account_key="c",
                    symbol="C",
                    value=100.0,
                ),
            )
        )
        formulas, literals = dashboard_cells(portfolio=mixed, today=TODAY)
        self.formulas, self.literals = cells(updates=formulas), cells(updates=literals)
        names = self._cells(block=BY_POSITION_COL, offset=0)

        self.assertNotIn("EUR", names)
        self.assertIn("C", names)

    def test_slices_are_ordered_largest_first(self) -> None:
        names = self._cells(block=BY_KIND_COL, offset=0)

        self.assertEqual(names.index("INVESTMENT"), 0)
        self.assertLess(names.index("529"), names.index("(no kind)"))

    def test_the_blocks_do_not_land_on_top_of_the_bands(self) -> None:
        # A QUERY that would spill into an occupied cell returns #REF! and shows
        # nothing at all, so nothing may be written into a band's path.
        starts = [
            SUMMARY_COL,
            BY_BROKER_COL,
            BY_SOURCE_COL,
            STALENESS_COL,
            UNREADABLE_COL,
            BY_KIND_COL,
            BY_POSITION_COL,
        ]
        self.assertEqual(len(set(starts)), len(starts))
        self.assertGreater(
            column_index(letter=BY_KIND_COL), column_index(letter=UNREADABLE_COL) + 1
        )
        self.assertGreaterEqual(
            column_index(letter=BY_POSITION_COL),
            column_index(letter=BY_KIND_COL) + ALLOCATION_WIDTH,
        )

    def test_the_names_go_up_raw_and_the_numbers_as_formulas(self) -> None:
        # A fund whose name begins with "=" stays a name instead of becoming a
        # formula the spreadsheet runs; a SUMIFS that went up raw would land as
        # the literal text of itself.
        block: str = BY_POSITION_COL

        # Two positions, cash, and the check row.
        bottom: int = FIRST_DATA_ROW + 3
        names: str = self._column(block=block, offset=0)
        values: str = self._column(block=block, offset=1)

        self.assertIn(f"{names}{FIRST_DATA_ROW}:{names}{bottom}", self.literals)
        self.assertIn(f"{values}{FIRST_DATA_ROW}:{values}{bottom}", self.formulas)

    def test_a_fund_named_like_a_formula_is_not_run(self) -> None:
        # The module docstring's whole reason for going up RAW, exercised on the
        # one column here that carries text a broker chose. A name is a name
        # even when it is spelled "=IMPORTXML(...)".
        hostile: str = '=IMPORTXML("http://example.invalid","//a")'
        formulas, literals = dashboard_cells(
            portfolio=allocating(
                holdings=(
                    HoldingRow(
                        broker="tsp",
                        source="tsp",
                        account="C Fund",
                        account_key="c",
                        symbol=hostile,
                        value=100.0,
                    ),
                )
            ),
            today=TODAY,
        )
        self.formulas, self.literals = cells(updates=formulas), cells(updates=literals)

        self.assertIn(hostile, self._cells(block=BY_POSITION_COL, offset=0))

        # In the batch that goes up RAW, and in no cell of the one that does not.
        names: str = self._column(block=BY_POSITION_COL, offset=0)
        self.assertTrue(
            any(name.startswith(names) for name in self.literals),
            "the name column did not go up as a literal",
        )
        for values in self.formulas.values():
            for row in values:
                self.assertNotIn(hostile, row)

    def test_the_name_column_is_literal_by_rule_and_not_by_inspection(
        self,
    ) -> None:
        # Asked of _block_updates directly, because dashboard_cells cannot
        # currently produce this grid: every block ends with a "Slices sum to"
        # row, so the name column is never all-formula and an inspection-based
        # split lands it in the literal batch by luck. That is a coincidence of
        # the present layout, not a property of it -- a block that lost its
        # check row would start executing scraped text. So the rule is pinned
        # where it lives.
        grid: list[list[Any]] = [
            ["Position", "Value (USD)", "Share of total (USD)"],
            ['=IMPORTXML("http://example.invalid","//a")', "=SUMIFS(x)", "=A1/B1"],
        ]
        formulas, literals = _block_updates(start=BY_POSITION_COL, grid=grid)

        self.assertEqual(
            cells(updates=literals)[
                f"{BY_POSITION_COL}{FIRST_DATA_ROW}:{BY_POSITION_COL}{FIRST_DATA_ROW}"
            ],
            [['=IMPORTXML("http://example.invalid","//a")']],
        )
        for values in cells(updates=formulas).values():
            for row in values:
                self.assertNotIn('=IMPORTXML("http://example.invalid","//a")', row)

    def test_a_name_is_grouped_exactly_as_it_was_written_to_the_tab(self) -> None:
        # etc.portfolio._cell writes verbatim, so a criterion that has been
        # tidied no longer matches the cell it is meant to find. "VTI " grouped
        # under "VTI" and searched for as "VTI" adds up to nothing at all, and
        # the row would sit there showing a confident zero.
        spaced = allocating(
            holdings=(
                HoldingRow(
                    broker="tsp",
                    source="tsp",
                    account="C Fund",
                    account_key="c",
                    symbol="VTI ",
                    value=100.0,
                ),
            )
        )
        formulas, literals = dashboard_cells(portfolio=spaced, today=TODAY)
        self.formulas, self.literals = cells(updates=formulas), cells(updates=literals)

        self.assertIn('"VTI "', self._cells(block=BY_POSITION_COL, offset=1)[0])

    def test_two_spellings_of_one_name_stay_two_slices(self) -> None:
        # They are two different strings on the tab. Merging them would leave a
        # criterion that finds one and a row that claims both.
        both = allocating(
            holdings=(
                HoldingRow(
                    broker="tsp",
                    source="tsp",
                    account="C Fund",
                    account_key="c",
                    symbol="VTI",
                    value=100.0,
                ),
                HoldingRow(
                    broker="tsp",
                    source="tsp",
                    account="C Fund",
                    account_key="c",
                    symbol="VTI ",
                    value=50.0,
                ),
            )
        )
        formulas, literals = dashboard_cells(portfolio=both, today=TODAY)
        self.formulas, self.literals = cells(updates=formulas), cells(updates=literals)
        criteria = self._cells(block=BY_POSITION_COL, offset=1)

        self.assertIn('"VTI"', criteria[0])
        self.assertIn('"VTI "', criteria[1])

    def test_a_name_of_nothing_but_spaces_is_still_labelled(self) -> None:
        # Stripped for the label, raw for the criterion. An all-spaces name
        # renders as an empty row, which is what a failed write looks like.
        spaces = allocating(
            holdings=(
                HoldingRow(
                    broker="tsp",
                    source="tsp",
                    account="C Fund",
                    account_key="c",
                    symbol="   ",
                    value=100.0,
                ),
            )
        )
        formulas, literals = dashboard_cells(portfolio=spaces, today=TODAY)
        self.formulas, self.literals = cells(updates=formulas), cells(updates=literals)

        self.assertEqual(self._cells(block=BY_POSITION_COL, offset=0)[0], "(no symbol)")
        self.assertIn('"   "', self._cells(block=BY_POSITION_COL, offset=1)[0])


if __name__ == "__main__":
    unittest.main()
