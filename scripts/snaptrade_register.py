"""One-time SnapTrade setup: store your key, link a brokerage, check health.

A personal API key is a clientId and a consumerKey, and that is the whole
identity. SnapTrade's own documentation is explicit about it:

    "Omit userId and userSecret when making API requests; SnapTrade resolves
    the user from the Personal API key."
    "Do not call Register user for Personal API key authentication."

So there is no user to create and no userId to look up. Registering one is not
merely unnecessary, it is impossible on this tier: /snapTrade/registerUser and
/snapTrade/listUsers advertise only the commercialApiKey auth mode, so the SDK
sends no credentials at all and the reply is a 403 reading "Authentication
credentials were not provided" -- which reads like a bad key rather than an
endpoint that is not available.

Everything StonkSmith depends on -- listBrokerageAuthorizations,
listUserAccounts, and the connection portal login -- accepts a personal key.

Secrets are written straight to the OS keyring through the same helpers the
broker reads them with. They are never printed, and never passed as arguments:
argv is readable by every process on the machine.

    export SNAPTRADE_CLIENT_ID='PERS-...'
    read -rs SNAPTRADE_CONSUMER_KEY && export SNAPTRADE_CONSUMER_KEY

    uv run python scripts/snaptrade_register.py store
    uv run python scripts/snaptrade_register.py status
    uv run python scripts/snaptrade_register.py link

Only ``store`` needs those two variables, because it runs before there is
anywhere to read them from. ``status`` and ``link`` resolve the pair the way the
broker does -- ``clientid`` from the config, the consumer key from the keyring --
so they work in any shell once setup is done. The environment still wins where
it is set, which is what makes a second key testable without editing config.

Verified against snaptrade-python-sdk 12.0.4.
"""

import argparse
import os
import sys
from typing import Any

import keyring.errors

from etc.config import get_snaptrade_client_id
from etc.secrets import get_secret, keyring_key, set_secret

BROKER_NAME = "snaptrade"
CONSUMER_KEY_ACCOUNT = "consumerKey"


def _env(name: str) -> str:
    """Read a required environment variable or explain how to set it."""

    value: str = os.environ.get(name, "")

    if not value:
        sys.exit(f"{name} is not set -- see this file's docstring.")

    return value


def _stored_client_id() -> str:
    """
    The clientId, from the environment or else from where the broker reads it.

    Only ``store`` genuinely needs this in the environment: it runs before there
    is a config to read. Every other command runs on a machine that has already
    been set up, and demanding it there asked the operator to re-export a value
    they had written into the config on the way past -- which is why the health
    check `docs/brokers.md` recommends failed on a working install, saying
    "SNAPTRADE_CLIENT_ID is not set" about a client id that plainly was.
    :return: The client id, or "" when neither source has one
    """

    return (
        os.environ.get("SNAPTRADE_CLIENT_ID", "").strip() or get_snaptrade_client_id()
    )


def _stored_consumer_key() -> str:
    """
    The consumerKey, from the environment or else from the OS keyring.

    Putting it in the keyring is the entire job of ``store``, and the line
    ``store`` prints on the way out points at ``status`` -- so requiring the
    variable again made the command it recommends fail in any shell that had not
    just exported it.

    A machine with no keyring backend at all raises rather than returning
    nothing, and that is a different problem from an empty keyring: it is said
    so here, because a traceback out of a setup script reads as the script being
    broken rather than as the machine lacking a place to keep secrets.
    :return: The consumer key, or "" when neither source has one
    """

    from_env: str = os.environ.get("SNAPTRADE_CONSUMER_KEY", "").strip()

    if from_env:
        return from_env

    try:
        stored: str | None = get_secret(
            key=keyring_key(broker=BROKER_NAME, username=CONSUMER_KEY_ACCOUNT)
        )

    except keyring.errors.KeyringError as e:
        sys.exit(
            f"Could not read the OS keyring: {e}\n"
            "Export SNAPTRADE_CONSUMER_KEY to get this command through without "
            "one. That is a workaround for reading, and only here: 'store' "
            "writes to the keyring, and the broker reads from it with no such "
            "fallback, so a machine with no backend cannot sync either way."
        )

    return stored or ""


