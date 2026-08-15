# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Removing one wrong mark, without removing the account or the history.

A snapshot is a record of what was observed when, so a wrong one does not
correct itself. The next sync writes a row beside it rather than over it, and
until someone removes it by hand it goes on being a data point in every chart
drawn from the table.

Both ways of getting one arrived from live TSP runs: a placeholder balance typed
onto a command line and run verbatim, and a real number computed from mismatched
inputs -- a statement's units for one fund priced with another fund's share
price, which came out ninety percent low and looked entirely ordinary in the
table.

What this must *not* do is take anything with it beyond the holdings recorded
under that one mark. Deleting the account would cascade away every other
snapshot and leave the next run to recreate the account -- turning one bad mark
into a duplicate account, which is the failure tests/test_account_identity.py
exists to prevent.
"""

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from sqlalchemy import text

from keyring_isolation import MemoryKeyringMixin
from stonksmith.etc.broker_db import BrokerDatabase
from stonksmith.etc.broker_nav import BrokerNavigator
from stonksmith.etc.infrastructure import create_db_engine
from stonksmith.etc.records import AccountIdentity, Holding

TSP = AccountIdentity(
    account_key="TSP L 2060", display_name="TSP L 2060", kind="INVESTMENT"
)

#: The shape of the mark that prompted this: units of one fund, priced with
#: another fund's price. Nothing about the row says so.
MISMATCHED = Holding(
    fund_code="L 2060", name="L 2060", units=340.000, price=24.6710, value=7790.83
)


class _DbCase(MemoryKeyringMixin, unittest.TestCase):
    """A throwaway database per test, never under $HOME."""

    def setUp(self) -> None:
        super().setUp()
        self._dir = tempfile.TemporaryDirectory()
        self.db = BrokerDatabase(
            create_db_engine(db_path=Path(self._dir.name) / "broker.db"), "tsp"
        )

    def tearDown(self) -> None:
        self.db.shutdown_db()
        self._dir.cleanup()
        super().tearDown()

    def count(self, table: str) -> int:
        with self.db.db_engine.connect() as conn:
            return int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())

    def save(self, **overrides: Any) -> int:
        kwargs: dict[str, Any] = {
            "account": TSP,
            "scraped_at": "2026-08-07 12:00:00",
            "as_of": "2026-08-06",
            "value": 7790.83,
            "holdings": [MISMATCHED],
        }
        kwargs.update(overrides)
        return self.db.save_snapshot(**kwargs)


class DeleteSnapshot(_DbCase):
    """The database method."""

    def test_the_mark_goes(self) -> None:
        bad = self.save()

        self.assertTrue(self.db.delete_snapshot(snapshot_id=bad))
        self.assertEqual(self.count("account_snapshots"), 0)

    def test_its_holdings_go_with_it(self) -> None:
        # Via ON DELETE CASCADE, which SQLite enforces only because
        # create_db_engine() turns foreign keys on. Without that PRAGMA the
        # holding survives its snapshot and shows up under no mark at all.
        bad = self.save()
        self.assertEqual(self.count("holdings"), 1)

        self.db.delete_snapshot(snapshot_id=bad)

        self.assertEqual(self.count("holdings"), 0)

    def test_the_account_stays(self) -> None:
        # THE property. The account is what the next run reuses; removing it
        # would turn one bad mark into a duplicate account.
        bad = self.save()

        self.db.delete_snapshot(snapshot_id=bad)

        self.assertEqual(self.count("accounts"), 1)

    def test_the_other_marks_stay(self) -> None:
        bad = self.save()
        good = self.save(scraped_at="2026-08-07 13:00:00", value=14794.59)

        self.db.delete_snapshot(snapshot_id=bad)

        self.assertEqual([row[0] for row in self.db.get_snapshots()], [good])

    def test_an_unknown_id_reports_rather_than_lying(self) -> None:
        # False, not an exception and not a cheerful "deleted". Typing the
        # wrong id has to be distinguishable from having removed something.
        self.assertFalse(self.db.delete_snapshot(snapshot_id=999))

    def test_and_removes_nothing(self) -> None:
        self.save()

        self.db.delete_snapshot(snapshot_id=999)

        self.assertEqual(self.count("account_snapshots"), 1)


class DeleteCommand(unittest.TestCase):
    """The shell wrapper, which still has to handle `delete creds`."""

    def setUp(self) -> None:
        self.db = MagicMock()
        self.nav = BrokerNavigator(
            main_menu=MagicMock(), database=self.db, broker_name="tsp"
        )

    def test_a_snapshot_id_reaches_the_database(self) -> None:
        self.nav.do_delete("snapshot 12")

        self.db.delete_snapshot.assert_called_once_with(snapshot_id=12)

    def test_creds_still_work(self) -> None:
        self.nav.do_delete("creds 3")

        self.db.delete_credential.assert_called_once_with(cred_id=3)

    def test_a_snapshot_id_does_not_go_to_delete_credential(self) -> None:
        # The two live in one command and take the same-looking argument, so
        # the routing is worth pinning: deleting credential 12 because the
        # operator asked to delete snapshot 12 is unrecoverable.
        self.nav.do_delete("snapshot 12")

        self.db.delete_credential.assert_not_called()

    def test_a_non_numeric_id_deletes_nothing(self) -> None:
        self.nav.do_delete("snapshot latest")

        self.db.delete_snapshot.assert_not_called()

    def test_an_unknown_word_deletes_nothing(self) -> None:
        self.nav.do_delete("accounts 1")

        self.db.delete_snapshot.assert_not_called()
        self.db.delete_credential.assert_not_called()

    def test_an_older_database_is_told_so_rather_than_raising(self) -> None:
        # Same probe history_rows() uses: a database predating snapshots has no
        # delete_snapshot, and an AttributeError out of a cmd loop that catches
        # nothing takes the whole shell down.
        del self.db.delete_snapshot

        with patch("stonksmith.etc.broker_nav.stonksmith_logger") as log:
            self.nav.do_delete("snapshot 12")

        self.assertIn("cannot delete", str(object=log.fail.call_args))

    def test_the_usage_line_names_both(self) -> None:
        with patch("stonksmith.etc.broker_nav.stonksmith_logger") as log:
            self.nav.do_delete("snapshot")

        said = str(object=log.fail.call_args)
        self.assertIn("delete creds", said)
        self.assertIn("delete snapshot", said)


if __name__ == "__main__":
    unittest.main()
