"""
Context module
"""

import configparser
from argparse import Namespace
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

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
    "SnapshotDbProtocol",
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
