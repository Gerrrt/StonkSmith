# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Module to scrape account balances from the Fidelity portfolio summary."""

import datetime
import re
from typing import Any, ClassVar

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from brokers.fidelity.saver import Saver
from etc.connection import Connection
from etc.context import BrokerDbProtocol, Context
from helpers.sheets import SheetsUnavailable

# Verified against a signed-in portfolio summary. The account list is Fidelity's
# "acct-selector" component: one __acct-wrapper per account, each carrying a
# name, an account number and a balance. A run that finds nothing writes the
# rendered page to ~/.stonksmith/logs so these can be corrected again.
ACCOUNT_ROW_SELECTORS: tuple[str, ...] = (
    ".acct-selector__acct-wrapper",
    ".acct-selector__acct-content",
)
ACCOUNT_NAME_SELECTORS: tuple[str, ...] = (".acct-selector__acct-name",)
ACCOUNT_BALANCE_SELECTORS: tuple[str, ...] = (".acct-selector__acct-balance",)
ACCOUNT_NUMBER_SELECTORS: tuple[str, ...] = (".acct-selector__acct-num",)

#: The account list is a Stencil web component that hydrates after the loading
#: spinner clears, so the page can look "done" while the markup is still absent.
#: Waiting for the component itself is the only reliable signal.
ACCOUNT_RENDER_TIMEOUT_MS = 20000

#: The balance element is written for screen readers and reads
#: ", balance:  $1,234.56", so the amount has to be pulled out of the sentence.
MONEY_PATTERN = re.compile(r"-?\$\s*-?[\d,]+(?:\.\d+)?")


def clean_money(text: str) -> str:
    """Pull the amount out of Fidelity's screen-reader balance text.

    Args:
        text (str): Raw element text, e.g. ", balance:  $1,234.56".

    Returns:
        str: Just the amount, or the stripped input if no amount is present.

    """
    found = MONEY_PATTERN.search(text)
    return found.group(0).replace(" ", "") if found else text.strip()


def capture_summary(connection: Connection) -> str | None:
    """Save the rendered page so selectors can be fixed from real markup.

    Reuses the broker's capture, which writes the HTML and a screenshot to
    ~/.stonksmith/logs with owner-only permissions.

    Args:
        connection (Connection): The live broker.

    Returns:
        str | None: Path to the saved HTML, or None if it could not be
        captured. The broker returns a Path; it is normalised to str here
        because the value is only ever displayed.

    """
    capture = getattr(connection, "capture_page", None)
    if not callable(capture):
        return None

    saved = capture(reason="no-accounts")
    return str(object=saved) if saved else None


class FidelityModule:
    """Scrape Fidelity account balances and sync them to the dashboard."""

    name: str = "fidelity"
    description: str = "Scrape account balances from the portfolio summary"
    supported_brokers: ClassVar[list[str]] = ["fidelity"]

    def __init__(self) -> None:
        """Initialize the class attributes."""
        self.export_format: str = "print"
        self.summary_url = "https://digital.fidelity.com/ftgw/digital/portfolio/summary"

    def options(
        self, context: Context | None, module_options: dict[str, Any] | None = None
    ) -> None:
        """Set up module options.

        Args:
            context (Context | None): Execution context supplied by ModuleLoader.
            module_options (dict[str, Any] | None): EXPORT sets the export
            format.

        """
        del context
        options: dict[str, Any] = module_options or {}
        self.export_format = options.get("EXPORT", "print")

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
            # Always capture. The old advice -- "re-run with -o DEBUG_DUMP=1" --
            # was useless twice over: the dump logged at INFO, which the default
            # log level hides, and 4000 chars of console output is not something
            # selectors can be fixed from anyway.
            saved: str | None = capture_summary(connection=connection)
            where: str = f" Page markup saved to {saved}." if saved else ""
            context.log.fail(
                msg=(
                    "No accounts found on the portfolio summary. The selectors "
                    f"in modules/fidelity_module.py need updating.{where}"
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
            # Wait for the component rather than assuming it has rendered: the
            # spinner clears well before the account list exists, and scraping
            # in that window returns nothing from a page that looks loaded.
            try:
                page.wait_for_selector(
                    selector, timeout=ACCOUNT_RENDER_TIMEOUT_MS, state="attached"
                )

            except PlaywrightTimeout:
                # This selector never appeared; try the next one. Anything else
                # -- a closed page or context, a protocol error -- is a real
                # failure and must not be reported as "no accounts found".
                continue

            found: list[Any] = page.locator(selector).all()
            if found:
                context.log.display(msg=f"Matched account rows via '{selector}'")
                rows = found
                break

        accounts: list[dict[str, str]] = []

        for row in rows:
            name: str = self._first_text(row=row, selectors=ACCOUNT_NAME_SELECTORS)
            balance: str = clean_money(
                text=self._first_text(row=row, selectors=ACCOUNT_BALANCE_SELECTORS)
            )
            number: str = self._first_text(row=row, selectors=ACCOUNT_NUMBER_SELECTORS)

            # Several Fidelity accounts can share a nickname, so the account
            # number disambiguates them in the database and the dashboard.
            label: str = f"{name} ({number})" if name and number else name or number

            if label or balance:
                accounts.append({"Account": label, "Balance": balance})

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
