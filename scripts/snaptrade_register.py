"""One-time SnapTrade setup: create a user, link a brokerage, check health.

Registering a SnapTrade user and linking a brokerage are both interactive and
happen once, so they live here rather than in the broker. `register` in
particular is a *state-changing* call that mints a user under your client id --
a broker that ran it automatically on a missing config would create a new user
and orphan every existing connection on the first misconfigured run.

Secrets are written straight to the OS keyring through the same helpers the
broker reads them with. They are never printed, and never passed as arguments:
argv is readable by every process on the machine.

    export SNAPTRADE_CLIENT_ID='PERS-...'
    read -rs SNAPTRADE_CONSUMER_KEY && export SNAPTRADE_CONSUMER_KEY

    uv run python scripts/snaptrade_register.py register --user-id garrett
    uv run python scripts/snaptrade_register.py link
    uv run python scripts/snaptrade_register.py status

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


def users(client: Any) -> int:
    """List the SnapTrade users that already exist under this client id.

    A userId is not issued by SnapTrade -- you choose it at registration. This
    exists to answer the other question: which ones have already been created,
    and therefore already own the linked brokerages.

    Only ids are returned. A userSecret is shown once, at registration, and
    cannot be read back afterwards.
    """

    existing = list(_body(client.authentication.list_snap_trade_users()))

    if not existing:
        print("No SnapTrade users exist yet under this client id.")
        print(f"Create one with:\n  {sys.argv[0]} register --user-id <name>")
        return 0

    print(f"{len(existing)} SnapTrade user(s) under this client id:\n")

    for entry in existing:
        held = get_secret(key=keyring_key(broker=BROKER_NAME, username=str(entry)))
        print(f"  {entry}{'   (secret in your keyring)' if held else ''}")

    print(
        "\nA userSecret is only ever shown at registration. If none of these has\n"
        "a secret in your keyring, you cannot adopt that user: register a new one\n"
        "and re-link its brokerages through the Connection Portal."
    )

    return 0


def register(client: Any, user_id: str, consumer_key: str) -> int:
    """Create a SnapTrade user and store both secrets in the keyring."""

    if not user_id:
        sys.exit("register needs --user-id <name>.")

    existing: str | None = get_secret(
        key=keyring_key(broker=BROKER_NAME, username=user_id)
    )

    if existing:
        sys.exit(
            f"A secret for SnapTrade user '{user_id}' is already in the keyring. "
            "Registering again would mint a different user and orphan its "
            "connections. Delete the keyring entry first if that is really wanted."
        )

    body: Any = _body(
        client.authentication.register_snap_trade_user(body={"userId": user_id})
    )

    returned_id = str(object=dict(body).get("userId") or user_id)
    user_secret = str(object=dict(body).get("userSecret") or "")

    if not user_secret:
        sys.exit("SnapTrade returned no userSecret; nothing stored.")

    set_secret(
        key=keyring_key(broker=BROKER_NAME, username=returned_id), secret=user_secret
    )
    set_secret(
        key=keyring_key(broker=BROKER_NAME, username=CONSUMER_KEY_ACCOUNT),
        secret=consumer_key,
    )

    client_id: str = _env("SNAPTRADE_CLIENT_ID")

    print(f"Registered SnapTrade user '{returned_id}'.")
    print("\nStored in the OS keyring (service 'stonksmith'):")
    print(f"  {keyring_key(broker=BROKER_NAME, username=returned_id)}")
    print(f"  {keyring_key(broker=BROKER_NAME, username=CONSUMER_KEY_ACCOUNT)}")
    print("\nAdd this to ~/.stonksmith/stonksmith.conf:")
    print("\n[SNAPTRADE]")
    print(f"clientid = {client_id}")
    print(f"userid = {returned_id}")
    print(f"\nThen link a brokerage:\n  {sys.argv[0]} link")

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

    sub.add_parser("users", help="list SnapTrade users that already exist")

    register_parser = sub.add_parser("register", help="create a SnapTrade user")
    register_parser.add_argument("--user-id", default="", help="a name you choose")

    for name, help_text in (
        ("link", "print a Connection Portal URL"),
        ("status", "connection health and account names"),
    ):
        command_parser = sub.add_parser(name, help=help_text)
        command_parser.add_argument("--user-id", default="", help="defaults to config")

    args = parser.parse_args()

    client_id: str = _env("SNAPTRADE_CLIENT_ID")
    consumer_key: str = _env("SNAPTRADE_CONSUMER_KEY")
    client: Any = _client(client_id, consumer_key)

    if args.command == "users":
        return users(client)

    if args.command == "register":
        return register(client, args.user_id, consumer_key)

    if args.command == "link":
        return link(client, args.user_id)

    return status(client, args.user_id)


if __name__ == "__main__":
    raise SystemExit(main())
