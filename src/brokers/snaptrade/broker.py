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

from typing import Any

from etc.api_connection import ApiConnection
from etc.config import get_snaptrade_client_id, get_snaptrade_user_id
from etc.logger import StonkSmithAdapter
from etc.secrets import get_secret, keyring_key

#: Matches the directory name, which is also the keyring namespace, the
#: <name>.db stem and the CLI subcommand.
BROKER_NAME = "snaptrade"

#: Keyring account for the consumer key. It belongs to the developer account
#: rather than to any user, so it gets a fixed name; etc.secrets.keyring_key
#: builds "snaptrade:consumerKey" from it. The user secret is stored under the
#: userId instead, so re-registering under a new id cannot silently resolve a
#: stale secret.
CONSUMER_KEY_ACCOUNT = "consumerKey"

SETUP_HINT = (
    "Run `uv run python scripts/snaptrade_register.py store --user-id <name>` to "
    "put your SnapTrade key material in the keyring, then set clientId and "
    "userId in the [SNAPTRADE] section of ~/.stonksmith/stonksmith.conf."
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
        self.user_id: str = ""
        self.user_secret: str = ""
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
        self.user_id = get_snaptrade_user_id()

        missing: list[str] = [
            name
            for name, value in (("clientId", self.client_id), ("userId", self.user_id))
            if not value
        ]
        if missing:
            verb: str = "is" if len(missing) == 1 else "are"
            self.logger.fail(
                msg=(
                    f"[SNAPTRADE] {' and '.join(missing)} {verb} not set in "
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

        self.user_secret = (
            get_secret(key=keyring_key(broker=BROKER_NAME, username=self.user_id)) or ""
        )

        if not self.user_secret:
            self.logger.fail(
                msg=(
                    f"No user secret in the keyring for SnapTrade user "
                    f"'{self.user_id}'. {SETUP_HINT}"
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
            connections: list[dict[str, Any]] = as_rows(
                self.client.connections.list_brokerage_authorizations(
                    user_id=self.user_id,
                    user_secret=self.user_secret,
                )
            )

        except Exception as e:
            status: Any = getattr(e, "status", None)

            if status in (401, 403):
                self.logger.fail(
                    msg=(
                        f"SnapTrade rejected the stored key ({status}). The "
                        f"consumer key or the secret for user "
                        f"'{self.user_id}' is wrong or has been rotated. "
                        f"{SETUP_HINT}"
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
                    f"SnapTrade has no brokerage connections for user "
                    f"'{self.user_id}'. Link one with: uv run python "
                    "scripts/snaptrade_register.py link"
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

        return as_rows(
            self.client.account_information.list_user_accounts(
                user_id=self.user_id,
                user_secret=self.user_secret,
            )
        )


#: BrokerLoader reads this off the path-loaded module, so the class name is free
#: to diverge from the directory name. It has to here: the SDK's own client
#: class is called SnapTrade, and shadowing it in this module would be a footgun.
Broker = SnapTradeBroker
