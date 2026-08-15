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

from keyring_isolation import MemoryKeyringMixin
from stonksmith.etc.broker_db import BrokerDatabase
from stonksmith.etc.broker_nav import DELETERS
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


if __name__ == "__main__":
    unittest.main()
