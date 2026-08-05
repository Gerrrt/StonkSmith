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
from etc.context import BrokerDbProtocol, Context
from helpers.schwab529plan import account_label, clean_up
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

        if not callable(getattr(db, "save_account_data", None)):
            context.log.fail(
                msg="DB contract violation: context.db does not implement "
                "save_account_data. Skipping DB save.",
            )
            db_ok = False
        else:
            for index, item in enumerate(balances):
                db.save_account_data(
                    account_name=account_label(
                        beneficiaries=beneficiaries, balance=item, index=index
                    ),
                    balance=item.get("Amount"),
                    timestamp=timestamp,
                )

        # 5. Sync: Push clean data to Google Sheets

        sheets_ok: bool = True

        try:
            context.log.highlight(msg="Syncing data to Google Sheets...")

            saver = Saver()

            saver.save_beneficiary(data=beneficiaries)
            saver.save_balance(data=balances)
            saver.save_investment(data=investments)
            saver.save_transactions(data=transactions)

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
