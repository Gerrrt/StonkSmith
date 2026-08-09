"""What actually reaches the cells.

The five savers wrote format_amount() output, which puts "$1,234.56" in a cell
nothing can add up. The contract says money is a number and an absent value is
absent. These tests are what keeps that true on the way out, rather than only in
the dataclass.
"""

import unittest
from typing import Any
from unittest.mock import MagicMock

from etc.portfolio import (
    ACCOUNT_COLUMNS,
    HOLDING_COLUMNS,
    TRANSACTION_COLUMNS,
    AccountRow,
    HoldingRow,
)
from etc.portfolio_sheet import (
    ACCOUNTS_TAB,
    BANNER,
    BANNER_CELL,
    CHUNK_ROWS,
    HOLDINGS_TAB,
    column_index,
    column_letter,
    column_of,
    last_column,
    write_rows,
)
from helpers.sheets import a1_range, fit


def owned(row_count: int = 1000, col_count: int = 26) -> MagicMock:
    """
    A worksheet that already carries the banner, so ``claim`` lets it through.
    :param row_count: The grid's current height
    :param col_count: The grid's current width
    :return: The fake worksheet
    :rtype: MagicMock
    """

    fake = MagicMock()
    fake.acell.return_value = MagicMock(value=BANNER)
    fake.row_count = row_count
    fake.col_count = col_count

    return fake


def written(worksheet: MagicMock) -> list[tuple[Any, str]]:
    """
    Every (values, range) pair an update call carried, in order.
    :param worksheet: The fake worksheet
    :return: One entry per update
    :rtype: list[tuple[Any, str]]
    """

    return [(call.args[0], call.args[1]) for call in worksheet.update.call_args_list]


class ColumnLetterTests(unittest.TestCase):
    def test_the_first_column_is_a(self) -> None:
        self.assertEqual(column_letter(index=1), "A")

    def test_the_contract_ends_where_it_says_it_does(self) -> None:
        self.assertEqual(last_column(columns=ACCOUNT_COLUMNS), "J")
        self.assertEqual(last_column(columns=HOLDING_COLUMNS), "P")
        self.assertEqual(last_column(columns=TRANSACTION_COLUMNS), "O")

    def test_it_keeps_working_past_z(self) -> None:
        # Append-only makes a twenty-seventh column a question of when, not
        # whether, and a letter that quietly went wrong there would take every
        # formula with it.
        self.assertEqual(column_letter(index=26), "Z")
        self.assertEqual(column_letter(index=27), "AA")
        self.assertEqual(column_letter(index=52), "AZ")
        self.assertEqual(column_letter(index=53), "BA")

    def test_a_column_number_below_one_is_an_error_not_a_letter(self) -> None:
        with self.assertRaises(ValueError):
            column_letter(index=0)

    def test_letters_and_indices_are_inverses(self) -> None:
        for index in (1, 7, 26, 27, 52, 53, 703):
            self.assertEqual(column_index(letter=column_letter(index=index)), index)

    def test_a_column_is_found_by_name_not_by_a_typed_letter(self) -> None:
        self.assertEqual(column_of(columns=ACCOUNT_COLUMNS, name="Value"), "G")
        self.assertEqual(column_of(columns=ACCOUNT_COLUMNS, name="Currency"), "H")
        self.assertEqual(column_of(columns=HOLDING_COLUMNS, name="Symbol"), "E")

    def test_asking_for_a_column_that_is_not_in_the_contract_raises(self) -> None:
        with self.assertRaises(KeyError):
            column_of(columns=ACCOUNT_COLUMNS, name="Balance")


class A1RangeTests(unittest.TestCase):
    """Moved off the deleted saver tests. The range still has to span its rows."""

    def test_range_spans_exactly_the_row_count(self) -> None:
        self.assertEqual(
            a1_range(first_col="B", last_col="D", first_row=3, row_count=1), "B3:D3"
        )
        self.assertEqual(
            a1_range(first_col="B", last_col="D", first_row=3, row_count=3), "B3:D5"
        )
        self.assertEqual(
            a1_range(first_col="B", last_col="I", first_row=10, row_count=2), "B10:I11"
        )


