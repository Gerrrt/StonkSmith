# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""One shape for what the databases hold, and one way to read it.

Five brokers wrote five unrelated worksheet layouts. Nothing shared a column:
"Balance" and "Value" named the same thing in different tabs, and `Synced`,
`Price date` and `Units as of` were three answers to one question. Each broker
was re-deriving its own projection of a shape the database already had.

So the projection lives here instead, once. Two row types, ordered columns, and
one function that produces them from every broker database in a workspace.

**The columns are append-only.** A new column goes on the end, never in the
middle. Anything reading this -- a worksheet formula most of all -- addresses a
column by position, and a column inserted at the front silently changes what
every one of them points at. `tests/test_portfolio_contract.py` pins the exact
tuples so that shift fails in CI rather than in a spreadsheet.

**Two row types rather than the one flat view this started out wanting.** An
account's value and the sum of its positions are different numbers: uninvested
cash sits in the balance and in no holding. A single view emitting positions
for accounts that have them and a balance for accounts that do not would
understate every account holding cash while looking like it totalled correctly.
So accounts carry the value, holdings carry the breakdown, and the two join on
(broker, account_key).

**Money is a number here, never a formatted string.** Every saver so far wrote
`format_amount()` output, which puts "$1,234.56" in a cell that cannot then be
added up. Formatting is the cell's job. `None` stays empty rather than becoming
zero, because an account that reported no number at all is not an account worth
nothing -- the database is careful about that distinction and this must not
throw it away.

Identity is per-broker. `account_key` is unique within one broker's database and
means nothing outside it: the same real-world 529 is "Schwab - Ezekiel 529 Plan"
to SnapTrade and "Ezekiel" to the Schwab scraper, with no stored field linking
them. Nothing here can dedupe across brokers, which is why the `[SNAPTRADE]
exclude_accounts` setting is still the thing that decides who owns an account.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from etc.broker_db import BrokerDatabase
from etc.config import get_workspace
from etc.context import PortfolioDbProtocol
from etc.infrastructure import create_db_engine
from etc.paths import workspace_dir

#: The account view, in order. One row per account, across every broker. The
#: sum of its Value column is the portfolio total; nothing else here totals.
ACCOUNT_COLUMNS: tuple[str, ...] = (
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
)

#: The holding view, in order. One row per position behind each account's newest
#: snapshot. The first four columns are the same identity prefix the account
#: view carries, so the two join on Broker + Account Key.
HOLDING_COLUMNS: tuple[str, ...] = (
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
)


def _cell(value: Any) -> Any:
    """
    Render one value for a grid, leaving an absent one absent.

    None becomes an empty cell rather than 0 or "None". A source that reported
    no number is saying something different from one that reported zero, and a
    view that cannot tell them apart is the reason the database stores a
    nullable value in the first place.
    :param value: The stored value
    :return: The value, or "" when there is none
    """

    return "" if value is None else value


def _reason(error: Exception) -> str:
    """
    Describe a failure in a way that always says something.

    An exception raised with no arguments stringifies to "" -- OSError() and
    sqlite3.DatabaseError() both do -- so str(e) alone can hand back a blank
    reason. A blank reason is worse than no field at all: it is a report that a
    broker could not be read, offering nothing about why, which is precisely the
    silence this field exists to break. The class name is always there.
    :param error: The exception to describe
    :return: A non-empty description
    :rtype: str
    """

    detail: str = str(object=error).strip()
    name: str = type(error).__name__

    return f"{name}: {detail}" if detail else name


@dataclass(frozen=True, slots=True)
class AccountRow:
    """
    One account, at whatever it was last observed to be worth.

    Frozen for the same reason the records in etc.records are: this is produced
    by a read and handed to a consumer, and nothing downstream should be editing
    it in place.
    """

    #: Which StonkSmith broker produced this -- "fidelity", "snaptrade", "tsp".
    broker: str

    #: The brokerage behind it, for an aggregator that names one. Falls back to
    #: the broker, so the column is never blank and can always be grouped on.
    source: str

    #: What to show a human. Free to change between runs; not identity.
    account: str

    #: Stable identity within this broker. What a formula should key on, and
    #: what the holding rows join back to.
    account_key: str

    kind: str | None = None
    beneficiary: str | None = None

    #: The value as a number, or None when the source reported none.
    value: float | None = None
    currency: str = "USD"

    #: The date the source says the value is for. Not when the run happened,
    #: and frequently absent -- several sources never say.
    as_of: str | None = None

    #: When the run that observed it happened.
    scraped_at: str = ""

    def cells(self) -> list[Any]:
        """
        This row in ACCOUNT_COLUMNS order.
        :return: One value per column
        :rtype: list[Any]
        """

        return [
            self.broker,
            self.source,
            self.account,
            self.account_key,
            _cell(self.kind),
            _cell(self.beneficiary),
            _cell(self.value),
            self.currency,
            _cell(self.as_of),
            _cell(self.scraped_at),
        ]


