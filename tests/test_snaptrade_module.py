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
from typing import Any, ClassVar
from unittest.mock import patch

from stonksmith.etc.portfolio import normalize_label
from stonksmith.helpers.sheets import SheetsUnavailable
from stonksmith.modules.snaptrade_module import (
    SnapTradeModule,
    activity_transaction,
    brokerage_name,
    currency_code,
    money,
    position_holding,
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

SCHWAB_CONNECTION = "conn-schwab"
FIDELITY_CONNECTION = "conn-fidelity"

#: What linking Schwab alongside Fidelity actually looks like: one key, one
#: listUserAccounts call, two connections behind it.
TWO_BROKERAGES: dict[str, dict[str, Any]] = {
    SCHWAB_CONNECTION: {
        "id": SCHWAB_CONNECTION,
        "disabled": False,
        "disabled_date": None,
        "brokerage": {"name": "Schwab", "slug": "SCHWAB"},
    },
    FIDELITY_CONNECTION: {
        "id": FIDELITY_CONNECTION,
        "disabled": False,
        "disabled_date": None,
        "brokerage": {"name": "Fidelity", "slug": "FIDELITY"},
    },
}


def account(**overrides: Any) -> dict[str, Any]:
    """A healthy Schwab investment account, synced an hour ago.

    "An hour ago" is measured from the real clock, not from NOW. The tests that
    pass an explicit ``now`` are unaffected -- a sync time in their future is
    still fresh -- but the ones that go through ``on_login`` use the real clock,
    and a literal date here meant this account aged out of the freshness window
    three days after it was written. It did: the suite went red on 2026-08-08
    with "its holdings last synced 4 days ago", having passed when it landed.
    """

    synced_an_hour_ago: str = (
        datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(hours=1)
    ).isoformat()

    base: dict[str, Any] = {
        "id": "acct-1",
        "name": "Alex IRA",
        "institution_name": "Schwab",
        "brokerage_authorization": LIVE_CONNECTION,
        "account_category": "INVESTMENT",
        "status": "open",
        "is_paper": False,
        "balance": {"total": {"amount": 6539.67, "currency": "USD"}},
        "sync_status": {
            "holdings": {
                "last_successful_sync": synced_an_hour_ago,
                "initial_sync_completed": True,
            }
        },
    }
    base.update(overrides)

    return base


def select(
    accounts: list[dict[str, Any]],
    *,
    connections: dict[str, dict[str, Any]] | None = None,
    **overrides: Any,
):
    defaults: dict[str, Any] = {
        "now": NOW,
        "max_age_days": 3,
        "include_liabilities": False,
        "allow_stale": False,
    }
    defaults.update(overrides)

    return select_accounts(
        accounts, CONNECTIONS if connections is None else connections, **defaults
    )


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
        healthy: dict[str, Any] = account()
        rows, skipped = select([healthy])

        self.assertEqual(skipped, [])
        self.assertEqual(len(rows), 1)

        # The worksheet's columns.
        self.assertEqual(
            {
                key: rows[0][key]
                for key in ("Brokerage", "Account", "Balance", "Category", "Synced")
            },
            {
                "Brokerage": "Schwab",
                "Account": "Alex IRA",
                "Balance": "$6,539.67",
                "Category": "INVESTMENT",
                "Synced": healthy["sync_status"]["holdings"]["last_successful_sync"],
            },
        )

    def test_a_row_carries_the_unformatted_number_for_the_database(self) -> None:
        # "Balance" is display text. Storing a number means keeping the number
        # that produced it, rather than parsing our own output back.
        rows, _ = select([account()])

        self.assertEqual(rows[0]["Amount"], 6539.67)
        self.assertEqual(rows[0]["Currency"], "USD")
        self.assertEqual(rows[0]["Id"], "acct-1")

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


class MultipleBrokerageTests(unittest.TestCase):
    """
    What linking a second brokerage exposes.

    One StonkSmith broker covers every brokerage SnapTrade connects, so the
    moment Schwab joins Fidelity these accounts share a database, a worksheet
    tab and -- unless the brokerage names them apart -- an identity.

    With one brokerage linked, a missing institution_name was cosmetic. With two
    it is silent data loss: identical account_keys collapse to one accounts row,
    and because every account in a run shares one scraped_at, the second
    account's balance overwrites the first's and its holdings are deleted. The
    run reports success.
    """

    def schwab(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = account(
            id="acct-schwab",
            name="Individual",
            institution_name="Schwab",
            brokerage_authorization=SCHWAB_CONNECTION,
        )
        base.update(overrides)

        return base

    def fidelity(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = account(
            id="acct-fidelity",
            name="Individual",
            institution_name="Fidelity",
            brokerage_authorization=FIDELITY_CONNECTION,
        )
        base.update(overrides)

        return base

    def keys(self, rows: list[dict[str, str]]) -> set[str]:
        """The account_key each row would be stored under."""

        return {SnapTradeModule.identity(row).account_key for row in rows}

    def test_two_brokerages_each_get_their_own_row(self) -> None:
        rows, skipped = select(
            [self.schwab(), self.fidelity()], connections=TWO_BROKERAGES
        )

        self.assertEqual(skipped, [])
        self.assertEqual({row["Brokerage"] for row in rows}, {"Schwab", "Fidelity"})

    def test_identically_named_accounts_at_two_brokerages_stay_distinct(self) -> None:
        rows, _ = select([self.schwab(), self.fidelity()], connections=TWO_BROKERAGES)

        self.assertEqual(
            self.keys(rows), {"Schwab - Individual", "Fidelity - Individual"}
        )

    def test_a_missing_institution_name_falls_back_to_the_connection(self) -> None:
        rows, _ = select(
            [self.schwab(institution_name=None)], connections=TWO_BROKERAGES
        )

        self.assertEqual(rows[0]["Brokerage"], "Schwab")

    def test_two_missing_institution_names_do_not_collide(self) -> None:
        # The regression this whole helper exists for. Both accounts are called
        # "Individual" and neither names its institution, so both used to key to
        # "unknown - Individual" -- one accounts row, one surviving balance.
        rows, _ = select(
            [self.schwab(institution_name=None), self.fidelity(institution_name=None)],
            connections=TWO_BROKERAGES,
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(len(self.keys(rows)), 2, "two accounts, two identities")

        for key in self.keys(rows):
            self.assertNotIn("unknown", key)

    def test_the_slug_is_used_when_the_connection_has_no_name(self) -> None:
        connections = {
            SCHWAB_CONNECTION: {
                "id": SCHWAB_CONNECTION,
                "disabled": False,
                "brokerage": {"slug": "SCHWAB"},
            }
        }

        rows, _ = select([self.schwab(institution_name=None)], connections=connections)

        self.assertEqual(rows[0]["Brokerage"], "SCHWAB")

    def test_a_connection_with_no_brokerage_falls_back_to_its_id(self) -> None:
        connections = {
            SCHWAB_CONNECTION: {"id": SCHWAB_CONNECTION, "disabled": False},
            FIDELITY_CONNECTION: {"id": FIDELITY_CONNECTION, "disabled": False},
        }

        rows, _ = select(
            [self.schwab(institution_name=None), self.fidelity(institution_name=None)],
            connections=connections,
        )

        self.assertIn(SCHWAB_CONNECTION, rows[0]["Brokerage"])
        self.assertEqual(len(self.keys(rows)), 2, "connection ids cannot repeat")

    def test_a_flattened_brokerage_object_does_not_crash_the_run(self) -> None:
        # dict("Schwab") raises ValueError, not KeyError, so an unguarded dict()
        # here would turn an odd payload into a dead run rather than a fallback.
        connections = {
            SCHWAB_CONNECTION: {
                "id": SCHWAB_CONNECTION,
                "disabled": False,
                "brokerage": "Schwab",
            }
        }

        rows, _ = select([self.schwab(institution_name=None)], connections=connections)

        self.assertIn(SCHWAB_CONNECTION, rows[0]["Brokerage"])

    def test_the_source_column_follows_the_brokerage_per_row(self) -> None:
        rows, _ = select([self.schwab(), self.fidelity()], connections=TWO_BROKERAGES)

        for row in rows:
            self.assertEqual(SnapTradeModule.identity(row).source, row["Brokerage"])

    def test_an_unattributable_account_is_still_named_in_its_skip(self) -> None:
        rows, skipped = select(
            [self.schwab(institution_name=None, brokerage_authorization=None)],
            connections=TWO_BROKERAGES,
        )

        self.assertEqual(rows, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("Individual", skipped[0])

    def test_a_disabled_schwab_connection_does_not_cost_fidelity_its_row(self) -> None:
        connections = dict(TWO_BROKERAGES)
        connections[SCHWAB_CONNECTION] = {
            **TWO_BROKERAGES[SCHWAB_CONNECTION],
            "disabled": True,
            "disabled_date": "2026-07-01",
        }

        rows, skipped = select(
            [self.schwab(), self.fidelity()], connections=connections
        )

        self.assertEqual([row["Brokerage"] for row in rows], ["Fidelity"])
        self.assertEqual(len(skipped), 1)
        self.assertIn("Schwab", skipped[0])

    def test_a_stale_account_at_a_degraded_brokerage_says_why(self) -> None:
        connections = {
            SCHWAB_CONNECTION: {
                "id": SCHWAB_CONNECTION,
                "disabled": False,
                "brokerage": {"name": "Schwab", "slug": "SCHWAB", "is_degraded": True},
            }
        }

        _, skipped = select(
            [
                self.schwab(
                    sync_status={
                        "holdings": {
                            "last_successful_sync": "2026-07-01T11:00:00+00:00",
                            "initial_sync_completed": True,
                        }
                    }
                )
            ],
            connections=connections,
        )

        self.assertEqual(len(skipped), 1)
        self.assertIn("degraded", skipped[0])

    def test_a_stale_account_at_a_healthy_brokerage_says_nothing_extra(self) -> None:
        _, skipped = select(
            [
                self.schwab(
                    sync_status={
                        "holdings": {
                            "last_successful_sync": "2026-07-01T11:00:00+00:00",
                            "initial_sync_completed": True,
                        }
                    }
                )
            ],
            connections=TWO_BROKERAGES,
        )

        self.assertEqual(len(skipped), 1)
        self.assertNotIn("degraded", skipped[0])


class ExcludedAccountTests(unittest.TestCase):
    """
    An account two brokers can both reach is money counted twice.

    Nothing in StonkSmith adds the tabs together, so the overlap corrupts no
    stored data -- it just quietly inflates any dashboard total that sums them.
    A Schwab-held 529 is the live case: schwab529plan scrapes it with a
    beneficiary and a principal/earnings split, and SnapTrade reports the same
    money again as one of five Schwab accounts.
    """

    def account_at(self, brokerage: str, name: str) -> dict[str, Any]:
        return account(id=f"acct-{name}", name=name, institution_name=brokerage)

    def test_an_excluded_account_is_skipped(self) -> None:
        rows, skipped = select(
            [self.account_at("Schwab", "Beneficiary A 529 Plan")],
            excluded=frozenset({"schwab / beneficiary a 529 plan"}),
        )

        self.assertEqual(rows, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("another broker covers it", skipped[0])

    def test_the_other_accounts_at_that_brokerage_still_sync(self) -> None:
        # Brokerage-level exclusion would be too coarse: one of five Schwab
        # accounts overlaps, and dropping the other four to fix it is worse
        # than the double count.
        rows, _ = select(
            [
                self.account_at("Schwab", "Beneficiary A 529 Plan"),
                self.account_at("Schwab", "Alex IRA"),
            ],
            excluded=frozenset({"schwab / beneficiary a 529 plan"}),
        )

        self.assertEqual([row["Account"] for row in rows], ["Alex IRA"])

    def test_exclusion_is_reported_before_any_other_reason(self) -> None:
        # An excluded account is not broken, it belongs to somebody else.
        # Reporting it as stale first sends the operator hunting a non-problem.
        stale = self.account_at("Schwab", "Beneficiary A 529 Plan")
        stale["sync_status"] = {
            "holdings": {
                "last_successful_sync": "2026-07-01T11:00:00+00:00",
                "initial_sync_completed": True,
            }
        }

        _, skipped = select(
            [stale], excluded=frozenset({"schwab / beneficiary a 529 plan"})
        )

        self.assertIn("another broker covers it", skipped[0])
        self.assertNotIn("last synced", skipped[0])

    def test_case_and_spacing_do_not_have_to_match(self) -> None:
        # One side is typed into a config file by hand. A capital letter
        # silently restoring the double count is the failure to avoid.
        rows, _ = select(
            [self.account_at("Schwab", "Beneficiary A 529 Plan")],
            excluded=frozenset(
                {normalize_label("  SCHWAB  /  beneficiary a 529 PLAN ")}
            ),
        )

        self.assertEqual(rows, [])

    def test_the_separator_may_be_written_without_spaces(self) -> None:
        # The one piece of punctuation this format demands is the one a person
        # retypes, so "Schwab/Beneficiary A 529 Plan" has to match the spaced form
        # the sync prints. Collapsing whitespace alone leaves them different.
        rows, _ = select(
            [self.account_at("Schwab", "Beneficiary A 529 Plan")],
            excluded=frozenset({normalize_label("Schwab/Beneficiary A 529 Plan")}),
        )

        self.assertEqual(rows, [])

    def test_the_separator_may_be_written_with_extra_spaces(self) -> None:
        rows, _ = select(
            [self.account_at("Schwab", "Beneficiary A 529 Plan")],
            excluded=frozenset(
                {normalize_label("Schwab   /   Beneficiary A 529 Plan")}
            ),
        )

        self.assertEqual(rows, [])

    def test_a_name_containing_a_slash_is_not_a_special_case(self) -> None:
        # Both sides get the same treatment, so an account whose own name has a
        # slash still matches itself.
        rows, _ = select(
            [self.account_at("Fidelity", "Individual/TOD")],
            excluded=frozenset({normalize_label("Fidelity / Individual / TOD")}),
        )

        self.assertEqual(rows, [])

    def test_a_same_named_account_elsewhere_is_not_caught(self) -> None:
        # The label carries the brokerage precisely so excluding one
        # brokerage's account cannot silently drop another's.
        rows, _ = select(
            [self.account_at("Fidelity", "Beneficiary A 529 Plan")],
            excluded=frozenset({"schwab / beneficiary a 529 plan"}),
        )

        self.assertEqual(len(rows), 1)

    def test_nothing_excluded_changes_nothing(self) -> None:
        rows, skipped = select([self.account_at("Schwab", "Alex IRA")])

        self.assertEqual(len(rows), 1)
        self.assertEqual(skipped, [])


class ExclusionSourcesTests(unittest.TestCase):
    """The config and --exclude are combined, not chosen between."""

    def context(self, exclude: Any) -> Any:
        return _StubContext(_StubDb(), exclude=exclude)

    def test_the_config_alone_is_used(self) -> None:
        with patch(
            "stonksmith.etc.config.get_snaptrade_excluded_accounts",
            return_value=["Schwab / Beneficiary A 529 Plan"],
        ):
            self.assertEqual(
                SnapTradeModule.excluded(context=self.context(exclude=None)),
                frozenset({"schwab / beneficiary a 529 plan"}),
            )

    def test_the_flag_adds_to_the_config_rather_than_replacing_it(self) -> None:
        # A cron run carries the standing overlap in config; --exclude is for
        # the one-off. Replacing would silently drop the standing one.
        with patch(
            "stonksmith.etc.config.get_snaptrade_excluded_accounts",
            return_value=["Schwab / Beneficiary A 529 Plan"],
        ):
            self.assertEqual(
                SnapTradeModule.excluded(
                    context=self.context(exclude=["Fidelity / Individual - TOD"])
                ),
                frozenset(
                    {"schwab / beneficiary a 529 plan", "fidelity / individual - tod"}
                ),
            )

    def test_blank_entries_are_dropped(self) -> None:
        # A trailing newline in the config is not an account called "".
        with patch(
            "stonksmith.etc.config.get_snaptrade_excluded_accounts",
            return_value=["", "   "],
        ):
            self.assertEqual(
                SnapTradeModule.excluded(context=self.context(exclude=[])), frozenset()
            )


class BrokerageNameTests(unittest.TestCase):
    """The fallback chain on its own, without an account payload around it."""

    def test_the_institution_name_wins_over_the_connection(self) -> None:
        # Never reordered: every account_key in every existing database was
        # built from institution_name, and preferring the connection would
        # rewrite keys for accounts that are healthy today.
        name = brokerage_name(
            account={"institution_name": "Schwab"},
            connection={"brokerage": {"name": "Charles Schwab & Co."}},
            conn_id=SCHWAB_CONNECTION,
        )

        self.assertEqual(name, "Schwab")

    def test_a_missing_connection_still_yields_the_connection_id(self) -> None:
        name = brokerage_name(account={}, connection=None, conn_id=SCHWAB_CONNECTION)

        self.assertIn(SCHWAB_CONNECTION, name)

    def test_nothing_at_all_is_the_only_route_to_unknown(self) -> None:
        self.assertEqual(
            brokerage_name(account={}, connection=None, conn_id=""), "unknown"
        )


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

    def test_an_unattributable_account_earns_a_caveat_not_silence(self) -> None:
        # An account with no brokerage_authorization cannot be credited to any
        # connection, so its own connection looks silent. Dropping the warning
        # entirely would trade a cosmetic false alarm for a real one going
        # unreported -- the blind spot this function exists to close.
        connections = {
            "c1": {"id": "c1", "disabled": False, "brokerage": {"name": "Schwab"}}
        }
        accounts = [account(brokerage_authorization=None)]

        warnings = silent_connections(accounts, connections)

        self.assertEqual(len(warnings), 1, "the warning is kept")
        self.assertIn("without a connection id", warnings[0], "and qualified")

    def test_no_caveat_when_every_account_is_attributable(self) -> None:
        connections = {
            LIVE_CONNECTION: CONNECTIONS[LIVE_CONNECTION],
            "conn-ibkr": {
                "id": "conn-ibkr",
                "disabled": False,
                "brokerage": {"name": "Interactive Brokers"},
            },
        }

        warnings = silent_connections([account()], connections)

        self.assertNotIn("without a connection id", warnings[0])

    def test_a_connection_with_no_brokerage_name_falls_back_to_its_id(self) -> None:
        connections = {"conn-x": {"id": "conn-x", "disabled": False}}

        warnings = silent_connections([], connections)

        self.assertIn("conn-x", warnings[0])

    def test_a_silent_schwab_is_named_while_fidelity_syncs(self) -> None:
        # The whole point of two brokerages behind one key: one going quiet must
        # not be hidden by the other one working.
        accounts = [
            account(
                id="acct-fidelity",
                institution_name="Fidelity",
                brokerage_authorization=FIDELITY_CONNECTION,
            )
        ]

        warnings = silent_connections(accounts, TWO_BROKERAGES)

        self.assertEqual(len(warnings), 1)
        self.assertIn("Schwab", warnings[0])
        self.assertNotIn("Fidelity", warnings[0])


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

    def __init__(
        self,
        accounts: list[dict[str, Any]],
        connections: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._accounts = accounts
        self.connections = CONNECTIONS if connections is None else connections

    def fetch_accounts(self) -> list[dict[str, Any]]:
        return self._accounts


class _WrongBroker:
    broker = "Fidelity"


class OnLoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = SnapTradeModule()
        self.db = _StubDb()

        # on_login() now reads the exclusion list, and get_config() backfills
        # any option missing from the shipped defaults by *rewriting* the
        # user's stonksmith.conf. Left alone this suite would edit the
        # developer's own config, which tests/test_suite_does_not_touch_home.py
        # exists to catch.
        excluded = patch(
            "stonksmith.etc.config.get_snaptrade_excluded_accounts", return_value=[]
        )
        self.addCleanup(excluded.stop)
        excluded.start()

    def test_balances_reach_the_database(self) -> None:
        context = _StubContext(self.db)

        with patch("stonksmith.modules.snaptrade_module.sync"):
            result = self.module.on_login(context, _StubBroker([account()]))  # type: ignore[arg-type]

        self.assertIsNot(result, False, "a working sync must not fail the run")
        self.assertEqual(len(self.db.saved), 1)
        self.assertEqual(self.db.saved[0]["balance"], "$6,539.67")

    def test_the_database_label_carries_the_brokerage(self) -> None:
        # Two brokerages can each hold a "ACME ESPP PLAN" and the accounts
        # table has no brokerage column to tell them apart.
        context = _StubContext(self.db)

        with patch("stonksmith.modules.snaptrade_module.sync"):
            self.module.on_login(context, _StubBroker([account()]))  # type: ignore[arg-type]

        self.assertEqual(self.db.saved[0]["account_name"], "Schwab - Alex IRA")

    def test_both_brokerages_reach_the_database_with_distinct_labels(self) -> None:
        accounts = [
            account(
                id="acct-schwab",
                name="Individual",
                institution_name="Schwab",
                brokerage_authorization=SCHWAB_CONNECTION,
            ),
            account(
                id="acct-fidelity",
                name="Individual",
                institution_name="Fidelity",
                brokerage_authorization=FIDELITY_CONNECTION,
            ),
        ]
        context = _StubContext(self.db)

        with patch("stonksmith.modules.snaptrade_module.sync"):
            self.module.on_login(context, _StubBroker(accounts, TWO_BROKERAGES))  # type: ignore[arg-type]

        self.assertEqual(
            {row["account_name"] for row in self.db.saved},
            {"Schwab - Individual", "Fidelity - Individual"},
        )

    def test_a_second_brokerage_with_no_institution_name_is_not_merged_away(
        self,
    ) -> None:
        # Where the collision actually bit: identical labels mean one accounts
        # row, and because both accounts share this run's scraped_at, the second
        # balance overwrites the first and its holdings are deleted.
        accounts = [
            account(
                id="acct-schwab",
                name="Individual",
                institution_name=None,
                brokerage_authorization=SCHWAB_CONNECTION,
            ),
            account(
                id="acct-fidelity",
                name="Individual",
                institution_name=None,
                brokerage_authorization=FIDELITY_CONNECTION,
            ),
        ]
        context = _StubContext(self.db)

        with patch("stonksmith.modules.snaptrade_module.sync"):
            self.module.on_login(context, _StubBroker(accounts, TWO_BROKERAGES))  # type: ignore[arg-type]

        labels = [row["account_name"] for row in self.db.saved]

        self.assertEqual(len(labels), 2)
        self.assertEqual(len(set(labels)), 2, "two accounts must not share a key")

    def test_the_timestamp_matches_the_other_brokers(self) -> None:
        context = _StubContext(self.db)

        with patch("stonksmith.modules.snaptrade_module.sync"):
            self.module.on_login(context, _StubBroker([account()]))  # type: ignore[arg-type]

        datetime.datetime.strptime(
            self.db.saved[0]["timestamp"], "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=datetime.UTC)

    def test_the_database_is_written_before_sheets(self) -> None:
        # Sheets is best-effort; a failure there must not cost the run its
        # balances.
        context = _StubContext(self.db)

        # refresh() rather than sync(): the "sync skipped" wording and the
        # decision not to fail the run live inside sync() now, so patching that
        # would remove the behaviour under test.
        with patch("stonksmith.etc.portfolio_sheet.refresh") as refresh:
            refresh.side_effect = SheetsUnavailable("no tab")
            result = self.module.on_login(context, _StubBroker([account()]))  # type: ignore[arg-type]

        self.assertEqual(len(self.db.saved), 1, "the balance survived")
        self.assertIsNot(result, False, "Sheets is best-effort; the run succeeded")
        self.assertTrue(any("sync skipped" in m for m in context.log.messages))

    def test_a_broken_sheets_client_does_not_lose_balances(self) -> None:
        context = _StubContext(self.db)

        # Faulted underneath sync() rather than in place of it, so the broad
        # except that keeps a Sheets crash from costing the run is the thing
        # actually exercised.
        with patch("stonksmith.etc.portfolio_sheet.refresh") as refresh:
            refresh.side_effect = RuntimeError("boom")
            result = self.module.on_login(context, _StubBroker([account()]))  # type: ignore[arg-type]

        self.assertEqual(len(self.db.saved), 1)
        self.assertIsNot(result, False, "Sheets is best-effort; the run succeeded")
        self.assertTrue(any("sync failed" in m for m in context.log.messages))

    def test_a_database_without_save_account_data_is_reported(self) -> None:
        context = _StubContext(_StubDbNoSave())

        with patch("stonksmith.modules.snaptrade_module.sync"):
            result = self.module.on_login(context, _StubBroker([account()]))  # type: ignore[arg-type]

        self.assertFalse(result, "nothing reached the database")
        self.assertTrue(any("DB contract violation" in m for m in context.log.messages))

    def test_nothing_syncable_writes_nothing_and_says_so(self) -> None:
        context = _StubContext(self.db)

        with patch("stonksmith.modules.snaptrade_module.sync") as sheet_sync:
            result = self.module.on_login(
                context,
                _StubBroker([account(brokerage_authorization=DEAD_CONNECTION)]),  # type: ignore[arg-type]
            )

        self.assertFalse(result, "nothing was written")
        self.assertEqual(self.db.saved, [])
        sheet_sync.assert_not_called()
        self.assertTrue(any("Nothing was written" in m for m in context.log.messages))

    def test_the_wrong_broker_fails_cleanly(self) -> None:
        context = _StubContext(self.db)

        result = self.module.on_login(context, _WrongBroker())  # type: ignore[arg-type]

        self.assertFalse(result, "the wrong broker means nothing was written")
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

        with patch("stonksmith.modules.snaptrade_module.sync"):
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

        result = self.module.on_login(context, _Exploding([]))  # type: ignore[arg-type]

        self.assertFalse(result, "a failed fetch means nothing was written")
        self.assertTrue(
            any("Could not list SnapTrade accounts" in m for m in context.log.messages)
        )


class CurrencyCodeTests(unittest.TestCase):
    """SnapTrade spells a currency two ways and both have to work.

    The API returns a currency object; the field is a bare string in enough
    places that assuming either one breaks the other. dict("USD") does not raise
    a KeyError, it raises a ValueError, so the wrong assumption is a crash
    rather than a wrong answer.
    """

    def test_a_currency_object(self) -> None:
        self.assertEqual(currency_code({"code": "cad", "name": "Canadian"}), "CAD")

    def test_a_bare_code(self) -> None:
        self.assertEqual(currency_code("usd"), "USD")

    def test_nothing_falls_back(self) -> None:
        self.assertEqual(currency_code(None), "USD")
        self.assertEqual(currency_code({}), "USD")


class PositionMappingTests(unittest.TestCase):
    """A SnapTrade position becomes a holding row."""

    POSITION: ClassVar[dict[str, Any]] = {
        "symbol": {
            "symbol": {
                "symbol": "VTI",
                "description": "Vanguard Total Market",
                "currency": {"code": "USD"},
            }
        },
        "units": 3,
        "price": 250,
        "average_purchase_price": 200,
    }

    def test_the_ticker_is_pulled_out_of_its_nesting(self) -> None:
        holding = position_holding(position=self.POSITION)

        self.assertEqual(holding.symbol, "VTI")
        self.assertEqual(holding.name, "Vanguard Total Market")

    def test_value_is_derived_from_units_and_price(self) -> None:
        self.assertEqual(position_holding(position=self.POSITION).value, 750.0)

    def test_cost_basis_is_the_average_price_times_the_units(self) -> None:
        # SnapTrade reports a per-unit average, not a total.
        self.assertEqual(position_holding(position=self.POSITION).cost_basis, 600.0)

    def test_a_missing_average_leaves_cost_basis_unset_rather_than_zero(self) -> None:
        position = {
            key: value
            for key, value in self.POSITION.items()
            if key != "average_purchase_price"
        }

        self.assertIsNone(position_holding(position=position).cost_basis)

    def test_a_flattened_symbol_does_not_crash_the_run(self) -> None:
        # dict("VTI") raises a ValueError, not a KeyError, so an unguarded
        # dict() on a response that flattened this would kill the whole sync.
        holding = position_holding(
            position={"symbol": {"symbol": "VTI"}, "units": 2, "price": 10}
        )

        self.assertEqual(holding.symbol, "VTI")
        self.assertEqual(holding.value, 20.0)

    def test_a_position_with_no_symbol_at_all_is_still_a_holding(self) -> None:
        holding = position_holding(position={"units": 2, "price": 10})

        self.assertIsNone(holding.symbol)
        self.assertEqual(holding.value, 20.0)

    def test_a_position_never_borrows_the_scraper_columns(self) -> None:
        holding = position_holding(position=self.POSITION)

        self.assertIsNone(holding.fund_code)
        self.assertIsNone(holding.principal)
        self.assertIsNone(holding.earnings)


class InstrumentPositionTests(unittest.TestCase):
    """
    The shape SnapTrade actually returns today.

    Verbatim from a live account: what is held is described under
    ``instrument``, and the average purchase price is called ``cost_basis``.
    Reading only the older nested ``symbol``/``average_purchase_price`` names
    against this produces a holding of Nones -- a row that is written, looks
    real, and says nothing. Numbers here are the real ones, so the arithmetic
    below is checkable against a brokerage statement.
    """

    FSKAX: ClassVar[dict[str, Any]] = {
        "instrument": {
            "kind": "mutualfund",
            "id": "6e0b7961-1e4a-4953-b780-65d29224e230",
            "symbol": "FSKAX",
            "raw_symbol": "FSKAX",
            "description": "Fidelity Total Market Index Fund",
            "currency": "USD",
            "exchange": "XNAS",
        },
        "units": "10.00",
        "price": "200.00",
        "cost_basis": "170.00",
        "currency": "USD",
        "cash_equivalent": False,
    }

    CASH: ClassVar[dict[str, Any]] = {
        "instrument": {
            "kind": "other",
            "symbol": "FCASH",
            "raw_symbol": "FCASH",
            "description": "CASH",
            "currency": "USD",
        },
        "units": "0.08",
        "price": "1",
        "cost_basis": "1",
        "currency": "USD",
    }

    def test_the_ticker_and_name_come_from_the_instrument(self) -> None:
        holding = position_holding(position=self.FSKAX)

        self.assertEqual(holding.symbol, "FSKAX")
        self.assertEqual(holding.name, "Fidelity Total Market Index Fund")

    def test_string_numbers_are_read_as_numbers(self) -> None:
        # Units and price arrive as strings from this endpoint.
        holding = position_holding(position=self.FSKAX)

        self.assertEqual(holding.units, 10.00)
        self.assertEqual(holding.price, 200.00)
        self.assertAlmostEqual(holding.value or 0, 2000.00, places=2)

    def test_cost_basis_is_per_unit_despite_the_name(self) -> None:
        # 170.00 against a 200.00 price is an average purchase price, not what
        # the whole position cost. Storing it as-is would understate the basis
        # by a factor of the unit count.
        self.assertAlmostEqual(
            position_holding(position=self.FSKAX).cost_basis or 0, 1700.00, places=2
        )

    def test_a_cash_like_instrument_maps_the_same_way(self) -> None:
        holding = position_holding(position=self.CASH)

        self.assertEqual(holding.symbol, "FCASH")
        self.assertEqual(holding.name, "CASH")
        self.assertAlmostEqual(holding.value or 0, 0.08, places=4)

    def test_the_currency_comes_through(self) -> None:
        self.assertEqual(position_holding(position=self.FSKAX).currency, "USD")

    def test_a_flattened_instrument_does_not_crash_the_run(self) -> None:
        holding = position_holding(
            position={"instrument": "FSKAX", "units": "2", "price": "10"}
        )

        self.assertIsNone(holding.symbol)
        self.assertEqual(holding.value, 20.0)

    def test_the_older_nested_shape_still_reads(self) -> None:
        # Both shapes, so a payload that has not moved yet is not silently
        # turned into a row of Nones.
        holding = position_holding(
            position={
                "symbol": {"symbol": {"symbol": "VTI", "description": "Vanguard"}},
                "units": 3,
                "price": 250,
                "average_purchase_price": 200,
            }
        )

        self.assertEqual(holding.symbol, "VTI")
        self.assertEqual(holding.cost_basis, 600.0)

    def test_a_zero_cost_basis_is_kept_rather_than_falling_through(self) -> None:
        # A genuinely free position -- a grant, a spinoff -- reports 0. Treating
        # that as "absent" would fall back to the old field and, finding
        # nothing, drop the basis entirely.
        holding = position_holding(
            position={
                "instrument": {"symbol": "GRANT"},
                "units": "10",
                "price": "5",
                "cost_basis": "0",
            }
        )

        self.assertEqual(holding.cost_basis, 0.0)


class ActivityMappingTests(unittest.TestCase):
    """A SnapTrade activity becomes a transaction row."""

    ACTIVITY: ClassVar[dict[str, Any]] = {
        "id": "act-1",
        "type": "DIVIDEND",
        "trade_date": "2025-12-29T00:00:00Z",
        "settlement_date": "2025-12-31T00:00:00Z",
        "units": 0,
        "price": 0,
        "amount": 12.34,
        "currency": {"code": "USD"},
        "symbol": {"symbol": "VTI"},
        "description": "Dividend received",
    }

    def test_dates_are_normalised(self) -> None:
        transaction = activity_transaction(activity=self.ACTIVITY)

        self.assertEqual(transaction.traded_on, "2025-12-29")
        self.assertEqual(transaction.processed_on, "2025-12-31")

    def test_the_source_id_is_carried_through(self) -> None:
        # With a real id there is nothing to derive, and a derived key would
        # break the moment SnapTrade reordered its window.
        self.assertEqual(
            activity_transaction(activity=self.ACTIVITY).external_id, "act-1"
        )

    def test_the_amount_becomes_the_value(self) -> None:
        self.assertEqual(activity_transaction(activity=self.ACTIVITY).value, 12.34)

    def test_a_zero_amount_is_not_dropped(self) -> None:
        activity = {**self.ACTIVITY, "amount": 0}

        self.assertEqual(activity_transaction(activity=activity).value, 0.0)


if __name__ == "__main__":
    unittest.main()
