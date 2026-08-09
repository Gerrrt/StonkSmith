# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""The canonical row shape, and the read path that produces it.

The column tuples are pinned literally. That looks like testing a constant
against itself, and it is not: these columns are addressed by *position* by
every worksheet formula written against them, so a column inserted in the
middle -- the natural way to add one -- silently repoints every formula at its
neighbour. Nothing else in the system notices. This test is the only thing that
turns "append-only" from a comment into a rule.

The rest is about the two things a view over several databases gets wrong
quietly: dropping rows, and inventing numbers. An account with no positions must
still appear, a broker whose file will not open must be reported rather than
skipped, and a value the source never gave must stay empty rather than become
zero.
"""

import tempfile
import unittest
from pathlib import Path
from typing import Any

from etc.broker_db import BrokerDatabase
from etc.context import PortfolioDbProtocol
from etc.infrastructure import create_db_engine
from etc.portfolio import (
    ACCOUNT_COLUMNS,
    HOLDING_COLUMNS,
    TRANSACTION_COLUMNS,
    AccountRow,
    HoldingRow,
    Portfolio,
    TransactionRow,
    _reason,
    read_broker,
    read_databases,
    read_workspace,
)
from etc.records import AccountIdentity, Holding, Transaction
from keyring_isolation import MemoryKeyringMixin

#: A scraped 529: a fund code, contributions and growth, no ticker.
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


class _FakeDb:
    """A database that answers the portfolio protocol from literals."""

    def __init__(
        self,
        accounts: list[tuple[Any, ...]] | None = None,
        holdings: list[tuple[Any, ...]] | None = None,
        transactions: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self._accounts = accounts or []
        self._holdings = holdings or []
        self._transactions = transactions or []

    def get_current_accounts(self) -> list[tuple[Any, ...]]:
        return self._accounts

    def get_current_holdings(self) -> list[tuple[Any, ...]]:
        return self._holdings

    def get_current_transactions(self) -> list[tuple[Any, ...]]:
        return self._transactions


def account_tuple(**overrides: Any) -> tuple[Any, ...]:
    """One row in get_current_accounts() order."""

    row: dict[str, Any] = {
        "account_key": "Ezekiel",
        "source": "",
        "display_name": "Ezekiel 529",
        "beneficiary": "Ezekiel A",
        "kind": "529",
        "value": 1234.56,
        "currency": "USD",
        "as_of": "2025-12-31",
        "scraped_at": "2026-01-01 00:00:00",
    }
    row.update(overrides)
    return tuple(row.values())


def holding_tuple(**overrides: Any) -> tuple[Any, ...]:
    """One row in get_current_holdings() order."""

    row: dict[str, Any] = {
        "account_key": "Ezekiel",
        "position": 0,
        "symbol": None,
        "fund_code": "SWX",
        "name": "Index 2030",
        "units": 10.5,
        "price": 117.58,
        "value": 1234.56,
        "principal": 1000.0,
        "earnings": 234.56,
        "cost_basis": None,
        "currency": "USD",
        "as_of": "2025-12-31",
        "scraped_at": "2026-01-01 00:00:00",
        "units_as_of": None,
    }
    row.update(overrides)
    return tuple(row.values())


def transaction_tuple(**overrides: Any) -> tuple[Any, ...]:
    """One row in get_current_transactions() order."""

    row: dict[str, Any] = {
        "account_key": "Ezekiel",
        "tx_type": "Contribution",
        "symbol": None,
        "description": None,
        "units": 1.5,
        "price": 100.0,
        "value": 150.0,
        "currency": "USD",
        # As the 529 scraper stores it: the source's own text, not ISO.
        "processed_on": "12/30/2025",
        "traded_on": "12/29/2025",
        "first_seen": "2026-01-01 00:00:00",
        "external_id": None,
    }
    row.update(overrides)
    return tuple(row.values())


class ColumnContractTests(unittest.TestCase):
    """The columns themselves. Append-only means append-only."""

    def test_account_columns_are_exactly_these_in_this_order(self) -> None:
        self.assertEqual(
            ACCOUNT_COLUMNS,
            (
                "Broker",
                "Source",
                "Account",
                "Account Key",
                "Kind",
                "Beneficiary",
                "Value",
                "Currency",
                "As Of",
                "Scraped At",
            ),
            "columns are append-only: add to the end, never in the middle",
        )

    def test_holding_columns_are_exactly_these_in_this_order(self) -> None:
        self.assertEqual(
            HOLDING_COLUMNS,
            (
                "Broker",
                "Source",
                "Account",
                "Account Key",
                "Symbol",
                "Name",
                "Units",
                "Price",
                "Value",
                "Cost Basis",
                "Principal",
                "Earnings",
                "Currency",
                "As Of",
                "Scraped At",
                "Units As Of",
            ),
            "columns are append-only: add to the end, never in the middle",
        )

    def test_transaction_columns_are_exactly_these_in_this_order(self) -> None:
        self.assertEqual(
            TRANSACTION_COLUMNS,
            (
                "Broker",
                "Source",
                "Account",
                "Account Key",
                "Type",
                "Symbol",
                "Description",
                "Units",
                "Price",
                "Value",
                "Currency",
                "Processed On",
                "Traded On",
                "First Seen",
                "External Id",
            ),
            "columns are append-only: add to the end, never in the middle",
        )

    def test_every_view_shares_the_identity_prefix(self) -> None:
        # What lets a formula join them. If these ever diverge, holdings and
        # movements can no longer be attributed to the account they belong to.
        self.assertEqual(ACCOUNT_COLUMNS[:4], HOLDING_COLUMNS[:4])
        self.assertEqual(ACCOUNT_COLUMNS[:4], TRANSACTION_COLUMNS[:4])

    def test_one_name_per_meaning(self) -> None:
        # The whole point of the exercise: "Balance" and "Value" named the same
        # thing in different tabs, and three columns dated the same fact.
        for columns in (ACCOUNT_COLUMNS, HOLDING_COLUMNS, TRANSACTION_COLUMNS):
            self.assertIn("Value", columns)
            self.assertNotIn("Balance", columns)
            self.assertNotIn("Synced", columns)
            self.assertNotIn("Price date", columns)

        # "As Of" means one thing -- the date the source says the *value* is
        # for -- and only the two views that have such a date carry it.
        for columns in (ACCOUNT_COLUMNS, HOLDING_COLUMNS):
            self.assertIn("As Of", columns)

    def test_a_movement_dates_itself_twice_and_calls_neither_one_as_of(
        self,
    ) -> None:
        # The same argument "Units As Of" won, one view along. A movement has a
        # settlement date and a trade date, routinely days apart, and neither is
        # "the date the source says the value is for". Borrowing "As Of" for one
        # of them would be the third answer to one question that this contract
        # exists to stop, so both are named for what they are.
        self.assertIn("Processed On", TRANSACTION_COLUMNS)
        self.assertIn("Traded On", TRANSACTION_COLUMNS)
        self.assertNotIn("As Of", TRANSACTION_COLUMNS)
        self.assertNotIn("Date", TRANSACTION_COLUMNS)
        self.assertNotIn("Settled", TRANSACTION_COLUMNS)

    def test_first_seen_is_not_scraped_at_wearing_a_different_hat(self) -> None:
        # "Scraped At" moves every sync on the other two views: it is when the
        # run that observed *this row* happened, and those rows are rewritten
        # each run. A movement is written once and deduped on its natural key
        # ever after, so the run that saw it never changes. Same shape of
        # distinction as the units date, so the same answer: its own name.
        self.assertIn("First Seen", TRANSACTION_COLUMNS)
        self.assertNotIn("Scraped At", TRANSACTION_COLUMNS)

        for columns in (ACCOUNT_COLUMNS, HOLDING_COLUMNS):
            self.assertIn("Scraped At", columns)
            self.assertNotIn("First Seen", columns)

    def test_the_units_date_is_a_second_meaning_not_a_second_spelling(self) -> None:
        # "Units As Of" is one of the three names the contract was written to
        # abolish, so its return needs an argument rather than a casing trick.
        #
        # "Synced" and "Price date" were other brokers' names for the fact "As
        # Of" already carries -- when is this number from. They stay gone. The
        # units date is not that fact. A TSP position's value is as of the price
        # date and its quantity is as of the last statement, weeks apart, and a
        # mark carrying one of them cannot say which. Two meanings, so two
        # names, which is what the rule says rather than an exception to it.
        self.assertIn("As Of", HOLDING_COLUMNS)
        self.assertIn("Units As Of", HOLDING_COLUMNS)

        # It qualifies "Units", and sits at the end where an appended column
        # belongs -- not beside "As Of", which would read as an alternative to
        # it rather than a companion.
        self.assertIn("Units", HOLDING_COLUMNS)
        self.assertEqual(HOLDING_COLUMNS[-1], "Units As Of")

        # And it is a holdings-only fact. An account has one date.
        self.assertNotIn("Units As Of", ACCOUNT_COLUMNS)

    def test_a_row_produces_exactly_one_cell_per_column(self) -> None:
        identity: dict[str, str] = {
            "broker": "tsp",
            "source": "tsp",
            "account": "TSP C",
            "account_key": "TSP C",
        }

        self.assertEqual(len(AccountRow(**identity).cells()), len(ACCOUNT_COLUMNS))
        self.assertEqual(len(HoldingRow(**identity).cells()), len(HOLDING_COLUMNS))
        self.assertEqual(
            len(TransactionRow(**identity).cells()), len(TRANSACTION_COLUMNS)
        )


class CellTypeTests(unittest.TestCase):
    """Numbers stay numbers, and absent stays absent."""

    def test_money_and_quantities_are_numbers_not_formatted_text(self) -> None:
        # Every saver so far wrote format_amount() output, so the cell held
        # "$1,234.56" and no formula could add it up.
        cells = AccountRow(
            broker="snaptrade",
            source="Schwab",
            account="Brokerage",
            account_key="Schwab - Brokerage",
            value=1234.56,
        ).cells()

        self.assertEqual(cells[ACCOUNT_COLUMNS.index("Value")], 1234.56)
        self.assertNotIsInstance(cells[ACCOUNT_COLUMNS.index("Value")], str)

    def test_a_missing_value_is_empty_rather_than_zero(self) -> None:
        # An account that reported no number is not an account worth nothing.
        cells = AccountRow(
            broker="fidelity", source="fidelity", account="Roth", account_key="Roth"
        ).cells()

        self.assertEqual(cells[ACCOUNT_COLUMNS.index("Value")], "")

    def test_absent_holding_fields_are_empty_rather_than_none_text(self) -> None:
        cells = HoldingRow(
            broker="snaptrade",
            source="Schwab",
            account="Brokerage",
            account_key="Schwab - Brokerage",
            symbol="VTI",
            units=3.0,
        ).cells()

        self.assertEqual(cells[HOLDING_COLUMNS.index("Principal")], "")
        self.assertEqual(cells[HOLDING_COLUMNS.index("Units")], 3.0)


class TotalTests(unittest.TestCase):
    """What the accounts add up to, including when there are none."""

    def test_an_empty_portfolio_totals_to_a_float(self) -> None:
        # sum() starts at int 0, so an empty total came back a different type
        # from every non-empty one -- fine until the one caller that checks.
        total = Portfolio().total()

        self.assertEqual(total, 0.0)
        self.assertIsInstance(total, float)

    def test_only_the_asked_for_currency_counts(self) -> None:
        # Adding a dollar to a euro is not wrong so much as meaningless, and
        # nothing here knows a rate.
        portfolio = Portfolio(
            accounts=(
                AccountRow(
                    broker="a", source="a", account="a", account_key="a", value=10.0
                ),
                AccountRow(
                    broker="b",
                    source="b",
                    account="b",
                    account_key="b",
                    value=99.0,
                    currency="EUR",
                ),
            )
        )

        self.assertEqual(portfolio.total(), 10.0)
        self.assertEqual(portfolio.total(currency="EUR"), 99.0)

    def test_an_account_with_no_value_does_not_break_the_total(self) -> None:
        portfolio = Portfolio(
            accounts=(
                AccountRow(
                    broker="a", source="a", account="a", account_key="a", value=10.0
                ),
                AccountRow(broker="b", source="b", account="b", account_key="b"),
            )
        )

        self.assertEqual(portfolio.total(), 10.0)


class FailureReasonTests(unittest.TestCase):
    """A reported failure has to actually report something."""

    def test_an_argumentless_exception_still_names_itself(self) -> None:
        # OSError() and sqlite3.DatabaseError() both stringify to "", so str(e)
        # alone yields a blank reason: a report that a broker could not be read
        # which says nothing about why, and blank is the silence this breaks.
        self.assertEqual(_reason(OSError()), "OSError")

    def test_a_message_is_kept_alongside_the_class(self) -> None:
        self.assertEqual(
            _reason(ValueError("file is not a database")),
            "ValueError: file is not a database",
        )


class ReadBrokerTests(unittest.TestCase):
    """Projecting one open database, with the mapping decisions in it."""

    def test_the_fake_satisfies_the_protocol_the_reader_asks_for(self) -> None:
        self.assertIsInstance(_FakeDb(), PortfolioDbProtocol)

    def test_an_account_with_no_positions_still_appears(self) -> None:
        # A brokerage that pre-aggregates -- a Schwab-held 529 through SnapTrade
        # -- gives a balance and nothing to break it down with. That is a fact
        # about the account, not a failed scrape, and dropping it would lose the
        # money from the total entirely.
        accounts, holdings, _ = read_broker(
            broker="snaptrade", db=_FakeDb(accounts=[account_tuple()])
        )

        self.assertEqual(len(accounts), 1)
        self.assertEqual(holdings, [])
        self.assertEqual(accounts[0].value, 1234.56)

    def test_a_direct_scraper_sources_itself(self) -> None:
        # Only an aggregator fills accounts.source. The column must still be
        # groupable, so it falls back to the broker rather than staying blank.
        accounts, _, _ = read_broker(
            broker="tsp", db=_FakeDb(accounts=[account_tuple(source="")])
        )

        self.assertEqual(accounts[0].source, "tsp")

    def test_an_aggregator_keeps_the_brokerage_it_read_from(self) -> None:
        accounts, _, _ = read_broker(
            broker="snaptrade", db=_FakeDb(accounts=[account_tuple(source="Schwab")])
        )

        self.assertEqual(accounts[0].source, "Schwab")
        self.assertEqual(accounts[0].broker, "snaptrade")

    def test_a_fund_code_lands_in_the_symbol_column(self) -> None:
        # A source that does not trade in tickers still has something to
        # identify a position by, and the view has one column for it.
        _, holdings, _ = read_broker(
            broker="schwab529plan",
            db=_FakeDb(accounts=[account_tuple()], holdings=[holding_tuple()]),
        )

        self.assertEqual(holdings[0].symbol, "SWX")
        self.assertEqual(holdings[0].principal, 1000.0)
        self.assertIsNone(holdings[0].cost_basis)

    def test_a_ticker_wins_over_an_absent_fund_code(self) -> None:
        _, holdings, _ = read_broker(
            broker="snaptrade",
            db=_FakeDb(
                accounts=[account_tuple()],
                holdings=[
                    holding_tuple(
                        symbol="VTI",
                        fund_code=None,
                        cost_basis=600.0,
                        principal=None,
                        earnings=None,
                    )
                ],
            ),
        )

        self.assertEqual(holdings[0].symbol, "VTI")
        self.assertEqual(holdings[0].cost_basis, 600.0)
        self.assertIsNone(holdings[0].principal)

    def test_a_holding_inherits_its_account_identity(self) -> None:
        _, holdings, _ = read_broker(
            broker="schwab529plan",
            db=_FakeDb(
                accounts=[account_tuple(display_name="Ezekiel 529")],
                holdings=[holding_tuple()],
            ),
        )

        self.assertEqual(holdings[0].account, "Ezekiel 529")
        self.assertEqual(holdings[0].account_key, "Ezekiel")

    def test_a_units_date_reaches_the_row_and_its_own_cell(self) -> None:
        db = _FakeDb(
            accounts=[account_tuple()],
            holdings=[holding_tuple(units_as_of="2026-06-30")],
        )

        _accounts, holdings, _ = read_broker(broker="tsp", db=db)

        self.assertEqual(holdings[0].units_as_of, "2026-06-30")
        self.assertEqual(
            holdings[0].cells()[HOLDING_COLUMNS.index("Units As Of")], "2026-06-30"
        )

    def test_the_units_date_does_not_displace_the_value_date(self) -> None:
        # Both dates, in one row, meaning different things. Collapsing them is
        # the thing this column was added to stop.
        db = _FakeDb(
            accounts=[account_tuple()],
            holdings=[holding_tuple(as_of="2026-08-07", units_as_of="2026-06-30")],
        )

        _accounts, holdings, _ = read_broker(broker="tsp", db=db)

        self.assertEqual(holdings[0].as_of, "2026-08-07")
        self.assertEqual(holdings[0].units_as_of, "2026-06-30")

    def test_a_holding_with_no_units_date_leaves_the_cell_empty(self) -> None:
        db = _FakeDb(
            accounts=[account_tuple()], holdings=[holding_tuple(units_as_of=None)]
        )

        _accounts, holdings, _ = read_broker(broker="tsp", db=db)

        self.assertEqual(holdings[0].cells()[HOLDING_COLUMNS.index("Units As Of")], "")

    def test_a_position_whose_account_is_missing_is_carried_not_dropped(self) -> None:
        # The real query cannot produce this; a losing-money-silently bug is
        # worse than a row whose name is a key.
        _, holdings, _ = read_broker(
            broker="ally", db=_FakeDb(holdings=[holding_tuple(account_key="orphan")])
        )

        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0].account, "orphan")


class ReadTransactionsTests(unittest.TestCase):
    """The third row shape, mapped out of the third reader."""

    def _one(self, **overrides: Any) -> TransactionRow:
        """One movement against the standard account."""

        _, _, transactions = read_broker(
            broker="schwab529plan",
            db=_FakeDb(
                accounts=[account_tuple()],
                transactions=[transaction_tuple(**overrides)],
            ),
        )
        return transactions[0]

    def test_a_movement_inherits_its_account_identity(self) -> None:
        row = self._one()

        self.assertEqual(row.broker, "schwab529plan")
        self.assertEqual(row.account, "Ezekiel 529")
        self.assertEqual(row.account_key, "Ezekiel")
        # A direct scraper is its own source, exactly as for the other two.
        self.assertEqual(row.source, "schwab529plan")

    def test_a_movement_whose_account_is_missing_is_carried_not_dropped(self) -> None:
        _, _, transactions = read_broker(
            broker="snaptrade",
            db=_FakeDb(transactions=[transaction_tuple(account_key="orphan")]),
        )

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].account, "orphan")

    def test_the_two_dates_land_in_their_own_columns(self) -> None:
        cells = self._one().cells()

        self.assertEqual(cells[TRANSACTION_COLUMNS.index("Processed On")], "2025-12-30")
        self.assertEqual(cells[TRANSACTION_COLUMNS.index("Traded On")], "2025-12-29")

    def test_a_source_written_date_is_normalized_on_the_way_out(self) -> None:
        # The 529 scraper stores "12/30/2025" because its natural key is built
        # from that text. Two formats in one column sort wrong -- "12/30/2025"
        # above "01/15/2026" -- so the view normalizes rather than the producer,
        # which would make every already-stored row look new.
        self.assertEqual(
            self._one(processed_on="12/30/2025").processed_on, "2025-12-30"
        )
        self.assertEqual(
            self._one(processed_on="2026-08-01").processed_on, "2026-08-01"
        )

    def test_an_unreadable_date_is_kept_rather_than_blanked(self) -> None:
        # A date nothing can parse is still evidence. Emptying the cell would
        # hide the one row worth looking at.
        self.assertEqual(self._one(processed_on="whenever").processed_on, "whenever")

    def test_the_newest_movement_comes_first(self) -> None:
        _, _, transactions = read_broker(
            broker="schwab529plan",
            db=_FakeDb(
                accounts=[account_tuple()],
                transactions=[
                    transaction_tuple(processed_on="12/30/2025"),
                    transaction_tuple(processed_on="01/15/2026"),
                ],
            ),
        )

        # Lexicographically "12/30/2025" beats "01/15/2026", which is exactly
        # the trap: ordering has to happen after the dates are comparable.
        self.assertEqual(
            [row.processed_on for row in transactions], ["2026-01-15", "2025-12-30"]
        )

    def test_first_seen_reaches_its_own_cell(self) -> None:
        cells = self._one().cells()

        self.assertEqual(
            cells[TRANSACTION_COLUMNS.index("First Seen")], "2026-01-01 00:00:00"
        )

    def test_what_a_scraped_table_never_says_stays_empty(self) -> None:
        # A 529 row has six fields and none of them is a symbol, a description
        # or an id. Empty means the source said nothing; "None" would be text.
        cells = self._one().cells()

        for name in ("Symbol", "Description", "External Id"):
            self.assertEqual(cells[TRANSACTION_COLUMNS.index(name)], "")

    def test_money_and_quantities_stay_numbers(self) -> None:
        cells = self._one().cells()

        self.assertEqual(cells[TRANSACTION_COLUMNS.index("Value")], 150.0)
        self.assertNotIsInstance(cells[TRANSACTION_COLUMNS.index("Value")], str)
        self.assertEqual(cells[TRANSACTION_COLUMNS.index("Units")], 1.5)

    def test_a_movement_with_no_value_is_empty_rather_than_zero(self) -> None:
        self.assertEqual(
            self._one(value=None).cells()[TRANSACTION_COLUMNS.index("Value")], ""
        )


class WorkspaceReadTests(MemoryKeyringMixin, unittest.TestCase):
    """Reading real databases, several of them, out of one workspace."""

    def setUp(self) -> None:
        super().setUp()
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.workspace = self.root / "default"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self._dir.cleanup()
        super().tearDown()

    def _write(
        self,
        broker: str,
        account: AccountIdentity,
        value: float,
        holdings: tuple[Holding, ...] = (),
        transactions: tuple[Transaction, ...] = (),
    ) -> None:
        db = BrokerDatabase(
            db_engine=create_db_engine(db_path=self.workspace / f"{broker}.db"),
            broker=broker,
        )
        db.save_snapshot(
            account=account,
            scraped_at="2026-01-01 00:00:00",
            value=value,
            as_of="2025-12-31",
            holdings=holdings,
            transactions=transactions,
        )
        db.shutdown_db()

    def test_a_history_longer_than_the_shell_reader_shows_comes_back_whole(
        self,
    ) -> None:
        # The reason this issue could not be closed by rendering the reader that
        # already existed. get_transactions() defaults to limit=500, so a tab
        # built on it would report the newest five hundred movements as though
        # they were all of them -- a number that looks complete with the missing
        # part invisible, on a tab whose whole purpose is history.
        movements = tuple(
            Transaction(
                processed_on=f"2026-01-{day % 28 + 1:02d}",
                tx_type="Contribution",
                value=float(day),
                raw=f"${day}.00",
            )
            for day in range(750)
        )
        self._write(
            broker="snaptrade",
            account=AccountIdentity(account_key="busy", display_name="Busy"),
            value=1.0,
            transactions=movements,
        )

        portfolio = read_workspace(workspace="default", root=self.root)

        self.assertEqual(len(portfolio.transactions), 750)

    def test_movements_from_every_broker_come_back_tagged(self) -> None:
        self._write(
            broker="schwab529plan",
            account=AccountIdentity(account_key="Ezekiel", display_name="Ezekiel 529"),
            value=1234.56,
            transactions=(
                Transaction(
                    processed_on="12/30/2025", tx_type="Contribution", value=150.0
                ),
            ),
        )
        self._write(
            broker="snaptrade",
            account=AccountIdentity(
                account_key="Schwab - Brokerage",
                display_name="Brokerage",
                source="Schwab",
            ),
            value=750.0,
            transactions=(
                Transaction(
                    processed_on="2026-08-01",
                    tx_type="BUY",
                    symbol="VTI",
                    description="Bought 3 VTI",
                    value=-750.0,
                    external_id="sn-1",
                ),
            ),
        )

        portfolio = read_workspace(workspace="default", root=self.root)

        self.assertEqual(
            {(row.broker, row.tx_type) for row in portfolio.transactions},
            {("schwab529plan", "Contribution"), ("snaptrade", "BUY")},
        )
        # Both brokers' dates arrive comparable, whatever the source wrote.
        self.assertEqual(
            sorted(row.processed_on or "" for row in portfolio.transactions),
            ["2025-12-30", "2026-08-01"],
        )

    def test_a_movement_joins_to_its_account_by_key(self) -> None:
        self._write(
            broker="snaptrade",
            account=AccountIdentity(
                account_key="Schwab - Brokerage",
                display_name="Brokerage",
                source="Schwab",
            ),
            value=750.0,
            transactions=(Transaction(processed_on="2026-08-01", tx_type="BUY"),),
        )

        portfolio = read_workspace(workspace="default", root=self.root)
        movement = portfolio.transactions[0]

        self.assertEqual(movement.account_key, "Schwab - Brokerage")
        self.assertEqual(movement.account, "Brokerage")
        self.assertEqual(movement.source, "Schwab")

    def test_accounts_from_every_broker_come_back_tagged(self) -> None:
        self._write(
            broker="schwab529plan",
            account=AccountIdentity(
                account_key="Ezekiel", display_name="Ezekiel 529", kind="529"
            ),
            value=1234.56,
            holdings=(FUND,),
        )
        self._write(
            broker="snaptrade",
            account=AccountIdentity(
                account_key="Schwab - Brokerage",
                display_name="Brokerage",
                source="Schwab",
            ),
            value=750.0,
            holdings=(POSITION,),
        )

        portfolio = read_workspace(workspace="default", root=self.root)

        self.assertEqual(portfolio.brokers_read, ("schwab529plan", "snaptrade"))
        self.assertEqual(portfolio.unreadable, ())
        self.assertEqual(
            {(row.broker, row.account_key) for row in portfolio.accounts},
            {("schwab529plan", "Ezekiel"), ("snaptrade", "Schwab - Brokerage")},
        )

    def test_the_total_is_the_sum_of_the_accounts(self) -> None:
        self._write(
            broker="schwab529plan",
            account=AccountIdentity(account_key="Ezekiel", display_name="Ezekiel"),
            value=1234.56,
            holdings=(FUND,),
        )
        self._write(
            broker="tsp",
            account=AccountIdentity(account_key="TSP C", display_name="TSP C"),
            value=750.0,
        )

        portfolio = read_workspace(workspace="default", root=self.root)

        self.assertAlmostEqual(portfolio.total(), 1984.56, places=2)

    def test_holdings_join_to_their_account_across_brokers(self) -> None:
        self._write(
            broker="schwab529plan",
            account=AccountIdentity(account_key="Ezekiel", display_name="Ezekiel 529"),
            value=1234.56,
            holdings=(FUND,),
        )
        self._write(
            broker="snaptrade",
            account=AccountIdentity(
                account_key="Schwab - Brokerage",
                display_name="Brokerage",
                source="Schwab",
            ),
            value=750.0,
            holdings=(POSITION,),
        )

        portfolio = read_workspace(workspace="default", root=self.root)
        keys = {(row.broker, row.account_key) for row in portfolio.accounts}

        self.assertEqual(len(portfolio.holdings), 2)

        for holding in portfolio.holdings:
            self.assertIn((holding.broker, holding.account_key), keys)

    def test_only_the_newest_snapshot_is_shown(self) -> None:
        # The view is current state. A second run adds a snapshot beside the
        # first rather than over it, and both appearing would double the total.
        account = AccountIdentity(account_key="Ezekiel", display_name="Ezekiel")
        self._write(broker="schwab529plan", account=account, value=1000.0)

        db = BrokerDatabase(
            db_engine=create_db_engine(db_path=self.workspace / "schwab529plan.db"),
            broker="schwab529plan",
        )
        db.save_snapshot(
            account=account, scraped_at="2026-01-02 00:00:00", value=1100.0
        )
        db.shutdown_db()

        portfolio = read_workspace(workspace="default", root=self.root)

        self.assertEqual(len(portfolio.accounts), 1)
        self.assertEqual(portfolio.accounts[0].value, 1100.0)

    def test_a_broker_that_will_not_open_is_reported_not_skipped(self) -> None:
        # Four brokers returned where five were expected produces a total that
        # is wrong by a whole account and looks entirely reasonable.
        self._write(
            broker="tsp",
            account=AccountIdentity(account_key="TSP C", display_name="TSP C"),
            value=750.0,
        )
        (self.workspace / "broken.db").write_text("not a database", encoding="utf-8")

        portfolio = read_workspace(workspace="default", root=self.root)

        self.assertEqual(portfolio.brokers_read, ("tsp",))
        self.assertEqual([name for name, _ in portfolio.unreadable], ["broken"])
        self.assertEqual(len(portfolio.accounts), 1)

    def test_a_missing_workspace_says_so(self) -> None:
        portfolio = read_workspace(workspace="nope", root=self.root)

        self.assertEqual(portfolio.accounts, ())
        self.assertEqual([name for name, _ in portfolio.unreadable], ["nope"])

    def test_reading_creates_no_database(self) -> None:
        # Globbing what is there, rather than enumerating brokers, is what keeps
        # a read from leaving five empty files behind.
        read_databases(paths=sorted(self.workspace.glob(pattern="*.db")))

        self.assertEqual(list(self.workspace.glob(pattern="*.db")), [])


if __name__ == "__main__":
    unittest.main()