class FitTests(unittest.TestCase):
    def test_a_grid_that_is_big_enough_is_left_alone(self) -> None:
        tab = owned()

        fit(worksheet=tab, rows=50, cols=10)

        tab.add_rows.assert_not_called()
        tab.add_cols.assert_not_called()

    def test_a_grid_too_short_for_the_write_is_grown(self) -> None:
        # clear() empties cells; it does not resize. An update past the last row
        # is rejected with a grid-limits error that says nothing about rows.
        tab = owned(row_count=1000)

        fit(worksheet=tab, rows=1500, cols=10)

        tab.add_rows.assert_called_once_with(500)

    def test_a_grid_too_narrow_for_the_contract_is_widened(self) -> None:
        tab = owned(col_count=5)

        fit(worksheet=tab, rows=10, cols=15)

        tab.add_cols.assert_called_once_with(10)


class WriteRowsTests(unittest.TestCase):
    def test_the_header_is_exactly_the_contract(self) -> None:
        tab = owned()

        write_rows(worksheet=tab, tab=ACCOUNTS_TAB, columns=ACCOUNT_COLUMNS, rows=[])

        self.assertIn(([list(ACCOUNT_COLUMNS)], "A2:J2"), written(worksheet=tab))

    def test_the_holdings_header_is_exactly_the_contract(self) -> None:
        tab = owned()

        write_rows(worksheet=tab, tab=HOLDINGS_TAB, columns=HOLDING_COLUMNS, rows=[])

        self.assertIn(([list(HOLDING_COLUMNS)], "A2:P2"), written(worksheet=tab))

    def test_the_banner_goes_in_before_the_data(self) -> None:
        # First in, so a write that dies partway leaves a tab that still
        # identifies itself as ours rather than one the next run refuses.
        tab = owned()

        write_rows(
            worksheet=tab,
            tab=ACCOUNTS_TAB,
            columns=ACCOUNT_COLUMNS,
            rows=[
                AccountRow(
                    broker="tsp", source="tsp", account="C", account_key="c"
                ).cells()
            ],
        )

        self.assertEqual(written(worksheet=tab)[0], ([[BANNER]], BANNER_CELL))

    def test_the_tab_is_emptied_before_anything_is_written(self) -> None:
        tab = owned()
        order: list[str] = []
        tab.clear.side_effect = lambda: order.append("clear")
        tab.update.side_effect = lambda *_a, **_k: order.append("update")

        write_rows(worksheet=tab, tab=ACCOUNTS_TAB, columns=ACCOUNT_COLUMNS, rows=[])

        self.assertEqual(order[0], "clear")

    def test_data_starts_on_the_third_row_and_spans_its_rows(self) -> None:
        tab = owned()
        rows = [
            AccountRow(
                broker="tsp", source="tsp", account=f"A{n}", account_key=f"a{n}"
            ).cells()
            for n in range(3)
        ]

        self.assertEqual(
            write_rows(
                worksheet=tab, tab=ACCOUNTS_TAB, columns=ACCOUNT_COLUMNS, rows=rows
            ),
            3,
        )
        self.assertEqual(written(worksheet=tab)[-1][1], "A3:J5")

    def test_an_empty_portfolio_still_writes_the_banner_and_header(self) -> None:
        # A sync that wrote nothing because it found nothing would leave the
        # previous run's numbers on screen looking current.
        tab = owned()

        write_rows(worksheet=tab, tab=ACCOUNTS_TAB, columns=ACCOUNT_COLUMNS, rows=[])

        ranges = [range_name for _, range_name in written(worksheet=tab)]
        self.assertEqual(ranges, [BANNER_CELL, "A2:J2"])

    def test_everything_goes_up_raw(self) -> None:
        # An account whose display name begins with "=" is a name, not a
        # formula, and an ISO date is the text the database stored, not a date
        # serial. USER_ENTERED would change both without saying so.
        tab = owned()

        write_rows(
            worksheet=tab,
            tab=ACCOUNTS_TAB,
            columns=ACCOUNT_COLUMNS,
            rows=[
                AccountRow(
                    broker="ally", source="ally", account="=SUM(A:A)", account_key="k"
                ).cells()
            ],
        )

        for call in tab.update.call_args_list:
            self.assertEqual(call.kwargs["value_input_option"], "RAW")

    def test_money_reaches_the_cell_as_a_number(self) -> None:
        # The single assertion that makes deleting the row builders permanent.
        tab = owned()

        write_rows(
            worksheet=tab,
            tab=ACCOUNTS_TAB,
            columns=ACCOUNT_COLUMNS,
            rows=[
                AccountRow(
                    broker="fidelity",
                    source="fidelity",
                    account="Brokerage",
                    account_key="x",
                    value=1234.56,
                ).cells()
            ],
        )

        cell: Any = written(worksheet=tab)[-1][0][0][
            list(ACCOUNT_COLUMNS).index("Value")
        ]
        self.assertIsInstance(cell, float)
        self.assertEqual(cell, 1234.56)

    def test_no_cell_is_formatted_money_text(self) -> None:
        tab = owned()

        write_rows(
            worksheet=tab,
            tab=HOLDINGS_TAB,
            columns=HOLDING_COLUMNS,
            rows=[
                HoldingRow(
                    broker="ally",
                    source="ally",
                    account="Individual",
                    account_key="x",
                    symbol="VTI",
                    units=10.5,
                    price=250.25,
                    value=2627.63,
                ).cells()
            ],
        )

        for cell in written(worksheet=tab)[-1][0][0]:
            if isinstance(cell, str):
                self.assertNotIn("$", cell)

    def test_a_value_the_source_never_gave_stays_empty(self) -> None:
        # An account that reported no number is not an account worth nothing.
        tab = owned()

        write_rows(
            worksheet=tab,
            tab=ACCOUNTS_TAB,
            columns=ACCOUNT_COLUMNS,
            rows=[
                AccountRow(
                    broker="tsp", source="tsp", account="C Fund", account_key="c"
                ).cells()
            ],
        )

        row: list[Any] = written(worksheet=tab)[-1][0][0]
        self.assertEqual(row[list(ACCOUNT_COLUMNS).index("Value")], "")
        self.assertEqual(row[list(ACCOUNT_COLUMNS).index("As Of")], "")

    def test_a_long_workspace_is_written_in_chunks(self) -> None:
        # One request carrying every position is one rejection away from losing
        # the whole write.
        tab = owned(row_count=5000)
        rows = [
            HoldingRow(
                broker="snaptrade", source="Schwab", account="A", account_key="a"
            ).cells()
            for _ in range(CHUNK_ROWS + 500)
        ]

        write_rows(worksheet=tab, tab=HOLDINGS_TAB, columns=HOLDING_COLUMNS, rows=rows)

        data = [
            (values, range_name)
            for values, range_name in written(worksheet=tab)
            if range_name not in (BANNER_CELL, "A2:P2")
        ]
        self.assertEqual([len(values) for values, _ in data], [CHUNK_ROWS, 500])
        self.assertEqual(data[0][1], f"A3:P{CHUNK_ROWS + 2}")
        self.assertEqual(data[1][1], f"A{CHUNK_ROWS + 3}:P{CHUNK_ROWS + 502}")

    def test_a_grid_that_exactly_fits_the_write_is_not_grown(self) -> None:
        # N data rows end on HEADER_ROW + N, because the header takes row 2 and
        # the data starts on the row after it. Asking for FIRST_DATA_ROW + N
        # asked for one row more than the write addresses, so a tab trimmed to
        # exactly fit gained a spare row it never used.
        rows = [
            AccountRow(
                broker="tsp", source="tsp", account=f"A{n}", account_key=f"a{n}"
            ).cells()
            for n in range(5)
        ]
        tab = owned(row_count=2 + len(rows))

        write_rows(worksheet=tab, tab=ACCOUNTS_TAB, columns=ACCOUNT_COLUMNS, rows=rows)

        self.assertEqual(written(worksheet=tab)[-1][1], f"A3:J{2 + len(rows)}")
        tab.add_rows.assert_not_called()

    def test_the_grid_is_grown_before_the_write_not_after(self) -> None:
        tab = owned(row_count=10)
        order: list[str] = []
        tab.add_rows.side_effect = lambda _n: order.append("grow")
        tab.update.side_effect = lambda *_a, **_k: order.append("update")

        write_rows(
            worksheet=tab,
            tab=ACCOUNTS_TAB,
            columns=ACCOUNT_COLUMNS,
            rows=[
                AccountRow(
                    broker="tsp", source="tsp", account=f"A{n}", account_key=f"a{n}"
                ).cells()
                for n in range(50)
            ],
        )

        self.assertEqual(order[0], "grow")


if __name__ == "__main__":
    unittest.main()
