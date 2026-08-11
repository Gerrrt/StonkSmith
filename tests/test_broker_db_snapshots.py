# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Writing a run: a value, the positions behind it, and the movements.

Three properties matter here, and each has a way of failing quietly:

* **Atomicity.** The engine is built with isolation_level="AUTOCOMMIT", under
  which every statement commits as it runs and `with conn.begin():` rolls
  nothing back. A snapshot that kept three of its six holdings would look
  exactly like an account that holds three funds.
* **Idempotence.** Re-running a scrape must not double the history. A snapshot
  is keyed on (account, scraped_at) and holdings are replaced wholesale.
* **Not over-deduplicating.** Two identical $50 contributions on the same day
  are indistinguishable field by field, and collapsing them loses half the
  money permanently.
"""

import itertools
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sqlalchemy import text

from etc.broker_db import BrokerDatabase, natural_keys
from etc.infrastructure import create_db_engine
from etc.records import AccountIdentity, Holding, Transaction
from keyring_isolation import MemoryKeyringMixin

BENEFICIARY_A = AccountIdentity(
    account_key="Beneficiary A",
    display_name="Beneficiary A",
    beneficiary="Beneficiary A Surname",
    kind="529",
    external_id="ACC-1",
)

#: A scraped 529 fund row: a fund code, contributions and growth, no ticker.
FUND = Holding(
    fund_code="SWX",
    name="Index 2030",
    units=10.5,
    price=117.58,
    value=1234.56,
    principal=1000.0,
    earnings=234.56,
)

#: An API position: a ticker and a cost basis, no principal or earnings.
POSITION = Holding(
    symbol="VTI",
    name="Vanguard Total Market",
    units=3.0,
    price=250.0,
    value=750.0,
    cost_basis=600.0,
)

CONTRIBUTION = Transaction(
    processed_on="12/30/2025",
    traded_on="12/29/2025",
    tx_type="Contribution",
    value=50.0,
    raw="$50.00",
)


class _SnapshotTestCase(MemoryKeyringMixin, unittest.TestCase):
    """A throwaway database per test, never under $HOME."""

    def setUp(self) -> None:
        super().setUp()
        self._dir = tempfile.TemporaryDirectory()
        self.db = BrokerDatabase(
            create_db_engine(db_path=Path(self._dir.name) / "broker.db"),
            "schwab529plan",
        )

    def tearDown(self) -> None:
        self.db.shutdown_db()
        self._dir.cleanup()
        super().tearDown()

    def count(self, table: str) -> int:
        with self.db.db_engine.connect() as conn:
            return int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())

    def stored_keys(self) -> list[str]:
        with self.db.db_engine.connect() as conn:
            return sorted(
                str(object=row[0])
                for row in conn.execute(text("SELECT natural_key FROM transactions"))
            )

    def save(self, **overrides: Any) -> int:
        kwargs: dict[str, Any] = {
            "account": BENEFICIARY_A,
            "scraped_at": "2026-01-01 00:00:00",
            "value": 1234.56,
            "raw_value": "$1,234.56",
            "as_of": "2025-12-31",
        }
        kwargs.update(overrides)
        return self.db.save_snapshot(**kwargs)


class WriteTests(_SnapshotTestCase):
    """One call writes identity, value, positions and movements."""

    def test_a_snapshot_links_to_its_account_and_holdings(self) -> None:
        snapshot_id = self.save(holdings=[FUND, POSITION])

        self.assertEqual(self.count("accounts"), 1)
        self.assertEqual(self.count("account_snapshots"), 1)
        self.assertEqual(len(self.db.get_holdings(snapshot_id=snapshot_id)), 2)

    def test_the_source_as_of_date_is_kept_apart_from_the_run_time(self) -> None:
        # A daily change is only meaningful against the date the value is for.
        self.save()

        snapshot = self.db.get_snapshots()[0]
        self.assertEqual(snapshot[2], "2025-12-31", "as_of")
        self.assertEqual(snapshot[3], "2026-01-01 00:00:00", "scraped_at")

    def test_both_holding_shapes_persist_without_borrowing_each_other_columns(
        self,
    ) -> None:
        self.save(holdings=[FUND, POSITION])

        with self.db.db_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT symbol, fund_code, principal, earnings, cost_basis "
                    "FROM holdings ORDER BY position"
                )
            ).fetchall()

        fund, position = rows
        self.assertEqual((fund[0], fund[1]), (None, "SWX"))
        self.assertEqual((fund[2], fund[3], fund[4]), (1000.0, 234.56, None))
        self.assertEqual((position[0], position[1]), ("VTI", None))
        self.assertEqual((position[2], position[3], position[4]), (None, None, 600.0))

    def test_an_account_with_no_positions_still_gets_a_snapshot(self) -> None:
        # A pre-aggregated 529 returns zero positions through SnapTrade. That is
        # a fact about the account, not a failed scrape.
        self.save(holdings=[])

        self.assertEqual(self.count("account_snapshots"), 1)
        self.assertEqual(self.count("holdings"), 0)

    def test_a_value_that_could_not_be_read_is_null_not_zero(self) -> None:
        self.save(value=None, raw_value="--")

        self.assertIsNone(self.db.get_snapshots()[0][4])

    def test_metadata_a_later_run_omits_is_not_blanked_out(self) -> None:
        # Sources drop fields. Overwriting a known beneficiary with the None a
        # quieter page produced would lose what the database already had.
        self.save()
        self.db.save_snapshot(
            account=AccountIdentity(
                account_key="Beneficiary A", display_name="Beneficiary A"
            ),
            scraped_at="2026-01-02 00:00:00",
            value=1300.0,
        )

        account = self.db.get_accounts()[0]
        self.assertEqual(account[3], "Beneficiary A Surname", "beneficiary")
        self.assertEqual(account[4], "529", "kind")


class UnitsDateTests(_SnapshotTestCase):
    """The two dates on one row, kept apart.

    A TSP mark is a unit count times a share price and the two are true on
    different days. Before this the units date rode in raw_value, which every
    other broker uses for the value text -- and which nothing read back, so the
    date was stored and invisible.
    """

    def test_a_units_date_persists_apart_from_the_snapshots_own(self) -> None:
        # The single assertion the whole column exists for.
        self.save(
            as_of="2026-08-07",
            holdings=[
                Holding(fund_code="L 2060", units=100.0, units_as_of="2026-06-30")
            ],
        )

        rows = self.db.get_current_holdings()

        self.assertEqual(rows[0][-1], "2026-06-30", "the units date")
        self.assertEqual(rows[0][12], "2026-08-07", "the value's date, untouched")

    def test_a_holding_that_never_dated_its_units_stores_null(self) -> None:
        # Not "", which would be a source saying nothing rather than a source
        # never asked. Every other absent date here is NULL.
        self.save(holdings=[Holding(symbol="VTI", units=10.0)])

        self.assertIsNone(self.db.get_current_holdings()[0][-1])

    def test_the_shell_view_carries_it_too(self) -> None:
        # docs/live-verification.md tells the reader to audit this date from
        # stonksmithdb, which was impossible while get_holdings omitted it.
        self.save(
            holdings=[
                Holding(fund_code="L 2060", units=100.0, units_as_of="2026-06-30")
            ]
        )

        rows = self.db.get_holdings()

        self.assertEqual(len(rows[0]), 11)
        self.assertEqual(rows[0][-1], "2026-06-30")


class IdempotenceTests(_SnapshotTestCase):
    """Re-running a scrape must not double anything."""

    def test_the_same_run_written_twice_is_one_snapshot(self) -> None:
        self.save(transactions=[CONTRIBUTION])
        self.save(transactions=[CONTRIBUTION])

        self.assertEqual(self.count("account_snapshots"), 1)
        self.assertEqual(self.count("transactions"), 1)

    def test_holdings_are_replaced_wholesale_not_appended(self) -> None:
        # A re-run that finds fewer positions must not leave the ones it no
        # longer sees lying around looking current.
        snapshot_id = self.save(holdings=[FUND, POSITION])
        self.save(holdings=[FUND])

        self.assertEqual(len(self.db.get_holdings(snapshot_id=snapshot_id)), 1)

    def test_a_later_run_adds_a_snapshot_without_re_adding_transactions(self) -> None:
        self.save(transactions=[CONTRIBUTION])
        self.save(scraped_at="2026-01-02 00:00:00", transactions=[CONTRIBUTION])

        self.assertEqual(self.count("account_snapshots"), 2)
        self.assertEqual(self.count("transactions"), 1)

    def test_a_re_scrape_contributes_only_what_is_new(self) -> None:
        later = Transaction(
            processed_on="12/31/2025",
            traded_on="12/31/2025",
            tx_type="Dividend",
            value=7.25,
            raw="$7.25",
        )

        self.save(transactions=[CONTRIBUTION])
        self.save(scraped_at="2026-01-02 00:00:00", transactions=[CONTRIBUTION, later])

        self.assertEqual(self.count("transactions"), 2)


class DuplicateTransactionTests(_SnapshotTestCase):
    """Identical movements are still two movements."""

    def test_two_identical_rows_in_one_batch_both_persist(self) -> None:
        self.save(transactions=[CONTRIBUTION, CONTRIBUTION])

        self.assertEqual(
            self.count("transactions"),
            2,
            "collapsing same-day duplicates loses half the money permanently",
        )

    def test_re_scraping_them_still_yields_exactly_two(self) -> None:
        self.save(transactions=[CONTRIBUTION, CONTRIBUTION])
        self.save(
            scraped_at="2026-01-02 00:00:00",
            transactions=[CONTRIBUTION, CONTRIBUTION],
        )

        self.assertEqual(self.count("transactions"), 2)

    def test_the_ordinal_only_separates_genuine_repeats(self) -> None:
        keys = natural_keys(rows=[CONTRIBUTION, CONTRIBUTION])

        self.assertNotEqual(keys[0], keys[1])
        self.assertEqual(keys, natural_keys(rows=[CONTRIBUTION, CONTRIBUTION]))

    def test_a_source_supplied_id_is_used_directly(self) -> None:
        # SnapTrade gives every activity an id, so there is nothing to derive.
        # A real id also survives what a derived key cannot: the same movement
        # reaching two windows separately is still one row here, where a derived
        # key would have to guess. See WindowOrderTests for that boundary.
        rows = [
            Transaction(external_id="abc", tx_type="BUY", value=1.0),
            Transaction(external_id="abc", tx_type="BUY", value=1.0),
        ]

        self.assertEqual(natural_keys(rows=rows), ["id:abc", "id:abc"])

        self.save(transactions=rows)
        self.assertEqual(self.count("transactions"), 1)


class WindowOrderTests(_SnapshotTestCase):
    """How much reordering the derived key survives, and where it stops."""

    #: Same day, same amount, same everything: only the ordinal separates them.
    TWIN = CONTRIBUTION
    OTHER = Transaction(
        processed_on="01/15/2026",
        traded_on="01/14/2026",
        tx_type="Dividend",
        value=3.10,
        raw="$3.10",
    )

    def test_a_reversed_window_produces_the_same_keys(self) -> None:
        window = [self.TWIN, self.TWIN, self.OTHER]

        self.assertEqual(
            sorted(natural_keys(rows=window)),
            sorted(natural_keys(rows=list(reversed(window)))),
        )

    def test_every_ordering_of_one_window_produces_the_same_keys(self) -> None:
        # The ordinal counts identical *content*, not position, so the keys are
        # a function of what the window holds rather than the order it came in.
        window = [self.TWIN, self.TWIN, self.OTHER]
        expected = sorted(natural_keys(rows=window))

        for ordering in itertools.permutations(window):
            self.assertEqual(
                sorted(natural_keys(rows=list(ordering))),
                expected,
                f"order changed the keys: {ordering}",
            )

    def test_a_newest_first_re_scrape_neither_duplicates_nor_drops(self) -> None:
        # The failure this guards: a source that starts paginating newest-first
        # would re-key its whole window, and every row would insert again.
        window = [self.OTHER, self.TWIN, self.TWIN]
        self.save(transactions=window)

        before = self.stored_keys()
        self.save(scraped_at="2026-01-02 00:00:00", transactions=list(reversed(window)))

        self.assertEqual(self.count("transactions"), 3)
        self.assertEqual(self.stored_keys(), before)

    def test_a_window_that_widens_still_gains_the_sibling(self) -> None:
        # One contribution stored, then a window holding both: the ordinal
        # reaches past what is already there rather than colliding with it.
        self.save(transactions=[self.TWIN])
        self.save(scraped_at="2026-01-02 00:00:00", transactions=[self.TWIN, self.TWIN])

        self.assertEqual(self.count("transactions"), 2)

    def test_a_pair_split_across_two_windows_cannot_be_told_from_a_re_scrape(
        self,
    ) -> None:
        # This is the bound, not an oversight. These two batches are
        # byte-identical to the same movement fetched twice -- which is exactly
        # what IdempotenceTests asserts must collapse to one row. No key derived
        # from content alone can separate the two cases, so the scheme picks the
        # side that never duplicates, and a genuine second contribution split
        # across windows is the price.
        self.save(transactions=[self.TWIN])
        self.save(scraped_at="2026-01-02 00:00:00", transactions=[self.TWIN])

        self.assertEqual(self.count("transactions"), 1)

    def test_a_source_supplied_id_is_unaffected_by_its_neighbours_moving(self) -> None:
        # A batch can hold both kinds at once: SnapTrade omitting an id on one
        # activity puts that row on the derived branch beside the others.
        window = [
            Transaction(external_id="act-1", tx_type="BUY", value=1.0),
            self.TWIN,
            self.TWIN,
            Transaction(external_id="act-2", tx_type="DIVIDEND", value=2.0),
        ]

        self.assertEqual(
            sorted(natural_keys(rows=window)),
            sorted(natural_keys(rows=list(reversed(window)))),
        )

        self.save(transactions=window)
        stored = self.stored_keys()
        self.save(scraped_at="2026-01-02 00:00:00", transactions=list(reversed(window)))

        self.assertEqual(self.count("transactions"), 4)
        self.assertEqual(self.stored_keys(), stored)


class AtomicityTests(_SnapshotTestCase):
    """Half a scrape must not reach the database."""

    def test_a_failure_partway_through_leaves_nothing_behind(self) -> None:
        # The engine runs in AUTOCOMMIT, where a plain conn.begin() rolls
        # nothing back. Without the SERIALIZABLE override in _write(), the
        # account and snapshot below would survive this raise.
        with (
            patch.object(
                BrokerDatabase,
                "_insert_transactions",
                side_effect=RuntimeError("network died mid-write"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.save(holdings=[FUND], transactions=[CONTRIBUTION])

        self.assertEqual(self.count("accounts"), 0)
        self.assertEqual(self.count("account_snapshots"), 0)
        self.assertEqual(self.count("holdings"), 0)
        self.assertEqual(self.count("transactions"), 0)

    def test_an_earlier_good_snapshot_is_not_rolled_back_too(self) -> None:
        self.save()

        with (
            patch.object(
                BrokerDatabase,
                "_insert_transactions",
                side_effect=RuntimeError("boom"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.save(scraped_at="2026-01-02 00:00:00", transactions=[CONTRIBUTION])

        self.assertEqual(self.count("account_snapshots"), 1)


class ReadTests(_SnapshotTestCase):
    """What the navigator and the savers read back."""

    def test_the_delta_between_consecutive_snapshots(self) -> None:
        self.save(value=1000.0)
        self.save(scraped_at="2026-01-02 00:00:00", value=1100.0)

        newest = self.db.get_daily_change()[0]
        self.assertEqual(newest[3], 1100.0)
        self.assertEqual(newest[4], 1000.0)
        self.assertEqual(newest[5], 100.0)

    def test_the_first_snapshot_has_no_delta_rather_than_a_zero_one(self) -> None:
        self.save(value=1000.0)

        self.assertIsNone(self.db.get_daily_change()[0][5])

    def test_latest_snapshots_returns_one_row_per_account(self) -> None:
        self.save(value=1000.0)
        self.save(scraped_at="2026-01-02 00:00:00", value=1100.0)
        self.db.save_snapshot(
            account=AccountIdentity(account_key="Other", display_name="Other"),
            scraped_at="2026-01-02 00:00:00",
            value=5.0,
        )

        latest = self.db.get_latest_snapshots()
        self.assertEqual(len(latest), 2)
        self.assertEqual({row[3] for row in latest}, {1100.0, 5.0})

    def test_holdings_default_to_the_newest_snapshot(self) -> None:
        self.save(holdings=[FUND])
        self.save(scraped_at="2026-01-02 00:00:00", holdings=[POSITION])

        current = self.db.get_holdings()
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0][1], "VTI")

    def test_save_transactions_works_without_a_snapshot(self) -> None:
        stored = self.db.save_transactions(
            account=BENEFICIARY_A,
            timestamp="2026-01-01 00:00:00",
            rows=[CONTRIBUTION],
        )

        self.assertEqual(stored, 1)
        self.assertEqual(self.count("account_snapshots"), 0)


class AccountHistoryTests(_SnapshotTestCase):
    """The unlimited read behind the Net Worth tab."""

    def test_it_returns_every_snapshot_not_only_the_newest(self) -> None:
        # The bug: get_current_accounts restricts to one snapshot per account,
        # so a sheet built on it shows today and throws the history away while
        # the database goes on holding it.
        self.save(value=1000.0)
        self.save(scraped_at="2026-01-02 00:00:00", value=1100.0)
        self.save(scraped_at="2026-01-03 00:00:00", value=1200.0)

        self.assertEqual(len(self.db.get_current_accounts()), 1)
        self.assertEqual(
            [row[5] for row in self.db.get_account_history()], [1000.0, 1100.0, 1200.0]
        )

    def test_it_returns_the_same_nine_columns_the_current_read_does(self) -> None:
        # Deliberately identical, so one projection in etc.portfolio serves
        # both and an account cannot end up named one thing on the Accounts tab
        # and another on the series.
        self.save(value=1000.0)

        self.assertEqual(self.db.get_account_history(), self.db.get_current_accounts())

    def test_a_snapshot_with_no_value_comes_back_as_null_not_zero(self) -> None:
        # The distinction the column is nullable for. The series drops such a
        # snapshot rather than carrying it, which it can only do if it arrives
        # distinguishable from a real zero.
        self.save(value=None)

        self.assertIsNone(self.db.get_account_history()[0][5])

    def test_it_returns_every_snapshot_however_many_there_are(self) -> None:
        # Unlimited for get_current_transactions's reason: this is the second
        # thing here that grows without bound, and a limit would be the
        # difference between a history and the newest page of one -- shown with
        # nothing whatever saying so.
        for day in range(1, 32):
            self.save(scraped_at=f"2026-01-{day:02d} 00:00:00", value=float(day))

        for month in range(2, 21):
            self.save(scraped_at=f"2026-{month:02d}-01 00:00:00", value=float(month))

        history = self.db.get_account_history()

        self.assertEqual(len(history), 50)
        self.assertEqual(history[0][5], 1.0)

    def test_snapshots_come_back_oldest_first_within_an_account(self) -> None:
        # A series is carried forward, which needs each account's readings in
        # the order they happened. Newest-first is the log's order, not this.
        self.save(scraped_at="2026-01-03 00:00:00", value=3.0)
        self.save(scraped_at="2026-01-01 00:00:00", value=1.0)
        self.save(scraped_at="2026-01-02 00:00:00", value=2.0)

        self.assertEqual(
            [row[5] for row in self.db.get_account_history()], [1.0, 2.0, 3.0]
        )


class CurrentTransactionsTests(_SnapshotTestCase):
    """The unlimited read behind the Transactions tab."""

    def _many(self, count: int) -> list[Transaction]:
        """Movements enough to run past the shell reader's default limit."""

        return [
            Transaction(
                processed_on=f"2026-01-{index % 28 + 1:02d}",
                tx_type="Contribution",
                value=float(index),
                raw=f"${index}.00",
            )
            for index in range(count)
        ]

    def test_it_carries_the_key_the_shell_reader_does_not(self) -> None:
        # get_transactions returns the display name, which is explicitly not
        # identity. A view joining across brokers has to have the key.
        self.save(transactions=[CONTRIBUTION])

        row = self.db.get_current_transactions()[0]

        self.assertEqual(row[0], "Beneficiary A")
        self.assertEqual(len(row), 12)

    def test_it_returns_every_movement_however_many_there_are(self) -> None:
        # The reason it exists. get_transactions stops at 500 by default, so a
        # tab built on that one would report the newest five hundred as though
        # they were all of them.
        self.save(transactions=self._many(count=640))

        self.assertEqual(len(self.db.get_transactions()), 500)
        self.assertEqual(len(self.db.get_current_transactions()), 640)

    def test_every_capped_reader_can_be_asked_for_all_of_it(self) -> None:
        # What `export` passes. The cap stays the default, because `show` still
        # wants one -- but a CSV that stops at five hundred rows cannot tell
        # anyone that it did, so the option has to exist.
        self.save(transactions=self._many(count=640))

        for index in range(130):
            self.save(
                scraped_at=f"2026-03-{index % 28 + 1:02d} {index % 24:02d}:00:00",
                value=float(index),
            )

        for reader, default, total in (
            (self.db.get_transactions, 500, 640),
            (self.db.get_snapshots, 100, 131),
            (self.db.get_daily_change, 100, 131),
        ):
            with self.subTest(reader=reader.__name__):
                self.assertEqual(len(reader()), default, "the default still caps")
                self.assertEqual(len(reader(limit=None)), total, "None means all")

    def test_a_filter_still_narrows_when_uncapped(self) -> None:
        # The limit and the filter are independent; asking for everything must
        # not quietly widen which account it came from.
        self.save(transactions=self._many(count=640))
        self.db.save_snapshot(
            account=AccountIdentity(account_key="Other", display_name="Other"),
            scraped_at="2026-01-02 00:00:00",
            transactions=[CONTRIBUTION],
            value=5.0,
        )

        everything = self.db.get_transactions(limit=None)
        just_one = self.db.get_transactions(account_id=1, limit=None)

        self.assertEqual(len(everything), 641)
        self.assertEqual(len(just_one), 640)

    def test_it_is_not_scoped_to_the_newest_snapshot(self) -> None:
        # Unlike the other two current-state readers. A movement is recorded
        # once and deduped thereafter, so every stored row is current -- an
        # older run's movements must not disappear when a newer run lands.
        self.save(transactions=[CONTRIBUTION])
        self.save(
            scraped_at="2026-02-01 00:00:00",
            transactions=[
                Transaction(
                    processed_on="2026-02-01", tx_type="Contribution", value=99.0
                )
            ],
        )

        self.assertEqual(len(self.db.get_current_transactions()), 2)


