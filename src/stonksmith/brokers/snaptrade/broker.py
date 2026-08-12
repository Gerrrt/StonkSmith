"""
SnapTrade broker class.

One StonkSmith broker covers every brokerage connected through SnapTrade. It is
an aggregator: the operator links Schwab, Fidelity and whatever else through its
Connection Portal once, and StonkSmith reads all of them through a single key.
One StonkSmith broker per brokerage would mean N copies of this file, N
databases and N worksheet tabs, all fed by the same two API calls.

BrokerLoader imports this file by path and reads the module-level ``Broker``
alias at the bottom, so imports here must be absolute: the module is executed
under the synthetic name "broker" with no package.
"""

import datetime
from typing import Any

from etc.api_connection import ApiConnection
from etc.config import get_snaptrade_client_id
from etc.logger import StonkSmithAdapter
from etc.secrets import get_secret, keyring_key

#: Matches the directory name, which is also the keyring namespace, the
#: <name>.db stem and the CLI subcommand.
BROKER_NAME = "snaptrade"

#: Keyring account for the consumer key. A personal API key is a clientId and a
#: consumerKey and nothing else -- SnapTrade resolves the user from the key, so
#: there is no userId or userSecret to hold -- which is why this is a fixed name
#: rather than being scoped to a user. etc.secrets.keyring_key builds
#: "snaptrade:consumerKey" from it.
CONSUMER_KEY_ACCOUNT = "consumerKey"

#: Envelope keys the positions list has been seen under, most authoritative
#: first. ``results`` is what snaptrade-python-sdk's AllAccountPositionsResponse
#: declares required and what a real sync receives; ``positions`` is what
#: SnapTrade's documentation and MCP server call the same list. Reading only one
#: of them yields no holdings against the other, silently.
POSITION_KEYS: tuple[str, ...] = ("results", "positions")

#: The second sentence is there because the first one is wrong about half the
#: time this fires. A keyring lookup that finds nothing is indistinguishable
#: from one that was never stored, and on macOS a scheduled run is exactly where
#: a key that is definitely stored comes back empty -- the login keychain is not
#: visible to a process outside the GUI session. Telling that operator to run
#: `store` sends them to re-store a key that is already there.
SETUP_HINT = (
    "Run `uv run python scripts/snaptrade_register.py store` to put your "
    "SnapTrade consumer key in the keyring, then set clientId in the "
    "[SNAPTRADE] section of ~/.stonksmith/stonksmith.conf. If this works by "
    "hand and only fails unattended, the key is stored and the keyring is not "
    "reachable from that context -- see docs/scheduling.md."
)


def as_rows(response: Any) -> list[dict[str, Any]]:
    """
    Normalize an SDK response into plain dictionaries.

    The generated client returns frozendict-backed schema objects. A shallow
    dict is enough: nested values still answer .get(), and everything
    downstream is written against plain mappings, so the module can be tested
    with literals instead of SDK objects.
    :param response: The SDK response, or anything list-like
    :return: One dictionary per entry
    :rtype: list[dict[str, Any]]
    """

    body: Any = getattr(response, "body", response)

    return [dict(entry) for entry in body]


