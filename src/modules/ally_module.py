# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Module to scrape balances and positions from the Ally Invest holdings page."""

import contextlib
import datetime
from typing import Any, ClassVar

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from brokers.ally.saver import Saver
from etc.connection import Connection
from etc.context import BrokerDbProtocol, Context, SnapshotDbProtocol
from etc.records import AccountIdentity, Holding
from helpers.ally import (
    INVESTMENT_KIND,
    SIDEBAR_SELECTOR,
    account_label,
    account_totals,
    holdings,
    masked_form,
    masked_matches,
    selected_account,
    sidebar_accounts,
)
from helpers.normalize import format_amount, format_units, to_amount, to_currency
from helpers.sheets import SheetsUnavailable

#: The account-value block above the holdings table. Waited for rather than the
#: table itself, because an account with no positions renders the block and an
#: empty table -- so requiring the table would turn "you hold nothing" into
#: "the selectors broke", and the two need different fixes.
TOTALS_SELECTOR = "holdings-account-totals"

#: The page is an Angular app behind a redirect; the shell arrives well before
#: the account data it renders.
RENDER_TIMEOUT_MS = 30000

#: The account rail renders after the holdings do, and not always inside the
#: same second. Short, because a rail that has not arrived by now is a rail
#: worth reporting rather than one worth waiting on -- the run has its
#: positions either way and an extra half minute buys nothing.
SIDEBAR_TIMEOUT_MS = 5000

#: Heading of the figure used as the account balance. Ally's own summary, and
#: the one number that includes uninvested cash as well as positions.
ACCOUNT_VALUE = "Account Value"

#: Reported on the dashboard beside the balance. Both are already signed by
#: helpers.ally.signed_amount, so a loss arrives with its minus sign.
TOTAL_GAIN_LOSS = "Total G/L"
DAY_GAIN_LOSS = "Today's G/L"


def capture_holdings(connection: Connection, reason: str = "no-holdings") -> str | None:
    """Save the rendered page so selectors can be fixed from real markup.

    Reuses the broker's capture, which writes the HTML and a screenshot to
    ~/.stonksmith/logs with owner-only permissions.

    Args:
        connection (Connection): The live broker.
        reason (str): Slug for the filename, naming what surprised the run.
            Defaults to the page never rendering its holdings at all.

    Returns:
        str | None: Path to the saved HTML, or None if it could not be
        captured.

    """
    capture = getattr(connection, "capture_page", None)
    if not callable(capture):
        return None

    saved = capture(reason=reason)
    return str(object=saved) if saved else None


def holding_rows(account: str, positions: list[Holding]) -> list[dict[str, Any]]:
    """Build the worksheet rows for one account's positions.

    Args:
        account (str): The account label the positions belong to.
        positions (list[Holding]): The parsed positions.

    Returns:
        list[dict[str, Any]]: One dict per position, keyed by worksheet header.

    """
    return [
        {
            "Account": account,
            "Symbol": holding.symbol,
            "Description": holding.name,
            "Units": format_units(holding.units),
            "Price": format_amount(holding.price, holding.currency),
            "Cost Basis": format_amount(holding.cost_basis, holding.currency),
            "Value": format_amount(holding.value, holding.currency),
        }
        for holding in positions
    ]


