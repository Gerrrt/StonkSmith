# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Google Sheets helpers shared by every broker's saver."""

from typing import Any

import gspread

#: The spreadsheet every broker writes into; each broker owns one worksheet tab.
SPREADSHEET_NAME = "Investment Account Scrapes"


def a1_range(first_col: str, last_col: str, first_row: int, row_count: int) -> str:
    """
    Build an A1 range that spans exactly ``row_count`` rows.
    :param first_col: Left-hand column letter, e.g. "B"
    :param last_col: Right-hand column letter, e.g. "D"
    :param first_row: 1-indexed row the data starts on
    :param row_count: Number of data rows being written
    :return: An A1 range such as "B3:D5"
    """

    last_row: int = first_row + row_count - 1
    return f"{first_col}{first_row}:{last_col}{last_row}"


def open_worksheet(worksheet_name: str, spreadsheet: str = SPREADSHEET_NAME) -> Any:
    """
    Authenticate once and return a worksheet handle.
    :param worksheet_name: The tab to open, e.g. "529 Plan"
    :param spreadsheet: The spreadsheet to open it in
    :return: A gspread worksheet
    """

    client: Any = gspread.oauth()
    return client.open(spreadsheet).worksheet(worksheet_name)
