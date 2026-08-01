# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Module to scrape account balances from the Fidelity portfolio summary."""

import datetime
from typing import Any, ClassVar

from brokers.fidelity.saver import Saver
from etc.connection import Connection
from etc.context import BrokerDbProtocol, Context
from helpers.sheets import SheetsUnavailable

# Fidelity renders the portfolio summary with their "PVD" design system. These
# selectors are the scrape surface and are the first thing to check when a run
# returns zero accounts -- they have NOT been verified against a live session.
# `stonksmith fidelity -M fidelity -o DEBUG_DUMP=1` writes the rendered account
# region to the log so the selectors can be corrected against real markup.
ACCOUNT_ROW_SELECTORS: tuple[str, ...] = (
    "[data-testid='account-row']",
    ".acct-selector__acct-row",
    ".pvd-table__row",
)
ACCOUNT_NAME_SELECTORS: tuple[str, ...] = (
    "[data-testid='account-name']",
    ".acct-selector__acct-name",
)
ACCOUNT_BALANCE_SELECTORS: tuple[str, ...] = (
    "[data-testid='account-balance']",
    ".acct-selector__acct-balance",
)


class FidelityModule:
    """Scrape Fidelity account balances and sync them to the dashboard."""

    name: str = "fidelity"
    description: str = "Scrape account balances from the portfolio summary"
    supported_brokers: ClassVar[list[str]] = ["fidelity"]

    def __init__(self) -> None:
        """Initialize the class attributes."""
        self.export_format: str = "print"
        self.debug_dump: bool = False
        self.summary_url = "https://digital.fidelity.com/ftgw/digital/portfolio/summary"

    def options(
        self, context: Context | None, module_options: dict[str, Any] | None = None
    ) -> None:
        """Set up module options.

        Args:
            context (Context | None): Execution context supplied by ModuleLoader.
            module_options (dict[str, Any] | None): EXPORT sets the export
            format; DEBUG_DUMP=1 logs the rendered account region so the
            selectors above can be checked against live markup.

        """
        del context
        options: dict[str, Any] = module_options or {}
        self.export_format = options.get("EXPORT", "print")
        self.debug_dump = str(options.get("DEBUG_DUMP", "")).lower() in {"1", "true"}

    def on_login(self, context: Context, connection: Connection) -> None:
        """Scrape the portfolio summary and persist the balances.

        Args:
            context (Context): Logging, database, and shared resources.
            connection (Connection): The authenticated Fidelity broker, whose
            `active_page` holds the logged-in Playwright page.

        """
        context.log.highlight(msg=f"Starting Fidelity sync for: {connection.username}")

        page: Any = getattr(connection, "active_page", None)
        if page is None:
            context.log.fail(
                msg="Fidelity module requires a browser-backed connection; "
                "no active page was found."
            )
            return

        # 1. Scrape
        try:
            page.goto(url=self.summary_url)

            # Only the browser-backed brokers know how to wait out their
            # spinner; fall back to a fixed wait for anything else.
            wait_for_spinner = getattr(connection, "wait_for_loading_sign", None)
            if callable(wait_for_spinner):
                wait_for_spinner()
            else:
                page.wait_for_timeout(timeout=5000)

        except Exception as e:
            context.log.exception(msg=f"Could not open the portfolio summary: {e}")
            return

        accounts: list[dict[str, str]] = self.scrape_accounts(
            page=page, context=context
        )

        if not accounts:
            context.log.fail(
                msg=(
                    "No accounts found on the portfolio summary. The selectors in "
                    "modules/fidelity_module.py likely need updating; re-run with "
                    "-o DEBUG_DUMP=1 to see the rendered markup."
                )
            )
            return

        context.log.success(msg=f"Found {len(accounts)} account(s)")

        # 2. Save to the local broker database
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
            for account in accounts:
                db.save_account_data(
                    account_name=account.get("Account"),
                    balance=account.get("Balance"),
                    timestamp=timestamp,
                )

        # 3. Sync to Google Sheets
        try:
            context.log.highlight(msg="Syncing data to Google Sheets...")
            Saver().save_accounts(data=list(accounts))
            context.log.success(msg="Google Sheets updated successfully!")

        except SheetsUnavailable as e:
            context.log.fail(msg=f"Google Sheets sync skipped: {e}")

        except Exception as e:
            # Broad on purpose: the balances are already in the broker database.
            context.log.fail(msg=f"Google Sheets sync failed: {e}")

        context.log.success(msg="Fidelity sync complete.")

    def scrape_accounts(self, page: Any, context: Context) -> list[dict[str, str]]:
        """Pull account names and balances off the rendered summary page.

        Each selector group is tried in order so a Fidelity markup change only
        needs a new entry at the top of the corresponding tuple.

        Args:
            page (Any): The authenticated Playwright page.
            context (Context): Used for logging.

        Returns:
            list[dict[str, str]]: One {"Account", "Balance"} dict per account.

        """
        rows: list[Any] = []

        for selector in ACCOUNT_ROW_SELECTORS:
            found: list[Any] = page.locator(selector).all()
            if found:
                context.log.display(msg=f"Matched account rows via '{selector}'")
                rows = found
                break

        if not rows and self.debug_dump:
            context.log.highlight(msg=f"Rendered body:\n{page.content()[:4000]}")

        accounts: list[dict[str, str]] = []

        for row in rows:
            name: str = self._first_text(row=row, selectors=ACCOUNT_NAME_SELECTORS)
            balance: str = self._first_text(
                row=row, selectors=ACCOUNT_BALANCE_SELECTORS
            )

            if name or balance:
                accounts.append({"Account": name, "Balance": balance})

        return accounts

    @staticmethod
    def _first_text(row: Any, selectors: tuple[str, ...]) -> str:
        """Return the text of the first selector that matches within a row.

        Args:
            row (Any): A Playwright locator for one account row.
            selectors (tuple[str, ...]): Candidate selectors, most specific first.

        Returns:
            str: The stripped text, or "" when nothing matched.

        """
        for selector in selectors:
            cell = row.locator(selector).first
            if cell.count():
                return str(object=cell.inner_text()).strip()

        return ""
