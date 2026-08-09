# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Browsing account history from the `stonksmithdb` shell.

Stored values are numbers. Printing them raw would show "1234.56" where every
other surface in StonkSmith shows "$1,234.56", and would render a CAD balance
wearing a dollar sign -- a number that sums cleanly into a USD total and is
wrong.

The other thing pinned here: a database written against the older contract has
none of these tables, and asking it for snapshots has to say so rather than
raising an AttributeError at a user who typed a documented command.
"""

import csv
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from etc.broker_db import BrokerDatabase
from etc.broker_nav import (
    CATEGORY_HEADERS,
    HISTORY_FILTERS,
    HISTORY_READERS,
    SHOW_LIMITS,
    BrokerNavigator,
)
from etc.infrastructure import create_db_engine
from etc.records import AccountIdentity, Holding, Transaction
from keyring_isolation import MemoryKeyringMixin


class _LegacyDb:
    """A database that predates account history."""

    def get_credentials(self, filter_term: str | None = None) -> list[tuple[Any, ...]]:
        del filter_term
        return []

    def get_credential_refs(
        self, filter_term: str | None = None
    ) -> list[tuple[Any, ...]]:
        del filter_term
        return []

    def get_account_data(self) -> list[tuple[Any, ...]]:
        return []

    def add_credential(
        self,
        username: str,
        secret: str,
        cred_type: str = "plaintext",
        source: str = "manual",
    ) -> str:
        del username, secret, cred_type, source
        return ""

    def delete_credential(self, cred_id: int) -> bool:
        del cred_id
        return False

    def shutdown_db(self) -> None:
        return None


class HeaderContractTests(MemoryKeyringMixin, unittest.TestCase):
    """Headers and readers describe the same set of categories.

    The mixin is not decoration: these open a real BrokerDatabase, and opening
    one runs migrate_plaintext_secrets against whatever keyring is installed.
    It was safe here only because a fresh database has no password column for
    that migration to find.
    """

    def test_every_reader_has_headers(self) -> None:
        self.assertEqual(set(HISTORY_READERS), set(CATEGORY_HEADERS) - {"creds"})

    def test_every_declared_filter_is_one_its_reader_actually_accepts(self) -> None:
        # The bug this pins: `show accounts <id>` passed account_id= to
        # get_accounts(), which takes none. cmd.Cmd catches nothing, so the
        # TypeError killed the shell. Checking the signatures means adding a
        # reader with the wrong filter name fails here rather than in a REPL.
        import inspect

        with tempfile.TemporaryDirectory() as tmp:
            db = BrokerDatabase(
                create_db_engine(db_path=Path(tmp) / "b.db"), "schwab529plan"
            )

            for category, parameter in HISTORY_FILTERS.items():
                with self.subTest(category=category):
                    self.assertIn(category, HISTORY_READERS)
                    signature = inspect.signature(
                        getattr(db, HISTORY_READERS[category])
                    )
                    self.assertIn(
                        parameter,
                        signature.parameters,
                        f"{HISTORY_READERS[category]}() has no {parameter} parameter",
                    )

            db.shutdown_db()

    def test_a_category_without_a_filter_is_one_whose_reader_takes_none(self) -> None:
        import inspect

        with tempfile.TemporaryDirectory() as tmp:
            db = BrokerDatabase(
                create_db_engine(db_path=Path(tmp) / "b.db"), "schwab529plan"
            )

            for category in set(HISTORY_READERS) - set(HISTORY_FILTERS):
                with self.subTest(category=category):
                    signature = inspect.signature(
                        getattr(db, HISTORY_READERS[category])
                    )
                    self.assertNotIn("account_id", signature.parameters)
                    self.assertNotIn("snapshot_id", signature.parameters)

            db.shutdown_db()

    def test_headers_match_what_the_database_returns(self) -> None:
        # A header list one column short silently mislabels every column after
        # the gap, which is worse than an error.
        with tempfile.TemporaryDirectory() as tmp:
            db = BrokerDatabase(
                create_db_engine(db_path=Path(tmp) / "b.db"), "schwab529plan"
            )
            db.save_snapshot(
                account=AccountIdentity(account_key="A", display_name="A"),
                scraped_at="2026-01-01 00:00:00",
                value=1.0,
                holdings=[Holding(symbol="VTI", units=1.0)],
                transactions=[Transaction(tx_type="BUY", value=1.0)],
            )

            for category, reader in HISTORY_READERS.items():
                rows = getattr(db, reader)()

                with self.subTest(category=category):
                    self.assertTrue(rows, f"{category} fixture produced no rows")
                    self.assertEqual(
                        len(rows[0]),
                        len(CATEGORY_HEADERS[category]),
                        f"{category} headers do not match the row width",
                    )

            db.shutdown_db()


class RenderTests(unittest.TestCase):
    """Numbers are shown the way the rest of StonkSmith shows them."""

    def test_money_columns_are_formatted_as_currency(self) -> None:
        rows = [(1, "Ezekiel", "2025-12-31", "2026-01-01", 1234.56, "USD")]

        cells = BrokerNavigator.render(category="snapshots", rows=rows)

        self.assertEqual(cells[0][4], "$1,234.56")

    def test_a_non_usd_value_does_not_get_a_dollar_sign(self) -> None:
        rows = [(1, "Ezekiel", "2025-12-31", "2026-01-01", 1234.56, "CAD")]

        cells = BrokerNavigator.render(category="snapshots", rows=rows)

        self.assertEqual(cells[0][4], "1,234.56 CAD")

    def test_a_missing_value_is_blank_rather_than_the_word_none(self) -> None:
        rows = [(1, "Ezekiel", None, "2026-01-01", None, "USD")]

        cells = BrokerNavigator.render(category="snapshots", rows=rows)

        self.assertEqual(cells[0][2], "")
        self.assertEqual(cells[0][4], "")

    def test_a_negative_delta_keeps_its_sign(self) -> None:
        rows = [("Ezekiel", None, "2026-01-02", 900.0, 1000.0, -100.0, "USD")]

        cells = BrokerNavigator.render(category="deltas", rows=rows)

        self.assertEqual(cells[0][5], "-$100.00")

    def test_non_money_columns_are_left_alone(self) -> None:
        rows = [
            (
                "Ezekiel",
                "VTI",
                "Vanguard",
                3.0,
                250.0,
                750.0,
                None,
                None,
                600.0,
                "USD",
                "2026-06-30",
            )
        ]

        cells = BrokerNavigator.render(category="holdings", rows=rows)

        self.assertEqual(cells[0][1], "VTI")
        self.assertEqual(cells[0][3], "3.0", "units are a count, not money")
        self.assertEqual(cells[0][5], "$750.00")
        self.assertEqual(cells[0][10], "2026-06-30", "a date, not money")

    def test_a_holding_with_no_units_date_renders_an_empty_cell(self) -> None:
        rows = [
            (
                "Ezekiel",
                "VTI",
                "Vanguard",
                3.0,
                250.0,
                750.0,
                None,
                None,
                600.0,
                "USD",
                None,
            )
        ]

        cells = BrokerNavigator.render(category="holdings", rows=rows)

        self.assertEqual(cells[0][10], "")


class HistoryRowsTests(MemoryKeyringMixin, unittest.TestCase):
    """Reading the tables, and explaining when there are none."""

    def setUp(self) -> None:
        super().setUp()
        self._dir = tempfile.TemporaryDirectory()
        self.db = BrokerDatabase(
            create_db_engine(db_path=Path(self._dir.name) / "b.db"), "schwab529plan"
        )
        self.db.save_snapshot(
            account=AccountIdentity(account_key="Ezekiel", display_name="Ezekiel"),
            scraped_at="2026-01-01 00:00:00",
            value=1000.0,
            holdings=[Holding(fund_code="SWX", units=1.0, value=1000.0)],
        )
        self.nav = BrokerNavigator(object(), self.db, "schwab529plan")

    def tearDown(self) -> None:
        self.db.shutdown_db()
        self._dir.cleanup()
        super().tearDown()

    def test_snapshots_come_back(self) -> None:
        rows = self.nav.history_rows(category="snapshots")

        self.assertIsNotNone(rows)
        assert rows is not None
        self.assertEqual(len(rows), 1)

    def test_holdings_can_be_narrowed_to_one_snapshot(self) -> None:
        snapshot_id = self.db.get_snapshots()[0][0]

        rows = self.nav.history_rows(
            category="holdings", argument=str(object=snapshot_id)
        )

        assert rows is not None
        self.assertEqual(len(rows), 1)

    def test_a_non_numeric_argument_is_refused_rather_than_ignored(self) -> None:
        # Silently showing everything would look like the filter worked.
        self.assertIsNone(
            self.nav.history_rows(category="snapshots", argument="Ezekiel")
        )

    def test_show_accounts_with_an_id_is_refused_rather_than_crashing(self) -> None:
        # get_accounts() takes no filter. Passing one raised a TypeError out of
        # a cmd loop that catches nothing, which killed the whole shell.
        self.assertIsNone(self.nav.history_rows(category="accounts", argument="1"))

    def test_show_deltas_with_an_id_is_refused_rather_than_ignored(self) -> None:
        # The quieter half of the same bug: this used to drop the argument and
        # render every account, which reads as a filter that matched everything.
        self.assertIsNone(self.nav.history_rows(category="deltas", argument="1"))

    def test_no_category_raises_when_given_an_id(self) -> None:
        for category in HISTORY_READERS:
            with self.subTest(category=category):
                try:
                    self.nav.history_rows(category=category, argument="1")

                except Exception as e:
                    self.fail(f"show {category} 1 raised {type(e).__name__}: {e}")

    def test_the_categories_that_do_filter_still_filter(self) -> None:
        snapshot_id = self.db.get_snapshots()[0][0]

        narrowed = self.nav.history_rows(
            category="holdings", argument=str(object=snapshot_id)
        )
        assert narrowed is not None
        self.assertEqual(len(narrowed), 1)

        missing = self.nav.history_rows(category="holdings", argument="9999")
        assert missing is not None
        self.assertEqual(len(missing), 0, "an unknown id must narrow to nothing")

    def test_a_legacy_database_explains_itself(self) -> None:
        nav = BrokerNavigator(object(), _LegacyDb(), "fidelity")

        self.assertIsNone(nav.history_rows(category="snapshots"))


class ExportWritesEverythingTests(MemoryKeyringMixin, unittest.TestCase):
    """
    A file is not a screenful.

    `export` used to call the reader with no arguments and inherit whatever cap
    it carried -- a hundred snapshots, five hundred movements -- then print
    "Exported transactions" over a file missing most of them. Nothing reading
    that CSV afterwards could tell. These are the assertions that fail before
    the fix.
    """

    def setUp(self) -> None:
        super().setUp()
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.db = BrokerDatabase(
            create_db_engine(db_path=self.root / "b.db"), "schwab529plan"
        )
        self.account = AccountIdentity(account_key="Ezekiel", display_name="Ezekiel")
        self.nav = BrokerNavigator(object(), self.db, "schwab529plan")

    def tearDown(self) -> None:
        self.db.shutdown_db()
        self._dir.cleanup()
        super().tearDown()

    def _movements(self, count: int) -> None:
        """Record `count` distinct movements against the one account."""

        self.db.save_snapshot(
            account=self.account,
            scraped_at="2026-01-01 00:00:00",
            value=1.0,
            transactions=[
                Transaction(
                    processed_on=f"2026-01-{index % 28 + 1:02d}",
                    tx_type="Contribution",
                    value=float(index),
                    raw=f"${index}.00",
                )
                for index in range(count)
            ],
        )

    def _snapshots(self, count: int) -> None:
        """Record `count` marks against the one account."""

        for index in range(count):
            self.db.save_snapshot(
                account=self.account,
                scraped_at=f"2026-02-{index % 28 + 1:02d} {index % 24:02d}:00:00",
                value=float(index),
            )

    def _rows_in(self, path: Path) -> list[list[str]]:
        """The CSV back off disk, header included."""

        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.reader(handle, delimiter=";"))

    def test_every_movement_reaches_the_file(self) -> None:
        # The regression. get_transactions caps at 500 by default, so this wrote
        # 500 rows and reported success.
        self._movements(count=640)
        target: Path = self.root / "tx.csv"

        self.nav.do_export(f"transactions {target}")

        self.assertEqual(len(self._rows_in(path=target)), 641, "640 rows + header")

    def test_every_snapshot_reaches_the_file(self) -> None:
        # Same defect, a lower cap: get_snapshots stops at 100.
        self._snapshots(count=130)
        target: Path = self.root / "snaps.csv"

        self.nav.do_export(f"snapshots {target}")

        self.assertEqual(len(self._rows_in(path=target)), 131, "130 rows + header")

    def test_the_export_says_how_many_rows_it_wrote(self) -> None:
        # The count is the only thing that could ever have revealed a short
        # file, since a truncated CSV looks exactly like a complete one.
        self._movements(count=640)
        target: Path = self.root / "tx.csv"

        with patch("etc.broker_nav.stonksmith_logger") as log:
            self.nav.do_export(f"transactions {target}")

        message: str = str(object=log.success.call_args.kwargs["msg"])

        self.assertIn("640", message)
        self.assertEqual(len(self._rows_in(path=target)) - 1, 640)

    def test_a_legacy_database_does_not_reach_the_writer(self) -> None:
        # history_rows returning None must stop the export, not hand None to
        # write_csv -- the show path already refuses; this one has to as well.
        nav = BrokerNavigator(object(), _LegacyDb(), "fidelity")
        target: Path = self.root / "never.csv"

        nav.do_export(f"snapshots {target}")

        self.assertFalse(target.exists())


class ShowStatesItsCapTests(MemoryKeyringMixin, unittest.TestCase):
    """A screenful is a courtesy, but a silent one is the bug over again."""

    def setUp(self) -> None:
        super().setUp()
        self._dir = tempfile.TemporaryDirectory()
        self.db = BrokerDatabase(
            create_db_engine(db_path=Path(self._dir.name) / "b.db"), "schwab529plan"
        )
        self.account = AccountIdentity(account_key="Ezekiel", display_name="Ezekiel")
        self.nav = BrokerNavigator(object(), self.db, "schwab529plan")

    def tearDown(self) -> None:
        self.db.shutdown_db()
        self._dir.cleanup()
        super().tearDown()

    def _movements(self, count: int) -> None:
        self.db.save_snapshot(
            account=self.account,
            scraped_at="2026-01-01 00:00:00",
            value=1.0,
            transactions=[
                Transaction(
                    processed_on=f"2026-01-{index % 28 + 1:02d}",
                    tx_type="Contribution",
                    value=float(index),
                    raw=f"${index}.00",
                )
                for index in range(count)
            ],
        )

    def _shown(self, category: str) -> tuple[list[list[str]], bool]:
        """What reached the table, and whether the notice was printed."""

        with (
            patch("helpers.db.print_table") as table,
            patch("etc.broker_nav.stonksmith_logger") as log,
        ):
            self.nav.do_show(category)

        return table.call_args.kwargs["data"], log.highlight.called

    def test_past_the_cap_it_says_so_and_names_export(self) -> None:
        self._movements(count=SHOW_LIMITS["transactions"] + 1)

        with (
            patch("helpers.db.print_table"),
            patch("etc.broker_nav.stonksmith_logger") as log,
        ):
            self.nav.do_show("transactions")

        message: str = str(object=log.highlight.call_args.kwargs["msg"])

        self.assertIn(str(object=SHOW_LIMITS["transactions"]), message)
        self.assertIn("export transactions", message)

    def test_the_extra_row_it_asked_for_never_reaches_the_screen(self) -> None:
        # show asks for cap + 1 to learn whether there are more. That row is a
        # probe, not data, and printing it would make the cap a lie.
        self._movements(count=SHOW_LIMITS["transactions"] + 40)

        data, _ = self._shown(category="transactions")

        self.assertEqual(len(data) - 1, SHOW_LIMITS["transactions"], "header + cap")

    def test_exactly_at_the_cap_it_says_nothing(self) -> None:
        # There is nothing more to see, so claiming otherwise would be the same
        # failure pointing the other way.
        self._movements(count=SHOW_LIMITS["transactions"])

        data, warned = self._shown(category="transactions")

        self.assertEqual(len(data) - 1, SHOW_LIMITS["transactions"])
        self.assertFalse(warned)

    def test_under_the_cap_it_says_nothing(self) -> None:
        self._movements(count=3)

        data, warned = self._shown(category="transactions")

        self.assertEqual(len(data) - 1, 3)
        self.assertFalse(warned)

    def test_a_category_with_no_cap_is_never_truncated(self) -> None:
        # accounts is one row per account and its reader takes no limit.
        self._movements(count=3)

        _, warned = self._shown(category="accounts")

        self.assertNotIn("accounts", SHOW_LIMITS)
        self.assertFalse(warned)


if __name__ == "__main__":
    unittest.main()
