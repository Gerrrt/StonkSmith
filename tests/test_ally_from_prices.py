# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Valuing Ally without signing in to it.

Ally refuses a restored session however it is stored -- nine runs, three
mechanisms, recorded in docs/live-verification.md -- so a daily unattended run
cannot scrape. It does not have to. The account holds one fund, units only
change when a deposit lands, and a published price needs no login, so the last
signed-in run's units multiplied by today's close is exact on every day the
units did not move.

What that arrangement can get wrong is the part nobody sees. A deposit adds
units this run cannot know about, so the total drifts low and keeps drifting
until somebody signs in again -- and every intervening run reports a number
that looks completely ordinary. So both ages are reported, and the price date
is written to as_of rather than the run's own clock.
"""

import json
import unittest
from typing import Any
from unittest.mock import MagicMock

from modules.ally_module import AllyModule

_ACCOUNT = "Individual (...0847)"

#: The real position, as the database holds it after a signed-in run.
_HOLDING_ROW: tuple[Any, ...] = (
    _ACCOUNT,
    "SWPPX",
    "Schwab S&P 500 Index",
    123.519,
    19.88,
    2455.56,
    None,
    None,
    2237.74,
    "USD",
)

#: (id, account, as_of, scraped_at, value, currency)
_SNAPSHOT_ROW: tuple[Any, ...] = (
    26,
    _ACCOUNT,
    None,
    "2026-08-07 20:40:18",
    2455.56,
    "USD",
)

_STAMPS = (1785936600, 1786023000, 1786109400)


def _payload(closes: tuple[float | None, ...] = (19.91, 19.88, None)) -> str:
    return json.dumps(
        obj={
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "USD", "gmtoffset": -14400},
                        "timestamp": list(_STAMPS),
                        "indicators": {"quote": [{"close": list(closes)}]},
                    }
                ],
                "error": None,
            }
        }
    )


class _Db:
    """A database that can be read back, as SnapshotReadDbProtocol requires."""

    def __init__(
        self,
        holdings: list[tuple[Any, ...]] | None = None,
        snapshots: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self._holdings = [_HOLDING_ROW] if holdings is None else holdings
        self._snapshots = [_SNAPSHOT_ROW] if snapshots is None else snapshots
        self.saved: list[dict[str, Any]] = []

    def get_credentials(self, filter_term: str | None = None) -> list[tuple[str, ...]]:
        return []

    def save_account_data(self, account_name, balance, timestamp) -> None:
        return None

    def shutdown_db(self) -> None:
        return None

    def save_transactions(self, *args: Any, **kwargs: Any) -> int:
        return 0

    def get_holdings(
        self, snapshot_id: int | None = None, limit: int = 500
    ) -> list[tuple[Any, ...]]:
        return self._holdings

    def get_snapshots(
        self, account_id: int | None = None, limit: int = 100
    ) -> list[tuple[Any, ...]]:
        return self._snapshots

    def save_snapshot(self, **kwargs: Any) -> int:
        self.saved.append(kwargs)
        return len(self.saved)


class _WriteOnlyDb(_Db):
    """One that predates history, so there is nothing to read back."""

    get_holdings = None  # type: ignore[assignment]
    get_snapshots = None  # type: ignore[assignment]


def _run(db: Any = None, payload: str | None = None, status_raises: bool = False):
    module = AllyModule()
    context = MagicMock()
    context.db = db if db is not None else _Db()
    context.args.from_prices = True

    connection = MagicMock()
    response = MagicMock()
    response.text = _payload() if payload is None else payload

    if status_raises:
        response.raise_for_status.side_effect = RuntimeError("503")

    connection.session.get.return_value = response

    ok = module.on_login(context, connection)
    return ok, context, connection


class TheOrdinaryRun(unittest.TestCase):
    """One fund, one account, a price published yesterday."""

    def test_it_succeeds_without_a_browser(self) -> None:
        ok, _context, connection = _run()

        self.assertTrue(ok)
        connection.page.goto.assert_not_called()

    def test_it_agrees_with_the_brokers_own_total(self) -> None:
        """123.519 x $19.88 is what Ally itself recorded: $2,455.56."""
        _ok, context, _connection = _run()

        self.assertEqual(context.db.saved[0]["value"], 2455.56)

    def test_as_of_carries_the_price_date_not_the_run_date(self) -> None:
        """as_of is "the date the source says the value is for"."""
        _ok, context, _connection = _run()

        self.assertEqual(context.db.saved[0]["as_of"], "2026-08-06")

    def test_the_units_are_carried_through_untouched(self) -> None:
        _ok, context, _connection = _run()
        held = context.db.saved[0]["holdings"][0]

        self.assertEqual(held.units, 123.519)
        self.assertEqual(held.symbol, "SWPPX")

    def test_the_cost_basis_survives(self) -> None:
        """It was not recomputed, but it must not be dropped either."""
        _ok, context, _connection = _run()

        self.assertEqual(context.db.saved[0]["holdings"][0].cost_basis, 2237.74)

    def test_the_account_keeps_its_identity(self) -> None:
        """A second row for the same account is the failure to avoid."""
        _ok, context, _connection = _run()

        self.assertEqual(context.db.saved[0]["account"].account_key, _ACCOUNT)


class SayingHowOld(unittest.TestCase):
    """Two halves, two ages, and the units are the one that goes wrong."""

    def _said(self, context: MagicMock) -> str:
        calls = (
            context.log.display.call_args_list
            + context.log.success.call_args_list
            + context.log.fail.call_args_list
        )
        return " ".join(str(object=c) for c in calls)

    def test_the_price_date_is_reported(self) -> None:
        _ok, context, _connection = _run()

        self.assertIn("2026-08-06", self._said(context))

    def test_when_the_units_were_recorded_is_reported(self) -> None:
        _ok, context, _connection = _run()

        self.assertIn("2026-08-07", self._said(context))

    def test_it_says_what_makes_the_units_go_stale(self) -> None:
        """A deposit adds units this run cannot see."""
        _ok, context, _connection = _run()

        self.assertIn("--manual-login", self._said(context))

    def test_unknown_units_age_is_said_not_implied(self) -> None:
        _ok, context, _connection = _run(db=_Db(snapshots=[]))

        self.assertIn("unknown time", self._said(context))


class WhenItCannot(unittest.TestCase):
    """Every one of these must refuse rather than invent a number."""

    def test_a_database_that_cannot_be_read_is_reported(self) -> None:
        ok, context, _connection = _run(db=_WriteOnlyDb())

        self.assertFalse(ok)
        self.assertIn(
            "--manual-login",
            " ".join(str(object=c) for c in context.log.fail.call_args_list),
        )

    def test_no_recorded_holdings_is_reported(self) -> None:
        ok, context, _connection = _run(db=_Db(holdings=[]))

        self.assertFalse(ok)
        self.assertEqual(context.db.saved, [])

    def test_a_feed_that_will_not_answer_saves_nothing(self) -> None:
        """Better no mark than one carried over from a previous day."""
        ok, context, _connection = _run(status_raises=True)

        self.assertFalse(ok)
        self.assertEqual(context.db.saved, [])

    def test_an_unpriced_symbol_saves_nothing(self) -> None:
        ok, context, _connection = _run(payload=_payload(closes=(None, None, None)))

        self.assertFalse(ok)
        self.assertEqual(context.db.saved, [])

    def test_a_holding_with_no_symbol_is_reported(self) -> None:
        row = list(_HOLDING_ROW)
        row[1] = None
        ok, context, _connection = _run(db=_Db(holdings=[tuple(row)]))

        self.assertFalse(ok)
        self.assertIn(
            "no symbol",
            " ".join(str(object=c) for c in context.log.fail.call_args_list),
        )


class TheFlagIsAsked(unittest.TestCase):
    """Never inferred from the browser being missing."""

    def test_without_the_flag_a_pageless_run_still_fails(self) -> None:
        """A browser that failed to start must not quietly become a valuation."""
        module = AllyModule()
        context = MagicMock()
        context.args.from_prices = False
        connection = MagicMock()
        connection.page = None

        self.assertFalse(module.on_login(context, connection))


if __name__ == "__main__":
    unittest.main()
