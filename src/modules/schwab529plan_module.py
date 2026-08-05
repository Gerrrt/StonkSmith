# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Module to login and scrape data from https://www.schwab529plan.com."""

import datetime
from typing import Any, ClassVar

from requests import Response
from requests.exceptions import RequestException

from brokers.schwab529plan.parser import Parser
from brokers.schwab529plan.saver import Saver
from etc.connection import Connection
from etc.context import BrokerDbProtocol, Context, SnapshotDbProtocol
from etc.records import AccountIdentity, Holding, Transaction
from helpers.normalize import (
    format_amount,
    format_units,
    to_amount,
    to_currency,
    to_iso_date,
)
from helpers.schwab529plan import (
    account_label,
    beneficiary_field,
    clean_up,
    holding_from_row,
    transaction_from_row,
)
from helpers.sheets import SheetsUnavailable


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
    def attribute_transactions(
        transactions: list[dict[str, Any]],
        balances: list[dict[str, Any]],
        context: Context,
    ) -> list[Transaction]:
        """Decide whether the scraped transactions can be assigned to an account.

        The dashboard renders one transaction table for the whole page, with
        nothing in it naming the account a row belongs to. With a single account
        on the page there is only one answer. With several there is no honest
        one: attaching them all to the first invents history for it, and copying
        them to each invents history for every account. Both look completely
        plausible afterwards, which is what makes them worse than storing
        nothing and saying so.

        Not fatal. The balances and holdings are the run's main product and they
        are unaffected.

        Args:
            transactions (list[dict[str, Any]]): Parsed transaction rows.
            balances (list[dict[str, Any]]): Parsed balance rows, one per account.
            context (Context): Used for logging.

        Returns:
            list[Transaction]: The transactions when they can be attributed,
            otherwise nothing.

        """
        if not transactions:
            return []

        if len(balances) != 1:
            context.log.fail(
                msg=(
                    f"{len(transactions)} transaction(s) were scraped but the "
                    f"page shows {len(balances)} accounts and the transaction "
                    "table does not say which account each row belongs to. "
                    "None were stored. Balances and holdings are unaffected."
                ),
            )
            return []

        return [transaction_from_row(row=row) for row in transactions]

    @staticmethod
    def holding_rows(
        db: BrokerDbProtocol, scraped: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Build the holdings block of the worksheet from stored rows.

        Args:
            db (BrokerDbProtocol): The broker database.
            scraped (list[dict[str, Any]]): This run's fund rows, used only when
            the database predates snapshot history.

        Returns:
            list[dict[str, Any]]: Rows in the worksheet's column order.

        """
        read = getattr(db, "get_holdings", None)

        if not callable(read):
            return list(scraped)

        return [
            {
                "Fund Code": symbol,
                "Fund": name,
                "Units": format_units(units),
                "Price": format_amount(price, currency),
                "Value": format_amount(value, currency),
                "Total Assets": format_amount(
                    (principal or 0) + (earnings or 0)
                    if principal is not None or earnings is not None
                    else None,
                    currency,
                ),
                "Principal": format_amount(principal, currency),
                "Earnings": format_amount(earnings, currency),
            }
            for (
                _account,
                symbol,
                name,
                units,
                price,
                value,
                principal,
                earnings,
                _cost_basis,
                currency,
            ) in read()
        ]

    @staticmethod
    def transaction_rows(
        db: BrokerDbProtocol, scraped: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Build the transactions block of the worksheet from stored rows.

        Args:
            db (BrokerDbProtocol): The broker database.
            scraped (list[dict[str, Any]]): This run's transaction rows, used
            only when the database predates snapshot history.

        Returns:
            list[dict[str, Any]]: Rows in the worksheet's column order.

        """
        read = getattr(db, "get_transactions", None)

        if not callable(read):
            return list(scraped)

        return [
            {
                "Processed": processed_on,
                "Traded": traded_on,
                "Type": tx_type,
                "Units": format_units(units),
                "Price": format_amount(price, currency),
                "Value": format_amount(value, currency),
            }
            for (
                _id,
                _account,
                processed_on,
                traded_on,
                tx_type,
                _symbol,
                units,
                price,
                value,
                currency,
            ) in read()
        ]

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
            attributed: list[Transaction] = self.attribute_transactions(
                transactions=transactions, balances=balances, context=context
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
                    # Only the account the transaction table can be attributed
                    # to receives them; see attribute_transactions.
                    transactions=attributed if len(balances) == 1 else (),
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

        sheets_ok: bool = True

        try:
            context.log.highlight(msg="Syncing data to Google Sheets...")

            saver = Saver()

            saver.save_beneficiary(data=beneficiaries)
            saver.save_balance(data=balances)
            saver.save_investment(data=self.holding_rows(db=db, scraped=investments))
            saver.save_transactions(
                data=self.transaction_rows(db=db, scraped=transactions)
            )

            context.log.success(msg="Google Sheets updated successfully!")

        except SheetsUnavailable as e:
            context.log.fail(msg=f"Google Sheets sync skipped: {e}")
            sheets_ok = False

        except Exception as e:
            # Deliberately broad: the scrape is already saved to the broker
            # database above, so a Sheets problem must not fail the run or bury
            # the result under a traceback from gspread/google-auth internals.
            context.log.fail(msg=f"Google Sheets sync failed: {e}")
            sheets_ok = False

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
