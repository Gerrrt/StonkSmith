"""
Save Ally Invest account data into Google Sheets.
"""

from typing import Any

from helpers.sheets import a1_range, open_worksheet

WORKSHEET_NAME = "Ally"

ACCOUNT_HEADERS: list[str] = ["Account", "Balance", "Total G/L", "Today's G/L"]
HOLDING_HEADERS: list[str] = [
    "Account",
    "Symbol",
    "Description",
    "Units",
    "Price",
    "Cost Basis",
    "Value",
]


class Saver:
    """
    Write Ally Invest snapshots to the shared dashboard.
    """

    def __init__(self) -> None:
        self.worksheet: Any = None

    def _prepare_sheet(self) -> None:
        """
        Authenticate once per run.
        :return: None
        """

        if not self.worksheet:
            self.worksheet = open_worksheet(worksheet_name=WORKSHEET_NAME)

    def save_accounts(self, data: list[dict[str, Any]]) -> None:
        """
        Write one row per account, clearing the tab first.

        Clears here rather than in save_holdings() because this runs first and
        the two blocks share the sheet: clearing twice would wipe whichever was
        written earlier.
        :param data: List of account dictionaries
        :return: None
        """

        self._prepare_sheet()

        if not self.worksheet:
            return

        self.worksheet.clear()
        self.worksheet.update([ACCOUNT_HEADERS], "B2:E2")

        rows: list[list[str | None]] = [
            [item.get(header) for header in ACCOUNT_HEADERS] for item in data
        ]

        if rows:
            self.worksheet.update(
                rows,
                a1_range(first_col="B", last_col="E", first_row=3, row_count=len(rows)),
            )

    def save_holdings(self, data: list[dict[str, Any]]) -> None:
        """
        Write one row per position, beside the accounts rather than below them.

        Two blocks in separate columns, because the number of accounts is not
        known when the layout is chosen: stacking them would put the holdings
        header at a row that a long account list overwrites.
        :param data: List of holding dictionaries
        :return: None
        """

        self._prepare_sheet()

        if not self.worksheet:
            return

        self.worksheet.update([HOLDING_HEADERS], "G2:M2")

        rows: list[list[str | None]] = [
            [item.get(header) for header in HOLDING_HEADERS] for item in data
        ]

        if rows:
            self.worksheet.update(
                rows,
                a1_range(first_col="G", last_col="M", first_row=3, row_count=len(rows)),
            )
