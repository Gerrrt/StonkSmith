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

import stonksmith.etc.config as etc_config
from config_isolation import UserConfigMixin
from stonksmith.etc.portfolio import (
    ACCOUNT_COLUMNS,
    HOLDING_COLUMNS,
    NET_WORTH_COLUMNS,
    TRANSACTION_COLUMNS,
    Portfolio,
)
from stonksmith.etc.portfolio_sheet import (
    ACCOUNTS_TAB,
    ALLOCATION_CHECK,
    ALLOCATION_REFUSED,
    BANNER,
    BY_CLASS_COL,
    BY_KIND_COL,
    BY_POSITION_COL,
    DASHBOARD_TAB,
    HEADER_ROW,
    HOLDINGS_TAB,
    MACHINE_OWNED_TABS,
    NET_WORTH_TAB,
    TRANSACTIONS_TAB,
    check_tabs,
    column_index,
)
from stonksmith.helpers.sheets import SheetsUnavailable

#: Two movements under one account, newest first, both normalized.
MOVEMENTS: tuple[tuple[str, str], ...] = (
    ("ACC-1", "2026-02-01"),
    ("ACC-1", "2026-01-15"),
)


def _split(ref: str) -> tuple[str, str]:
    """
    An A1 reference as its letters and its digits, either of which may be empty.
    :param ref: A reference such as "AD3", "A" or ""
    :return: (column letters, row digits)
    :rtype: tuple[str, str]
    """

    letters: str = "".join(char for char in ref if char.isalpha())
    digits: str = "".join(char for char in ref if char.isdigit())

    return letters, digits


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
        first_col, first_digits = _split(ref=start)
        last_col, last_digits = _split(ref=end) if end else (first_col, "")
        first_row = int(first_digits)
        last_row = int(last_digits) if last_digits else len(self.grid)

        # Via column_index rather than ord(), because the allocation blocks sit
        # past Z: "AD" under an ord() subtraction is not a column at all, and the
        # fake would answer an empty range for the block it was asked about --
        # which reads exactly like a block that failed to write.
        low: int = column_index(letter=first_col) - 1
        high: int = column_index(letter=last_col) - 1

        rows: list[list[object]] = []

        for number in range(first_row, last_row + 1):
            line = self.grid[number - 1] if number - 1 < len(self.grid) else []
            cells = [
                line[index] if index < len(line) else ""
                for index in range(low, high + 1)
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


def allocation_block(
    heading: str,
    slices: tuple[tuple[object, object, object], ...] = (("INVESTMENT", 1234.5, 1.0),),
    summed: object = 1234.5,
    share: object = 1.0,
) -> list[list[object]]:
    """
    One block's grid, header row first, closing on its check row.

    Defaults to a block that is right: one slice worth the whole portfolio, and a
    check row agreeing with it. Every argument exists so a test can make exactly
    one thing wrong, because a read-back checked only against a correct sheet
    proves the reader runs rather than that it looks.
    :param heading: What the name column is called
    :param slices: (name, value, share) per slice
    :param summed: What the check row says the values come to
    :param share: What the check row says the shares come to
    :return: The block's rows
    :rtype: list[list[object]]
    """

    rows: list[list[object]] = [[heading, "Value (USD)", "Share of total (USD)"]]
    rows += [list(entry) for entry in slices]
    rows.append([ALLOCATION_CHECK, summed, share])

    return rows


def _place(grid: list[list[object]], start: str, rows: list[list[object]]) -> None:
    """
    Write a block into the grid at its start column, from the header row down.
    :param grid: The tab's grid, extended as needed
    :param start: The block's first column letter
    :param rows: The block's rows, header first
    :return: None
    """

    column: int = column_index(letter=start) - 1

    for offset, cells in enumerate(rows):
        number: int = HEADER_ROW - 1 + offset

        while len(grid) <= number:
            grid.append([])

        line: list[object] = grid[number]

        for index, cell in enumerate(cells):
            while len(line) <= column + index:
                line.append("")

            line[column + index] = cell


def dashboard_tab(
    computed: object = 1234.5,
    as_read: object = 1234.5,
    blocks: dict[str, list[list[object]]] | None = None,
) -> Tab:
    grid: list[list[object]] = [
        [BANNER],
        ["Summary", "Value"],
        ["Total (USD)", computed],
        ["Total as read", as_read],
        ["Accounts", 1],
    ]

    if blocks is None:
        blocks = {
            BY_KIND_COL: allocation_block(heading="Account kind"),
            BY_POSITION_COL: allocation_block(heading="Position"),
        }

    for start, rows in blocks.items():
        _place(grid=grid, start=start, rows=rows)

    return Tab(grid=grid)


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


def run(
    fake: MagicMock,
    movements: int = len(MOVEMENTS),
    classes: dict[str, str] | None = None,
) -> dict[str, bool]:
    """
    Run the read-back over a fake book and return each case by name.

    ``classes`` is passed rather than left to default, so nothing here reads the
    developer's own config -- and so the asset class block, which is drawn only
    when a mapping exists, is present or absent because the test said so.
    :param fake: The fake spreadsheet
    :param movements: How many movements the databases are said to hold
    :param classes: The asset class mapping to check against
    :return: Case name to whether it passed
    :rtype: dict[str, bool]
    """

    transactions = tuple(MagicMock() for _ in range(movements))

    with patch(
        "stonksmith.etc.portfolio_sheet.read_workspace",
        return_value=Portfolio(transactions=transactions),
    ):
        cases = check_tabs(book=fake, classes=classes or {})

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

    def test_no_case_still_calls_itself_unconfirmed(self) -> None:
        # Money and the two totals used to say so, because what a rendered cell
        # comes back as was an assumption no test here could settle. The
        # 2026-08-10 run settled it in both directions -- a wrong assumption would
        # have failed rather than passed quietly -- so the marker came off. This
        # keeps it off: putting one back means a new assumption, not this one.
        cases = run(fake=book())
        marked = [name for name in cases if "unconfirmed" in name.lower()]

        self.assertEqual(marked, [])

    def test_a_missing_tab_reports_rather_than_creating_one(self) -> None:
        # Creating it would manufacture the thing being checked.
        fake = book()
        fake.worksheet.side_effect = SheetsUnavailable("has no tab named 'Dashboard'")

        with self.assertRaises(SheetsUnavailable):
            run(fake=fake)

        fake.add_worksheet.assert_not_called()


class AllocationReadBackTests(UserConfigMixin, unittest.TestCase):
    """
    The closing row every allocation block writes, and nothing used to read.

    The block puts "Slices sum to" at its foot so that a wrong base "shows up as
    a share column that does not come to 1, visible without anybody having to add
    the column up by hand". Visible to a person, and to nothing else: the row was
    written and never read back, so a block whose shares came to 0.8 was written,
    reported as a success, and agreed with by every other check in this file.

    So each case here makes exactly one number wrong and asks whether the check
    notices, and one asks whether a correct block still passes -- because a check
    that fails on everything is no more use than one that passes on everything.
    """

    def _dashboard(self, **blocks: list[list[object]]) -> MagicMock:
        """A book whose dashboard carries exactly the blocks named."""

        return book(**{DASHBOARD_TAB: dashboard_tab(blocks=dict(blocks))})

    def test_slices_that_do_not_come_to_the_total_are_caught(self) -> None:
        # The whole point. 1200 of a 1234.50 portfolio is a slice that failed to
        # land, and every other check on the tab agrees with it.
        fake = self._dashboard(
            **{
                BY_KIND_COL: allocation_block(heading="Account kind", summed=1200.0),
                BY_POSITION_COL: allocation_block(heading="Position"),
            }
        )
        cases = run(fake=fake)

        self.assertFalse(cases["The account kind allocation adds up"])
        self.assertTrue(cases["The position allocation adds up"])

    def test_shares_that_do_not_come_to_one_are_caught(self) -> None:
        # A wrong base: the values are right and the percentages are of the
        # wrong thing, which is exactly the failure that looks like a breakdown.
        fake = self._dashboard(
            **{
                BY_KIND_COL: allocation_block(heading="Account kind"),
                BY_POSITION_COL: allocation_block(heading="Position", share=0.8),
            }
        )
        cases = run(fake=fake)

        self.assertTrue(cases["The account kind allocation adds up"])
        self.assertFalse(cases["The position allocation adds up"])

    def test_a_block_with_no_check_row_is_caught(self) -> None:
        # Not silently skipped. A block missing its own closing row is a block
        # that did not finish writing, and "nothing to check" must not read as
        # "checked and fine".
        headless: list[list[object]] = [
            ["Position", "Value (USD)", "Share of total (USD)"],
            ["VTI", 1234.5, 1.0],
        ]
        fake = self._dashboard(
            **{
                BY_KIND_COL: allocation_block(heading="Account kind"),
                BY_POSITION_COL: headless,
            }
        )

        self.assertFalse(run(fake=fake)["The position allocation adds up"])

    def test_a_refusal_passes_because_it_is_the_block_working(self) -> None:
        # A block that refuses to draw is the safety mechanism firing, not a
        # defect. Reading it as one would report the guard as the fault.
        refused: list[list[object]] = [
            ["Position", "Value (USD)", "Share of total (USD)"],
            [ALLOCATION_REFUSED, "positions exceed account balances by 5.00 USD", ""],
        ]
        fake = self._dashboard(
            **{
                BY_KIND_COL: allocation_block(heading="Account kind"),
                BY_POSITION_COL: refused,
            }
        )

        self.assertTrue(run(fake=fake)["The position allocation adds up"])

    def test_the_class_block_is_checked_only_when_one_was_asked_for(self) -> None:
        # Absent is correct with no mapping, and a failure with one. Inferring
        # which from the tab cannot tell those apart.
        both = {
            BY_KIND_COL: allocation_block(heading="Account kind"),
            BY_POSITION_COL: allocation_block(heading="Position"),
        }
        name = "The asset class allocation adds up"

        self.assertNotIn(name, run(fake=self._dashboard(**both)))
        self.assertFalse(
            run(fake=self._dashboard(**both), classes={"VTI": "US Stock"})[name]
        )

    def test_a_drawn_class_block_passes_when_it_adds_up(self) -> None:
        fake = self._dashboard(
            **{
                BY_KIND_COL: allocation_block(heading="Account kind"),
                BY_POSITION_COL: allocation_block(heading="Position"),
                BY_CLASS_COL: allocation_block(heading="Asset class"),
            }
        )
        cases = run(fake=fake, classes={"VTI": "US Stock"})

        self.assertTrue(cases["The asset class allocation adds up"], cases)

    def test_an_empty_workspace_does_not_fail_on_shares_of_nothing(self) -> None:
        # Every share is IFERROR'd to "" when the total is zero, so the column
        # sums to nothing. There is no base to be wrong about, so the question
        # is not asked rather than answered no.
        empty = allocation_block(heading="Account kind", slices=(), summed=0, share=0)
        fake = book(
            **{
                DASHBOARD_TAB: dashboard_tab(
                    computed=0,
                    as_read=0,
                    blocks={
                        BY_KIND_COL: empty,
                        BY_POSITION_COL: allocation_block(
                            heading="Position", slices=(), summed=0, share=0
                        ),
                    },
                )
            }
        )
        cases = run(fake=fake)

        self.assertTrue(cases["The account kind allocation adds up"], cases)
        self.assertTrue(cases["The position allocation adds up"], cases)

    def test_the_mapping_comes_from_config_when_it_is_not_passed(self) -> None:
        # The default path, which the rest of this file bypasses. check_tabs has
        # to consult the same config the sync did, or verify would check for a
        # block the run never drew -- or miss the one it did.
        etc_config.user_cfg_path.write_text(
            data="[ALLOCATION]\nasset_classes =\n    VTI = US Stock\n"
        )
        etc_config.reset_config_cache()

        transactions = tuple(MagicMock() for _ in range(len(MOVEMENTS)))

        with patch(
            "stonksmith.etc.portfolio_sheet.read_workspace",
            return_value=Portfolio(transactions=transactions),
        ):
            cases = check_tabs(book=book())

        self.assertIn(
            "The asset class allocation adds up", {case.name for case in cases}
        )


if __name__ == "__main__":
    unittest.main()