def as_page_rows(response: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Normalize a *paginated* SDK response.

    Activities do not come back as a bare list like accounts do: the body is
    ``{"data": [...], "pagination": {...}}``. Handing that to as_rows iterates
    the envelope's keys instead of the records -- so this is a separate
    function rather than a flag on the other one. Positions are wrapped too,
    differently again; see as_keyed_rows.
    :param response: The SDK response
    :return: The records, and the pagination block
    :rtype: tuple[list[dict[str, Any]], dict[str, Any]]
    """

    body: Any = getattr(response, "body", response)

    if isinstance(body, list):
        # Some SDK versions unwrap it. Tolerate both rather than betting.
        return [dict(entry) for entry in body], {}

    data: Any = body.get("data") if hasattr(body, "get") else None
    pagination: Any = body.get("pagination") if hasattr(body, "get") else None

    return [dict(entry) for entry in (data or [])], dict(pagination or {})


def as_keyed_rows(response: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """
    Normalize a response whose records sit under a named key.

    Positions arrive wrapped: records under one key, a ``data_freshness`` block
    under another. Passing that to as_rows iterates the envelope's *keys*, so
    the first thing it tries to build a row from is the key's own name, and
    ``dict("results")`` raises "dictionary update sequence element #0 has length
    1; 2 is required" -- a message naming nothing an operator could act on, for
    every account on every brokerage, because the shape has nothing to do with
    the data.

    Two names are accepted because the wire and the SDK disagree. The generated
    client's ``AllAccountPositionsResponse`` requires ``results``, and that is
    what a real sync sees; SnapTrade's own documentation and its MCP server both
    call the same list ``positions``. Keying on one of them alone silently
    yields no holdings against the other -- no error, no rows, a run that looks
    healthy -- which is how this shipped once already.

    Tolerates a bare list too, for the same reason as_page_rows does: some SDK
    versions unwrap the envelope.
    :param response: The SDK response
    :param keys: Envelope keys to look under, most authoritative first
    :return: One dictionary per record
    :rtype: list[dict[str, Any]]
    """

    body: Any = getattr(response, "body", response)

    if isinstance(body, list):
        return [dict(entry) for entry in body]

    if not hasattr(body, "get"):
        return []

    for key in keys:
        rows: Any = body.get(key)

        # `is not None`, not truthiness: an envelope that explicitly carries an
        # empty list has answered the question, and falling through to the next
        # name would be looking for a second opinion that cannot exist.
        if rows is not None:
            return [dict(entry) for entry in rows]

    return []


class SnapTradeBroker(ApiConnection):
    """
    Read every connected brokerage through one SnapTrade key.
    """

    session_label = "snaptrade"

    def __init__(self) -> None:
        super().__init__()
        self.broker = "SnapTrade"
        self.name = "SnapTrade"
        self.client_id: str = ""
        #: Connections indexed by id. An account's ``brokerage_authorization``
        #: is a connection id, so this is the join that catches a disabled
        #: connection still serving months-old cached balances. Filled in by
        #: verify_access(); the module reads it off the second argument of
        #: on_login(), since Context has no field for broker state.
        self.connections: dict[str, dict[str, Any]] = {}

    def broker_logger(self) -> None:
        """
        Set up logger for the SnapTrade broker class.
        """

        self.logger = StonkSmithAdapter(
            extra={"broker": self.broker, "username": self.username},
            logger=self.logger.logger,
        )

    def create_conn_obj(self) -> bool:
        """
        Read the key material and build the SnapTrade client.

        Every failure reports itself: broker_flow() prints nothing for a False
        return, so a quiet path here is a run that does nothing silently.
        :return: True when the client is ready
        :rtype: bool
        """

        self.client_id = get_snaptrade_client_id()

        if not self.client_id:
            self.logger.fail(
                msg=(
                    "[SNAPTRADE] clientId is not set in "
                    f"~/.stonksmith/stonksmith.conf. {SETUP_HINT}"
                ),
            )
            return False

        consumer_account: str = keyring_key(
            broker=BROKER_NAME, username=CONSUMER_KEY_ACCOUNT
        )
        consumer_key: str | None = get_secret(key=consumer_account)

        if not consumer_key:
            self.logger.fail(
                msg=(
                    f"No SnapTrade consumer key in the keyring under "
                    f"'{consumer_account}'. {SETUP_HINT}"
                ),
            )
            return False

        # Imported here rather than at module scope. The generated SDK costs
        # roughly 0.4s and 500 modules to import, and every broker.py under
        # src/brokers is imported by path whenever stonksmithdb lists brokers.
        # A run that never touches SnapTrade should not pay for it.
        try:
            from snaptrade_client import SnapTrade, SnapTradeAuth

        except ImportError as e:
            self.logger.fail(
                msg=f"snaptrade-python-sdk is not installed ({e}). Run `uv sync`.",
            )
            return False

        self.client = SnapTrade(
            auth=SnapTradeAuth.personal_api_key(
                consumer_key=consumer_key,
                client_id=self.client_id,
            )
        )

        return True

    def verify_access(self) -> bool:
        """
        Prove the stored key works, and index the connections while doing it.

        Listing connections is the cheapest authenticated call available and the
        module needs the result anyway, so this is not a contrived ping.
        :return: True when SnapTrade answered with at least one connection
        :rtype: bool
        """

        try:
            # No user_id or user_secret: a personal API key carries its own user
            # context, and SnapTrade's docs are explicit that both are omitted.
            connections: list[dict[str, Any]] = as_rows(
                self.client.connections.list_brokerage_authorizations()
            )

        except Exception as e:
            status: Any = getattr(e, "status", None)

            if status in (401, 403):
                self.logger.fail(
                    msg=(
                        f"SnapTrade rejected the stored key ({status}). The "
                        f"clientId or consumer key is wrong or has been "
                        f"rotated. {SETUP_HINT}"
                    ),
                )
            else:
                self.logger.fail(msg=f"Could not reach SnapTrade: {e}")

            return False

        self.connections = {
            str(object=entry.get("id")): entry
            for entry in connections
            if entry.get("id")
        }

        if not self.connections:
            self.logger.fail(
                msg=(
                    "SnapTrade has no brokerage connections for this key. Link "
                    "one with: uv run python scripts/snaptrade_register.py link"
                ),
            )
            return False

        disabled: list[str] = [
            str(object=dict(entry.get("brokerage") or {}).get("name") or "unknown")
            for entry in self.connections.values()
            if entry.get("disabled")
        ]

        if disabled:
            # Not fatal: the healthy connections still sync. The module skips
            # accounts behind these, because SnapTrade keeps serving their last
            # cached balance rather than reporting an error.
            self.logger.fail(
                msg=(
                    f"Disabled SnapTrade connection(s): {', '.join(sorted(disabled))}. "
                    "Their accounts will be skipped. Reconnect with: uv run "
                    "python scripts/snaptrade_register.py link"
                ),
            )

        return True

    def fetch_accounts(self) -> list[dict[str, Any]]:
        """
        Every account across every connection, in one call.

        SnapTrade serves this from a daily cache by design, which is what the
        module's freshness check is written against.
        :return: One dictionary per account
        :rtype: list[dict[str, Any]]
        """

        return as_rows(self.client.account_information.list_user_accounts())

    def fetch_positions(self, account_id: str) -> list[dict[str, Any]]:
        """
        Every position held in one account.

        An empty list is a legitimate answer, not a failure: a brokerage that
        reports an account pre-aggregated -- a Schwab-held 529, for instance --
        gives SnapTrade a balance and no positions at all. The caller records the
        balance either way.

        Read through as_keyed_rows, not as_rows: the body is an envelope. The
        SDK names the list ``results``; the documented wire format calls it
        ``positions``. Both are tried, because getting it wrong returns nothing
        rather than failing.
        :param account_id: The SnapTrade account id
        :return: One dictionary per position
        :rtype: list[dict[str, Any]]
        """

        return as_keyed_rows(
            self.client.account_information.get_all_account_positions(
                account_id=account_id
            ),
            keys=POSITION_KEYS,
        )

    def fetch_activities(
        self,
        account_id: str,
        start_date: datetime.date,
        end_date: datetime.date,
        page_limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Transactions for one account over a bounded window.

        Paginated, and followed to the end: stopping at the first page would
        silently record whichever movements happened to sort first and drop the
        rest, which is the failure mode this broker's whole module is written to
        avoid. ``page_limit`` is a backstop against a pagination block that never
        reports itself exhausted -- an infinite loop against a paid API is worse
        than a short read that says so.
        :param account_id: The SnapTrade account id
        :param start_date: Oldest date to ask for
        :param end_date: Newest date to ask for
        :param page_limit: How many pages to follow at most
        :return: One dictionary per activity
        :rtype: list[dict[str, Any]]
        """

        collected: list[dict[str, Any]] = []
        offset: int = 0

        for _ in range(page_limit):
            rows, pagination = as_page_rows(
                self.client.account_information.get_account_activities(
                    account_id=account_id,
                    start_date=start_date,
                    end_date=end_date,
                    offset=offset,
                )
            )

            collected.extend(rows)

            if not rows:
                break

            total: Any = pagination.get("total")
            offset += len(rows)

            if total is None or offset >= int(total):
                break

        return collected


#: BrokerLoader reads this off the path-loaded module, so the class name is free
#: to diverge from the directory name. It has to here: the SDK's own client
#: class is called SnapTrade, and shadowing it in this module would be a footgun.
Broker = SnapTradeBroker