class FalsyIdsStillNarrowTests(_SnapshotTestCase):
    """
    Id 0 is an unknown id, not an absent filter.

    Every reader here built its WHERE clause on `if account_id`, so the one
    falsy id dropped the clause instead of matching nothing -- and 999 already
    returned nothing, which made 0 the only id that behaved differently. Two
    accounts, because with one the dropped filter and the applied one both
    return the same single row.
    """

    def setUp(self) -> None:
        super().setUp()
        self.save(holdings=[FUND], transactions=[CONTRIBUTION])
        self.db.save_snapshot(
            account=AccountIdentity(account_key="Other", display_name="Other"),
            scraped_at="2026-01-02 00:00:00",
            value=750.0,
            holdings=[POSITION],
            transactions=[
                Transaction(
                    processed_on="12/31/2025", tx_type="Contribution", value=5.0
                )
            ],
        )

    def test_account_id_zero_narrows_snapshots_rather_than_showing_all(self) -> None:
        self.assertEqual(len(self.db.get_snapshots()), 2, "both accounts are stored")

        self.assertEqual(self.db.get_snapshots(account_id=0), [])

    def test_account_id_zero_narrows_transactions_rather_than_showing_all(
        self,
    ) -> None:
        stored = self.db.get_transactions()
        self.assertEqual(len(stored), 2, "both movements are stored")

        self.assertEqual(self.db.get_transactions(account_id=0), [])

    def test_snapshot_id_zero_narrows_holdings_rather_than_meaning_current(
        self,
    ) -> None:
        # The quieter half: a falsy id here selected the newest-snapshot branch,
        # so `show holdings 0` answered with current positions rather than none.
        self.assertEqual(len(self.db.get_holdings()), 2, "one per account, newest each")

        self.assertEqual(self.db.get_holdings(snapshot_id=0), [])


if __name__ == "__main__":
    unittest.main()
