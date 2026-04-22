"""
Navigate database entries for Schwab529
"""

import cmd
import sys
import typing
from collections.abc import Sequence

from etc.logger import stonksmith_logger
from helpers import db as helper_db


class _DatabaseLike(typing.Protocol):
    """Protocol for database methods used by the navigator."""

    def get_credentials(
        self, filter_term: str | None = None
    ) -> list[tuple[object, ...]]: ...

    def shutdown_db(self) -> None: ...


class UserExitedProto(Exception):
    """
    Exception raised when the user exits the database navigator.
    """


def help_export() -> None:
    """
    Help message for export.
    """

    print("Export database entries to file.\nUsage: export creds <>")


def help_show() -> None:
    """
    Help message for show.
    """

    print("Show database entries in a table.\nUsage: show creds <>")


class DatabaseNavigator(cmd.Cmd):
    """
    Navigate database entries for Schwab529
    """

    def __init__(
        self, main_menu: object, database: _DatabaseLike, broker_name: str
    ) -> None:
        super().__init__()
        self.main_menu: object = main_menu
        self.db: _DatabaseLike = database
        self.broker: str = broker_name
        self.prompt = f"stonksmithdb ({self.broker}) > "

    def do_back(self, line: str) -> typing.NoReturn:
        """
        Back to main menu
        :param line:
        :type line:
        :return:
        :rtype:
        """

        raise UserExitedProto

    def do_exit(self, line: str) -> typing.NoReturn:
        """
        Exit the whole application
        :param line:
        :type line:
        :return:
        :rtype:
        """

        self.db.shutdown_db()
        sys.exit(0)

    def do_export(self, line: str) -> None:
        """
        Export data to CSV
        Usage: export creds <>
        :param line:
        :type line:
        :return:
        :rtype:
        """

        args: list[str] = line.split()
        if len(args) < 2:
            stonksmith_logger.fail(msg="Usage: export creds <>")
            return

        category: str = args[0].lower()
        filename: str = args[1]

        if category == "creds":
            creds: list[tuple[object, ...]] = self.db.get_credentials()
            headers: Sequence[str] = ("ID", "User", "Pass", "Type", "Source")
            helper_db.write_csv(filename=filename, headers=headers, entries=creds)
            stonksmith_logger.success(msg=f"Exported creds to {filename}")
        else:
            stonksmith_logger.fail(msg=f"Unknown category {category}")

    def do_show(self, line: str) -> None:
        """
        Show data in a table
        Usage: show creds
        :param line:
        :type line:
        :return:
        :rtype:
        """

        if line.lower() == "creds":
            data: list[tuple[object, ...]] = self.db.get_credentials()
            headers: list[str] = ["ID", "User", "Pass", "Type", "Source"]
            table_data: list[list[str]] = [headers] + [
                [str(object=value) for value in row] for row in data
            ]
            helper_db.print_table(data=table_data, title=f"{self.broker} Credentials")

        else:
            stonksmith_logger.fail(msg="Usage: show creds")
