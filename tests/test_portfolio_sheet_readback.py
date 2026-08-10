"""Reading the tabs back, which is what a successful write cannot do.

write_rows() returning says the request was accepted. It does not say the values
arrived as the kind of thing they were meant to be: money can land as text, a
column can drift, and a date can reach a cell in whatever format its source used,
all through a RAW upload that reports success.

Every case here is checked twice -- once against a tab that is right, and once
against the same tab with one thing wrong. A read-back test that only ever sees a
correct sheet proves that the reader runs, not that it looks.

One check is deliberately missing. An absent date arriving as an empty cell
rather than as an empty string cannot be seen from a read at all: Sheets returns
"" or a short row for both, and only a formula's behaviour over the cell tells
them apart. That one stays an eyeball check.
"""

import unittest
from unittest.mock import MagicMock, patch

from gspread.utils import ValueRenderOption

from etc.portfolio import (
    ACCOUNT_COLUMNS,
    HOLDING_COLUMNS,
    NET_WORTH_COLUMNS,
    TRANSACTION_COLUMNS,
    Portfolio,
)
from etc.portfolio_sheet import (
    ACCOUNTS_TAB,
    BANNER,
    DASHBOARD_TAB,
    HOLDINGS_TAB,
    MACHINE_OWNED_TABS,
    NET_WORTH_TAB,
    TRANSACTIONS_TAB,
    check_tabs,
)
from helpers.sheets import SheetsUnavailable

#: Two movements under one account, newest first, both normalized.
MOVEMENTS: tuple[tuple[str, str], ...] = (
    ("ACC-1", "2026-02-01"),
    ("ACC-1", "2026-01-15"),
)


class Tab:
    """
    A tab that answers reads off a grid, addressed the way the checks address it.

    Ranges arrive as "A2:J2" or "D3:D", so this parses rather than pattern-matches
    on the exact string: a check that changed which columns it asked for would
    otherwise keep passing against a stub keyed on the old range.
    """

    def __init__(self, grid: list[list[object]], first_cell: object = BANNER) -> None:
        self.grid = grid
        self.first_cell = first_cell

    def acell(self, cell: str) -> MagicMock:
        del cell
        return MagicMock(value=self.first_cell)

    def get_values(
        self, range_name: str, value_render_option: str | None = None
    ) -> list[list[object]]:
        # Honoured, not ignored, and this is the point. A formatted read gives
        # display text for every cell, so a check that asked for formatted when it
        # meant unformatted would see "1234.5" and call a good sheet broken. A
        # fake that returned the grid regardless would pass that check and hide
        # it -- which is what the first version of this file did.
        as_text: bool = str(object=value_render_option) == str(
            object=ValueRenderOption.formatted
        )
        start, _, end = range_name.partition(":")
        first_col, first_row = start[0], int(start[1:])
        last_col = end[0] if end else first_col
        last_row = int(end[1:]) if end and end[1:] else len(self.grid)

        rows: list[list[object]] = []

        for number in range(first_row, last_row + 1):
            line = self.grid[number - 1] if number - 1 < len(self.grid) else []
            cells = [
                line[index] if index < len(line) else ""
                for index in range(
                    ord(first_col) - ord("A"), ord(last_col) - ord("A") + 1
                )
            ]

            if as_text:
                cells = ["" if cell == "" else str(object=cell) for cell in cells]

            # Sheets trims trailing empties, and a wholly empty row comes back
            # short. Reproducing that is the point: the checks have to cope.
            while cells and cells[-1] == "":
                cells.pop()

            rows.append(cells)

        while rows and not rows[-1]:
            rows.pop()

        return rows


def accounts_tab(value: object = 1234.5, as_of: str = "2026-02-01") -> Tab:
    return Tab(
        grid=[
            [BANNER],
            list(ACCOUNT_COLUMNS),
            [
                "Ally",
                "ally",
                "Brokerage",
                "ACC-1",
                "brokerage",
                "",
                value,
                "USD",
                as_of,
                "2026-02-02",
            ],
        ]
    )


def holdings_tab() -> Tab:
    return Tab(grid=[[BANNER], list(HOLDING_COLUMNS)])


def transactions_tab(rows: tuple[tuple[str, str], ...] = MOVEMENTS) -> Tab:
    key = list(TRANSACTION_COLUMNS).index("Account Key")
    processed = list(TRANSACTION_COLUMNS).index("Processed On")
    grid: list[list[object]] = [[BANNER], list(TRANSACTION_COLUMNS)]

    for account, date in rows:
        line: list[object] = [""] * len(TRANSACTION_COLUMNS)
        line[key], line[processed] = account, date
        grid.append(line)

    return Tab(grid=grid)


def net_worth_tab() -> Tab:
    return Tab(grid=[[BANNER], list(NET_WORTH_COLUMNS)])


def dashboard_tab(computed: object = 1234.5, as_read: object = 1234.5) -> Tab:
    return Tab(
        grid=[
            [BANNER],
            ["Summary", "Value"],
            ["Total (USD)", computed],
            ["Total as read", as_read],
            ["Accounts", 1],
        ]
    )


def book(**overrides: Tab) -> MagicMock:
    tabs: dict[str, Tab] = {
        ACCOUNTS_TAB: accounts_tab(),
        HOLDINGS_TAB: holdings_tab(),
        TRANSACTIONS_TAB: transactions_tab(),
        NET_WORTH_TAB: net_worth_tab(),
        DASHBOARD_TAB: dashboard_tab(),
    }
    tabs.update(overrides)

    fake = MagicMock()
    fake.worksheet.side_effect = lambda title: tabs[title]

    return fake


