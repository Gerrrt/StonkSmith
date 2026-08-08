"""
Context module
"""

import configparser
from argparse import Namespace
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from etc.logger import StonkSmithAdapter
from etc.paths import stonksmith_path
from etc.records import AccountIdentity, Holding, Transaction

#: Re-exported so a module author has one import for everything it hands the
#: database: `from etc.context import Context, AccountIdentity, Holding`.
__all__ = [
    "AccountIdentity",
    "BrokerDbProtocol",
    "Context",
    "Holding",
    "PortfolioDbProtocol",
    "SnapshotDbProtocol",
    "SnapshotReadDbProtocol",
    "Transaction",
]


@runtime_checkable
class BrokerDbProtocol(Protocol):
    """
    Structural interface that every broker database must satisfy.
    """

    def get_credentials(
        self, filter_term: str | None = None
    ) -> list[tuple[str, ...]]: ...

    def save_account_data(
        self, account_name: str | None, balance: str | None, timestamp: str
    ) -> None: ...

    def shutdown_db(self) -> None: ...


@runtime_checkable
class SnapshotDbProtocol(BrokerDbProtocol, Protocol):
    """
    A database that keeps history, rather than one balance per account.

    Deliberately a second protocol rather than three more methods on
    BrokerDbProtocol. Modules under ~/.stonksmith/modules were written against
    the smaller one, and a database that only implements it is not broken -- it
    just predates account history. Modules test for this one and fall back, the
    same way they already test for save_account_data itself.
    """

    def save_snapshot(
        self,
        account: AccountIdentity,
        scraped_at: str,
        value: float | None,
        currency: str = "USD",
        as_of: str | None = None,
        raw_value: str | None = None,
        holdings: Sequence[Holding] = (),
        transactions: Sequence[Transaction] = (),
    ) -> int: ...

    def save_transactions(
        self,
        account: AccountIdentity,
        timestamp: str,
        rows: Sequence[Transaction],
    ) -> int: ...


@runtime_checkable
class SnapshotReadDbProtocol(SnapshotDbProtocol, Protocol):
    """
    A database whose history can be read back, not only written to.

    A third protocol for the same reason there is a second one. Every protocol
    above this is about handing the database something; this is the first that
    asks for anything back, and a database that cannot answer is not broken --
    it just cannot serve a module that values a position from what a previous
    run observed. Modules test for this one and fall back, as they already do
    for SnapshotDbProtocol.

    What wants it: a broker whose session cannot be reused. Ally refuses a
    restored session however it is stored, so a daily run cannot scrape -- but
    a unit count does not change between deposits, and a published price needs
    no login. Reading the last observed units is what makes that possible, and
    it is the one thing a write-only interface cannot provide.
    """

    def get_snapshots(
        self, account_id: int | None = None, limit: int = 100
    ) -> list[tuple[Any, ...]]: ...

    def get_holdings(
        self, snapshot_id: int | None = None, limit: int = 500
    ) -> list[tuple[Any, ...]]: ...


@runtime_checkable
class PortfolioDbProtocol(Protocol):
    """
    A database that can describe its current state by account identity.

    The interface etc.portfolio reads through. Unlike the three above, this one
    does not extend the chain -- it stands alone, and deliberately. Those are
    layered because a *module* holds one database and asks how much of the
    contract it supports before deciding what to write. Nothing here writes. A
    reader that demanded save_snapshot in order to answer a question about
    balances would be asking for a capability it never uses, and would shut out
    exactly the read-only consumers this exists to serve.

    Also distinct from SnapshotReadDbProtocol, which asks what a *particular*
    snapshot held so a module can reprice it. This asks what every account is
    worth *now*, keyed on the identity that survives a display name changing --
    which is what a view spanning several brokers has to join on.
    """

    def get_current_accounts(self) -> list[tuple[Any, ...]]: ...

    def get_current_holdings(self) -> list[tuple[Any, ...]]: ...


class Context:
    """
    Context class
    """

    def __init__(
        self,
        db: BrokerDbProtocol,
        logger: StonkSmithAdapter,
        args: Namespace,
        active_username: str | None = None,
        active_password: str | None = None,
    ) -> None:
        self.args: Namespace = args
        self.db: BrokerDbProtocol = db
        self.log: StonkSmithAdapter = logger
        self.active_username: str | None = active_username
        self.active_password: str | None = active_password
        self.cli_usernames: list[str] = list(getattr(args, "username", []))
        self.cli_passwords: list[str] = list(getattr(args, "password", []))

        self.home_dir = Path(stonksmith_path)
        self.log_folder_path: Path = self.home_dir / "logs"
        self.config_file: Path = self.home_dir / "stonksmith.conf"

        self.conf = configparser.ConfigParser()
        if self.config_file.exists():
            self.conf.read(filenames=str(object=self.config_file))

        self.local_ip = None
