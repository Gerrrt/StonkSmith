"""Linking a brokerage must ask for the smallest grant that works.

A SnapTrade connection is a standing authorization against the brokerage, and
some of them -- Schwab among them -- will grant trading. StonkSmith reads
balances, positions and activities and places no orders, so the connection has
no business holding a permission the tool never exercises. That grant is decided
once, when the connection is created; re-authorizing it later does not
necessarily narrow it.

Which makes the default worth a test. scripts/ is otherwise untested on purpose
-- these are one-off operator tools, run by hand, sometimes against dependencies
StonkSmith does not install -- and ty excludes the directory outright. So
nothing else in the gate would notice this default quietly becoming "trade".

link() is a pure kwargs builder around one SDK call, so a stub client that
records what it was asked for covers it with no network and no key.
"""

import importlib.util
import unittest
from pathlib import Path
from typing import Any

SCRIPT_FILE = Path(__file__).resolve().parents[1] / "scripts" / "snaptrade_register.py"


def _load_script() -> Any:
    """Load the script by path, since scripts/ is not an importable package."""

    spec = importlib.util.spec_from_file_location("snaptrade_register", SCRIPT_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


register = _load_script()


class _Authentication:
    def __init__(self, body: Any) -> None:
        self.body = body
        self.calls: list[dict[str, Any]] = []

    def login_snap_trade_user(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)

        return self.body


class _StubClient:
    """Records what link() asked SnapTrade for, and answers with a portal URL."""

    def __init__(self, body: Any = None) -> None:
        self.authentication = _Authentication(
            {"redirectURI": "https://app.snaptrade.com/portal"}
            if body is None
            else body
        )

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.authentication.calls


class LinkTests(unittest.TestCase):
    def test_a_link_requests_a_read_only_connection_by_default(self) -> None:
        client = _StubClient()

        self.assertEqual(register.link(client=client), 0)
        self.assertEqual(client.calls[0]["connection_type"], "read")

    def test_the_brokerage_slug_is_forwarded(self) -> None:
        client = _StubClient()

        register.link(client=client, broker="SCHWAB")

        self.assertEqual(client.calls[0]["broker"], "SCHWAB")

    def test_reconnect_and_connection_type_travel_together(self) -> None:
        # Repairing a connection still says what it wants to be granted.
        client = _StubClient()

        register.link(client=client, reconnect="conn-1", connection_type="trade")

        self.assertEqual(client.calls[0]["reconnect"], "conn-1")
        self.assertEqual(client.calls[0]["connection_type"], "trade")

    def test_an_empty_connection_type_is_omitted_entirely(self) -> None:
        # SnapTrade validates this against an enum, so a blank string is a 400
        # rather than a fall back to its own default.
        client = _StubClient()

        register.link(client=client, connection_type="")

        self.assertNotIn("connection_type", client.calls[0])

    def test_nothing_optional_is_sent_when_nothing_was_asked_for(self) -> None:
        client = _StubClient()

        register.link(client=client)

        self.assertEqual(set(client.calls[0]), {"connection_type"})

    def test_a_response_with_no_redirect_uri_is_fatal(self) -> None:
        # Printing nothing and exiting 0 would look exactly like a successful
        # link that the operator then waits forever to finish.
        client = _StubClient(body={"detail": "something went wrong"})

        with self.assertRaises(SystemExit):
            register.link(client=client)


if __name__ == "__main__":
    unittest.main()
