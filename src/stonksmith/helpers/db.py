"""
db.py: Helpers for local database
"""

import csv
from collections.abc import Sequence
from pathlib import Path

import tabulate


def print_table(data: list[list[str]], title: str) -> None:
    """
    Prints data in a table
    :param data: List of lists containing the table data
    :param title: Title of the table
    :return: None
    """

    print(title)
    print(tabulate.tabulate(tabular_data=data, headers="", tablefmt="grid"))
    print()


def write_csv(
    filename: str | Path,
    headers: Sequence[object],
    entries: Sequence[Sequence[object]],
) -> None:
    """
    Writes entries to a csv file
    :param filename:
    :param headers:
    :param entries:
    :return:
    """

    path: Path = Path(filename).expanduser()
    try:
        with path.open(mode="w", newline="", encoding="utf-8") as f:
            write = csv.writer(
                f,
                delimiter=";",
                lineterminator="\n",
                escapechar="\\",
            )
            write.writerow(headers)
            write.writerows(entries)

    except OSError as e:
        print(f"[-] Error writing CSV to {filename}: {e}")


def write_list(filename: str | Path, entries: Sequence[object]) -> None:
    """
    Writes a list of strings to a text file.
    :param filename:
    :param entries:
    :return:
    """

    path: Path = Path(filename).expanduser()
    try:
        with path.open(mode="w", encoding="utf-8") as f:
            for line in entries:
                f.write(f"{line}\n")

    except OSError as e:
        print(f"[-] Error writing list to {filename}: {e}")
