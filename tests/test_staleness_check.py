# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""The check a schedule has no other way to make.

`docs/scheduling.md` opens by naming the failure this closes: a cron job that
errors every night gets muted, after which the portfolio has stopped updating and
nothing says so. Exit code 1 already covers a module reporting it did nothing.
This covers the quiet way, which the design itself creates -- the Net Worth series
carries a value forward for thirty days and --from-prices reprices a recorded unit
count indefinitely, so a broker can go dark for a month while every run exits 0.

So the cases that matter here are the ones where something looks fine and is not.
Each builds a real database rather than stubbing a portfolio, because the whole
path is the thing under test: what the databases hold, what the rule makes of it,
and what the shell exits with.
"""

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_isolation import UserConfigMixin
from etc.broker_db import BrokerDatabase
from etc.infrastructure import create_db_engine
from etc.portfolio import (
    STALE_DAYS,
    AccountRow,
    Portfolio,
    is_stale,
    stale_accounts,
    stale_cutoff,
    stale_reason,
)
from etc.records import AccountIdentity
from etc.stonksmithdb import StonkSmithDBMenu
from keyring_isolation import MemoryKeyringMixin

TODAY = dt.date(2026, 8, 11)


class RuleTests(unittest.TestCase):
    """What counts as stale, which has to fail closed rather than guess."""

    def setUp(self) -> None:
        self.cutoff = stale_cutoff(today=TODAY, days=STALE_DAYS)

    def test_the_cutoff_is_the_window_back_from_today(self) -> None:
        self.assertEqual(self.cutoff, "2026-08-04")

    def test_a_recent_date_is_fresh(self) -> None:
        self.assertFalse(is_stale(as_of="2026-08-10", cutoff=self.cutoff))

    def test_the_cutoff_day_itself_is_fresh(self) -> None:
        # A boundary worth pinning rather than discovering: "older than" is the
        # rule the dashboard's QUERY uses, and < rather than <= is what makes an
        # account that reported exactly on the cutoff count as still good.
        self.assertFalse(is_stale(as_of=self.cutoff, cutoff=self.cutoff))

    def test_an_older_date_is_stale(self) -> None:
        self.assertTrue(is_stale(as_of="2026-08-03", cutoff=self.cutoff))

    def test_no_date_is_stale(self) -> None:
        # A number with no date attached is a claim about no particular day.
        for missing in (None, "", "   "):
            with self.subTest(missing=missing):
                self.assertTrue(is_stale(as_of=missing, cutoff=self.cutoff))

    def test_a_date_nothing_could_read_is_stale(self) -> None:
        # The one a string comparison gets backwards, and the reason this rule
        # is in Python rather than only in the dashboard's QUERY: "whenever" is
        # greater than any real date as text, so it reads as fresher than today
        # and an account whose parser broke looks like the healthiest one there.
        for unreadable in ("whenever", "12/30/2025", "2026-08", "yesterday"):
            with self.subTest(unreadable=unreadable):
                self.assertTrue(is_stale(as_of=unreadable, cutoff=self.cutoff))

    def test_each_kind_of_stale_says_which_kind_it_is(self) -> None:
        # A reader told only "stale" is being sent to look at the wrong thing.
        self.assertEqual(stale_reason(as_of=None, today=TODAY), "no as-of date")
        self.assertIn("nothing could read", stale_reason(as_of="whenever", today=TODAY))
        self.assertEqual(
            stale_reason(as_of="2026-01-31", today=TODAY),
            "as of 2026-01-31, 192 days old",
        )

    def test_an_unreadable_date_is_not_given_an_age(self) -> None:
        # It has none. Saying "42 days old" about text nothing parsed would be
        # inventing the number the check exists to be honest about.
        self.assertNotIn("days old", stale_reason(as_of="whenever", today=TODAY))


def account(broker: str, as_of: str | None) -> AccountRow:
    return AccountRow(
        broker=broker,
        source=broker,
        account=broker.upper(),
        account_key=broker,
        as_of=as_of,
    )


class OrderingTests(unittest.TestCase):
    def test_the_undated_come_first_and_the_rest_oldest_first(self) -> None:
        # Neither a missing date nor an unreadable one is an age, so sorting
        # them in among real dates by their text ranks 'whenever' as younger
        # than a genuine January -- which puts the worst row last.
        holds = Portfolio(
            accounts=(
                account(broker="tsp", as_of="2026-01-31"),
                account(broker="snaptrade", as_of="whenever"),
                account(broker="ally", as_of=None),
                account(broker="fidelity", as_of="2026-07-01"),
            )
        )
        found = stale_accounts(
            portfolio=holds, cutoff=stale_cutoff(today=TODAY, days=STALE_DAYS)
        )

        self.assertEqual(
            [row.broker for row in found],
            ["ally", "snaptrade", "tsp", "fidelity"],
        )

    def test_a_fresh_account_is_not_in_the_list(self) -> None:
        holds = Portfolio(
            accounts=(
                account(broker="ally", as_of="2026-08-10"),
                account(broker="tsp", as_of="2026-01-31"),
            )
        )
        found = stale_accounts(
            portfolio=holds, cutoff=stale_cutoff(today=TODAY, days=STALE_DAYS)
        )

        self.assertEqual([row.broker for row in found], ["tsp"])


class ShellTests(UserConfigMixin, MemoryKeyringMixin, unittest.TestCase):
    """The command, its exit status, and what it prints."""

    def setUp(self) -> None:
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "default").mkdir()

    def _write(self, broker: str, as_of: str | None, key: str = "ACC-1") -> None:
        db = BrokerDatabase(
            db_engine=create_db_engine(db_path=self.root / "default" / f"{broker}.db"),
            broker=broker,
        )
        db.save_snapshot(
            account=AccountIdentity(
                account_key=key, display_name=key, kind="INVESTMENT"
            ),
            scraped_at="2026-08-11 09:00:00",
            as_of=as_of,
            value=100.0,
            currency="USD",
            holdings=[],
            transactions=[],
        )
        db.shutdown_db()

    def _run(self, line: str = "") -> tuple[bool, str]:
        """Run `stale` against the built workspace; return (failed, output)."""

        shell = StonkSmithDBMenu.__new__(StonkSmithDBMenu)
        shell.workspace = "default"
        shell.failed = False

        printed: list[str] = []

        with (
            patch("etc.portfolio.workspace_dir", str(object=self.root)),
            patch(
                "builtins.print",
                side_effect=lambda *a: printed.append(" ".join(map(str, a))),
            ),
        ):
            shell.do_stale(line)

        return shell.failed, "\n".join(printed)

    def test_a_fresh_workspace_passes(self) -> None:
        self._write(broker="ally", as_of=dt.date.today().isoformat())
        failed, output = self._run()

        self.assertFalse(failed, output)

    def test_success_still_says_something(self) -> None:
        # A check whose success is silent is one nobody can tell ran, which is
        # the same failure mode as the muted cron job this exists to catch.
        self._write(broker="ally", as_of=dt.date.today().isoformat())
        _, output = self._run()

        self.assertIn("0 of 1 accounts are stale", output)

    def test_a_stale_account_fails_and_is_named(self) -> None:
        self._write(broker="ally", as_of=dt.date.today().isoformat())
        self._write(broker="tsp", as_of="2026-01-31")
        failed, output = self._run()

        self.assertTrue(failed)
        self.assertIn("tsp / ACC-1", output)
        self.assertIn("1 of 2 accounts are stale", output)

        # And the fresh one is not dragged in with it.
        self.assertNotIn("ally / ACC-1:", output)

    def test_an_account_with_no_date_fails(self) -> None:
        self._write(broker="schwab529plan", as_of=None)
        failed, output = self._run()

        self.assertTrue(failed)
        self.assertIn("no as-of date", output)

    def test_an_unreadable_date_fails_rather_than_reading_as_fresh(self) -> None:
        # The whole reason this is not just the dashboard's QUERY in Python.
        self._write(broker="snaptrade", as_of="whenever")
        failed, output = self._run()

        self.assertTrue(failed)
        self.assertIn("nothing could read", output)

    def test_a_broker_that_will_not_open_fails(self) -> None:
        # Not stale data: no data. do_sheet already treats this as a failure
        # rather than a note, and a total short by a whole broker is the failure
        # this project keeps finding.
        self._write(broker="ally", as_of=dt.date.today().isoformat())
        (self.root / "default" / "tsp.db").write_text(data="this is not a database")

        failed, output = self._run()

        self.assertTrue(failed)
        self.assertIn("could not be read", output)

    def test_the_day_count_is_honoured(self) -> None:
        # Fresh at the default window, stale at one day.
        self._write(
            broker="ally", as_of=(dt.date.today() - dt.timedelta(days=3)).isoformat()
        )

        self.assertFalse(self._run()[0])
        self.assertTrue(self._run(line="1")[0])

    def test_a_day_count_that_is_not_a_number_fails_without_raising(self) -> None:
        self._write(broker="ally", as_of=dt.date.today().isoformat())
        failed, output = self._run(line="soon")

        self.assertTrue(failed)
        self.assertIn("not a number of days", output)

    def test_a_negative_day_count_is_refused(self) -> None:
        # It puts the cutoff in the future, which makes every account stale
        # including the one written this morning. Not a stricter check, a broken
        # one -- and it would report a healthy workspace as entirely rotten.
        self._write(broker="ally", as_of=dt.date.today().isoformat())
        failed, output = self._run(line="-3")

        self.assertTrue(failed)
        self.assertIn("cannot be negative", output)
        self.assertNotIn("1 of 1 accounts are stale", output)


if __name__ == "__main__":
    unittest.main()
