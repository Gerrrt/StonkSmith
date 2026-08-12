# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Module to login and scrape data from https://www.schwab529plan.com."""

import datetime
from collections.abc import Callable
from typing import Any, ClassVar

from requests import Response
from requests.exceptions import RequestException

from brokers.schwab529plan.parser import Parser
from etc.connection import Connection
from etc.context import BrokerDbProtocol, Context, SnapshotDbProtocol
from etc.portfolio_sheet import sync
from etc.records import AccountIdentity, Holding, Transaction
from helpers.normalize import (
    to_amount,
    to_currency,
    to_iso_date,
)
from helpers.schwab529plan import (
    account_hint,
    account_label,
    beneficiary_field,
    clean_up,
    holding_from_row,
    match_account,
    transaction_from_row,
)


class Schwab529Module:
    """Module to log in and scrape data from https://www.schwab529plan.com."""

    name: str = "schwab529plan"
    description: str = "Log in and scrape account data"
    supported_brokers: ClassVar[list[str]] = ["schwab529plan"]

    def __init__(self) -> None:
        """Initialize the class attributes."""
        self.export_format: str | None = "print"
        self.login_url = "https://www.schwab529plan.com/swatpl/aggregator/sessionCreate/collectAggrCredentials.cs"
        self.dashboard_url = "https://www.schwab529plan.com/swatpl/aggregator/overview/viewAggrOverview.cs"

    def options(
        self, context: Context | None, module_options: dict[str, Any] | None = None
    ) -> None:
        """Set up module options, such as export format.

        Args:
            context (Context | None): Execution context supplied by ModuleLoader.
            Unused today, but part of the module contract.
            module_options (dict[str, Any] | None): Optional dictionary of
            module-specific options.

        """
        del context
        options: dict[str, Any] = module_options or {}
        self.export_format: Any = options.get("EXPORT", "print")

    @staticmethod
    def holdings_for(investments: list[dict[str, Any]], index: int) -> list[Holding]:
        """Collect the fund rows belonging to one account.

        The page renders one fund table per account in the same order as the
        balance headings, and the parser stamps each row with the index of the
        table it came from -- so this is the pairing, not a guess.

        Args:
            investments (list[dict[str, Any]]): Parsed fund rows.
            index (int): Position of the account being saved.

        Returns:
            list[Holding]: That account's holdings, in page order.

        """
        return [
            holding_from_row(row=row)
            for row in investments
            if row.get("Table") == index
        ]

    @staticmethod
    def account_candidates(
        beneficiaries: list[dict[str, Any]], balances: list[dict[str, Any]]
    ) -> list[list[str]]:
        """Collect every string that identifies each account on the page.

        What a transaction row calls an account and what the balance headings
        call it need not be the same word: a row might name the beneficiary, or
        print a masked account number. All three known spellings go into the
        pool and ``match_account`` decides.

        Args:
            beneficiaries (list[dict[str, Any]]): Parsed beneficiary rows.
            balances (list[dict[str, Any]]): Parsed balance rows, one per account.

        Returns:
            list[list[str]]: Identifying strings per account, in balance order.

        """
        return [
            [
                value
                for value in (
                    account_label(
                        beneficiaries=beneficiaries, balance=item, index=index
                    ),
                    beneficiary_field(
                        beneficiaries=beneficiaries, index=index, key="Name"
                    ),
                    beneficiary_field(
                        beneficiaries=beneficiaries, index=index, key="Account"
                    ),
                )
                if value
            ]
            for index, item in enumerate(balances)
        ]

    @classmethod
    def attribute_transactions(
        cls,
        transactions: list[dict[str, Any]],
        balances: list[dict[str, Any]],
        context: Context,
        beneficiaries: list[dict[str, Any]] | None = None,
        structure: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> dict[int, list[Transaction]]:
        """Work out which account each scraped transaction belongs to.

        Four rules, tried in order and each weaker than the one before:

        1. **The page said so.** A row that carries an account -- in a column, a
           section heading above it, an attribute, or its table's caption --
           goes to the account it names. Rows whose marker matches nothing, or
           matches two accounts, are dropped and reported: the ones that did
           match are still correct, and throwing them away as well would lose
           real history to protect nothing.
        2. **One table per account.** Failing that, when the page renders as
           many transaction tables as it shows balances, they pair by position
           -- the same rule ``holdings_for`` already applies to the fund tables,
           which the page renders the same way.
        3. **One account.** Failing that, a page showing a single balance has
           only one answer.
        4. **Nothing.** Otherwise none are stored and the run says so. Attaching
           them all to the first account invents history for it, and copying
           them to each invents history for every account. Both look completely
           plausible afterwards, which is what makes them worse than an empty
           table and a message.

        Not fatal in any case. The balances and holdings are the run's main
        product and they are unaffected.

        Args:
            transactions (list[dict[str, Any]]): Parsed transaction rows.
            balances (list[dict[str, Any]]): Parsed balance rows, one per account.
            context (Context): Used for logging.
            beneficiaries (list[dict[str, Any]] | None): Parsed beneficiary rows,
            used to recognise an account a row names.
            structure (Callable[[], list[dict[str, Any]]] | None): Reads the
            shape of the transaction markup. Deferred rather than a value
            because it walks every row, and it is only ever wanted on the paths
            where attribution falls short -- which is neither the single-account
            path nor the one where the page names its accounts.

        Returns:
            dict[int, list[Transaction]]: Transactions keyed by the position of
            the account they belong to. Accounts with none are absent.

        """
        if not transactions:
            return {}

        candidates: list[list[str]] = cls.account_candidates(
            beneficiaries=beneficiaries or [], balances=balances
        )
        tables: list[int] = sorted(
            {row["Table"] for row in transactions if row.get("Table") is not None}
        )

        # A table's caption identifies an account only when the page renders a
        # table per account. One table covering everybody, captioned with one
        # beneficiary's name, would hand that beneficiary everybody's history --
        # exactly the invention this whole function exists to refuse.
        keys: tuple[str, ...] = (
            ("Account", "Section")
            if len(tables) <= 1 and len(balances) > 1
            else ("Account", "Section", "Title")
        )

        # 1. The page named the account.
        named: dict[int, list[Transaction]] = {}
        unresolved: list[str] = []

        for row in transactions:
            hint: str | None = account_hint(row=row, keys=keys)

            if hint is None:
                unresolved.append("")
                continue

            index: int | None = match_account(hint=hint, candidates=candidates)

            if index is None:
                unresolved.append(hint)
                continue

            named.setdefault(index, []).append(transaction_from_row(row=row))

        if named:
            if unresolved:
                cls._report_unattributed(
                    context=context,
                    count=len(unresolved),
                    total=len(transactions),
                    hints=unresolved,
                    structure=structure,
                )

            return dict(sorted(named.items()))

        # 2. One table per account, in the same order as the balances.
        if len(tables) > 1 and len(tables) == len(balances):
            context.log.highlight(
                msg=(
                    f"The transaction history is split into {len(tables)} tables "
                    f"and the page shows {len(balances)} accounts, so each table "
                    "was read as that account's history -- the same pairing the "
                    "fund tables use. No row named its own account."
                ),
            )

            paired: dict[int, list[Transaction]] = {}

            for position, table in enumerate(iterable=tables):
                rows: list[Transaction] = [
                    transaction_from_row(row=row)
                    for row in transactions
                    if row.get("Table") == table
                ]

                if rows:
                    paired[position] = rows

            return paired

        # 3. A single account on the page leaves one answer.
        if len(balances) == 1:
            return {0: [transaction_from_row(row=row) for row in transactions]}

        # 4. No honest attribution.
        context.log.fail(
            msg=(
                f"{len(transactions)} transaction(s) were scraped but the "
                f"page shows {len(balances)} accounts and the transaction "
                "table does not say which account each row belongs to. "
                "None were stored. Balances and holdings are unaffected."
            ),
        )
        cls._log_structure(context=context, structure=structure)

        return {}

    @classmethod
    def _report_unattributed(
        cls,
        context: Context,
        count: int,
        total: int,
        hints: list[str],
        structure: Callable[[], list[dict[str, Any]]] | None,
    ) -> None:
        """Say which rows were dropped when only some could be attributed.

        The rows that did match are stored, so this is not the run failing; it
        is the part of the history that is missing, named rather than left to be
        noticed as a gap months later.

        Args:
            context (Context): Used for logging.
            count (int): How many rows could not be attributed.
            total (int): How many were scraped.
            hints (list[str]): What those rows said about their account.
            structure (Callable[[], list[dict[str, Any]]] | None): Reads the
            markup's shape.

        """
        distinct: list[str] = sorted({hint for hint in hints if hint})
        named: str = (
            f" They named: {', '.join(distinct)}."
            if distinct
            else " They named no account at all."
        )

        context.log.fail(
            msg=(
                f"{count} of {total} transaction(s) could not be matched to an "
                f"account on the page and were not stored.{named} The other "
                f"{total - count} were stored against the account they name."
            ),
        )
        cls._log_structure(context=context, structure=structure)

    @staticmethod
    def _log_structure(
        context: Context, structure: Callable[[], list[dict[str, Any]]] | None
    ) -> None:
        """Print the shape of the transaction markup, values excluded.

        Issue #36's blocking question is what a multi-beneficiary transaction
        table actually renders, and it can only be answered from a live login.
        Printing the shape whenever attribution falls short answers it from a
        run somebody was doing anyway.

        Args:
            context (Context): Used for logging.
            structure (Callable[[], list[dict[str, Any]]] | None): Reads one
            entry per table. Called here and nowhere else, so a run that
            attributes cleanly never walks the markup a second time.

        """
        if structure is None:
            return

        tables: list[dict[str, Any]] = structure()

        if not tables:
            return

        context.log.highlight(
            msg=(
                "Transaction markup, so the next version can attribute these "
                "(no cell values are shown):"
            ),
        )

        for table in tables:
            context.log.highlight(
                msg=(
                    f"  table {table.get('Table')}: "
                    f"caption={table.get('Caption')!r} "
                    f"headers={table.get('Headers')} "
                    f"rows={table.get('Rows')} "
                    f"cells-per-row={table.get('Widths')} "
                    f"attributes={table.get('Attributes')}"
                ),
            )

    def on_login(self, context: Context, connection: Connection) -> bool:
        """Perform the login and scraping process for Schwab529Plan.

        Args:
            context (Context): The execution context, providing access to logging,
            database, and other shared resources.
            connection (Connection): The connection object containing session and
            authentication details for the broker.

        Returns:
            bool: False when nothing reached the database.

        """
        context.log.highlight(msg=f"Starting Schwab529 sync for: {connection.username}")

        # 1. Scrape: Use session from broker

        try:
            response: Response = connection.session.get(url=self.dashboard_url)
            if not response.ok:
                context.log.fail(msg="Could not access Schwab529plan dashboard")
                return False

            if self._looks_like_login_page(response=response):
                context.log.fail(
                    msg=(
                        "Authenticated session not established: received login page "
                        f"instead of dashboard (url={response.url})."
                    ),
                )
                return False

        except RequestException as e:
            context.log.exception(
                msg="Exception during Schwab529plan account scrape",
                extra={"error": str(e)},
            )
            return False

        # 2. Parse

        schwab529_parser: Parser = Parser(response=response)

        raw_beneficiaries: list[dict[str, str | None]] = (
            schwab529_parser.beneficiary_data()
        )
        raw_balances: list[dict[str, str | None]] = schwab529_parser.balance_data()
        raw_investments: list[dict[str, str | None]] = (
            schwab529_parser.investment_data()
        )
        raw_transactions: list[dict[str, str | None]] = (
            schwab529_parser.transaction_data()
        )

        # 3. Clean

        beneficiaries: Any = clean_up(data=raw_beneficiaries)
        balances: Any = clean_up(data=raw_balances)
        investments: Any = clean_up(data=raw_investments)
        transactions: Any = clean_up(data=raw_transactions)

        # 4. Save to local database

        context.log.highlight(msg="Updating local broker database...")
        timestamp: str = datetime.datetime.now(tz=datetime.UTC).strftime(
            format="%Y-%m-%d %H:%M:%S",
        )

        db: BrokerDbProtocol = context.db
        db_ok: bool = True

        if isinstance(db, SnapshotDbProtocol):
            attributed: dict[int, list[Transaction]] = self.attribute_transactions(
                transactions=transactions,
                balances=balances,
                context=context,
                beneficiaries=beneficiaries,
                structure=schwab529_parser.transaction_structure,
            )

            for index, item in enumerate(balances):
                amount: Any = item.get("Amount")

                db.save_snapshot(
                    account=AccountIdentity(
                        # The label the pre-history schema stored, unchanged, so
                        # a user's existing rows and this one are the same
                        # account rather than two.
                        account_key=account_label(
                            beneficiaries=beneficiaries, balance=item, index=index
                        ),
                        display_name=account_label(
                            beneficiaries=beneficiaries, balance=item, index=index
                        ),
                        external_id=beneficiary_field(
                            beneficiaries=beneficiaries, index=index, key="Account"
                        ),
                        beneficiary=beneficiary_field(
                            beneficiaries=beneficiaries, index=index, key="Name"
                        ),
                        kind="529",
                    ),
                    scraped_at=timestamp,
                    # The balance heading carries the date the plan struck the
                    # value, which is not when this run happened to read it.
                    as_of=to_iso_date(item.get("Date")),
                    value=to_amount(amount),
                    currency=to_currency(amount),
                    raw_value=str(object=amount) if amount is not None else None,
                    holdings=self.holdings_for(investments=investments, index=index),
                    # An account receives only the rows attribute_transactions
                    # could show belong to it, which for a page that names no
                    # account at all is none of them.
                    transactions=attributed.get(index, ()),
                )

        elif callable(getattr(db, "save_account_data", None)):
            for index, item in enumerate(balances):
                db.save_account_data(
                    account_name=account_label(
                        beneficiaries=beneficiaries, balance=item, index=index
                    ),
                    balance=item.get("Amount"),
                    timestamp=timestamp,
                )

        else:
            context.log.fail(
                msg="DB contract violation: context.db does not implement "
                "save_account_data. Skipping DB save.",
            )
            db_ok = False

        # 5. Sync: Push clean data to Google Sheets

        sheets_ok: bool = sync(context=context)

        if db_ok and sheets_ok:
            context.log.success(msg="Schwab529Plan sync complete.")
        elif db_ok:
            # Still success level: the data landed, so the run succeeded and
            # exits 0. Only the wording changes -- claiming "complete" directly
            # after "Google Sheets sync failed" was the lie.
            context.log.success(
                msg="Schwab529Plan data saved locally; the dashboard was not updated."
            )

        # A DB contract violation already reported itself at fail level; a
        # summary line here would only restate it more vaguely.
        return db_ok

    @staticmethod
    def _looks_like_login_page(response: Response) -> bool:
        """Check if the response looks like a login page rather than a dashboard.

        Args:
            response (Response): The HTTP response to check.

        Returns:
            bool: True if the response appears to be a login page, False otherwise.

        """
        response_url: str = str(object=response.url).lower()
        if "collectaggrcredentials.cs" in response_url:
            return True

        body_lc: str = response.text.lower()
        return "struts.token.name" in body_lc and "passcode" in body_lc
