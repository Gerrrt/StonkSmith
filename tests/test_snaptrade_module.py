"""Every account SnapTrade returns is a candidate for being wrong.

A disabled connection keeps serving its last cached balance instead of raising.
A credit card is a debt wearing an account's clothes. A closed account reports a
final balance that passes every freshness check. A connection that has not
finished its first sync reports accounts with no balance at all.

select_accounts() is the one place all of that is decided, so it is pure and
every case below is a literal dictionary. Nothing here touches the SDK, the
network, the keyring or Google Sheets.
"""

import datetime
import unittest
from argparse import Namespace
from typing import Any
from unittest.mock import patch

from helpers.sheets import SheetsUnavailable
from modules.snaptrade_module import (
    SnapTradeModule,
    money,
    select_accounts,
    silent_connections,
)

NOW = datetime.datetime(2026, 8, 4, 12, 0, tzinfo=datetime.UTC)

LIVE_CONNECTION = "conn-live"
DEAD_CONNECTION = "conn-dead"

CONNECTIONS: dict[str, dict[str, Any]] = {
    LIVE_CONNECTION: {"id": LIVE_CONNECTION, "disabled": False, "disabled_date": None},
    DEAD_CONNECTION: {
        "id": DEAD_CONNECTION,
        "disabled": True,
        "disabled_date": "2026-06-01",
    },
}


def account(**overrides: Any) -> dict[str, Any]:
    """A healthy Schwab investment account, synced an hour ago."""

    base: dict[str, Any] = {
        "id": "acct-1",
        "name": "Garrett IRA",
        "institution_name": "Schwab",
        "brokerage_authorization": LIVE_CONNECTION,
        "account_category": "INVESTMENT",
        "status": "open",
        "is_paper": False,
        "balance": {"total": {"amount": 6539.67, "currency": "USD"}},
        "sync_status": {
            "holdings": {
                "last_successful_sync": "2026-08-04T11:00:00+00:00",
                "initial_sync_completed": True,
            }
        },
    }
    base.update(overrides)

    return base


def select(accounts: list[dict[str, Any]], **overrides: Any):
    defaults: dict[str, Any] = {
        "now": NOW,
        "max_age_days": 3,
        "include_liabilities": False,
        "allow_stale": False,
    }
    defaults.update(overrides)

    return select_accounts(accounts, CONNECTIONS, **defaults)


class MoneyTests(unittest.TestCase):
    def test_usd_is_formatted_like_the_scrapers_store_it(self) -> None:
        self.assertEqual(money(1234.5, "USD"), "$1,234.50")

    def test_a_negative_usd_balance_keeps_the_sign_outside(self) -> None:
        self.assertEqual(money(-15646.44, "USD"), "-$15,646.44")

    def test_a_non_usd_balance_never_gets_a_dollar_sign(self) -> None:
        # A $ on a CAD number sums cleanly into a USD total and is wrong.
        self.assertEqual(money(1234.5, "CAD"), "1,234.50 CAD")

    def test_a_decimal_amount_is_accepted(self) -> None:
        from decimal import Decimal

        self.assertEqual(money(Decimal("2166.30"), "USD"), "$2,166.30")


