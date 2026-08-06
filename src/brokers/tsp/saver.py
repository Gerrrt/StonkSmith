"""
Save TSP account data into Google Sheets.
"""

from typing import Any

from helpers.sheets import a1_range, open_worksheet

WORKSHEET_NAME = "TSP"

HEADERS: list[str] = [
    "Fund",
    "Units",
    "Units as of",
    "Share price",
    "Price date",
    "Value",
    "Basis",
]


class Saver:
    """
    Write TSP marks to the shared dashboard.
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
        Write one row per fund.

        Both dates travel with the number on purpose. A TSP mark is a unit
        count multiplied by a share price, and the two are true as of different
        days -- the price is today's, the units are as old as the last
        statement. A single value with no provenance is exactly what makes a
        stale number look current.
        :param data: List of mark dictionaries
        :return: None
        """

        self._prepare_sheet()

        if not self.worksheet:
            return

        self.worksheet.clear()
        self.worksheet.update([HEADERS], "B2:H2")

        rows: list[list[str | None]] = [
            [item.get(header) for header in HEADERS] for item in data
        ]

        if rows:
            self.worksheet.update(
                rows,
                a1_range(first_col="B", last_col="H", first_row=3, row_count=len(rows)),
            )
