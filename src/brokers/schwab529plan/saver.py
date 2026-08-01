"""
Save account data from https://www.schwab529.com/ into Google Sheets.
"""

from typing import Any

from helpers.sheets import a1_range as _a1_range
from helpers.sheets import open_worksheet

WORKSHEET_NAME = "529 Plan"


class Saver:
    """
    Save account data from https://www.schwab529.com/
    """

    def __init__(self) -> None:
        self.worksheet: Any = None

    def _prepare_sheet(self) -> None:
        """
        Internal helper to authenticate once per run.
        :return: None
        """

        if not self.worksheet:
            self.worksheet = open_worksheet(worksheet_name=WORKSHEET_NAME)

    def save_beneficiary(self, data: list[dict[str, Any]]) -> None:
        """
        Save beneficiary data to Google Sheets.
        :param data: List of beneficiary dictionaries
        :return: None
        """

        self._prepare_sheet()
        if self.worksheet:
            self.worksheet.clear()
            self.worksheet.update([["Title", "Name", "Account"]], "B2:D2")
            rows: list[list[str | None]] = [
                [a.get("Title"), a.get("Name"), a.get("Account")] for a in data
            ]
            if rows:
                self.worksheet.update(
                    rows,
                    _a1_range(
                        first_col="B", last_col="D", first_row=3, row_count=len(rows)
                    ),
                )

    def save_balance(self, data: list[dict[str, Any]]) -> None:
        """
        Save balance data from https://www.schwab529.com/
        :param data: List of balance dictionaries
        :return: None
        """

        self._prepare_sheet()
        if self.worksheet:
            self.worksheet.update([["Title", "Amount", "Date"]], "G2:I2")
            rows: list[list[str | None]] = [
                [a.get("Title"), a.get("Amount"), a.get("Date")] for a in data
            ]
            if rows:
                self.worksheet.update(
                    rows,
                    _a1_range(
                        first_col="G", last_col="I", first_row=3, row_count=len(rows)
                    ),
                )

    def save_investment(self, data: list[dict[str, Any]]) -> None:
        """
        Save investment data from https://www.schwab529.com/
        :param data: List of investment dictionaries
        :return: None
        """

        self._prepare_sheet()
        if self.worksheet:
            headers: list[str] = [
                "Fund Code",
                "Fund",
                "Units",
                "Price",
                "Value",
                "Total Assets",
                "Principal",
                "Earnings",
            ]
            self.worksheet.update([headers], "B9:I9")
            rows: list[list[str | None]] = [
                [
                    a.get("Fund Code"),
                    a.get("Fund"),
                    a.get("Units"),
                    a.get("Price"),
                    a.get("Value"),
                    a.get("Total Assets"),
                    a.get("Principal"),
                    a.get("Earnings"),
                ]
                for a in data
            ]
            if rows:
                self.worksheet.update(
                    rows,
                    _a1_range(
                        first_col="B", last_col="I", first_row=10, row_count=len(rows)
                    ),
                )

    def save_transactions(self, data: list[dict[str, Any]]) -> None:
        """
        Save transaction data from https://www.schwab529.com/
        :param data: List of transaction dictionaries
        :return: None
        """

        self._prepare_sheet()
        if self.worksheet:
            headers: list[str] = [
                "Processed",
                "Traded",
                "Type",
                "Units",
                "Price",
                "Value",
            ]
            self.worksheet.update([headers], "C16:H16")
            rows: list[list[str | None]] = [
                [
                    a.get("Processed"),
                    a.get("Traded"),
                    a.get("Type"),
                    a.get("Units"),
                    a.get("Price"),
                    a.get("Value"),
                ]
                for a in data
            ]
            if rows:
                self.worksheet.append_rows(rows, table_range="C17:H17")