@dataclass(frozen=True, slots=True)
class HoldingRow:
    """
    One position behind one account's newest snapshot.

    Every position field is optional because the shapes this carries overlap
    only partly -- a scraped 529 fills fund code, principal and earnings; an API
    position fills symbol and cost basis. Neither filling the other's columns is
    normal rather than an error.
    """

    broker: str
    source: str
    account: str
    account_key: str

    #: The ticker, or the fund code for sources that do not trade in tickers.
    symbol: str | None = None
    name: str | None = None

    units: float | None = None
    price: float | None = None
    value: float | None = None
    cost_basis: float | None = None

    #: 529 plans report contributions and growth separately.
    principal: float | None = None
    earnings: float | None = None

    currency: str = "USD"
    as_of: str | None = None
    scraped_at: str = ""

    def cells(self) -> list[Any]:
        """
        This row in HOLDING_COLUMNS order.
        :return: One value per column
        :rtype: list[Any]
        """

        return [
            self.broker,
            self.source,
            self.account,
            self.account_key,
            _cell(self.symbol),
            _cell(self.name),
            _cell(self.units),
            _cell(self.price),
            _cell(self.value),
            _cell(self.cost_basis),
            _cell(self.principal),
            _cell(self.earnings),
            self.currency,
            _cell(self.as_of),
            _cell(self.scraped_at),
        ]


@dataclass(frozen=True, slots=True)
class Portfolio:
    """
    Everything the workspace's databases currently say, and what could not be
    asked.

    ``unreadable`` is not decoration. A read that quietly returns four brokers
    when five were expected produces a total that is wrong by a whole account
    and looks perfectly reasonable, which is the failure this project keeps
    finding: the run reported success because from its side nothing went wrong.
    """

    accounts: tuple[AccountRow, ...] = ()
    holdings: tuple[HoldingRow, ...] = ()

    #: Brokers whose database was opened and read, in the order read.
    brokers_read: tuple[str, ...] = ()

    #: (name, reason) for anything that could not be read -- normally a broker,
    #: or the workspace itself when the whole directory is missing.
    unreadable: tuple[tuple[str, str], ...] = ()

    def total(self, currency: str = "USD") -> float:
        """
        What the accounts in one currency add up to.

        Only accounts, never holdings, and only one currency at a time: adding a
        dollar to a euro produces a number that is not wrong so much as
        meaningless, and nothing here knows a rate.
        :param currency: The currency to total
        :return: The sum of the matching accounts' values
        :rtype: float
        """

        # Started at 0.0 rather than sum()'s implicit int 0, so a portfolio with
        # nothing in it returns the same type as one with something in it. A
        # total that is an int only when it is empty is the kind of thing that
        # works everywhere until it reaches the one caller that checks.
        return sum(
            (
                row.value
                for row in self.accounts
                if row.value is not None and row.currency == currency
            ),
            0.0,
        )