def _client(client_id: str, consumer_key: str) -> Any:
    """Build a SnapTrade client."""

    try:
        from snaptrade_client import SnapTrade, SnapTradeAuth

    except ImportError:
        sys.exit("snaptrade-python-sdk is not installed. Run `uv sync`.")

    return SnapTrade(
        auth=SnapTradeAuth.personal_api_key(
            consumer_key=consumer_key,
            client_id=client_id,
        )
    )


def _body(response: Any) -> Any:
    """Unwrap the SDK's response wrapper."""

    return getattr(response, "body", response)


def store(consumer_key: str, client_id: str) -> int:
    """Put the SnapTrade consumer key into the OS keyring.

    Purely local: it writes the keyring and prints the config line, so it does
    not need a working client and cannot fail on a bad key.
    """

    existing: str | None = get_secret(
        key=keyring_key(broker=BROKER_NAME, username=CONSUMER_KEY_ACCOUNT)
    )

    set_secret(
        key=keyring_key(broker=BROKER_NAME, username=CONSUMER_KEY_ACCOUNT),
        secret=consumer_key,
    )

    print(f"{'Replaced' if existing else 'Stored'} the SnapTrade consumer key in")
    print(
        f"the OS keyring (service 'stonksmith', "
        f"{keyring_key(broker=BROKER_NAME, username=CONSUMER_KEY_ACCOUNT)})."
    )
    print("\nAdd this to ~/.stonksmith/stonksmith.conf:")
    print("\n[SNAPTRADE]")
    print(f"clientid = {client_id}")
    print(f"\nThen check what is linked:\n  {sys.argv[0]} status")

    return 0


def link(
    client: Any,
    reconnect: str = "",
    broker: str = "",
    connection_type: str = "read",
) -> int:
    """Print a Connection Portal URL for linking or repairing a brokerage.

    Without --reconnect the portal creates a connection, and SnapTrade de-dupes:
    "if the user has an existing connection with the brokerage ... SnapTrade will
    return the existing connection instead of creating a new one". So supplying
    fresh credentials for a brokerage already connected can silently do nothing --
    observed with an Interactive Brokers connection whose updated_date never
    moved across a reconnect attempt.

    --reconnect points the portal at one specific connection and re-authorizes
    that one, which is the documented way to repair a connection rather than
    replace it.

    connection_type defaults to read because a connection is a standing
    authorization against the brokerage, and StonkSmith only ever reads balances,
    positions and activities. Some brokerages -- Schwab among them -- will happily
    grant trading, which is a permission nothing here uses and every future bug
    could. It is decided when the connection is *created*: re-authorizing through
    --reconnect does not necessarily narrow a connection that was already granted
    trade, so downgrading one means deleting it and linking it again.
    """

    kwargs: dict[str, str] = {}

    if reconnect:
        kwargs["reconnect"] = reconnect
    if broker:
        kwargs["broker"] = broker
    if connection_type:
        # Omitted entirely when empty rather than sent blank: SnapTrade validates
        # this against an enum, so "" is a 400 rather than a fall back to its own
        # default.
        kwargs["connection_type"] = connection_type

    body: Any = _body(client.authentication.login_snap_trade_user(**kwargs))

    url = str(object=dict(body).get("redirectURI") or "")

    if not url:
        sys.exit(f"SnapTrade returned no redirect URI: {body}")

    print(
        "This URL signs in as you and expires in about 5 minutes. Treat it like\n"
        "a password: open it yourself, and never paste it into a bug report.\n"
    )
    print(url)

    return 0


