"""Ask SnapTrade which brokerages it actually covers.

Answers the coverage question in issue #21 from the authoritative /brokerages
endpoint rather than from SnapTrade's paginated marketing pages, which disagree
with it. The 2026-08-05 run found Schwab supporting read *and* trade (and
currently flagged degraded), no Ally Invest at all, and Vanguard supported as a
bonus.

An earlier version of this docstring reported Schwab as read-only. That came
from allows_trading, which SnapTrade contradicts across its own endpoints --
the trap _flags() below exists to explain. authorization_types is the field
that decides it, and it reads read/trade.

Read-only: it lists integrations. It never touches an account, a balance or a
trade, and it needs no connected brokerage.

Credentials come from the environment. They are never printed, written, or
passed as arguments -- argv is readable by every process on the machine:

    export SNAPTRADE_CLIENT_ID='PERS-...'
    read -rs SNAPTRADE_CONSUMER_KEY && export SNAPTRADE_CONSUMER_KEY

Run it without adding a dependency to StonkSmith:

    uv run --with snaptrade-python-sdk python scripts/snaptrade_coverage.py

Verified against snaptrade-python-sdk 12.0.4.
"""

import os
import sys
from typing import Any

#: The names issue #21 needs decided. Matched case-insensitively as substrings,
#: since display names carry suffixes ("Ally Invest Securities").
WANTED = ("ally", "fidelity", "schwab", "vanguard")


def _client() -> Any:
    """Build a SnapTrade client from environment credentials."""

    try:
        from snaptrade_client import SnapTrade, SnapTradeAuth
    except ImportError:
        sys.exit(
            "snaptrade_client is not installed. Run this with:\n"
            "  uv run --with snaptrade-python-sdk python scripts/snaptrade_coverage.py"
        )

    client_id: str | None = os.environ.get("SNAPTRADE_CLIENT_ID")
    consumer_key: str | None = os.environ.get("SNAPTRADE_CONSUMER_KEY")

    missing: list[str] = [
        name
        for name, value in (
            ("SNAPTRADE_CLIENT_ID", client_id),
            ("SNAPTRADE_CONSUMER_KEY", consumer_key),
        )
        if not value
    ]
    if missing:
        sys.exit(f"Set {' and '.join(missing)} first -- see this file's docstring.")

    # personal_api_key is the free individual-developer tier, whose client ids
    # are prefixed PERS-. commercial_api_key is the paid tier and takes the same
    # two arguments.
    return SnapTrade(
        auth=SnapTradeAuth.personal_api_key(
            consumer_key=consumer_key,
            client_id=client_id,
        )
    )


def _rows(response: Any) -> list[dict[str, Any]]:
    """Normalize the SDK's response wrapper into plain dicts."""

    body: Any = getattr(response, "body", response)

    return [dict(entry) for entry in body]


def _flags(row: dict[str, Any]) -> str:
    """One-line capability summary for a brokerage.

    Capability comes from ``authorization_types``, NOT from ``allows_trading``.
    SnapTrade returns contradictory values for that boolean across its own
    endpoints -- false from /brokerages and partner info, true from the
    brokerage embedded in a connection, for the same brokerage on the same day.
    Reading it made this script report Schwab as read-only when Schwab can in
    fact be connected read or trade.
    """

    auth_types: list[str] = sorted(
        {
            str(entry.get("type"))
            for entry in row.get("authorization_types") or []
            if entry.get("type")
        }
    )

    parts: list[str] = ["/".join(auth_types) if auth_types else "unknown"]

    if not row.get("enabled", True):
        parts.append("DISABLED")
    if row.get("maintenance_mode"):
        parts.append("maintenance")
    if row.get("is_degraded"):
        parts.append("degraded")
    if row.get("has_reporting"):
        parts.append("reporting")

    return ", ".join(parts)


def main() -> int:
    """List every brokerage, then answer the names issue #21 asked about."""

    rows: list[dict[str, Any]] = _rows(
        _client().reference_data.list_all_brokerages(),
    )
    rows.sort(key=lambda r: str(r.get("name", "")).lower())

    print(f"{len(rows)} brokerages\n")

    width: int = max((len(str(r.get("name", ""))) for r in rows), default=20)
    for row in rows:
        print(f"  {row.get('name', '')!s:<{width}}  {_flags(row)}")

    print("\n--- what issue #21 asked ---")
    for wanted in WANTED:
        hits: list[dict[str, Any]] = [
            r
            for r in rows
            if wanted in f"{r.get('name', '')} {r.get('slug', '')}".lower()
        ]

        if not hits:
            print(f"  {wanted:<10} NOT SUPPORTED -- needs a scraper")
            continue

        for hit in hits:
            print(f"  {wanted:<10} {hit.get('name')} -- {_flags(hit)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
