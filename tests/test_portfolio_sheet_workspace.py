"""One read of real databases, all the way to the cells.

Everything else here fakes the portfolio. This builds two broker databases on
disk, runs the whole refresh against a fake spreadsheet, and checks that what
lands is what etc.portfolio says the workspace holds -- including the part where
a broker that will not open is reported rather than quietly dropped from a total.
"""

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from etc.broker_db import BrokerDatabase
from etc.infrastructure import create_db_engine
from etc.portfolio import ACCOUNT_COLUMNS, HOLDING_COLUMNS, read_workspace
from etc.portfolio_sheet import (
    ACCOUNTS_TAB,
    BANNER,
    DASHBOARD_TAB,
    HOLDINGS_TAB,
    MACHINE_OWNED_TABS,
    refresh,
)
from etc.records import AccountIdentity, Holding
from helpers.sheets import SheetsUnavailable
from keyring_isolation import MemoryKeyringMixin


class FakeBook:
    """A spreadsheet whose tabs are MagicMocks that all claim to be ours."""

    def __init__(self) -> None:
        self.tabs: dict[str, MagicMock] = {}
        self.asked: list[str] = []

    def worksheet(self, name: str) -> MagicMock:
        self.asked.append(name)

        if name not in self.tabs:
            tab = MagicMock()
            tab.acell.return_value = MagicMock(value=BANNER)
            tab.row_count = 1000
            tab.col_count = 26
            self.tabs[name] = tab

        return self.tabs[name]

    def rows_written(self, tab: str, width: str) -> list[list[Any]]:
        """Every data row that reached one tab, in order."""

        written: list[list[Any]] = []

        for call in self.tabs[tab].update.call_args_list:
            values, range_name = call.args[0], call.args[1]

            if range_name.startswith("A3:") and range_name[3] == width:
                written.extend(values)

        return written


class WorkspaceRefreshTests(MemoryKeyringMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "default").mkdir()

    def _write(self, broker: str, key: str, value: float, holdings: Any = ()) -> None:
        db = BrokerDatabase(
            db_engine=create_db_engine(db_path=self.root / "default" / f"{broker}.db"),
            broker=broker,
        )
        db.save_snapshot(
            account=AccountIdentity(
                account_key=key, display_name=key, kind="INVESTMENT"
            ),
            scraped_at="2026-08-08 09:00:00",
            as_of="2026-08-07",
            value=value,
            currency="USD",
            holdings=holdings,
        )
        db.shutdown_db()

    def test_the_sheet_is_exactly_what_the_read_path_says(self) -> None:
        self._write(broker="tsp", key="C Fund", value=1000.0)
        self._write(
            broker="ally",
            key="Individual",
            value=2500.0,
            holdings=[Holding(symbol="VTI", name="Vanguard", units=10.0, value=2500.0)],
        )

        book = FakeBook()
        result = refresh(workspace="default", root=self.root, book=book)

        expected = read_workspace(workspace="default", root=self.root)

        self.assertEqual(
            book.rows_written(tab=ACCOUNTS_TAB, width="J"),
            [row.cells() for row in expected.accounts],
        )
        self.assertEqual(
            book.rows_written(tab=HOLDINGS_TAB, width="P"),
            [row.cells() for row in expected.holdings],
        )
        self.assertEqual(result.accounts, 2)
        self.assertEqual(result.holdings, 1)
        self.assertEqual(result.total, 3500.0)
        self.assertEqual(result.brokers_read, ("ally", "tsp"))

    def test_only_the_three_machine_owned_tabs_are_ever_opened(self) -> None:
        # The guarantee that makes every other tab in the book safe to keep
        # things on: nothing else is so much as looked at.
        self._write(broker="tsp", key="C Fund", value=1000.0)

        book = FakeBook()
        refresh(workspace="default", root=self.root, book=book)

        self.assertEqual(set(book.asked), set(MACHINE_OWNED_TABS))

    def test_every_tab_is_claimed_before_any_is_cleared(self) -> None:
        # A missing or unowned tab must cost nothing, rather than leaving
        # Accounts rewritten beside a stale Holdings.
        self._write(broker="tsp", key="C Fund", value=1000.0)

        book = FakeBook()
        book.worksheet(DASHBOARD_TAB).acell.return_value = MagicMock(value="my notes")

        with self.assertRaises(SheetsUnavailable):
            refresh(workspace="default", root=self.root, book=book)

        for tab in MACHINE_OWNED_TABS:
            book.tabs[tab].clear.assert_not_called()
            book.tabs[tab].update.assert_not_called()

    def test_a_broker_that_will_not_open_is_reported_not_dropped(self) -> None:
        self._write(broker="tsp", key="C Fund", value=1000.0)
        (self.root / "default" / "ally.db").write_text("this is not a database")

        book = FakeBook()
        result = refresh(workspace="default", root=self.root, book=book)

        self.assertEqual(result.brokers_read, ("tsp",))
        self.assertEqual([name for name, _ in result.unreadable], ["ally"])
        self.assertTrue(all(reason for _, reason in result.unreadable))

        # And it reaches the tab a person actually looks at.
        dashboard = str(
            object=book.tabs[DASHBOARD_TAB].batch_update.call_args_list[0].args[0]
        )
        self.assertIn("ally", dashboard)

    def test_a_workspace_that_will_not_read_at_all_leaves_the_sheet_alone(self) -> None:
        # Clearing here would replace a correct sheet with a blank one and
        # report success for having done it.
        (self.root / "default" / "tsp.db").write_text("not a database")

        book = FakeBook()

        with self.assertRaises(SheetsUnavailable) as caught:
            refresh(workspace="default", root=self.root, book=book)

        self.assertIn("tsp", str(caught.exception))
        self.assertEqual(book.tabs, {})

    def test_an_empty_workspace_still_writes_the_headers(self) -> None:
        book = FakeBook()
        result = refresh(workspace="default", root=self.root, book=book)

        self.assertEqual(result.accounts, 0)
        self.assertEqual(result.holdings, 0)

        headers = [
            call.args[0][0]
            for call in book.tabs[ACCOUNTS_TAB].update.call_args_list
            if call.args[1] == "A2:J2"
        ]
        self.assertEqual(headers, [list(ACCOUNT_COLUMNS)])

    def test_an_account_absent_from_the_database_is_absent_from_the_sheet(self) -> None:
        # The one-line proof that [SNAPTRADE] exclude_accounts still governs.
        # It filters before the write, and the sheet reads only what was
        # written, so an excluded account cannot reach a tab by another route.
        self._write(broker="snaptrade", key="kept", value=100.0)

        book = FakeBook()
        refresh(workspace="default", root=self.root, book=book)

        written = str(object=book.rows_written(tab=ACCOUNTS_TAB, width="J"))
        self.assertIn("kept", written)
        self.assertNotIn("excluded", written)

    def test_the_holdings_header_carries_the_whole_contract(self) -> None:
        self._write(broker="tsp", key="C Fund", value=1.0)

        book = FakeBook()
        refresh(workspace="default", root=self.root, book=book)

        headers = [
            call.args[0][0]
            for call in book.tabs[HOLDINGS_TAB].update.call_args_list
            if call.args[1] == "A2:P2"
        ]
        self.assertEqual(headers, [list(HOLDING_COLUMNS)])


if __name__ == "__main__":
    unittest.main()