class SelectAccountsTests(unittest.TestCase):
    def test_a_healthy_account_is_written(self) -> None:
        rows, skipped = select([account()])

        self.assertEqual(skipped, [])
        self.assertEqual(
            rows,
            [
                {
                    "Brokerage": "Schwab",
                    "Account": "Garrett IRA",
                    "Balance": "$6,539.67",
                    "Category": "INVESTMENT",
                    "Synced": "2026-08-04T11:00:00+00:00",
                }
            ],
        )

    def test_an_account_on_a_disabled_connection_is_skipped(self) -> None:
        rows, skipped = select([account(brokerage_authorization=DEAD_CONNECTION)])

        self.assertEqual(rows, [])
        self.assertIn("disabled since 2026-06-01", skipped[0])

    def test_a_disabled_connection_is_skipped_even_with_every_override(self) -> None:
        rows, _ = select(
            [account(brokerage_authorization=DEAD_CONNECTION)],
            allow_stale=True,
            include_liabilities=True,
            max_age_days=99999,
        )

        self.assertEqual(rows, [], "stale cached data is never worth writing")

    def test_an_account_whose_connection_is_missing_fails_closed(self) -> None:
        rows, skipped = select([account(brokerage_authorization="conn-unknown")])

        self.assertEqual(rows, [])
        self.assertIn("freshness cannot be judged", skipped[0])

    def test_a_liability_is_skipped_by_default(self) -> None:
        rows, skipped = select(
            [
                account(
                    name="CREDIT CARD",
                    institution_name="Chase",
                    account_category="LOC",
                    status=None,
                    balance={"total": {"amount": -15646.44, "currency": "USD"}},
                )
            ]
        )

        self.assertEqual(rows, [])
        self.assertIn("--include-liabilities", skipped[0])

    def test_a_liability_can_be_opted_in(self) -> None:
        rows, _ = select(
            [
                account(
                    name="CREDIT CARD",
                    account_category="LOC",
                    status=None,
                    balance={"total": {"amount": -15646.44, "currency": "USD"}},
                )
            ],
            include_liabilities=True,
        )

        self.assertEqual(rows[0]["Balance"], "-$15,646.44")
        self.assertEqual(rows[0]["Category"], "LOC")

    def test_a_deposit_account_is_written(self) -> None:
        # Regression against filtering to INVESTMENT only, which would silently
        # drop cash and savings.
        rows, _ = select([account(account_category="DEPOSIT")])

        self.assertEqual(len(rows), 1)

    def test_an_unclassified_account_is_written(self) -> None:
        # account_category is nullable. An allow-list would drop these too.
        rows, _ = select([account(account_category=None)])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Category"], "UNCLASSIFIED")

    def test_a_paper_account_is_always_skipped(self) -> None:
        rows, skipped = select(
            [account(is_paper=True)],
            allow_stale=True,
            include_liabilities=True,
        )

        self.assertEqual(rows, [])
        self.assertIn("paper", skipped[0])

    def test_a_closed_account_is_skipped(self) -> None:
        # It keeps reporting its final balance, and that balance synced
        # successfully, so no freshness check would catch it.
        rows, skipped = select([account(status="closed")])

        self.assertEqual(rows, [])
        self.assertIn("status is closed", skipped[0])

    def test_an_archived_account_is_skipped(self) -> None:
        rows, _ = select([account(status="archived")])

        self.assertEqual(rows, [])

    def test_an_account_with_no_status_is_written(self) -> None:
        # Several brokerages never populate it; absence is not closure.
        rows, _ = select([account(status=None)])

        self.assertEqual(len(rows), 1)

    def test_a_stale_account_is_skipped(self) -> None:
        rows, skipped = select(
            [
                account(
                    sync_status={
                        "holdings": {
                            "last_successful_sync": "2026-07-01T00:00:00+00:00",
                            "initial_sync_completed": True,
                        }
                    }
                )
            ]
        )

        self.assertEqual(rows, [])
        self.assertIn("34 days ago", skipped[0])
        self.assertIn("--allow-stale", skipped[0])

    def test_a_stale_account_can_be_opted_in_and_is_marked(self) -> None:
        rows, _ = select(
            [
                account(
                    sync_status={
                        "holdings": {
                            "last_successful_sync": "2026-07-01T00:00:00+00:00",
                            "initial_sync_completed": True,
                        }
                    }
                )
            ],
            allow_stale=True,
        )

        self.assertIn("(STALE)", rows[0]["Synced"])

    def test_a_day_old_account_is_not_flagged(self) -> None:
        # SnapTrade refreshes daily by design. A default that flagged healthy
        # accounts would train the operator into passing --allow-stale always.
        rows, skipped = select(
            [
                account(
                    sync_status={
                        "holdings": {
                            "last_successful_sync": "2026-08-03T11:00:00+00:00",
                            "initial_sync_completed": True,
                        }
                    }
                )
            ]
        )

        self.assertEqual(skipped, [])
        self.assertEqual(len(rows), 1)

    def test_a_missing_sync_time_fails_closed(self) -> None:
        rows, skipped = select([account(sync_status={"holdings": {}})])

        self.assertEqual(rows, [])
        self.assertIn("never recorded a successful holdings sync", skipped[0])

    def test_an_unfinished_first_sync_is_skipped(self) -> None:
        rows, skipped = select(
            [
                account(
                    sync_status={
                        "holdings": {
                            "last_successful_sync": "2026-08-04T11:00:00+00:00",
                            "initial_sync_completed": False,
                        }
                    }
                )
            ]
        )

        self.assertEqual(rows, [])
        self.assertIn("first sync has not finished", skipped[0])

    def test_unavailable_holdings_are_skipped(self) -> None:
        rows, skipped = select(
            [
                account(
                    sync_status={
                        "holdings": {
                            "last_successful_sync": "2026-08-04T11:00:00+00:00",
                            "initial_sync_completed": True,
                            "holdings_unavailable": True,
                        }
                    }
                )
            ]
        )

        self.assertEqual(rows, [])
        self.assertIn("unavailable", skipped[0])

    def test_a_missing_balance_is_skipped(self) -> None:
        rows, skipped = select([account(balance={})])

        self.assertEqual(rows, [])
        self.assertIn("no balance", skipped[0])

    def test_a_balance_with_no_amount_is_skipped(self) -> None:
        rows, skipped = select([account(balance={"total": {"currency": "USD"}})])

        self.assertEqual(rows, [])
        self.assertIn("no balance", skipped[0])

    def test_a_zero_balance_is_written(self) -> None:
        # An ESPP with nothing in it is a real datapoint, unlike a missing one.
        rows, _ = select([account(balance={"total": {"amount": 0, "currency": "USD"}})])

        self.assertEqual(rows[0]["Balance"], "$0.00")

    def test_every_skip_is_reported(self) -> None:
        rows, skipped = select(
            [
                account(id="a", is_paper=True),
                account(id="b", status="closed"),
                account(id="c", account_category="LOC"),
                account(id="d"),
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(len(skipped), 3, "no account is dropped silently")


class SilentConnectionTests(unittest.TestCase):
    """A connection that returns nothing produces no other message at all."""

    def test_a_connection_with_accounts_is_not_flagged(self) -> None:
        self.assertEqual(silent_connections([account()], CONNECTIONS), [])

    def test_an_enabled_connection_with_no_accounts_is_named(self) -> None:
        # The Interactive Brokers case: authenticated, not disabled, zero
        # accounts, and previously invisible in the run output.
        connections = {
            LIVE_CONNECTION: CONNECTIONS[LIVE_CONNECTION],
            "conn-ibkr": {
                "id": "conn-ibkr",
                "disabled": False,
                "brokerage": {"name": "Interactive Brokers"},
            },
        }

        warnings = silent_connections([account()], connections)

        self.assertEqual(len(warnings), 1)
        self.assertIn("Interactive Brokers", warnings[0])
        self.assertIn("returned no accounts", warnings[0])

    def test_a_disabled_connection_is_left_to_the_broker(self) -> None:
        # verify_access() already names disabled connections; saying it twice
        # for one problem is the noise the guard exists to avoid.
        warnings = silent_connections([account()], CONNECTIONS)

        self.assertEqual(warnings, [])

    def test_a_connection_whose_accounts_were_all_skipped_is_not_flagged(self) -> None:
        # It did return accounts. Each skip reports itself, so flagging the
        # connection too would double up on an already-explained outcome.
        connections = {
            LIVE_CONNECTION: CONNECTIONS[LIVE_CONNECTION],
        }
        accounts = [account(is_paper=True)]

        rows, skipped = select_accounts(
            accounts,
            connections,
            now=NOW,
            max_age_days=3,
            include_liabilities=False,
            allow_stale=False,
        )

        self.assertEqual(rows, [])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(silent_connections(accounts, connections), [])

    def test_several_silent_connections_are_all_named(self) -> None:
        connections = {
            "a": {"id": "a", "disabled": False, "brokerage": {"name": "Zeta"}},
            "b": {"id": "b", "disabled": False, "brokerage": {"name": "Alpha"}},
        }

        warnings = silent_connections([], connections)

        self.assertEqual(len(warnings), 2)
        self.assertIn("Alpha", warnings[0], "sorted, so output is stable")

    def test_a_connection_with_no_brokerage_name_falls_back_to_its_id(self) -> None:
        connections = {"conn-x": {"id": "conn-x", "disabled": False}}

        warnings = silent_connections([], connections)

        self.assertIn("conn-x", warnings[0])


class _StubLog:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def _record(self, msg: Any) -> None:
        self.messages.append(str(msg))

    fail = success = highlight = display = _record


class _StubDb:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    def get_credentials(self, filter_term: str | None = None) -> list[tuple[str, ...]]:
        return []

    def save_account_data(self, account_name, balance, timestamp) -> None:
        self.saved.append(
            {"account_name": account_name, "balance": balance, "timestamp": timestamp}
        )

    def shutdown_db(self) -> None:
        pass


class _StubDbNoSave(_StubDb):
    save_account_data = None  # type: ignore[assignment]


class _StubContext:
    def __init__(self, db: Any, **args: Any) -> None:
        self.db = db
        self.log = _StubLog()
        self.args = Namespace(
            max_age_days=3, allow_stale=False, include_liabilities=False, **args
        )


class _StubBroker:
    broker = "SnapTrade"

    def __init__(self, accounts: list[dict[str, Any]]) -> None:
        self._accounts = accounts
        self.connections = CONNECTIONS

    def fetch_accounts(self) -> list[dict[str, Any]]:
        return self._accounts


class _WrongBroker:
    broker = "Fidelity"


class OnLoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = SnapTradeModule()
        self.db = _StubDb()

    def test_balances_reach_the_database(self) -> None:
        context = _StubContext(self.db)

        with patch("modules.snaptrade_module.Saver"):
            self.module.on_login(context, _StubBroker([account()]))  # type: ignore[arg-type]

        self.assertEqual(len(self.db.saved), 1)
        self.assertEqual(self.db.saved[0]["balance"], "$6,539.67")

    def test_the_database_label_carries_the_brokerage(self) -> None:
        # Two brokerages can each hold a "MICROSOFT ESPP PLAN" and the accounts
        # table has no brokerage column to tell them apart.
        context = _StubContext(self.db)

        with patch("modules.snaptrade_module.Saver"):
            self.module.on_login(context, _StubBroker([account()]))  # type: ignore[arg-type]

        self.assertEqual(self.db.saved[0]["account_name"], "Schwab - Garrett IRA")

    def test_the_timestamp_matches_the_other_brokers(self) -> None:
        context = _StubContext(self.db)

        with patch("modules.snaptrade_module.Saver"):
            self.module.on_login(context, _StubBroker([account()]))  # type: ignore[arg-type]

        datetime.datetime.strptime(
            self.db.saved[0]["timestamp"], "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=datetime.UTC)

    def test_the_database_is_written_before_sheets(self) -> None:
        # Sheets is best-effort; a failure there must not cost the run its
        # balances.
        context = _StubContext(self.db)

        with patch("modules.snaptrade_module.Saver") as saver:
            saver.return_value.save_accounts.side_effect = SheetsUnavailable("no tab")
            self.module.on_login(context, _StubBroker([account()]))  # type: ignore[arg-type]

        self.assertEqual(len(self.db.saved), 1, "the balance survived")
        self.assertTrue(any("sync skipped" in m for m in context.log.messages))

    def test_a_broken_sheets_client_does_not_lose_balances(self) -> None:
        context = _StubContext(self.db)

        with patch("modules.snaptrade_module.Saver") as saver:
            saver.return_value.save_accounts.side_effect = RuntimeError("boom")
            self.module.on_login(context, _StubBroker([account()]))  # type: ignore[arg-type]

        self.assertEqual(len(self.db.saved), 1)
        self.assertTrue(any("sync failed" in m for m in context.log.messages))

    def test_a_database_without_save_account_data_is_reported(self) -> None:
        context = _StubContext(_StubDbNoSave())

        with patch("modules.snaptrade_module.Saver"):
            self.module.on_login(context, _StubBroker([account()]))  # type: ignore[arg-type]

        self.assertTrue(any("DB contract violation" in m for m in context.log.messages))

    def test_nothing_syncable_writes_nothing_and_says_so(self) -> None:
        context = _StubContext(self.db)

        with patch("modules.snaptrade_module.Saver") as saver:
            self.module.on_login(
                context,
                _StubBroker([account(brokerage_authorization=DEAD_CONNECTION)]),  # type: ignore[arg-type]
            )

        self.assertEqual(self.db.saved, [])
        saver.assert_not_called()
        self.assertTrue(any("Nothing was written" in m for m in context.log.messages))

    def test_the_wrong_broker_fails_cleanly(self) -> None:
        context = _StubContext(self.db)

        self.module.on_login(context, _WrongBroker())  # type: ignore[arg-type]

        self.assertEqual(self.db.saved, [])
        self.assertTrue(
            any("needs the SnapTrade broker" in m for m in context.log.messages)
        )

    def test_a_silent_connection_is_reported_during_a_successful_run(self) -> None:
        # The regression that prompted this: a run that syncs three brokerages
        # fine while a fourth quietly contributes nothing must still say so.
        broker = _StubBroker([account()])
        broker.connections = {
            LIVE_CONNECTION: CONNECTIONS[LIVE_CONNECTION],
            "conn-ibkr": {
                "id": "conn-ibkr",
                "disabled": False,
                "brokerage": {"name": "Interactive Brokers"},
            },
        }
        context = _StubContext(self.db)

        with patch("modules.snaptrade_module.Saver"):
            self.module.on_login(context, broker)  # type: ignore[arg-type]

        self.assertEqual(len(self.db.saved), 1, "the healthy account still synced")
        self.assertTrue(
            any("Interactive Brokers" in m for m in context.log.messages),
            "the empty connection must not be invisible",
        )

    def test_a_failing_fetch_is_reported_not_raised(self) -> None:
        class _Exploding(_StubBroker):
            def fetch_accounts(self) -> list[dict[str, Any]]:
                raise RuntimeError("connection reset")

        context = _StubContext(self.db)

        self.module.on_login(context, _Exploding([]))  # type: ignore[arg-type]

        self.assertTrue(
            any("Could not list SnapTrade accounts" in m for m in context.log.messages)
        )


if __name__ == "__main__":
    unittest.main()
