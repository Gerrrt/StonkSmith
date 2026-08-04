# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Sync balances for every brokerage connected through SnapTrade.

The filtering lives in a module-level function rather than a method because
every hazard this module exists to handle is worth testing on its own, with
plain dictionaries and no SDK, no network and no broker.

The hazards, in the order they bite:

* A disabled connection does not raise. SnapTrade keeps serving the last
  balance it cached, indefinitely, so a sync that ignored connection state would
  write months-old numbers into the dashboard and report success every time.
* A liability is not an investment. A credit card arrives with a large negative
  balance and would quietly subtract itself from a portfolio total.
* An account can stop being real -- closed, archived, paper -- while still
  reporting a plausible final balance that passes every freshness check.
* A brand new connection reports its accounts before the first sync finishes,
  with no balance or a zero one. Writing that records a false datapoint that
  looks exactly like a real one forever after.
* A connection can be enabled, unbroken, and still return nothing. Every other
  message here is derived from an account, so a brokerage that contributes none
  produces no output whatsoever and the run looks completely healthy while
  covering one brokerage fewer than it should.

Every exclusion is reported. Silently dropping an account is the one outcome
worse than any of the above.
"""

import datetime
from typing import Any, ClassVar

from brokers.snaptrade.saver import Saver
from etc.connection import Connection
from etc.context import BrokerDbProtocol, Context
from helpers.sheets import SheetsUnavailable

#: Account categories that are debts rather than holdings. Excluded by default
#: and opted back in with --include-liabilities.
#:
#: NOTE: this excludes rather than including only INVESTMENT on purpose. The
#: field is nullable and also carries DEPOSIT, so an allow-list would silently
#: drop cash accounts and anything SnapTrade has not classified yet.
LIABILITY_CATEGORIES = frozenset({"LOC"})

#: Account statuses that still represent money you have. ``None`` is accepted
#: too -- several brokerages never populate it.
LIVE_STATUSES = frozenset({"open"})


def holdings_status(account: dict[str, Any]) -> dict[str, Any]:
    """
    The holdings half of an account's sync status.
    :param account: One account as returned by SnapTrade
    :return: The holdings status, or an empty mapping
    :rtype: dict[str, Any]
    """

    sync_status: dict[str, Any] = dict(account.get("sync_status") or {})

    return dict(sync_status.get("holdings") or {})


def money(amount: Any, currency: Any) -> str:
    """
    Format a balance the way the scraper brokers already store them.

    A dollar sign is only applied to USD. Stamping one onto another currency
    produces a number that sums cleanly into a USD total and is wrong.
    :param amount: The balance, a Decimal from the SDK
    :param currency: The ISO currency code
    :return: Currency text such as "$1,234.56" or "1,234.56 CAD"
    :rtype: str
    """

    value = float(amount)
    code = str(object=currency or "").upper()

    if code == "USD":
        return f"-${abs(value):,.2f}" if value < 0 else f"${value:,.2f}"

    return f"{value:,.2f} {code}".strip()


def staleness(
    account: dict[str, Any], *, now: datetime.datetime, max_age_days: int
) -> str:
    """
    Why an account's holdings should not be trusted, if they should not.

    Fails closed: an account with no successful sync recorded is stale. The
    obvious phrasing -- skip the check when the timestamp is missing -- inverts
    the intent and trusts exactly the accounts least worth trusting.
    :param account: One account as returned by SnapTrade
    :param now: Current UTC time
    :param max_age_days: How old a successful sync may be
    :return: A reason, or "" when the holdings are fresh
    :rtype: str
    """

    status: dict[str, Any] = holdings_status(account)

    if status.get("holdings_unavailable"):
        return "SnapTrade reports its holdings as unavailable"

    if status.get("initial_sync_completed") is False:
        return "its first sync has not finished"

    raw: Any = status.get("last_successful_sync")
    if not raw:
        return "SnapTrade has never recorded a successful holdings sync for it"

    try:
        synced = datetime.datetime.fromisoformat(str(object=raw))

    except ValueError:
        return f"its last sync time ({raw}) could not be read"

    if synced.tzinfo is None:
        synced = synced.replace(tzinfo=datetime.UTC)

    age: int = (now - synced).days

    if age > max_age_days:
        return f"its holdings last synced {age} days ago"

    return ""


def silent_connections(
    accounts: list[dict[str, Any]], connections: dict[str, dict[str, Any]]
) -> list[str]:
    """
    Enabled connections that returned no accounts at all.

    Observed in the field: an Interactive Brokers connection authenticated,
    reported ``disabled: false`` with no error anywhere, and returned zero
    accounts because the Flex Query behind it covered none. The sync quietly
    covered three brokerages instead of four and said nothing, because every
    other message this module prints is derived from an account -- and there
    were no accounts to derive one from.

    Disabled connections are excluded: the broker already names those, and
    saying it twice for one problem is the noise that guard was written to
    avoid.

    An account that arrives without a ``brokerage_authorization`` cannot be
    attributed to anything, so its connection can look silent when it is not.
    That earns a caveat rather than silence of its own: dropping every warning
    whenever one account is unattributable would restore the exact blind spot
    this function exists to close, trading a cosmetic false alarm for the real
    one going unreported.
    :param accounts: Accounts as returned by SnapTrade
    :param connections: Connections indexed by id, from the broker
    :return: One description per connection that contributed nothing
    :rtype: list[str]
    """

    seen: set[str] = set()
    unattributable: bool = False

    for account in accounts:
        conn_id = str(object=account.get("brokerage_authorization") or "")

        if conn_id:
            seen.add(conn_id)
        else:
            unattributable = True

    caveat: str = (
        " Note that at least one account arrived without a connection id, so it "
        "could belong to this one."
        if unattributable
        else ""
    )

    silent: list[str] = []

    for conn_id, connection in connections.items():
        if conn_id in seen or connection.get("disabled"):
            continue

        name = str(
            object=dict(connection.get("brokerage") or {}).get("name") or conn_id
        )
        silent.append(
            f"{name} is connected and enabled but returned no accounts. Nothing "
            "from it was synced. Check that the brokerage side of the connection "
            f"still covers the accounts you expect.{caveat}"
        )

    return sorted(silent)


def select_accounts(
    accounts: list[dict[str, Any]],
    connections: dict[str, dict[str, Any]],
    *,
    now: datetime.datetime,
    max_age_days: int,
    include_liabilities: bool,
    allow_stale: bool,
) -> tuple[list[dict[str, str]], list[str]]:
    """
    Split accounts into rows worth writing and reasons for the rest.

    Pure: plain dictionaries in, plain dictionaries out.
    :param accounts: Accounts as returned by SnapTrade
    :param connections: Connections indexed by id, from the broker
    :param now: Current UTC time
    :param max_age_days: How old a successful holdings sync may be
    :param include_liabilities: Whether to sync credit and other debts
    :param allow_stale: Whether to sync accounts that failed the freshness check
    :return: Rows to write, and one reason per excluded account
    :rtype: tuple[list[dict[str, str]], list[str]]
    """

    rows: list[dict[str, str]] = []
    skipped: list[str] = []

    for account in accounts:
        name = str(object=account.get("name") or account.get("id") or "unnamed")
        brokerage = str(object=account.get("institution_name") or "unknown")
        label = f"{brokerage} / {name}"

        if account.get("is_paper"):
            skipped.append(f"Skipped {label}: it is a paper trading account.")
            continue

        status: Any = account.get("status")
        if status is not None and str(object=status) not in LIVE_STATUSES:
            skipped.append(f"Skipped {label}: its status is {status}.")
            continue

        conn_id = str(object=account.get("brokerage_authorization") or "")
        connection: dict[str, Any] | None = connections.get(conn_id)

        if connection is None:
            # Fail closed: without its connection there is no way to tell
            # whether this balance is live or cached from months ago.
            skipped.append(
                f"Skipped {label}: SnapTrade did not return its connection "
                f"({conn_id or 'none recorded'}), so its freshness cannot be judged."
            )
            continue

        if connection.get("disabled"):
            skipped.append(
                f"Skipped {label}: its connection has been disabled since "
                f"{connection.get('disabled_date') or 'an unknown date'}, so the "
                "balance SnapTrade returns is the last one it cached."
            )
            continue

        category: Any = account.get("account_category")
        category_name = str(object=category) if category is not None else "UNCLASSIFIED"

        if category_name in LIABILITY_CATEGORIES and not include_liabilities:
            skipped.append(
                f"Skipped {label}: it is a liability ({category_name}). Pass "
                "--include-liabilities to sync it."
            )
            continue

        total: dict[str, Any] = dict(
            dict(account.get("balance") or {}).get("total") or {}
        )
        amount: Any = total.get("amount")

        if amount is None:
            skipped.append(f"Skipped {label}: SnapTrade returned no balance for it.")
            continue

        stale: str = staleness(account, now=now, max_age_days=max_age_days)

        if stale and not allow_stale:
            skipped.append(
                f"Skipped {label}: {stale}. Pass --allow-stale to sync it anyway."
            )
            continue

        synced = str(object=holdings_status(account).get("last_successful_sync") or "")

        rows.append(
            {
                "Brokerage": brokerage,
                "Account": name,
                "Balance": money(amount, total.get("currency")),
                "Category": category_name,
                "Synced": f"{synced} (STALE)" if stale else synced or "unknown",
            }
        )

    return rows, skipped


class SnapTradeModule:
    """
    Sync every SnapTrade-connected brokerage into one database and one tab.
    """

    name: str = "snaptrade"
    description: str = "Sync balances for every brokerage connected via SnapTrade"
    supported_brokers: ClassVar[list[str]] = ["snaptrade"]

    def __init__(self) -> None:
        """Initialize the class attributes."""

        self.export_format: str = "print"

    def options(
        self, context: Context | None, module_options: dict[str, Any] | None = None
    ) -> None:
        """
        Set up module options.

        This module takes no -o options. Freshness and category policy are
        broker flags instead, because they decide what reaches the database:
        --max-age-days, --allow-stale, --include-liabilities.
        :param context: Unused
        :param module_options: Options passed with -o KEY=VALUE
        """

        del context

        self.export_format = (module_options or {}).get("EXPORT", "print")

    def on_login(self, context: Context, connection: Connection) -> None:
        """
        Fetch, filter and persist every connected brokerage's balances.
        :param context: The module context
        :param connection: The SnapTrade broker instance
        """

        fetch = getattr(connection, "fetch_accounts", None)

        if not callable(fetch):
            context.log.fail(
                msg=(
                    "This module needs the SnapTrade broker; "
                    f"{connection.broker} cannot list SnapTrade accounts."
                ),
            )
            return

        try:
            accounts: list[dict[str, Any]] = fetch()

        except Exception as e:
            context.log.fail(msg=f"Could not list SnapTrade accounts: {e}")
            return

        connections: dict[str, dict[str, Any]] = getattr(connection, "connections", {})

        # Before anything derived from accounts, because a connection that
        # returned none produces no other message at all.
        for warning in silent_connections(accounts, connections):
            context.log.fail(msg=warning)

        rows, skipped = select_accounts(
            accounts,
            connections,
            now=datetime.datetime.now(tz=datetime.UTC),
            max_age_days=getattr(context.args, "max_age_days", 3),
            include_liabilities=getattr(context.args, "include_liabilities", False),
            allow_stale=getattr(context.args, "allow_stale", False),
        )

        for reason in skipped:
            context.log.fail(msg=reason)

        if not rows:
            context.log.fail(
                msg=(
                    f"No accounts to sync out of {len(accounts)} returned by "
                    "SnapTrade. Nothing was written."
                ),
            )
            return

        context.log.success(msg=f"Syncing {len(rows)} account(s)")

        # The database comes first: Sheets is best-effort, and a failure there
        # must not cost the run its balances.
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
            for row in rows:
                # One brokerage's account names are not unique across all of
                # them -- two can each hold a "MICROSOFT ESPP PLAN" -- and the
                # accounts table has no brokerage column to tell them apart.
                db.save_account_data(
                    account_name=f"{row['Brokerage']} - {row['Account']}",
                    balance=row["Balance"],
                    timestamp=timestamp,
                )

        try:
            context.log.highlight(msg="Syncing data to Google Sheets...")
            Saver().save_accounts(data=list(rows))
            context.log.success(msg="Google Sheets updated successfully!")

        except SheetsUnavailable as e:
            context.log.fail(msg=f"Google Sheets sync skipped: {e}")

        except Exception as e:
            # Broad on purpose: the balances are already in the broker database.
            context.log.fail(msg=f"Google Sheets sync failed: {e}")

        context.log.success(msg="SnapTrade sync complete.")