def read_broker(
    broker: str, db: PortfolioDbProtocol
) -> tuple[list[AccountRow], list[HoldingRow]]:
    """
    Project one already-open broker database into the canonical rows.

    Separate from read_workspace, which does the opening, so that this -- the
    part with the mapping decisions in it -- can be tested against literals.
    :param broker: The broker name, which becomes the Broker column
    :param db: An open database
    :return: Its accounts and their positions
    :rtype: tuple[list[AccountRow], list[HoldingRow]]
    """

    accounts: list[AccountRow] = []
    by_key: dict[str, AccountRow] = {}

    for (
        account_key,
        source,
        display_name,
        beneficiary,
        kind,
        value,
        currency,
        as_of,
        scraped_at,
    ) in db.get_current_accounts():
        row = AccountRow(
            broker=broker,
            # Only an aggregator fills this; a direct scraper is its own source.
            source=str(object=source or "").strip() or broker,
            account=display_name,
            account_key=account_key,
            kind=kind,
            beneficiary=beneficiary,
            value=value,
            currency=currency or "USD",
            as_of=as_of,
            scraped_at=scraped_at or "",
        )
        accounts.append(row)
        by_key[account_key] = row

    holdings: list[HoldingRow] = []

    for (
        account_key,
        _position,
        symbol,
        fund_code,
        name,
        units,
        price,
        value,
        principal,
        earnings,
        cost_basis,
        currency,
        as_of,
        scraped_at,
    ) in db.get_current_holdings():
        parent: AccountRow | None = by_key.get(account_key)

        holdings.append(
            HoldingRow(
                broker=broker,
                # A position whose account did not come back is not something
                # the real query can produce -- it joins through accounts. It is
                # still carried rather than dropped, keyed by the one identity
                # it definitely has, because losing a position silently is worse
                # than showing one whose name is a key.
                source=parent.source if parent else broker,
                account=parent.account if parent else account_key,
                account_key=account_key,
                # Which of the two a source fills is a fact about the source; the
                # column shows whichever there is.
                symbol=symbol or fund_code,
                name=name,
                units=units,
                price=price,
                value=value,
                cost_basis=cost_basis,
                principal=principal,
                earnings=earnings,
                currency=currency or "USD",
                as_of=as_of,
                scraped_at=scraped_at or "",
            )
        )

    return accounts, holdings


def workspace_path(workspace: str | None = None, root: Path | None = None) -> Path:
    """
    Where a workspace's broker databases live.
    :param workspace: The workspace name, or None for the configured one
    :param root: The directory workspaces live in, for tests
    :return: The workspace directory, which may not exist
    :rtype: Path
    """

    return Path(root or workspace_dir) / (workspace or get_workspace())


def read_databases(paths: Iterable[Path]) -> Portfolio:
    """
    Read the given broker databases into one set of canonical rows.

    The broker name is the file stem, which is how main.py names them in the
    first place. Databases are opened directly as BrokerDatabase rather than
    through each broker's Database subclass: those subclasses do nothing but set
    the name this already knows, and going through BrokerLoader would import
    five broker packages -- and their optional dependencies -- to run a read.

    Opening is not free of writes. BrokerDatabase applies its pending
    migrations on open, so a database written before account history is upgraded
    by being read. That is deliberate: the alternative is a read path that
    cannot see the oldest data.
    :param paths: Database files, one per broker
    :return: Their accounts and positions, and whatever would not open
    :rtype: Portfolio
    """

    accounts: list[AccountRow] = []
    holdings: list[HoldingRow] = []
    read: list[str] = []
    unreadable: list[tuple[str, str]] = []

    for path in paths:
        broker: str = path.stem
        db: BrokerDatabase | None = None

        try:
            db = BrokerDatabase(db_engine=create_db_engine(db_path=path), broker=broker)
            broker_accounts, broker_holdings = read_broker(broker=broker, db=db)

        # Deliberately broad. A file in this directory can fail to be a usable
        # database in more ways than are worth enumerating -- corrupt, truncated,
        # unreadable, or simply not SQLite -- and one bad file must not cost the
        # caller the other four brokers. What it must not do is vanish, so the
        # reason is carried out rather than logged and forgotten.
        except Exception as e:
            unreadable.append((broker, _reason(e)))
            continue

        finally:
            if db is not None:
                db.shutdown_db()

        accounts.extend(broker_accounts)
        holdings.extend(broker_holdings)
        read.append(broker)

    return Portfolio(
        accounts=tuple(accounts),
        holdings=tuple(holdings),
        brokers_read=tuple(read),
        unreadable=tuple(unreadable),
    )


def read_workspace(workspace: str | None = None, root: Path | None = None) -> Portfolio:
    """
    Every account and position across every broker in one workspace.

    This is the single read path out of the databases: a worksheet sync, a
    dashboard, or anything else that wants to show what is held consumes this
    rather than reaching into a broker's tables and inventing its own shape.
    :param workspace: The workspace name, or None for the configured one
    :param root: The directory workspaces live in, for tests
    :return: What the workspace holds, and whatever would not open
    :rtype: Portfolio
    """

    directory: Path = workspace_path(workspace=workspace, root=root)

    if not directory.is_dir():
        # Reported rather than returned as an empty portfolio, which reads
        # identically to a workspace whose brokers have simply never run.
        return Portfolio(
            unreadable=((directory.name, f"no workspace directory at {directory}"),)
        )

    return read_databases(paths=sorted(directory.glob(pattern="*.db")))
