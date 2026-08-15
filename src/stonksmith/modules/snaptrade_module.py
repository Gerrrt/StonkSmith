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

from stonksmith.etc.connection import Connection
from stonksmith.etc.context import BrokerDbProtocol, Context, SnapshotDbProtocol
from stonksmith.etc.portfolio import normalize_label
from stonksmith.etc.portfolio_sheet import sync
from stonksmith.etc.records import AccountIdentity, Holding, Transaction
from stonksmith.helpers.normalize import format_amount, to_amount, to_iso_date

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


#: Formatting money is not SnapTrade-specific -- every broker stores balances
#: the same way -- so it lives in helpers.normalize now. Kept as a name here
#: because this module is where it was, and callers import it from here.
money = format_amount


def _mapping(value: Any) -> dict[str, Any]:
    """
    Read a nested object, tolerating a source that flattened it to a string.
    :param value: A mapping, a bare string, or nothing
    :return: The mapping, or an empty one
    :rtype: dict[str, Any]
    """

    if hasattr(value, "keys"):
        return dict(value)

    return {}


def currency_code(currency: Any, default: str = "USD") -> str:
    """
    Read an ISO code out of whichever shape SnapTrade used.

    The API returns a currency object -- ``{"code": "USD", "name": ...}`` -- but
    the field is a bare string in enough places, and in enough of this project's
    own fixtures, that assuming either one breaks the other. dict("USD") does
    not raise a KeyError, it raises a ValueError.
    :param currency: A currency object, an ISO code, or nothing
    :param default: What to return when there is no code to read
    :return: An ISO currency code
    :rtype: str
    """

    if isinstance(currency, str):
        return currency.upper() or default

    if hasattr(currency, "get"):
        code: Any = currency.get("code")

        if code:
            return str(object=code).upper()

    return default


def brokerage_name(
    account: dict[str, Any], connection: dict[str, Any] | None, conn_id: str
) -> str:
    """
    Name the brokerage an account came from, distinctly from every other
    brokerage.

    This is identity, not decoration. ``SnapTradeModule.identity()`` builds
    ``account_key`` as "<brokerage> - <account>", and ``account_key`` is what
    joins this run's snapshot to every previous one.

    Deliberately *not* unique per account. Two Fidelity accounts both answer
    "Fidelity", and they must: ``account_key`` pairs this with the account's own
    name, so the brokerage half only has to tell brokerages apart. The one thing
    it may never do is hand the same answer to two different brokerages.

    With one brokerage linked, falling back to a constant was cosmetic. With two
    it destroys data, silently, on every run, and still exits 0. Two accounts
    both called "Individual", at two brokerages that both left
    ``institution_name`` empty, used to key to "unknown - Individual" -- and
    ``_upsert_account`` upserts on ``(broker, account_key)``, so both resolve to
    a single accounts row. ``save_snapshot`` then upserts on
    ``(account_id, scraped_at)``, and every account in a run shares one
    ``scraped_at``, so the second account's balance overwrites the first's and
    the holdings replace deletes the first's rows. One account, one balance, no
    error anywhere.

    So the last rung is one that cannot collide: a connection id is unique per
    connection and stable across runs, so two accounts that fall all the way
    through to it, behind different connections, can never produce the same
    string no matter how little SnapTrade is willing to say about either.

    The earlier rungs repeat, on purpose. Two accounts behind one connection
    both answer "Fidelity", and so do two separate connections to Fidelity.
    Both are right: those accounts really are at the same brokerage, and it is
    the account's own name that separates them.

    ``institution_name`` stays first, and unconditionally. Every account_key in
    every existing database was built from it; preferring the connection's name
    would rewrite keys for accounts that are perfectly healthy today and split
    their history in two. That ordering is also why the later rungs are safe: a
    fallback that later becomes a real ``institution_name`` starts a *new*
    account rather than corrupting an old one. A split history can be merged by
    hand. A merged one has already lost the numbers it overwrote.
    :param account: One account as returned by SnapTrade
    :param connection: Its connection, or None when it could not be resolved
    :param conn_id: Its ``brokerage_authorization``, which may be empty
    :return: A name for the brokerage, unique per connection wherever possible
    :rtype: str
    """

    institution: str = str(object=account.get("institution_name") or "")

    if institution:
        return institution

    # _mapping rather than dict(): some responses flatten this to a bare string,
    # and dict("Schwab") raises ValueError, not KeyError.
    brokerage: dict[str, Any] = _mapping(
        (connection or {}).get("brokerage") if connection else None
    )

    for field in ("name", "slug"):
        value: str = str(object=brokerage.get(field) or "")

        if value:
            return value

    if conn_id:
        # Ugly in the sheet, and unique, which is the property that matters.
        return f"connection {conn_id}"

    # Only reachable for an account with no brokerage_authorization at all,
    # which select_accounts() skips before it can ever reach the database.
    return "unknown"


