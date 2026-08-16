"""Removing an account that should never have been in the workspace.

`delete account` was refused here for a long time, and the comment recording why
is still in broker_nav because half of it still holds. The argument was that
deleting an account cascades away every snapshot under it -- the opposite of the
narrow correction `delete snapshot` is for -- *and that the next run would
recreate the account anyway*.

The second half is what changed, and only for an account whose source has been
made to stop reporting it. The worked example is the one that prompted this: an
aggregator returning a 529 that a dedicated scraper already covers. Those are two
accounts to this database -- ``account_key`` is unique inside one broker and
means nothing outside it -- so the same money is counted twice in every total
drawn from the workspace, and no amount of deleting individual snapshots fixes
it, because the account is the thing that should not exist.

`[SNAPTRADE] exclude_accounts` stops the writing. It does not remove what is
already stored, and the stored row keeps appearing forever: the account view
returns each account's newest snapshot regardless of its age. So the two are
halves of one operation, and the command says so every time rather than letting
a deletion look permanent and reappear overnight.

The first half of the original argument stands and is why this reports by name:
it cascades, there is no undo, and reading the name back is the operator's only
check on having typed the id from the right row.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from keyring_isolation import MemoryKeyringMixin
from stonksmith.etc.broker_db import BrokerDatabase
from stonksmith.etc.broker_nav import DELETERS, BrokerNavigator
from stonksmith.etc.infrastructure import create_db_engine
from stonksmith.etc.records import AccountIdentity, Holding, Transaction


class DeletingAnAccountTakesItsHistory(MemoryKeyringMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.engine = create_db_engine(db_path=Path(self.tmp.name) / "snaptrade.db")
        self.db = BrokerDatabase(db_engine=self.engine, broker="snaptrade")
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.shutdown_db)

        # Two accounts, so every case can check the other one survived. This is
        # the shape that prompted the command: one real account and one an
        # aggregator reported that another broker already covers.
        for key, name, when in (
            ("Schwab - Sam 529 Plan", "Sam 529 Plan", "2026-08-05 18:30:00"),
            ("Schwab - Alex IRA", "Alex IRA", "2026-08-13 18:30:00"),
        ):
            for stamp in (when, when.replace("18:30", "06:35")):
                self.db.save_snapshot(
                    account=AccountIdentity(
                        account_key=key, display_name=name, source="Schwab"
                    ),
                    scraped_at=stamp,
                    as_of=stamp[:10],
                    value=1395.72,
                    currency="USD",
                    holdings=[Holding(symbol="SWX", units=1.0, value=1395.72)],
                    transactions=[
                        Transaction(
                            tx_type="CONTRIBUTION",
                            value=50.0,
                            processed_on=stamp[:10],
                            external_id=f"{key}-{stamp}",
                        )
                    ],
                )

        self.ids = {row[2]: row[0] for row in self.db.get_accounts()}

    def test_it_reports_the_name_and_how_much_history_it_took(self) -> None:
        # Named rather than numbered, because there is no undo and this line is
        # the only check on having typed the right id.
        removed = self.db.delete_account(account_id=self.ids["Sam 529 Plan"])

        self.assertEqual(removed, ("Sam 529 Plan", 2))

    def test_the_account_is_gone(self) -> None:
        self.db.delete_account(account_id=self.ids["Sam 529 Plan"])

        self.assertEqual([row[2] for row in self.db.get_accounts()], ["Alex IRA"])

    def test_its_snapshots_and_holdings_go_with_it(self) -> None:
        # Through ON DELETE CASCADE, which SQLite honours only because
        # create_db_engine() turns foreign keys on. Without that the rows are
        # orphaned rather than removed and the account view still finds them.
        self.db.delete_account(account_id=self.ids["Sam 529 Plan"])

        remaining = {row[0] for row in self.db.get_current_accounts()}

        self.assertEqual(remaining, {"Schwab - Alex IRA"})

        # get_holdings() leads with the *display name* while get_current_accounts
        # leads with the key -- two reads, two shapes, and asserting the key here
        # fails against a perfectly good cascade. Worth the comment: the columns
        # are documented per method precisely because they differ.
        self.assertTrue(
            all(row[0] == "Alex IRA" for row in self.db.get_holdings()),
            "a holding survived the account it hung from",
        )

    def test_its_transactions_go_with_it(self) -> None:
        self.db.delete_account(account_id=self.ids["Sam 529 Plan"])

        self.assertTrue(
            all(
                row[0] == "Schwab - Alex IRA"
                for row in self.db.get_current_transactions()
            ),
            "a movement survived the account it was recorded against",
        )

    def test_the_other_account_is_untouched(self) -> None:
        # The whole point of cascading on account_id rather than anything
        # broader. A deletion that took a neighbour's history with it would be
        # discovered a month later and never explained.
        self.db.delete_account(account_id=self.ids["Sam 529 Plan"])

        kept = self.db.get_current_accounts()

        self.assertEqual(len(kept), 1)
        self.assertEqual(len(self.db.get_snapshots(account_id=None, limit=None)), 2)

    def test_an_unknown_id_reports_nothing_removed(self) -> None:
        # None rather than a raise, and distinct from a successful removal, so
        # the shell can say "no account with id 99" rather than claiming it
        # deleted one.
        self.assertIsNone(self.db.delete_account(account_id=9999))
        self.assertEqual(len(self.db.get_accounts()), 2)


class TheShellOffersIt(unittest.TestCase):
    def test_account_is_a_delete_target(self) -> None:
        self.assertIn("account", DELETERS)

    def test_it_is_wired_to_the_database_method(self) -> None:
        self.assertEqual(DELETERS["account"], ("delete_account", "account_id"))

    def test_the_narrow_deletions_still_exist(self) -> None:
        # Adding the broad one must not have replaced them. `delete snapshot` is
        # for a mark that is wrong; this is for an account that should not be
        # there, and neither substitutes for the other.
        self.assertIn("snapshot", DELETERS)
        self.assertIn("creds", DELETERS)


class TheShellSaysWhatItTook(unittest.TestCase):
    """The command, driven the way an operator drives it.

    Everything above tests the database. The branch that turns its return value
    into words -- the two-tuple unpack, the name and count, and the reminder
    that this deletion is only half an operation -- had nothing on it at all, so
    the entire safety story rested on code no test ran.
    """

    def setUp(self) -> None:
        self.db = MagicMock()

        # A bare MagicMock is truthy and unpacks to nothing, so the branch would
        # raise ValueError rather than report. Stating the return here is also
        # what lets the assertions below be about the words rather than the id.
        self.db.delete_account.return_value = ("Sam 529 Plan", 4)

        self.nav = BrokerNavigator(
            main_menu=MagicMock(), database=self.db, broker_name="snaptrade"
        )

    def _said(self, line: str) -> tuple[str, str]:
        """(what it reported, what it warned) for one `delete`."""

        with patch("stonksmith.etc.broker_nav.stonksmith_logger") as log:
            self.nav.do_delete(line)

        return str(object=log.success.call_args), str(object=log.highlight.call_args)

    def test_an_account_id_reaches_the_database(self) -> None:
        self.nav.do_delete("account 7")

        self.db.delete_account.assert_called_once_with(account_id=7)

    def test_it_is_not_routed_to_either_narrow_deletion(self) -> None:
        # The three live in one command and take the same-looking argument.
        # Deleting credential 7, or snapshot 7, because the operator asked to
        # delete account 7 is unrecoverable in the same way the account is.
        self.nav.do_delete("account 7")

        self.db.delete_snapshot.assert_not_called()
        self.db.delete_credential.assert_not_called()

    def test_it_reports_the_name_and_the_count_not_just_the_id(self) -> None:
        # An operator who typed the id from the wrong row of `show accounts`
        # finds out here or not at all: it cascades and there is no undo.
        reported, _ = self._said("account 7")

        self.assertIn("Sam 529 Plan", reported)
        self.assertIn("4", reported)

    def test_it_warns_that_the_account_comes_back(self) -> None:
        # The deletion sticks only if the source has been made to stop reporting
        # the account. Printed every time rather than documented once, because
        # the failure mode is a row that looks removed and is back by morning.
        _, warned = self._said("account 7")

        self.assertIn("coming back", warned)
        self.assertIn("exclude_accounts", warned)

    def test_a_snapshot_deletion_carries_no_such_warning(self) -> None:
        # `delete snapshot` does not have that failure mode -- the next sync
        # writes a row beside the removed one, it does not restore it. A warning
        # printed on both would stop being read on either.
        self.db.delete_snapshot.return_value = True

        with patch("stonksmith.etc.broker_nav.stonksmith_logger") as log:
            self.nav.do_delete("snapshot 12")

        log.highlight.assert_not_called()

    def test_an_unknown_id_is_reported_rather_than_unpacked(self) -> None:
        # None, not a tuple. Unpacking it would raise out of a cmd loop that
        # catches nothing, so the miss has to be caught before the name is read.
        self.db.delete_account.return_value = None

        with patch("stonksmith.etc.broker_nav.stonksmith_logger") as log:
            self.nav.do_delete("account 9999")

        self.assertIn("No account with id 9999", str(object=log.fail.call_args))
        log.success.assert_not_called()
        log.highlight.assert_not_called()


if __name__ == "__main__":
    unittest.main()
