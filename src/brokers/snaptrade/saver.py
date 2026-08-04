"""
Save SnapTrade account data into Google Sheets.
"""

from typing import Any

from helpers.sheets import a1_range, open_worksheet

WORKSHEET_NAME = "SnapTrade"

#: One tab covers every brokerage connected through SnapTrade, so unlike the
#: per-broker tabs this one has to name the institution. Category and Synced
#: come along because a row can be a liability or a deliberately stale reading,
#: and a bare name and balance would not say which.
HEADERS = ["Brokerage", "Account", "Balance", "Category", "Synced"]

FIRST_COL = "B"
LAST_COL = "F"
FIRST_ROW = 3


class Saver:
    """
    Write SnapTrade account snapshots to the shared dashboard.
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
        Write one row per account.
        :param data: List of dictionaries keyed by HEADERS
        :return: None
        """

        self._prepare_sheet()

        if not self.worksheet:
            return

        self.worksheet.clear()
        self.worksheet.update([HEADERS], f"{FIRST_COL}2:{LAST_COL}2")

        rows: list[list[str | None]] = [
            [item.get(header) for header in HEADERS] for item in data
        ]

        if rows:
            self.worksheet.update(
                rows,
                a1_range(
                    first_col=FIRST_COL,
                    last_col=LAST_COL,
                    first_row=FIRST_ROW,
                    row_count=len(rows),
                ),
            )
