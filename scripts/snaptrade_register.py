"""One-time SnapTrade setup: store your key, link a brokerage, check health.

Storing key material and linking a brokerage happen once and are interactive, so
they live here rather than in the broker.

Note what this does *not* do. Creating a SnapTrade user is a commercial-tier
call: /snapTrade/registerUser and /snapTrade/listUsers advertise only the
commercialApiKey auth mode, so a personal key gets a 403 reading "Authentication
credentials were not provided" -- the SDK sends no auth at all for a mode the
endpoint does not offer. On the personal tier the userId and userSecret come
from the SnapTrade dashboard, and `store` puts them where the broker looks.

The three endpoints the broker itself depends on -- listBrokerageAuthorizations,
listUserAccounts and the connection portal login -- all accept a personal key.

Secrets are written straight to the OS keyring through the same helpers the
broker reads them with. They are never printed, and never passed as arguments:
argv is readable by every process on the machine.

    export SNAPTRADE_CLIENT_ID='PERS-...'
    read -rs SNAPTRADE_CONSUMER_KEY && export SNAPTRADE_CONSUMER_KEY
    read -rs SNAPTRADE_USER_SECRET && export SNAPTRADE_USER_SECRET

    uv run python scripts/snaptrade_register.py store --user-id <dashboard id>
    uv run python scripts/snaptrade_register.py status
    uv run python scripts/snaptrade_register.py link

Verified against snaptrade-python-sdk 12.0.4.
"""

import argparse
import os
import sys
from typing import Any

from etc.config import get_snaptrade_user_id
from etc.secrets import get_secret, keyring_key, set_secret

BROKER_NAME = "snaptrade"
CONSUMER_KEY_ACCOUNT = "consumerKey"


def _env(name: str) -> str:
    """Read a required environment variable or explain how to set it."""

    value: str = os.environ.get(name, "")

    if not value:
        sys.exit(f"{name} is not set -- see this file's docstring.")

    return value


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


def _resolve_user(user_id: str) -> tuple[str, str]:
    """The user id and its secret, from the argument or config plus keyring."""

    resolved: str = user_id or get_snaptrade_user_id()

    if not resolved:
        sys.exit(
            "No userId. Pass --user-id, or set it in the [SNAPTRADE] section of "
            "~/.stonksmith/stonksmith.conf."
        )

    secret: str | None = get_secret(
        key=keyring_key(broker=BROKER_NAME, username=resolved)
    )

    if not secret:
        sys.exit(
            f"No keyring secret for SnapTrade user '{resolved}'. Run: "
            f"{sys.argv[0]} register --user-id {resolved}"
        )

    return resolved, secret


def store(user_id: str, consumer_key: str, client_id: str) -> int:
    """Put the SnapTrade key material into the OS keyring.

    Creating a user is a commercial-tier call: /snapTrade/registerUser and
    /snapTrade/listUsers both advertise only the commercialApiKey auth mode, so
    a personal key gets a 403 with "Authentication credentials were not
    provided" -- the SDK sends no auth for a mode the endpoint does not offer.
    On the personal tier the userId and userSecret come from the SnapTrade
    dashboard instead, and this stores them.
    """

    if not user_id:
        sys.exit("store needs --user-id <name from the SnapTrade dashboard>.")

    user_secret: str = _env("SNAPTRADE_USER_SECRET")

    existing: str | None = get_secret(
        key=keyring_key(broker=BROKER_NAME, username=user_id)
    )

    set_secret(
        key=keyring_key(broker=BROKER_NAME, username=user_id), secret=user_secret
    )
    set_secret(
        key=keyring_key(broker=BROKER_NAME, username=CONSUMER_KEY_ACCOUNT),
        secret=consumer_key,
    )

    verb = "Replaced" if existing else "Stored"
    print(f"{verb} the key material for SnapTrade user '{user_id}'.")
    print("\nIn the OS keyring (service 'stonksmith'):")
    print(f"  {keyring_key(broker=BROKER_NAME, username=user_id)}")
    print(f"  {keyring_key(broker=BROKER_NAME, username=CONSUMER_KEY_ACCOUNT)}")
    print("\nAdd this to ~/.stonksmith/stonksmith.conf:")
    print("\n[SNAPTRADE]")
    print(f"clientid = {client_id}")
    print(f"userid = {user_id}")
    print(f"\nThen check what is linked:\n  {sys.argv[0]} status")

    return 0


def link(client: Any, user_id: str) -> int:
    """Print a Connection Portal URL for linking or repairing a brokerage."""

    resolved, secret = _resolve_user(user_id)

    body: Any = _body(
        client.authentication.login_snap_trade_user(
            user_id=resolved, user_secret=secret
        )
    )

    url = str(object=dict(body).get("redirectURI") or "")

    if not url:
        sys.exit(f"SnapTrade returned no redirect URI: {body}")

    print(
        "This URL signs in as you and expires in about 5 minutes. Treat it like\n"
        "a password: open it yourself, and never paste it into a bug report.\n"
    )
    print(url)

    return 0


def status(client: Any, user_id: str) -> int:
    """Connection health and account names. Prints no balances."""

    resolved, secret = _resolve_user(user_id)

    connections = [
        dict(entry)
        for entry in _body(
            client.connections.list_brokerage_authorizations(
                user_id=resolved, user_secret=secret
            )
        )
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
        dict(entry)
        for entry in _body(
            client.account_information.list_user_accounts(
                user_id=resolved, user_secret=secret
            )
        )
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

    store_parser = sub.add_parser(
        "store", help="put dashboard key material into the keyring"
    )
    store_parser.add_argument(
        "--user-id", default="", help="the userId from the SnapTrade dashboard"
    )

    for name, help_text in (
        ("link", "print a Connection Portal URL"),
        ("status", "connection health and account names"),
    ):
        command_parser = sub.add_parser(name, help=help_text)
        command_parser.add_argument("--user-id", default="", help="defaults to config")

    args = parser.parse_args()

    client_id: str = _env("SNAPTRADE_CLIENT_ID")
    consumer_key: str = _env("SNAPTRADE_CONSUMER_KEY")

    # store is purely local -- it writes the keyring and prints config lines --
    # so it must not need a working client to run.
    if args.command == "store":
        return store(args.user_id, consumer_key, client_id)

    client: Any = _client(client_id, consumer_key)

    if args.command == "link":
        return link(client, args.user_id)

    return status(client, args.user_id)


if __name__ == "__main__":
    raise SystemExit(main())