class AllyModule:
    """Scrape Ally Invest balances and positions and sync them to the dashboard."""

    name: str = "ally"
    description: str = "Scrape balances and positions from the holdings page"
    supported_brokers: ClassVar[list[str]] = ["ally"]

    def __init__(self) -> None:
        """Initialize the class attributes."""
        self.export_format: str = "print"
        self.holdings_url = "https://live.invest.ally.com/accounts/holdings-balances"

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

    def on_login(self, context: Context, connection: Connection) -> bool:
        """Scrape the holdings page and persist what it says.

        Ally shows one account's positions at a time, so this reads the sidebar
        as well: it is the only place the page says how many accounts exist.
        The selected account gets its balance and its positions; any other
        investment account gets the balance the sidebar prints, and a line
        saying its positions were not read. Neither is silently dropped, which
        is the outcome that would otherwise look exactly like success.

        Args:
            context (Context): Logging, database, and shared resources.
            connection (Connection): The authenticated Ally broker, whose
            `active_page` holds the logged-in Playwright page.

        Returns:
            bool: False when nothing reached the database.

        """
        context.log.highlight(msg=f"Starting Ally sync for: {connection.username}")

        # The attribute, not the active_page property. getattr's default only
        # covers AttributeError, and active_page raises RuntimeError when the
        # browser was never started -- so asking for the property turns "no
        # page" into a traceback instead of the message below. Reading `page`
        # answers None for both cases: a connection that is not browser-backed
        # at all, and one whose browser did not start.
        page: Any = getattr(connection, "page", None)
        if page is None:
            context.log.fail(
                msg="Ally module requires a browser-backed connection; "
                "no active page was found."
            )
            return False

        # 1. Scrape
        try:
            page.goto(url=self.holdings_url)
            page.wait_for_selector(
                TOTALS_SELECTOR, timeout=RENDER_TIMEOUT_MS, state="attached"
            )

        except PlaywrightTimeout:
            saved: str | None = capture_holdings(connection=connection)
            where: str = f" Page markup saved to {saved}." if saved else ""
            context.log.fail(
                msg=(
                    "The holdings page never rendered its account totals. "
                    "Either the session expired or the selectors in "
                    f"helpers/ally.py need updating.{where}"
                )
            )
            return False

        except Exception as e:
            context.log.exception(msg=f"Could not open the holdings page: {e}")
            return False

        # The rail is not what the wait above covers, and it arrives later.
        # Without this wait, a rail that had merely not rendered yet looks
        # exactly like one whose selectors moved -- which is the wrong
        # conclusion, and it was drawn once already, from a run whose successor
        # parsed the same rail without complaint. A timeout here is fine: the
        # branch below reports an absent rail properly.
        with contextlib.suppress(PlaywrightTimeout):
            page.wait_for_selector(
                SIDEBAR_SELECTOR, timeout=SIDEBAR_TIMEOUT_MS, state="attached"
            )

        soup = BeautifulSoup(markup=page.content(), features="html.parser")
        accounts: list[dict[str, Any]] = self.scrape_accounts(
            soup=soup, context=context
        )

        if not accounts:
            saved = capture_holdings(connection=connection)
            where = f" Page markup saved to {saved}." if saved else ""
            context.log.fail(
                msg=(
                    "No investment accounts found on the holdings page. The "
                    f"selectors in helpers/ally.py need updating.{where}"
                )
            )
            return False

        # A run that reaches here has its positions, so this is not a failure --
        # but the rail is the only place the page says how many accounts exist,
        # and scrape_accounts() falls back to the heading when it parses empty.
        # That fallback describes exactly one account, so a second one would go
        # unmentioned by a run that looked entirely successful. Capture the
        # markup while it is on screen: the failure paths above never see a
        # rendered page, so nothing else in the run can.
        if not sidebar_accounts(soup=soup):
            saved = capture_holdings(connection=connection, reason="empty-account-rail")
            where = f" Page markup saved to {saved}." if saved else ""
            context.log.highlight(
                msg=(
                    "The account rail was still empty after waiting, on a page "
                    "that did render its holdings. Only the account on screen "
                    "was read, so any other account is missing from this run. "
                    f"Compare the markup against helpers/ally.py.{where}"
                )
            )

        context.log.success(msg=f"Found {len(accounts)} investment account(s)")

        # 2. Save to the local broker database
        timestamp: str = datetime.datetime.now(tz=datetime.UTC).strftime(
            format="%Y-%m-%d %H:%M:%S",
        )

        db: BrokerDbProtocol = context.db
        db_ok: bool = True

        if isinstance(db, SnapshotDbProtocol):
            for account in accounts:
                balance: str = account.get("Balance") or ""

                db.save_snapshot(
                    account=AccountIdentity(
                        # The masked label, both times: it is what previous runs
                        # stored, it survives Ally re-masking, and two Ally
                        # accounts can share a nickname.
                        account_key=account["Account"],
                        display_name=account["Account"],
                        external_id=account.get("Number") or None,
                        kind="INVESTMENT",
                    ),
                    scraped_at=timestamp,
                    value=to_amount(balance),
                    currency=to_currency(balance),
                    raw_value=balance,
                    holdings=account.get("Holdings") or (),
                )

        elif callable(getattr(db, "save_account_data", None)):
            for account in accounts:
                db.save_account_data(
                    account_name=account.get("Account"),
                    balance=account.get("Balance"),
                    timestamp=timestamp,
                )

        else:
            context.log.fail(
                msg="DB contract violation: context.db does not implement "
                "save_account_data. Skipping DB save.",
            )
            db_ok = False

        # 3. Sync to Google Sheets
        sheets_ok: bool = True

        try:
            context.log.highlight(msg="Syncing data to Google Sheets...")
            saver = Saver()
            saver.save_accounts(data=accounts)
            saver.save_holdings(
                data=[
                    row
                    for account in accounts
                    for row in holding_rows(
                        account=account["Account"],
                        positions=list(account.get("Holdings") or ()),
                    )
                ]
            )
            context.log.success(msg="Google Sheets updated successfully!")

        except SheetsUnavailable as e:
            context.log.fail(msg=f"Google Sheets sync skipped: {e}")
            sheets_ok = False

        except Exception as e:
            # Broad on purpose: the balances are already in the broker database.
            context.log.fail(msg=f"Google Sheets sync failed: {e}")
            sheets_ok = False

        if db_ok and sheets_ok:
            context.log.success(msg="Ally sync complete.")
        elif db_ok:
            context.log.success(
                msg="Ally balances saved locally; the dashboard was not updated."
            )

        return db_ok

    def scrape_accounts(
        self, soup: BeautifulSoup, context: Context
    ) -> list[dict[str, Any]]:
        """Turn one rendered holdings page into per-account rows.

        The page shows every account in the sidebar but only one account's
        positions, so the two have to be reconciled: the sidebar's masked
        number is matched against the full number in the heading. When they
        pair up the positions attach to that account; when the heading names an
        account the sidebar does not list, its number is masked the same way so
        both routes produce one identity rather than two.

        Args:
            soup (BeautifulSoup): The parsed holdings page.
            context (Context): Used for logging.

        Returns:
            list[dict[str, Any]]: One dict per investment account, carrying the
            worksheet's columns plus "Number" and "Holdings".

        """
        listed: list[dict[str, str]] = sidebar_accounts(soup=soup)
        totals: dict[str, str] = account_totals(soup=soup)
        positions: list[Holding] = holdings(soup=soup)
        name, number = selected_account(soup=soup)

        # Every exclusion reports itself. The sidebar lists Ally Bank deposit
        # accounts too, and a bank balance appearing under a brokerage would be
        # as wrong as it silently vanishing is confusing.
        for other in listed:
            if other["Kind"] != INVESTMENT_KIND:
                context.log.display(
                    msg=(
                        f"Skipping {other['Label']}: it is an Ally Bank "
                        f"{other['Kind']} account, not an Ally Invest one."
                    )
                )

        investments: list[dict[str, str]] = [
            row for row in listed if row["Kind"] == INVESTMENT_KIND
        ]
        accounts: list[dict[str, Any]] = []
        selected: int | None = self._which_is_selected(
            investments=investments, name=name, number=number, context=context
        )

        for index, row in enumerate(iterable=investments):
            is_selected: bool = index == selected

            if is_selected:
                accounts.append(
                    self._row(
                        label=row["Label"],
                        number=number or row["Number"],
                        balance=totals.get(ACCOUNT_VALUE) or row["Balance"],
                        totals=totals,
                        positions=positions,
                    )
                )

            else:
                # Balance only. Reading its positions would mean switching
                # accounts in the page, and a balance recorded without holdings
                # is a smaller loss than an account that goes unmentioned.
                context.log.highlight(
                    msg=(
                        f"{row['Label']}: recording the balance the sidebar "
                        "shows. Its positions are not on this page -- select "
                        "the account in the browser and re-run to store them."
                    )
                )
                accounts.append(
                    self._row(
                        label=row["Label"],
                        number=row["Number"],
                        balance=row["Balance"],
                        totals={},
                        positions=[],
                    )
                )

        # Only when the heading names an account the sidebar genuinely does not
        # list. Adding a row here because the heading merely lacked a *number*
        # would file the account twice -- once from the sidebar as "Brokerage
        # (...0111)" carrying only a balance, and once from the heading as
        # "Brokerage" carrying the positions -- which is the split history this
        # reconciliation exists to prevent.
        unlisted: bool = selected is None and bool(number or not investments)

        if unlisted and name:
            # Mask its number the way the sidebar would, so this run and any
            # run that does see the sidebar agree on one identity.
            label: str = account_label(name=name, number=masked_form(number=number))
            context.log.highlight(
                msg=(
                    f"{label} is showing its holdings but is not in the "
                    "account list; recording it from the page heading."
                )
            )
            accounts.append(
                self._row(
                    label=label,
                    number=number,
                    balance=totals.get(ACCOUNT_VALUE) or "",
                    totals=totals,
                    positions=positions,
                )
            )

        return accounts

    @staticmethod
    def _which_is_selected(
        investments: list[dict[str, str]],
        name: str,
        number: str,
        context: Context,
    ) -> int | None:
        """Decide which sidebar account the positions on screen belong to.

        Normally the account number does it: the sidebar masks it, the heading
        does not. The awkward case is a heading with no number at all, which
        `selected_account()` reports as "" rather than guessing. Then:

        * one investment account -- unambiguous, the positions are its own
        * several -- unattributable, so nothing gets them. Guessing would file
          one account's positions under another, and that is worse than the
          balances-only run this falls back to, because a wrong holding reads
          as fact while a missing one is reported.

        Args:
            investments (list[dict[str, str]]): Sidebar investment accounts.
            name (str): The nickname from the page heading.
            number (str): The account number from the heading, possibly "".
            context (Context): Used for logging.

        Returns:
            int | None: Index into `investments`, or None when the positions
            cannot be attributed to any of them.

        """
        if number:
            return next(
                (
                    index
                    for index, row in enumerate(iterable=investments)
                    if masked_matches(masked=row["Number"], number=number)
                ),
                None,
            )

        if len(investments) == 1:
            return 0

        if investments and name:
            context.log.fail(
                msg=(
                    f"The holdings on screen say they belong to {name}, but "
                    "the page heading gives no account number and there are "
                    f"{len(investments)} investment accounts to choose from. "
                    "Recording balances only; no account is given positions "
                    "that might be another's."
                )
            )

        return None

    @staticmethod
    def _row(
        label: str,
        number: str,
        balance: str,
        totals: dict[str, str],
        positions: list[Holding],
    ) -> dict[str, Any]:
        """Assemble one account's row.

        Args:
            label (str): The account's display and identity string.
            number (str): The account number, masked or full.
            balance (str): The account value as text.
            totals (dict[str, str]): The headline figures, empty for an account
            whose page was not on screen.
            positions (list[Holding]): The account's positions, possibly empty.

        Returns:
            dict[str, Any]: The row.

        """
        return {
            "Account": label,
            "Balance": balance,
            "Total G/L": totals.get(TOTAL_GAIN_LOSS, ""),
            "Today's G/L": totals.get(DAY_GAIN_LOSS, ""),
            "Number": number,
            "Holdings": positions,
        }