def status(client: Any) -> int:
    """Connection health and account names. Prints no balances."""

    connections = [
        dict(entry)
        for entry in _body(client.connections.list_brokerage_authorizations())
    ]

    print(f"{len(connections)} connection(s)\n")

    for entry in connections:
        brokerage = dict(entry.get("brokerage") or {})
        state = "DISABLED" if entry.get("disabled") else "ok"
        degraded = " (degraded)" if brokerage.get("is_degraded") else ""
        print(f"  {brokerage.get('name', '?'):<24} {state}{degraded}")

        if entry.get("disabled"):
            print(f"      disabled since {entry.get('disabled_date') or 'unknown'}")

    accounts = [
        dict(entry) for entry in _body(client.account_information.list_user_accounts())
    ]

    print(f"\n{len(accounts)} account(s) -- balances deliberately omitted\n")

    for entry in accounts:
        synced = dict(dict(entry.get("sync_status") or {}).get("holdings") or {}).get(
            "last_successful_sync"
        )
        flags = [str(object=entry.get("account_category") or "UNCLASSIFIED")]

        if entry.get("is_paper"):
            flags.append("paper")
        if entry.get("status") not in (None, "open"):
            flags.append(str(object=entry.get("status")))

        print(f"  {entry.get('institution_name') or '?'!s:<12} ", end="")
        print(f"{entry.get('name') or '?'!s:<44} ", end="")
        print(f"{','.join(flags):<16} synced {synced or 'never'}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("store", help="put the consumer key into the keyring")
    sub.add_parser("status", help="connection health and account names")

    link_parser = sub.add_parser("link", help="print a Connection Portal URL")
    link_parser.add_argument(
        "--reconnect",
        default="",
        help=(
            "connection id to re-authorize instead of creating a new connection; "
            "required when the brokerage is already connected, because SnapTrade "
            "de-dupes and would otherwise return the existing one unchanged"
        ),
    )
    link_parser.add_argument(
        "--broker",
        default="",
        help="brokerage slug to preselect, e.g. SCHWAB or INTERACTIVE-BROKERS-FLEX",
    )
    link_parser.add_argument(
        "--connection-type",
        default="read",
        choices=("read", "trade", "trade-if-available"),
        help=(
            "how much access the connection grants (default: read). StonkSmith "
            "only reads balances, positions and activities, so a trade "
            "connection grants a permission nothing here uses; "
            "'trade-if-available' is the escape hatch for a brokerage that "
            "offers nothing narrower"
        ),
    )

    args = parser.parse_args()

    if args.command == "store":
        # Required here and nowhere else: this is the command that puts them
        # where the others look.
        return store(_env("SNAPTRADE_CONSUMER_KEY"), _env("SNAPTRADE_CLIENT_ID"))

    client_id: str = _stored_client_id()

    # Before the keyring, not after: with no clientId this exits either way, and
    # reaching for a secret on the way to saying so is what turns a missing
    # config line into a keyring error on a machine that has no keyring.
    if not client_id:
        sys.exit(
            "No SnapTrade clientId. Set 'clientid' in the [SNAPTRADE] section of "
            "~/.stonksmith/stonksmith.conf, or export SNAPTRADE_CLIENT_ID."
        )

    consumer_key: str = _stored_consumer_key()

    if not consumer_key:
        sys.exit(
            "No SnapTrade consumer key in the OS keyring under "
            f"'{keyring_key(broker=BROKER_NAME, username=CONSUMER_KEY_ACCOUNT)}'. "
            "Run this script's 'store' command, or export SNAPTRADE_CONSUMER_KEY."
            "\n\nIf 'store' has already been run and this works in your own "
            "shell, the key is there and this context cannot see it -- which is "
            "what a scheduled run on macOS looks like, because the login "
            "keychain is not visible outside the GUI session. See "
            "docs/scheduling.md."
        )

    client: Any = _client(client_id, consumer_key)

    if args.command == "link":
        return link(
            client=client,
            reconnect=args.reconnect,
            broker=args.broker,
            connection_type=args.connection_type,
        )

    return status(client)


if __name__ == "__main__":
    raise SystemExit(main())
