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

import stonksmith.etc.broker_nav as broker_nav
from keyring_isolation import MemoryKeyringMixin
from stonksmith.etc.broker_db import BrokerDatabase, natural_keys
from stonksmith.etc.broker_nav import (
    CATEGORY_HEADERS,
    CURRENCY_HEADER,
    HISTORY_FILTERS,
    HISTORY_READERS,
    MONEY_HEADERS,
    SHOW_COLUMNS,
    SHOW_LIMITS,
    BrokerNavigator,
)
from stonksmith.etc.infrastructure import create_db_engine
from stonksmith.etc.records import AccountIdentity, Holding, Transaction


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

    def test_every_money_column_is_one_the_contract_has(self) -> None:
        # What the integers could not give. MONEY_COLUMNS held positions, so a
        # column inserted mid-tuple moved the money without moving the numbers,
        # and formatting a bare float as currency looks entirely correct.
        for category, names in MONEY_HEADERS.items():
            with self.subTest(category=category):
                for name in names:
                    self.assertIn(name, CATEGORY_HEADERS[category])

    def test_every_currency_column_is_one_the_contract_has(self) -> None:
        for category, name in CURRENCY_HEADER.items():
            with self.subTest(category=category):
                self.assertIn(name, CATEGORY_HEADERS[category])

    def test_the_screen_only_asks_for_columns_the_export_has(self) -> None:
        # SHOW_COLUMNS is a subset selected from CATEGORY_HEADERS, not a second
        # list written out beside it -- which is what keeps show and export from
        # disagreeing about what a column means or where it sits.
        for category, names in SHOW_COLUMNS.items():
            with self.subTest(category=category):
                self.assertIn(category, CATEGORY_HEADERS)
                for name in names:
                    self.assertIn(name, CATEGORY_HEADERS[category])

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
        rows = [(1, "Beneficiary A", "2025-12-31", "2026-01-01", 1234.56, "USD")]

        cells = BrokerNavigator.render(category="snapshots", rows=rows)

        self.assertEqual(cells[0][4], "$1,234.56")

    def test_a_non_usd_value_does_not_get_a_dollar_sign(self) -> None:
        rows = [(1, "Beneficiary A", "2025-12-31", "2026-01-01", 1234.56, "CAD")]

        cells = BrokerNavigator.render(category="snapshots", rows=rows)

        self.assertEqual(cells[0][4], "1,234.56 CAD")

    def test_a_missing_value_is_blank_rather_than_the_word_none(self) -> None:
        rows = [(1, "Beneficiary A", None, "2026-01-01", None, "USD")]

        cells = BrokerNavigator.render(category="snapshots", rows=rows)

        self.assertEqual(cells[0][2], "")
        self.assertEqual(cells[0][4], "")

    def test_a_negative_delta_keeps_its_sign(self) -> None:
        rows = [("Beneficiary A", None, "2026-01-02", 900.0, 1000.0, -100.0, "USD")]

        cells = BrokerNavigator.render(category="deltas", rows=rows)

        self.assertEqual(cells[0][5], "-$100.00")

    def test_non_money_columns_are_left_alone(self) -> None:
        rows = [
            (
                "Beneficiary A",
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
                "Beneficiary A",
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
            account=AccountIdentity(
                account_key="Beneficiary A", display_name="Beneficiary A"
            ),
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
            self.nav.history_rows(category="snapshots", argument="Beneficiary A")
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

    def test_an_id_of_zero_narrows_like_any_other_unknown_id(self) -> None:
        # This method gates on `if not argument`, which "0" passes, while the
        # readers gated on `if account_id`, which 0 does not. The two disagreed
        # on exactly one value, and 'show snapshots 0' rendered every account.
        self.db.save_snapshot(
            account=AccountIdentity(account_key="Other", display_name="Other"),
            scraped_at="2026-01-02 00:00:00",
            value=5.0,
        )

        everything = self.nav.history_rows(category="snapshots")
        assert everything is not None
        self.assertEqual(len(everything), 2)

        narrowed = self.nav.history_rows(category="snapshots", argument="0")
        assert narrowed is not None
        self.assertEqual(len(narrowed), 0, "no account has id 0, so nothing matches")

    def test_a_legacy_database_explains_itself(self) -> None:
        nav = BrokerNavigator(object(), _LegacyDb(), "fidelity")

        self.assertIsNone(nav.history_rows(category="snapshots"))


class MoneyStillLandsOnMoneyTests(unittest.TestCase):
    """
    The assertion that fails if the positional tables come back.

    `Description` went in after `Symbol`, which moved Units, Price, Value and
    Currency one place right. Under the old MONEY_COLUMNS of (7, 8) that put
    Units and Price in the money columns and read the currency off Value.
    """

    def _row(self, currency: str = "USD") -> list[str]:
        """One rendered transactions row, in export-contract order."""

        return BrokerNavigator.render(
            category="transactions",
            rows=[
                (
                    1,
                    "Brokerage",
                    "2026-08-01",
                    "2026-07-31",
                    "BUY",
                    "VTI",
                    "Bought 3 VTI",
                    3.0,
                    250.0,
                    750.0,
                    currency,
                    "2026-08-09 09:00:00",
                    "sn-1",
                    "id:sn-1",
                    "$750.00",
                )
            ],
        )[0]

    def _at(self, cells: list[str], name: str) -> str:
        return cells[CATEGORY_HEADERS["transactions"].index(name)]

    def test_price_and_value_are_money(self) -> None:
        cells = self._row()

        self.assertEqual(self._at(cells=cells, name="Price"), "$250.00")
        self.assertEqual(self._at(cells=cells, name="Value"), "$750.00")

    def test_units_are_not_money(self) -> None:
        # The one that catches the shift: Units sits where Price used to.
        self.assertEqual(self._at(cells=self._row(), name="Units"), "3.0")

    def test_the_new_columns_are_left_alone(self) -> None:
        cells = self._row()

        self.assertEqual(self._at(cells=cells, name="Description"), "Bought 3 VTI")
        self.assertEqual(self._at(cells=cells, name="External Id"), "sn-1")

    def test_the_diagnostic_columns_are_left_alone(self) -> None:
        # Both went on the end, which is where a positional table would notice
        # nothing -- so the pin is that neither is *formatted*. Raw Value here
        # is the source's own "$750.00": already money-shaped, and rendering it
        # as money again is precisely what would destroy the one thing it is
        # kept for, which is being byte-for-byte what the source wrote.
        cells = self._row()

        self.assertEqual(self._at(cells=cells, name="Natural Key"), "id:sn-1")
        self.assertEqual(self._at(cells=cells, name="Raw Value"), "$750.00")

    def test_a_cad_movement_keeps_the_dollar_sign_off(self) -> None:
        # Proves the currency column is still found after the insertion. Read
        # one place left, it would have picked up "750.0" and formatted as USD.
        self.assertEqual(
            self._at(cells=self._row(currency="CAD"), name="Value"), "750.00 CAD"
        )

    def test_an_unknown_header_is_refused_rather_than_skipped(self) -> None:
        # A name the contract does not have is a typo. Formatting nothing is
        # indistinguishable from formatting correctly, so it has to raise.
        with (
            patch.dict(
                broker_nav.MONEY_HEADERS,
                {"transactions": ("Nonexistent",)},
                clear=False,
            ),
            self.assertRaises(KeyError),
        ):
            self._row()


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
        self.account = AccountIdentity(
            account_key="Beneficiary A", display_name="Beneficiary A"
        )
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

        with patch("stonksmith.etc.broker_nav.stonksmith_logger") as log:
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

    def test_the_columns_the_tab_shows_reach_the_csv(self) -> None:
        # The asymmetry this closes. The Transactions tab has Description,
        # First Seen and External Id; the shell could not reach any of them,
        # which made "Sheets is a view of what stonksmithdb reports" untrue.
        self.db.save_snapshot(
            account=self.account,
            scraped_at="2026-01-01 00:00:00",
            value=1.0,
            transactions=[
                Transaction(
                    processed_on="2026-08-01",
                    tx_type="BUY",
                    symbol="VTI",
                    description="Bought 3 VTI @ 250.00",
                    value=-750.0,
                    external_id="sn-8842",
                )
            ],
        )
        target: Path = self.root / "tx.csv"

        self.nav.do_export(f"transactions {target}")
        header, row = self._rows_in(path=target)

        for name in ("Description", "First Seen", "External Id"):
            self.assertIn(name, header)

        self.assertEqual(row[header.index("Description")], "Bought 3 VTI @ 250.00")
        self.assertEqual(row[header.index("External Id")], "sn-8842")
        self.assertTrue(row[header.index("First Seen")])

    def test_a_derived_key_reaches_the_csv_beside_the_text_it_was_built_from(
        self,
    ) -> None:
        # The asymmetry this one opens, in the other direction. The tab has
        # neither of these and still should not; the point is that a key kept
        # legible rather than hashed is now legible *somewhere*, which is the
        # entire justification for keeping it that way.
        #
        # No external_id, so the row takes the deriving branch and the key is
        # the pipe-joined body rather than "id:...".
        movement = Transaction(
            processed_on="12/30/2025",
            traded_on="12/30/2025",
            tx_type="Contribution",
            value=50.0,
            raw="$50.00",
        )
        self.db.save_snapshot(
            account=self.account,
            scraped_at="2026-01-01 00:00:00",
            value=1.0,
            transactions=[movement],
        )
        target: Path = self.root / "tx.csv"

        self.nav.do_export(f"transactions {target}")
        header, row = self._rows_in(path=target)

        # Pinned against the function rather than a literal: the two cannot
        # drift apart, and a change to how keys are built shows up here as the
        # export changing rather than as a test needing a new string typed in.
        self.assertEqual(
            row[header.index("Natural Key")], natural_keys(rows=[movement])[0]
        )
        # The source's own text, not the parsed number beside it. "50.0" here
        # would mean the column had been sourced from `value`, which is the one
        # thing it exists not to be.
        self.assertEqual(row[header.index("Raw Value")], "$50.00")
        self.assertIn("#0", row[header.index("Natural Key")])

    def test_a_source_supplied_id_reaches_the_csv_as_the_key_it_becomes(self) -> None:
        # The other branch, and the one a 529-only fixture would never show.
        # A SnapTrade row derives nothing, so the column reads "id:<theirs>" --
        # which is what tells you at a glance that a mismatch there is the
        # source's doing rather than a format change on our side.
        self.db.save_snapshot(
            account=self.account,
            scraped_at="2026-01-01 00:00:00",
            value=1.0,
            transactions=[
                Transaction(
                    processed_on="2026-08-01",
                    tx_type="BUY",
                    symbol="VTI",
                    value=-750.0,
                    external_id="sn-8842",
                )
            ],
        )
        target: Path = self.root / "tx.csv"

        self.nav.do_export(f"transactions {target}")
        header, row = self._rows_in(path=target)

        self.assertEqual(row[header.index("Natural Key")], "id:sn-8842")
        # raw is nullable and SnapTrade never sets it. An empty cell is the
        # honest rendering of that; "None" is a four-letter value that sorts
        # and filters like data.
        self.assertEqual(row[header.index("Raw Value")], "")

    def test_the_csv_keeps_numbers_rather_than_currency_text(self) -> None:
        # export writes raw rows and never calls render(), which is what lets
        # the Value column sum in a spreadsheet.
        self.db.save_snapshot(
            account=self.account,
            scraped_at="2026-01-01 00:00:00",
            value=1.0,
            transactions=[
                Transaction(processed_on="2026-08-01", tx_type="BUY", value=-750.0)
            ],
        )
        target: Path = self.root / "tx.csv"

        self.nav.do_export(f"transactions {target}")
        header, row = self._rows_in(path=target)

        self.assertEqual(float(row[header.index("Value")]), -750.0)
        self.assertNotIn("$", row[header.index("Value")])


class ShowStatesItsCapTests(MemoryKeyringMixin, unittest.TestCase):
    """A screenful is a courtesy, but a silent one is the bug over again."""

    def setUp(self) -> None:
        super().setUp()
        self._dir = tempfile.TemporaryDirectory()
        self.db = BrokerDatabase(
            create_db_engine(db_path=Path(self._dir.name) / "b.db"), "schwab529plan"
        )
        self.account = AccountIdentity(
            account_key="Beneficiary A", display_name="Beneficiary A"
        )
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

    def _shown(self, category: str) -> tuple[list[list[str]], list[str]]:
        """
        What reached the table, and the row-cap notices that went with it.

        The second half was a bool until `show` gained a second thing it can
        say. Returning the matching messages rather than "highlight was called"
        is what stops the column notice from standing in for this one.
        :param category: The category to show
        :return: The table rows, and any notice saying rows were left off
        :rtype: tuple[list[list[str]], list[str]]
        """

        with (
            patch("stonksmith.helpers.db.print_table") as table,
            patch("stonksmith.etc.broker_nav.stonksmith_logger") as log,
        ):
            self.nav.do_show(category)

        notices = [
            str(object=call.kwargs["msg"]) for call in log.highlight.call_args_list
        ]

        # `show` has two things it may say, and they are different findings: it
        # stopped early, and it left a column out. Matched on wording rather
        # than on "highlight was called", so one cannot stand in for the other.
        return table.call_args.kwargs["data"], [
            notice for notice in notices if "there are more" in notice
        ]

    def test_past_the_cap_it_says_so_and_names_export(self) -> None:
        self._movements(count=SHOW_LIMITS["transactions"] + 1)

        _, capped = self._shown(category="transactions")

        self.assertEqual(len(capped), 1)
        self.assertIn(str(object=SHOW_LIMITS["transactions"]), capped[0])
        self.assertIn("export transactions", capped[0])

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

        data, capped = self._shown(category="transactions")

        self.assertEqual(len(data) - 1, SHOW_LIMITS["transactions"])
        self.assertEqual(capped, [])

    def test_under_the_cap_it_says_nothing(self) -> None:
        self._movements(count=3)

        data, capped = self._shown(category="transactions")

        self.assertEqual(len(data) - 1, 3)
        self.assertEqual(capped, [])

    def test_the_wide_columns_are_left_off_and_named(self) -> None:
        # Not shown, and not silently: a column missing without mention is the
        # same fault as a row count that stops without mention.
        #
        # Every one of them named, rather than any one of them: a regression
        # that quietly stopped dropping a column, or dropped one without saying
        # so, reads as a passing test if the assertion only looks for the first.
        self._movements(count=1)

        with (
            patch("stonksmith.helpers.db.print_table") as table,
            patch("stonksmith.etc.broker_nav.stonksmith_logger") as log,
        ):
            self.nav.do_show("transactions")

        header: list[str] = table.call_args.kwargs["data"][0]
        notices: str = "\n".join(
            str(object=call.kwargs["msg"]) for call in log.highlight.call_args_list
        )

        for name in ("Description", "Natural Key", "Raw Value"):
            self.assertNotIn(name, header)
            self.assertIn(name, notices)

        # Plural, because there are three of them now. "is too wide" over a
        # list of three is the kind of wrong that says the message was written
        # for one column and never re-read.
        self.assertIn("are too wide", notices)
        self.assertIn("export transactions", notices)
        self.assertIn("includes them", notices)

    def test_the_bounded_new_columns_are_still_shown(self) -> None:
        # Width is the only reason anything is dropped. A timestamp and an id
        # fit, and twelve columns is the width holdings has always run at --
        # what does not fit is free text, a whole row's text pipe-joined, and
        # whatever a source happened to print.
        self._movements(count=1)

        with (
            patch("stonksmith.helpers.db.print_table") as table,
            patch("stonksmith.etc.broker_nav.stonksmith_logger"),
        ):
            self.nav.do_show("transactions")

        header: list[str] = table.call_args.kwargs["data"][0]

        self.assertIn("First Seen", header)
        self.assertIn("External Id", header)
        self.assertEqual(len(header), 12)

    def test_a_category_that_hides_nothing_says_nothing(self) -> None:
        self._movements(count=1)

        with (
            patch("stonksmith.helpers.db.print_table"),
            patch("stonksmith.etc.broker_nav.stonksmith_logger") as log,
        ):
            self.nav.do_show("snapshots")

        notices: str = "\n".join(
            str(object=call.kwargs["msg"]) for call in log.highlight.call_args_list
        )

        self.assertNotIn("too wide", notices)

    def test_a_category_with_no_cap_is_never_truncated(self) -> None:
        # accounts is one row per account and its reader takes no limit.
        self._movements(count=3)

        _, capped = self._shown(category="accounts")

        self.assertNotIn("accounts", SHOW_LIMITS)
        self.assertEqual(capped, [])


if __name__ == "__main__":
    unittest.main()
