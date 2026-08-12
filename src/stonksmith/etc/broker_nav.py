# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Shared ``stonksmithdb`` sub-shell for browsing a broker's database.

Each broker package exposes a ``DatabaseNavigator`` in ``db_navigator.py``, which
BrokerLoader imports by file path. The commands are identical across brokers, so
they live here.

Secrets are masked on display and omitted from exports; the keyring reference is
exported instead.
"""

import cmd
import sys
import typing
from collections.abc import Sequence
from getpass import getpass

from stonksmith.etc.config import process_secret
from stonksmith.etc.exceptions import SwitchBroker, UserExitedProto
from stonksmith.etc.logger import stonksmith_logger
from stonksmith.helpers import db as helper_db
from stonksmith.helpers.normalize import format_amount

#: Column headers for each thing the shell can show or export, in the order the
#: corresponding read method returns them. One place, so `show` and `export`
#: cannot drift apart about what a column means or where it sits.
#:
#: This is the *export* contract: everything the reader returns. `show` renders
#: a subset of it, named in SHOW_COLUMNS below and selected from these rather
#: than written out separately -- which is what keeps the sentence above true
#: while letting a terminal decline a column it cannot fit.
CATEGORY_HEADERS: dict[str, tuple[str, ...]] = {
    "creds": ("ID", "User", "Pass", "Type", "Source"),
    "accounts": ("ID", "Source", "Account", "Beneficiary", "Kind", "Last Seen"),
    "snapshots": ("ID", "Account", "As Of", "Scraped", "Value", "Currency"),
    "holdings": (
        "Account",
        "Symbol",
        "Name",
        "Units",
        "Price",
        "Value",
        "Principal",
        "Earnings",
        "Cost Basis",
        "Currency",
        "Units As Of",
    ),
    "transactions": (
        "ID",
        "Account",
        "Processed",
        "Traded",
        "Type",
        "Symbol",
        "Description",
        "Units",
        "Price",
        "Value",
        "Currency",
        "First Seen",
        "External Id",
        "Natural Key",
        "Raw Value",
    ),
    "deltas": (
        "Account",
        "As Of",
        "Scraped",
        "Value",
        "Previous",
        "Change",
        "Currency",
    ),
}

#: Which read method backs each history category.
HISTORY_READERS: dict[str, str] = {
    "accounts": "get_accounts",
    "snapshots": "get_snapshots",
    "holdings": "get_holdings",
    "transactions": "get_transactions",
    "deltas": "get_daily_change",
}

#: Which columns `show` prints, per category. A category absent from here prints
#: all of them, which is every category but one.
#:
#: `transactions` omits three, all of them for width. print_table hands rows to
#: tabulate with no limit and nothing here truncates a cell, so one long value
#: turns the whole grid into wrapped soup. Description is free text a source
#: wrote and SnapTrade's runs to a sentence; Natural Key is a whole row's text
#: pipe-joined, so it is as wide as the row it keys; Raw Value is whatever the
#: source printed, bounded by nothing. Everything else the tab shows is bounded
#: and stays -- First Seen is a timestamp, External Id is an id -- and twelve
#: columns is the width `holdings` has always run at.
#:
#: The last two are also the two the tab does not have, and that asymmetry is
#: the point rather than an oversight. Sheets is a view of what stonksmithdb
#: reports, which is a floor and not a ceiling: every column the tab shows must
#: be reachable from here, while a column that only answers "why did this row
#: not dedup" has no business on a portfolio tab and every business in a CSV
#: pulled to find out.
#:
#: Dropping a column is not free, and do_show says so out loud rather than
#: quietly handing back a narrower table than the export contract promises. A
#: column missing without mention is the same fault as a row count that stops
#: without mention.
SHOW_COLUMNS: dict[str, tuple[str, ...]] = {
    "transactions": (
        "ID",
        "Account",
        "Processed",
        "Traded",
        "Type",
        "Symbol",
        "Units",
        "Price",
        "Value",
        "Currency",
        "First Seen",
        "External Id",
    ),
}

#: How many rows `show` prints, per category. A category absent from here has no
#: cap -- `accounts` is one row per account and its reader takes no limit.
#:
#: The numbers are the ones these reads have always used; what is new is that
#: the shell states the cap rather than inheriting four different ones from the
#: database layer without knowing it. That mattered because `export` inherited
#: them too, and wrote a five-hundred-row CSV that looked like a whole file.
#: Printing is a screenful and a cap is a courtesy; a file is not, so `export`
#: passes None and these do not apply to it.
SHOW_LIMITS: dict[str, int] = {
    "snapshots": 100,
    "holdings": 500,
    "transactions": 500,
    "deltas": 100,
}

#: Columns holding money, per category, so a stored number is shown as currency
#: rather than as a bare float.
#:
#: Named rather than numbered, which they were until a column had to go into the
#: middle of one of these tuples. A position is not a fact about a column; it is
#: a fact about every column to its left. Inserting "Description" after "Symbol"
#: moved Price, Value and Currency along by one, and the old (7, 8) then
#: formatted Symbol and Units as money and read the currency off Value -- with
#: nothing to notice, since a number formats as currency perfectly well.
#:
#: etc.portfolio_sheet reached the same conclusion for the same reason and its
#: column_of() says so: "Every formula in this module is built through here
#: rather than typed. That is the whole of what makes them append-only-safe."
MONEY_HEADERS: dict[str, tuple[str, ...]] = {
    "snapshots": ("Value",),
    # Not "Units": a quantity is a count, not money, and (4, 5, 6, 7, 8) began
    # one past it for exactly that reason.
    "holdings": ("Price", "Value", "Principal", "Earnings", "Cost Basis"),
    "transactions": ("Price", "Value"),
    "deltas": ("Value", "Previous", "Change"),
}

#: Which column carries the currency code, so a CAD balance is not rendered with
#: a "$". Named for the same reason as the tuples above.
CURRENCY_HEADER: dict[str, str] = {
    "snapshots": "Currency",
    "holdings": "Currency",
    "transactions": "Currency",
    "deltas": "Currency",
}

#: Which categories accept an id to narrow by, and what that id means. A
#: category absent from here takes no argument at all -- `accounts` is one row
#: per account already, and `deltas` spans every account by definition.
#:
#: Stated as data rather than as a chain of ifs because the two ways of getting
#: it wrong are both silent-ish: passing the filter to a reader that does not
#: take one is a TypeError out of a cmd loop that catches nothing, and dropping
#: the filter on the floor renders the full table in a way that looks exactly
#: like a filter that matched everything.
HISTORY_FILTERS: dict[str, str] = {
    "snapshots": "account_id",
    "holdings": "snapshot_id",
    "transactions": "account_id",
}

#: What `delete` can remove, as {word: (method, keyword)}.
#:
#: Snapshots are here because a wrong mark is not self-correcting. The next sync
#: adds a row beside it rather than replacing it -- snapshots record what was
#: observed when -- so a placeholder typed into a command line, or a real number
#: computed from mismatched inputs, stays in every chart drawn from the table
#: until it is removed by hand.
#:
#: Accounts are deliberately absent. Deleting one cascades away every snapshot
#: under it, which is the opposite of the narrow correction this is for, and the
#: next run would recreate the account anyway.
DELETERS: dict[str, tuple[str, str]] = {
    "creds": ("delete_credential", "cred_id"),
    "snapshot": ("delete_snapshot", "snapshot_id"),
}


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
            "    show creds               credentials, masked\n"
            "    show accounts            the accounts this broker knows\n"
            "    show snapshots [<acct>]  what each account was worth, over time\n"
            "    show holdings [<snap>]   the positions behind a snapshot\n"
            "    show transactions [<acct>]  recorded movements\n"
            "    show deltas              the change between consecutive snapshots\n"
            "    export creds <file>      write a CSV (never includes secrets)\n"
            "    export <category> <file> also accounts, snapshots, holdings,\n"
            "                             transactions or deltas -- the whole\n"
            "                             table, however long, unlike show\n"
            "    delete creds <id>        remove a credential\n"
            "    delete snapshot <id>     remove one wrong mark and its holdings\n"
            "    broker <name>            switch straight to another broker\n"
            "    brokers                  leave and list the available brokers\n"
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
        Switch straight to another broker, no `back` required. With no name,
        leaves this broker and lists the available ones.
        Usage: broker [<name>]
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
        Delete a credential, or a single snapshot and its holdings.
        Usage: delete creds <id> | delete snapshot <id>
        :param line:
        """

        args: list[str] = line.split()
        target: str = args[0].lower() if args else ""

        if len(args) < 2 or target not in DELETERS:
            stonksmith_logger.fail(
                msg=f"Usage: {' | '.join(f'delete {name} <id>' for name in DELETERS)}"
            )
            return

        try:
            row_id: int = int(args[1])

        except ValueError:
            stonksmith_logger.fail(msg=f"Not a {target} id: {args[1]}")
            return

        method, parameter = DELETERS[target]
        remove = getattr(self.db, method, None)

        # Probed for the same reason history_rows() probes its readers: a
        # database written against the older contract has no snapshot tables at
        # all, and saying so beats an AttributeError.
        if not callable(remove):
            stonksmith_logger.fail(
                msg=(
                    f"This broker's database cannot delete a {target}. "
                    "Re-run a sync to build the newer tables."
                )
            )
            return

        if remove(**{parameter: row_id}):
            stonksmith_logger.success(msg=f"Deleted {target} {row_id}")
        else:
            stonksmith_logger.fail(msg=f"No {target} with id {row_id}")

    def history_rows(
        self, category: str, argument: str = "", limit: int | None = None
    ) -> list[tuple[object, ...]] | None:
        """
        Read one of the history tables, or explain why it cannot be read.

        Probed rather than assumed, the way every other optional capability
        here is: a database written against the older contract has no snapshot
        tables, and saying so beats an AttributeError.

        ``limit`` defaults to None, meaning everything, and a caller that wants
        less has to say so. That is deliberately the opposite way round from
        how this read: it used to call the reader with no arguments and take
        whatever default the database happened to carry, which is how ``export``
        came to write a five-hundred-row CSV and report success. A cap is a
        display choice, so it belongs to the thing doing the displaying.
        :param category: One of HISTORY_READERS
        :param argument: An optional account or snapshot id to filter on
        :param limit: How many rows at most, or None for all of them
        :return: The rows, or None when this database cannot answer
        :rtype: list[tuple[object, ...]] | None
        """

        reader = getattr(self.db, HISTORY_READERS[category], None)

        if not callable(reader):
            stonksmith_logger.fail(
                msg=(
                    f"This broker's database predates account history, so there "
                    f"are no {category} to show. Re-run a sync to build them."
                )
            )
            return None

        # get_accounts takes no limit at all -- one row per account is already
        # the whole of it -- so it is called the way it always was.
        capped: dict[str, typing.Any] = (
            {} if category not in SHOW_LIMITS else {"limit": limit}
        )

        if not argument:
            return list(reader(**capped))

        parameter: str | None = HISTORY_FILTERS.get(category)

        if parameter is None:
            # Refused rather than dropped. Ignoring it would render the whole
            # table, which looks exactly like a filter that matched everything.
            stonksmith_logger.fail(
                msg=(
                    f"'show {category}' takes no id. Narrow with "
                    f"{' or '.join(f'show {name} <id>' for name in HISTORY_FILTERS)}."
                )
            )
            return None

        try:
            target: int = int(argument)

        except ValueError:
            stonksmith_logger.fail(msg=f"Not an id: {argument}")
            return None

        return list(reader(**{parameter: target}, **capped))

    @staticmethod
    def render(category: str, rows: Sequence[Sequence[object]]) -> list[list[str]]:
        """
        Turn stored rows into display cells, money included.

        A stored value is a number. Printing it raw shows "1234.56" where every
        other surface in StonkSmith shows "$1,234.56", and shows a CAD balance
        wearing a dollar sign if the currency column is ignored.

        Which columns those are is looked up by name every call rather than
        stored as positions. See MONEY_HEADERS for why. A name the contract does
        not have raises here rather than being skipped: a source that gave no
        number is an ordinary thing and is handled below, but a header this
        module asked for and cannot find is a typo, and formatting nothing is
        indistinguishable from formatting correctly.
        :param category: Which table these rows came from
        :param rows: The rows
        :return: One list of cells per row
        :rtype: list[list[str]]
        :raises KeyError: if a money or currency header is not in the contract
        """

        headers: tuple[str, ...] = CATEGORY_HEADERS[category]

        def position(name: str) -> int:
            """
            Where a named column sits in this category's contract.
            :param name: The header, exactly as CATEGORY_HEADERS spells it
            :return: Its index
            :rtype: int
            :raises KeyError: if the contract has no such column
            """

            try:
                return headers.index(name)

            except ValueError as e:
                raise KeyError(f"no column named {name!r} in {list(headers)}") from e

        money_at: tuple[int, ...] = tuple(
            position(name=name) for name in MONEY_HEADERS.get(category, ())
        )
        currency_name: str | None = CURRENCY_HEADER.get(category)
        currency_at: int | None = (
            None if currency_name is None else position(name=currency_name)
        )

        rendered: list[list[str]] = []

        for row in rows:
            currency: object = (
                row[currency_at]
                if currency_at is not None and currency_at < len(row)
                else "USD"
            )

            cells: list[str] = [
                format_amount(value, currency)
                if index in money_at and value is not None
                else ("" if value is None else str(object=value))
                for index, value in enumerate(row)
            ]
            rendered.append(cells)

        return rendered

    def do_export(self, line: str) -> None:
        """
        Export data to CSV. Secrets are never written; the keyring reference is
        exported instead.

        Writes everything, and says how many rows that was. Both halves matter:
        this used to inherit whatever cap the reader carried -- a hundred
        snapshots, five hundred movements -- and print "Exported transactions"
        over a file that was missing most of them. A short file is invisible
        once it is on disk, so the count is the only thing that could have said.
        Usage: export creds|accounts|snapshots|holdings|transactions|deltas <file>
        :param line:
        """

        args: list[str] = line.split()
        if len(args) < 2:
            stonksmith_logger.fail(
                msg=(
                    "Usage: export creds|accounts|snapshots|holdings|"
                    "transactions|deltas <file>"
                )
            )
            return

        category: str = args[0].lower()
        filename: str = args[1]

        if category == "creds":
            rows: list[tuple[object, ...]] = self.db.get_credential_refs()
            headers: Sequence[str] = ("ID", "User", "KeyringRef", "Type", "Source")

        elif category in HISTORY_READERS:
            # None, explicitly: a file is not a screenful, and nothing reading
            # the CSV afterwards could tell it had been cut short.
            found = self.history_rows(category=category, limit=None)

            if found is None:
                return

            rows = found
            headers = CATEGORY_HEADERS[category]

        else:
            stonksmith_logger.fail(msg=f"Unknown category {category}")
            return

        helper_db.write_csv(filename=filename, headers=headers, entries=rows)
        stonksmith_logger.success(msg=f"Exported {len(rows)} {category} to {filename}")

    def do_show(self, line: str) -> None:
        """
        Show data in a table. Secrets are masked unless audit_mode is enabled.
        Usage: show creds | accounts | snapshots | holdings | transactions | deltas
        :param line:
        """

        parts: list[str] = line.strip().lower().split()
        category: str = parts[0] if parts else ""
        argument: str = parts[1] if len(parts) > 1 else ""

        if category == "creds":
            data: list[tuple[object, ...]] = self.db.get_credentials()
            table_data: list[list[str]] = [list(CATEGORY_HEADERS["creds"])]

            for row in data:
                cells: list[str] = [str(object=value) for value in row]
                # Position 2 is the resolved secret; never print it verbatim.
                if len(cells) > 2:
                    cells[2] = process_secret(text=cells[2])
                table_data.append(cells)

            helper_db.print_table(data=table_data, title=f"{self.broker} Credentials")

        elif category in HISTORY_READERS:
            cap: int | None = SHOW_LIMITS.get(category)
            # One more than will be printed. That extra row is never displayed;
            # it is how this knows there *are* more without a second count
            # query, which makes the notice below a fact rather than a guess.
            # A table of exactly `cap` rows says nothing, and is right to.
            rows = self.history_rows(
                category=category,
                argument=argument,
                limit=None if cap is None else cap + 1,
            )

            if rows is None:
                return

            more: bool = cap is not None and len(rows) > cap
            shown: Sequence[Sequence[object]] = rows if cap is None else rows[:cap]

            # Rendered at full width first, then narrowed. render() finds its
            # money and currency columns by name against the export contract,
            # so formatting has to happen before any column is taken away.
            headers: tuple[str, ...] = CATEGORY_HEADERS[category]
            display: tuple[str, ...] = SHOW_COLUMNS.get(category, headers)
            keep: list[int] = [headers.index(name) for name in display]

            table: list[list[str]] = [list(display)]
            table.extend(
                [cells[index] for index in keep]
                for cells in self.render(category=category, rows=shown)
            )

            helper_db.print_table(
                data=table, title=f"{self.broker} {category.capitalize()}"
            )

            if more:
                stonksmith_logger.highlight(
                    msg=(
                        f"Showing the first {cap} {category}; there are more. "
                        f"'export {category} <file>' writes all of them."
                    )
                )

            dropped: list[str] = [name for name in headers if name not in display]

            if dropped:
                stonksmith_logger.highlight(
                    msg=(
                        f"{', '.join(dropped)} {'is' if len(dropped) == 1 else 'are'} "
                        f"too wide for a terminal and not shown; "
                        f"'export {category} <file>' includes "
                        f"{'it' if len(dropped) == 1 else 'them'}."
                    )
                )

        else:
            stonksmith_logger.fail(
                msg=(
                    "Usage: show creds|accounts|snapshots|holdings|transactions|deltas"
                )
            )
