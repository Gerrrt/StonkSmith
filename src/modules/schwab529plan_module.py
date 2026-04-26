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
from helpers.schwab529plan import clean_up


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

    def options(self, _: str, module_options: dict[str, Any] | None = None) -> None:
        """Set up module options, such as export format.

        Args:
            _: str: Placeholder for potential future use (e.g., context or config).
            module_options (dict[str, Any] | None): Optional dictionary of
            module-specific options.

        """
        options: dict[str, Any] = module_options or {}
        self.export_format: Any = options.get("EXPORT", "print")

    def on_login(self, context: Context, connection: Connection) -> None:
        """Perform the login and scraping process for Schwab529Plan.

        Args:
            context (Context): The execution context, providing access to logging,
            database, and other shared resources.
            connection (Connection): The connection object containing session and
            authentication details for the broker.

        """
        context.log.highlight(msg=f"Starting Schwab529 sync for: {connection.username}")

        # 1. Scrape: Use session from broker

        try:
            response: Response = connection.session.get(url=self.dashboard_url)
            if not response.ok:
                context.log.fail(msg="Could not access Schwab529plan dashboard")
                return

            if self._looks_like_login_page(response=response):
                context.log.fail(
                    msg=(
                        "Authenticated session not established: received login page "
                        f"instead of dashboard (url={response.url})."
                    ),
                )
                return

        except RequestException as e:
            context.log.exception(
                msg="Exception during Schwab529plan account scrape",
                extra={"error": str(e)},
            )
            return

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
        if not callable(getattr(db, "save_account_data", None)):
            context.log.fail(
                msg="DB contract violation: context.db does not implement "
                "save_account_data. Skipping DB save.",
            )
        else:
            for item in balances:
                db.save_account_data(
                    account_name=item.get("Title"),
                    balance=item.get("Amount"),
                    timestamp=timestamp,
                )

        # 5. Sync: Push clean data to Google Sheets

        try:
            context.log.highlight(msg="Syncing data to Google Sheets...")

            saver = Saver()

            saver.save_beneficiary(data=beneficiaries)
            saver.save_balance(data=balances)
            saver.save_investment(data=investments)
            saver.save_transactions(data=transactions)

            context.log.success(msg="Google Sheets updated successfully!")

        except OSError as e:
            context.log.fail(msg=f"Google Sheets sync failed: {e}")

        context.log.success(msg="Schwab529Plan sync complete.")

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