def position_holding(position: dict[str, Any]) -> Holding:
    """
    Turn one SnapTrade position into a holding row.

    Pure: plain dictionary in, record out, so the mapping is testable without an
    SDK.

    Two shapes, both read. SnapTrade now describes what is held under
    ``instrument`` -- ``{"kind", "symbol", "description", "currency"}`` -- and
    reports the average purchase price as ``cost_basis``. It used to nest a
    ``symbol`` inside a ``symbol`` and call that price ``average_purchase_price``.
    Reading only the current one would turn every holding into a row of Nones
    against any payload still using the old names, which is worse than the error
    that shape mismatch used to raise: an empty row is written and looks real.

    ``cost_basis`` is per unit despite the name -- 8.93 units of FSKAX report
    213.32 as ``price`` and 181.91 as ``cost_basis`` -- so what the position cost
    is still that times the units. Missing either leaves it None rather than
    guessing a zero.
    :param position: One position as returned by SnapTrade
    :return: The holding
    :rtype: Holding
    """

    # _mapping, not dict(): every one of these is flattened to a bare string by
    # some payloads, and dict("VTI") raises ValueError rather than KeyError, so
    # an unguarded dict() turns an odd position into a dead run.
    instrument: dict[str, Any] = _mapping(position.get("instrument"))
    nested: dict[str, Any] = _mapping(position.get("symbol"))
    inner: dict[str, Any] = _mapping(nested.get("symbol"))

    units: float | None = to_amount(position.get("units"))
    price: float | None = to_amount(position.get("price"))
    # Current name first. The old one is not a fallback for a *missing* value so
    # much as for a whole older payload, so order only matters if both appear.
    average: float | None = to_amount(
        position.get("cost_basis")
        if position.get("cost_basis") is not None
        else position.get("average_purchase_price")
    )

    return Holding(
        symbol=str(
            object=instrument.get("symbol")
            or inner.get("symbol")
            or nested.get("symbol")
            or ""
        )
        or None,
        name=str(
            object=instrument.get("description")
            or inner.get("description")
            or nested.get("description")
            or ""
        )
        or None,
        units=units,
        price=price,
        value=units * price if units is not None and price is not None else None,
        cost_basis=units * average
        if units is not None and average is not None
        else None,
        currency=currency_code(
            position.get("currency")
            or instrument.get("currency")
            or inner.get("currency")
            or nested.get("currency")
        ),
    )