def run(fake: MagicMock, movements: int = len(MOVEMENTS)) -> dict[str, bool]:
    """
    Run the read-back over a fake book and return each case by name.
    :param fake: The fake spreadsheet
    :param movements: How many movements the databases are said to hold
    :return: Case name to whether it passed
    :rtype: dict[str, bool]
    """

    transactions = tuple(MagicMock() for _ in range(movements))

    with patch(
        "etc.portfolio_sheet.read_workspace",
        return_value=Portfolio(transactions=transactions),
    ):
        cases = check_tabs(book=fake)

    return {case.name: case.passed for case in cases}


class ReadBackTests(unittest.TestCase):
    def test_a_correct_sheet_passes_every_check(self) -> None:
        self.assertTrue(all(run(fake=book()).values()), run(fake=book()))

    def test_every_tab_is_read_including_the_one_without_columns(self) -> None:
        fake = book()
        run(fake=fake)

        asked = {call.args[0] for call in fake.worksheet.call_args_list}

        self.assertEqual(asked, set(MACHINE_OWNED_TABS))

    def test_a_missing_banner_is_named_by_tab(self) -> None:
        stripped = holdings_tab()
        stripped.first_cell = ""

        cases = run(fake=book(Holdings=stripped))
        banner = [name for name in cases if "banner" in name]

        self.assertFalse(cases[banner[0]])

    def test_a_drifted_column_fails_the_contract(self) -> None:
        wrong = list(HOLDING_COLUMNS)
        wrong[3], wrong[4] = wrong[4], wrong[3]
        drifted = Tab(grid=[[BANNER], wrong])

        cases = run(fake=book(Holdings=drifted))
        contract = [name for name in cases if name.startswith(HOLDINGS_TAB)]

        self.assertFalse(cases[contract[0]])

    def test_a_short_movement_count_is_caught(self) -> None:
        # The tab has two rows; the databases are said to hold three.
        cases = run(fake=book(), movements=3)
        count = [name for name in cases if "movements" in name]

        self.assertFalse(cases[count[0]])

    def test_a_date_in_the_source_format_is_caught(self) -> None:
        # The 529 scraper's "12/30/2025" reaching a cell means normalization was
        # skipped -- and it sorts above every January, so the order is wrong too.
        odd = transactions_tab(rows=(("ACC-1", "12/30/2025"), ("ACC-1", "2026-01-15")))

        cases = run(fake=book(Transactions=odd))
        iso = [name for name in cases if "YYYY-MM-DD" in name]

        self.assertFalse(cases[iso[0]])

    def test_rows_out_of_order_within_an_account_are_caught(self) -> None:
        backwards = transactions_tab(
            rows=(("ACC-1", "2026-01-15"), ("ACC-1", "2026-02-01"))
        )

        cases = run(fake=book(Transactions=backwards))
        order = [name for name in cases if "newest-first" in name]

        self.assertFalse(cases[order[0]])

    def test_two_accounts_each_sorted_do_not_read_as_unsorted(self) -> None:
        # Ordering is per account, not across the tab: the second account starts
        # over at its own newest, which is not a regression.
        split = transactions_tab(
            rows=(
                ("ACC-1", "2026-02-01"),
                ("ACC-1", "2026-01-15"),
                ("ACC-2", "2026-03-01"),
                ("ACC-2", "2026-02-20"),
            )
        )

        cases = run(fake=book(Transactions=split), movements=4)
        order = [name for name in cases if "newest-first" in name]

        self.assertTrue(cases[order[0]])

    def test_money_as_text_is_caught(self) -> None:
        cases = run(fake=book(Accounts=accounts_tab(value="1234.50")))
        money = [name for name in cases if "not text" in name]

        self.assertFalse(cases[money[0]])

    def test_totals_that_disagree_are_caught(self) -> None:
        cases = run(fake=book(Dashboard=dashboard_tab(as_read=1200.0)))
        totals = [name for name in cases if "two totals" in name]

        self.assertFalse(cases[totals[0]])

    def test_totals_within_a_rounding_of_each_other_agree(self) -> None:
        cases = run(fake=book(Dashboard=dashboard_tab(as_read=1234.499)))
        totals = [name for name in cases if "two totals" in name]

        self.assertTrue(cases[totals[0]])

    def test_a_reordered_summary_is_caught_rather_than_read_off_by_a_row(self) -> None:
        # The totals are found by label, so a summary whose rows moved fails here
        # instead of quietly comparing the wrong two cells.
        moved = Tab(grid=[[BANNER], ["Summary", "Value"], ["Accounts", 1]])

        cases = run(fake=book(Dashboard=moved))
        totals = [name for name in cases if "two totals" in name]

        self.assertFalse(cases[totals[0]])

    def test_the_render_dependent_cases_say_they_are_unconfirmed(self) -> None:
        # Until this has run once against real Sheets, a failure on one of these
        # three is ambiguous between a wrong sheet and a wrong assertion. Saying
        # so is the difference between a finding and a guess.
        cases = run(fake=book())
        marked = [name for name in cases if "unconfirmed" in name]

        self.assertEqual(len(marked), 2)

    def test_a_missing_tab_reports_rather_than_creating_one(self) -> None:
        # Creating it would manufacture the thing being checked.
        fake = book()
        fake.worksheet.side_effect = SheetsUnavailable("has no tab named 'Dashboard'")

        with self.assertRaises(SheetsUnavailable):
            run(fake=fake)

        fake.add_worksheet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
