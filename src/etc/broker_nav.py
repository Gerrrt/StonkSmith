# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Shared ``stonksmithdb`` sub-shell for browsing a broker's database.

Each broker package exposes a ``DatabaseNavigator`` that BrokerLoader imports by
file path. The commands are identical across brokers, so they live here.

Secrets are masked on display and omitted from exports; the keyring reference is
exported instead.
"""

import cmd
import sys
import typing
from collections.abc import Sequence
from getpass import getpass

from etc.config import process_secret
from etc.exceptions import SwitchBroker, UserExitedProto
from etc.logger import stonksmith_logger
from helpers import db as helper_db


class DatabaseLike(typing.Protocol):
    """The database surface the navigator relies on."""

    def get_credentials(
        self, filter_term: str | None = None
    ) -> list[tuple[object, ...]]: ...

    def get_credential_refs(
        self, filter_term: str | None = None
    ) -> list[tuple[object, ...]]: ...

    def get_account_data(self) -> list[tuple[object, ...]]: ...

    def add_credential(
        self,
        username: str,
        secret: str,
        cred_type: str = "plaintext",
        source: str = "manual",
    ) -> str: ...

    def delete_credential(self, cred_id: int) -> bool: ...

    def shutdown_db(self) -> None: ...


class BrokerNavigator(cmd.Cmd):
    """Interactive shell over one broker's credential and account tables."""

    #: Commands that belong to the top-level shell, used to explain the mistake
    #: when one of them is typed in here.
    PARENT_SHELL_COMMANDS: typing.ClassVar[frozenset[str]] = frozenset({"workspace"})

    def __init__(
        self, main_menu: object, database: DatabaseLike, broker_name: str
    ) -> None:
        super().__init__()
        self.main_menu: object = main_menu
        self.db: DatabaseLike = database
        self.broker: str = broker_name
        self.prompt = f"stonksmithdb ({self.broker}) > "
        self.intro = (
            f"\n[*] {broker_name}:\n"
            "    add creds <username>     store a credential "
            "(the secret goes to the OS keyring)\n"
            "    show creds | accounts    credentials (masked) or saved balances\n"
            "    export creds <file>      write a CSV (never includes secrets)\n"
            "    delete creds <id>        remove a credential\n"
            "    broker <name>            switch straight to another broker\n"
            "    back                     return to the broker list\n"
        )

    def get_names(self) -> list[str]:
        """
        Hide the EOF handler from help and tab-completion.
        :return: Command names to advertise
        """

        return [name for name in super().get_names() if name != "do_EOF"]

    def default(self, line: str) -> None:
        """
        Explain unknown input rather than printing "*** Unknown syntax".
        :param line: The command the user typed
        """

        parts: list[str] = line.split()
        command: str = parts[0].lower() if parts else ""

        # Reported through the logger, like every other message in this shell.
        # It renders the "[-]" marker and indentation itself.
        if command in self.PARENT_SHELL_COMMANDS:
            stonksmith_logger.fail(
                msg=(
                    f"'{command}' belongs to the top level. "
                    f"Type 'back' first, then '{line}'."
                )
            )
            return

        stonksmith_logger.fail(
            msg=f"Unknown command: {line}. Type 'help' for the commands here."
        )

    def do_broker(self, line: str) -> typing.NoReturn:
        """
        Switch straight to another broker, no `back` required.
        Usage: broker <name>
        :param line:
        """

        raise SwitchBroker(broker=line.strip())

    def do_brokers(self, line: str) -> typing.NoReturn:
        """
        Leave this broker and list the available ones.
        :param line:
        """

        del line
        raise SwitchBroker(broker="")

    def do_back(self, line: str) -> typing.NoReturn:
        """
        Return to the main menu.
        :param line:
        """

        del line
        raise UserExitedProto

    def do_exit(self, line: str) -> typing.NoReturn:
        """
        Exit the whole application.
        :param line:
        """

        del line
        self.db.shutdown_db()
        sys.exit(0)

    def do_add(self, line: str) -> None:
        """
        Add a credential. The secret is prompted for and stored in the OS
        keyring; only a reference to it is written to the database.
        Usage: add creds <username>
        :param line:
        """

        args: list[str] = line.split()

        if len(args) < 2 or args[0].lower() != "creds":
            stonksmith_logger.fail(msg="Usage: add creds <username>")
            return

        username: str = args[1]
        secret: str = getpass(prompt=f"Password for {username}: ")

        if not secret:
            stonksmith_logger.fail(msg="Empty secret; nothing stored.")
            return

        key: str = self.db.add_credential(username=username, secret=secret)
        stonksmith_logger.success(msg=f"Stored credential for {username} ({key})")

    def do_delete(self, line: str) -> None:
        """
        Delete a credential and its keyring entry.
        Usage: delete creds <id>
        :param line:
        """

        args: list[str] = line.split()

        if len(args) < 2 or args[0].lower() != "creds":
            stonksmith_logger.fail(msg="Usage: delete creds <id>")
            return

        try:
            cred_id: int = int(args[1])

        except ValueError:
            stonksmith_logger.fail(msg=f"Not a credential id: {args[1]}")
            return

        if self.db.delete_credential(cred_id=cred_id):
            stonksmith_logger.success(msg=f"Deleted credential {cred_id}")
        else:
            stonksmith_logger.fail(msg=f"No credential with id {cred_id}")

    def do_export(self, line: str) -> None:
        """
        Export data to CSV. Secrets are never written; the keyring reference is
        exported instead.
        Usage: export creds <file> | export accounts <file>
        :param line:
        """

        args: list[str] = line.split()
        if len(args) < 2:
            stonksmith_logger.fail(msg="Usage: export creds|accounts <file>")
            return

        category: str = args[0].lower()
        filename: str = args[1]

        if category == "creds":
            rows: list[tuple[object, ...]] = self.db.get_credential_refs()
            headers: Sequence[str] = ("ID", "User", "KeyringRef", "Type", "Source")

        elif category == "accounts":
            rows = self.db.get_account_data()
            headers = ("ID", "Account", "Balance", "Updated")

        else:
            stonksmith_logger.fail(msg=f"Unknown category {category}")
            return

        helper_db.write_csv(filename=filename, headers=headers, entries=rows)
        stonksmith_logger.success(msg=f"Exported {category} to {filename}")

    def do_show(self, line: str) -> None:
        """
        Show data in a table. Secrets are masked unless audit_mode is enabled.
        Usage: show creds | show accounts
        :param line:
        """

        category: str = line.strip().lower()

        if category == "creds":
            data: list[tuple[object, ...]] = self.db.get_credentials()
            table_data: list[list[str]] = [["ID", "User", "Pass", "Type", "Source"]]

            for row in data:
                cells: list[str] = [str(object=value) for value in row]
                # Position 2 is the resolved secret; never print it verbatim.
                if len(cells) > 2:
                    cells[2] = process_secret(text=cells[2])
                table_data.append(cells)

            helper_db.print_table(data=table_data, title=f"{self.broker} Credentials")

        elif category == "accounts":
            accounts: list[tuple[object, ...]] = self.db.get_account_data()
            account_table: list[list[str]] = [["ID", "Account", "Balance", "Updated"]]
            account_table.extend(
                [str(object=value) for value in row] for row in accounts
            )
            helper_db.print_table(data=account_table, title=f"{self.broker} Accounts")

        else:
            stonksmith_logger.fail(msg="Usage: show creds|accounts")