def activity_transaction(activity: dict[str, Any]) -> Transaction:
    """
    Turn one SnapTrade activity into a transaction row.

    ``external_id`` is carried through because SnapTrade supplies one. That
    matters for deduplication: with a real id there is nothing to derive, and a
    derived key only holds while a same-content group keeps arriving whole in one
    window. SnapTrade is the producer that windows and paginates, so it is the
    one where that could stop being true.

    An activity that arrives without an id falls back to ``None`` here rather
    than failing, and ``natural_keys()`` then derives a key for it like any
    scraped row. That is the safe reading of a missing field, and it is also the
    one place a SnapTrade movement inherits the scraper's exposure.
    :param activity: One activity as returned by SnapTrade
    :return: The transaction
    :rtype: Transaction
    """

    symbol: dict[str, Any] = _mapping(activity.get("symbol"))

    return Transaction(
        processed_on=to_iso_date(activity.get("settlement_date")) or "",
        traded_on=to_iso_date(activity.get("trade_date")) or "",
        tx_type=str(object=activity.get("type") or ""),
        symbol=str(object=symbol.get("symbol") or "") or None,
        description=str(object=activity.get("description") or "") or None,
        units=to_amount(activity.get("units")),
        price=to_amount(activity.get("price")),
        value=to_amount(activity.get("amount")),
        currency=currency_code(activity.get("currency")),
        external_id=str(object=activity.get("id") or "") or None,
    )


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
    excluded: frozenset[str] = frozenset(),
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
    :param excluded: Normalized labels another broker already covers
    :return: Rows to write, and one reason per excluded account
    :rtype: tuple[list[dict[str, str]], list[str]]
    """

    rows: list[dict[str, str]] = []
    skipped: list[str] = []

    for account in accounts:
        # Resolved up here because the connection now names the brokerage when
        # the account does not, so the label depends on it -- not only the
        # freshness checks further down. The checks themselves stay where they
        # are: moving those would change which reason wins for an account that
        # fails more than one.
        conn_id = str(object=account.get("brokerage_authorization") or "")
        connection: dict[str, Any] | None = connections.get(conn_id)

        name = str(object=account.get("name") or account.get("id") or "unnamed")
        brokerage: str = brokerage_name(
            account=account, connection=connection, conn_id=conn_id
        )
        label = f"{brokerage} / {name}"

        if normalize_label(label) in excluded:
            # First, deliberately. Every other skip describes something wrong
            # with the account; this one says the account is fine and belongs
            # to somebody else, so reporting it as stale or unclassified first
            # would send the operator looking for a problem that is not there.
            skipped.append(
                f"Skipped {label}: excluded, because another broker covers it. "
                "Remove it from exclude_accounts in the [SNAPTRADE] config "
                "section to sync it here instead."
            )
            continue

        if account.get("is_paper"):
            skipped.append(f"Skipped {label}: it is a paper trading account.")
            continue

        status: Any = account.get("status")
        if status is not None and str(object=status) not in LIVE_STATUSES:
            skipped.append(f"Skipped {label}: its status is {status}.")
            continue

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
            # Attribution, not detection. staleness() already caught this; what
            # is_degraded adds is *whose fault it is*, which changes the action
            # from "re-link your connection" to "wait for SnapTrade". Said only
            # here, on a message that is already firing, because the flag
            # describes SnapTrade's integration rather than this connection and
            # would otherwise warn on every run of a brokerage that has been
            # degraded for weeks -- the noise verify_access() deliberately avoids.
            degraded: str = (
                " SnapTrade has flagged this brokerage's integration as "
                "degraded, so this is likely their end rather than yours."
                if _mapping(connection.get("brokerage")).get("is_degraded")
                else ""
            )

            skipped.append(
                f"Skipped {label}: {stale}. Pass --allow-stale to sync it "
                f"anyway.{degraded}"
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
                # Below here is for the database rather than the sheet. The
                # formatted "Balance" above is display text; storing a number
                # means keeping the number that produced it rather than parsing
                # our own output back.
                "Id": str(object=account.get("id") or ""),
                "Amount": amount,
                "Currency": currency_code(total.get("currency")),
                "SyncedAt": synced,
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

    @staticmethod
    def identity(row: dict[str, str]) -> AccountIdentity:
        """
        Who an account is, in the terms the database keys on.

        ``account_key`` stays the composite name the pre-history schema stored,
        because that string is what joins this run to every previous one. The
        brokerage now also gets a column of its own, which is what the composite
        was standing in for.
        :param row: A selected account row
        :return: The identity
        :rtype: AccountIdentity
        """

        return AccountIdentity(
            account_key=f"{row['Brokerage']} - {row['Account']}",
            display_name=row["Account"],
            source=row["Brokerage"],
            external_id=row["Id"] or None,
            kind=row["Category"],
            currency=row["Currency"],
        )

    @staticmethod
    def excluded(context: Context) -> frozenset[str]:
        """
        Accounts another broker owns, from the config and the command line.

        The union rather than either alone: the config carries the standing
        overlap, which is the one a cron run has to know about without being
        told, and --exclude covers the one-off.

        Read here rather than at import time, so a config edit takes effect on
        the next run and the module stays importable without one.
        :param context: The module context
        :return: Normalized labels to skip
        :rtype: frozenset[str]
        """

        from stonksmith.etc.config import get_snaptrade_excluded_accounts

        labels: list[str] = list(get_snaptrade_excluded_accounts())
        labels.extend(getattr(context.args, "exclude", None) or [])

        return frozenset(normalize_label(label) for label in labels if label.strip())

    def positions(
        self, connection: Connection, row: dict[str, str], context: Context
    ) -> tuple[list[Holding], bool]:
        """
        Fetch one account's positions, reporting rather than raising on failure.

        An account that returns nothing is not an error: a brokerage that
        pre-aggregates -- a Schwab-held 529 -- reports a balance and no positions
        at all, and that is a fact worth storing as it stands. A call that
        *fails*, though, is different from one that returns nothing, so it says
        so and the balance is still recorded.

        **Which is why this returns whether it read, as well as what it read.**
        Both cases produce an empty list, and account_value() below computes the
        balance from the positions -- so a failed fetch that looked like an empty
        account would price a real account at its cash alone. On a brokerage
        account that is most of its value, silently.
        :param connection: The SnapTrade broker instance
        :param row: A selected account row
        :param context: The module context
        :return: (the account's holdings, whether they were actually read)
        :rtype: tuple[list[Holding], bool]
        """

        if getattr(context.args, "no_positions", False):
            return [], False

        fetch = getattr(connection, "fetch_positions", None)

        if not callable(fetch) or not row["Id"]:
            return [], False

        try:
            positions: list[dict[str, Any]] = fetch(account_id=row["Id"])

        except Exception as e:
            # One account's positions failing must not cost the run the other
            # accounts' balances, which are already selected and about to write.
            context.log.fail(
                msg=(
                    f"Could not read positions for {row['Brokerage']} / "
                    f"{row['Account']}: {e}. Its balance is still recorded."
                ),
            )
            return [], False

        return [position_holding(position=position) for position in positions], True

    def cash(
        self, connection: Connection, row: dict[str, str], context: Context
    ) -> float | None:
        """
        One account's cash, in the account's own currency.

        The half of an account no position expresses, and routinely negative: an
        overdraft transfer out or a margin loan is a debt the securities do not
        mention. An account holding $3,500.00 of a fund against -$800.00 of cash
        is worth $2,700.00, and summing its positions says $3,500.00.

        None rather than 0.0 when it could not be read, and the difference
        matters: zero cash is a real answer that makes the account worth its
        positions, while "not read" must leave the cached total in place rather
        than quietly writing off a margin loan.
        :param connection: The SnapTrade broker instance
        :param row: A selected account row
        :param context: The module context
        :return: The cash balance, or None when it could not be read
        :rtype: float | None
        """

        fetch = getattr(connection, "fetch_balance", None)

        if not callable(fetch) or not row["Id"]:
            return None

        try:
            balances: list[dict[str, Any]] = fetch(account_id=row["Id"])

        except Exception as e:
            context.log.fail(
                msg=(
                    f"Could not read cash for {row['Brokerage']} / "
                    f"{row['Account']}: {e}. Its cached balance is used instead."
                ),
            )
            return None

        for balance in balances:
            # Matched on the account's own currency rather than summed across
            # them: a brokerage may hold several in one account, and adding a
            # dollar to a euro produces a number that is not wrong so much as
            # meaningless.
            code: str = str(
                object=dict(balance.get("currency") or {}).get("code") or ""
            )

            if code == row["Currency"]:
                return to_amount(balance.get("cash"))

        return None

    def account_value(
        self,
        row: dict[str, str],
        holdings: list[Holding],
        positions_read: bool,
        cash: float | None,
        context: Context,
    ) -> float | None:
        """
        What the account is worth: its positions plus its cash, where both are known.

        **The cached total is a fallback here rather than the source**, and that
        is the whole point of this method. SnapTrade serves ``list_user_accounts``
        from a daily cache by design -- its own documentation says so -- and the
        number it carries is measurably the *previous* sync's position value:
        two accounts in this workspace matched yesterday's positions to the cent
        on the following day. Every balance in the workspace was a day stale, and
        the net worth series with it.

        Positions plus cash is live on both halves and reconciles exactly with
        what SnapTrade's own total eventually says, which is what makes it safe
        to prefer.

        Three ways back to the cached figure, and each of them is a case where
        the computed one would be wrong rather than merely unavailable:

        - **Positions were not read.** A failed fetch and an empty account look
          identical afterwards, so computing from an unread list prices the
          account at its cash alone.
        - **The account reports no positions at all.** A pre-aggregated 529
          gives a balance and nothing to sum; positions plus cash would be zero.
        - **Cash could not be read.** The securities alone omit a margin loan,
          which overstates the account by the size of the debt.
        :param row: A selected account row, carrying the cached balance
        :param holdings: What the account holds
        :param positions_read: Whether the positions fetch actually succeeded
        :param cash: The account's cash, or None when it could not be read
        :param context: The module context
        :return: The account's value
        :rtype: float | None
        """

        cached: float | None = to_amount(row["Amount"])

        if not positions_read or not holdings or cash is None:
            return cached

        priced: float = sum(holding.value or 0.0 for holding in holdings)
        value: float = round(number=priced + cash, ndigits=2)

        if round(number=cash, ndigits=2):
            # Said out loud, because a total that is not the sum of the visible
            # positions is the thing a reader would otherwise reconcile by hand.
            # Negative cash especially: a brokerage account worth less than the
            # fund inside it is a margin loan, and it should be named rather
            # than left as a gap.
            currency: str = row["Currency"]

            context.log.display(
                msg=(
                    f"{row['Account']}: positions "
                    f"{format_amount(amount=priced, currency=currency)} "
                    f"{'less' if cash < 0 else 'plus'} cash "
                    f"{format_amount(amount=abs(cash), currency=currency)} = "
                    f"{format_amount(amount=value, currency=currency)}"
                )
            )

        return value

    def activities(
        self, connection: Connection, row: dict[str, str], context: Context
    ) -> list[Transaction]:
        """
        Fetch one account's recent transactions over a bounded window.

        Same failure posture as positions: report and continue. The window is
        bounded because the endpoint is per account and paginated, and the
        database deduplicates anyway, so re-fetching all of history every run
        buys nothing.
        :param connection: The SnapTrade broker instance
        :param row: A selected account row
        :param context: The module context
        :return: The account's transactions, possibly none
        :rtype: list[Transaction]
        """

        days: int = int(getattr(context.args, "history_days", 90) or 0)

        if days <= 0:
            return []

        fetch = getattr(connection, "fetch_activities", None)

        if not callable(fetch) or not row["Id"]:
            return []

        end: datetime.date = datetime.datetime.now(tz=datetime.UTC).date()

        try:
            activities: list[dict[str, Any]] = fetch(
                account_id=row["Id"],
                start_date=end - datetime.timedelta(days=days),
                end_date=end,
            )

        except Exception as e:
            context.log.fail(
                msg=(
                    f"Could not read transactions for {row['Brokerage']} / "
                    f"{row['Account']}: {e}. Its balance is still recorded."
                ),
            )
            return []

        return [activity_transaction(activity=activity) for activity in activities]

    def on_login(self, context: Context, connection: Connection) -> bool:
        """
        Fetch, filter and persist every connected brokerage's balances.
        :param context: The module context
        :param connection: The SnapTrade broker instance
        :return: False when nothing reached the database
        :rtype: bool
        """

        fetch = getattr(connection, "fetch_accounts", None)

        if not callable(fetch):
            context.log.fail(
                msg=(
                    "This module needs the SnapTrade broker; "
                    f"{connection.broker} cannot list SnapTrade accounts."
                ),
            )
            return False

        try:
            accounts: list[dict[str, Any]] = fetch()

        except Exception as e:
            context.log.fail(msg=f"Could not list SnapTrade accounts: {e}")
            return False

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
            excluded=self.excluded(context=context),
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
            return False

        context.log.success(msg=f"Syncing {len(rows)} account(s)")

        # The database comes first: Sheets is best-effort, and a failure there
        # must not cost the run its balances.
        timestamp: str = datetime.datetime.now(tz=datetime.UTC).strftime(
            format="%Y-%m-%d %H:%M:%S",
        )

        db: BrokerDbProtocol = context.db
        db_ok: bool = True

        if isinstance(db, SnapshotDbProtocol):
            for row in rows:
                # Fetched before the write rather than inline in it, because the
                # value is now computed *from* the positions rather than taken
                # from the cached total beside them.
                holdings, positions_read = self.positions(
                    connection=connection, row=row, context=context
                )

                db.save_snapshot(
                    account=self.identity(row=row),
                    scraped_at=timestamp,
                    value=self.account_value(
                        row=row,
                        holdings=holdings,
                        positions_read=positions_read,
                        cash=self.cash(connection=connection, row=row, context=context),
                        context=context,
                    ),
                    currency=row["Currency"],
                    as_of=to_iso_date(row["SyncedAt"]),
                    # Still the cached figure as the source printed it. raw_value
                    # is the record of what the source said, and what it said is
                    # not what is now stored beside it -- keeping the two apart
                    # is the point of having both.
                    raw_value=row["Balance"],
                    holdings=holdings,
                    transactions=self.activities(
                        connection=connection, row=row, context=context
                    ),
                )

        elif callable(getattr(db, "save_account_data", None)):
            for row in rows:
                # One brokerage's account names are not unique across all of
                # them -- two can each hold a "ACME ESPP PLAN" -- and the
                # accounts table has no brokerage column to tell them apart.
                db.save_account_data(
                    account_name=f"{row['Brokerage']} - {row['Account']}",
                    balance=row["Balance"],
                    timestamp=timestamp,
                )

        else:
            context.log.fail(
                msg="DB contract violation: context.db does not implement "
                "save_account_data. Skipping DB save.",
            )
            db_ok = False

        sheets_ok: bool = sync(context=context)

        if db_ok and sheets_ok:
            context.log.success(msg="SnapTrade sync complete.")
        elif db_ok:
            # Still success level: the balances landed, so the run succeeded and
            # exits 0. Only the wording changes -- claiming "complete" directly
            # after "Google Sheets sync failed" was the lie.
            context.log.success(
                msg="SnapTrade balances saved locally; the dashboard was not updated."
            )

        # A DB contract violation already reported itself at fail level; a
        # summary line here would only restate it more vaguely.
        return db_ok
