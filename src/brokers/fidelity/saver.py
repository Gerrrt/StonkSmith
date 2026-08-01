"""
Save Fidelity account data into Google Sheets.
"""

from typing import Any

from helpers.sheets import a1_range, open_worksheet

WORKSHEET_NAME = "Fidelity"


class Saver:
    """
    Write Fidelity account snapshots to the shared dashboard.
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
        :param data: List of {"Account", "Balance"} dictionaries
        :return: None
        """

        self._prepare_sheet()

        if not self.worksheet:
            return

        self.worksheet.clear()
        self.worksheet.update([["Account", "Balance"]], "B2:C2")

        rows: list[list[str | None]] = [
            [item.get("Account"), item.get("Balance")] for item in data
        ]

        if rows:
            self.worksheet.update(
                rows,
                a1_range(first_col="B", last_col="C", first_row=3, row_count=len(rows)),
            )
