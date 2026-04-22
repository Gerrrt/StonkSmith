"""
Context module
"""

import configparser
from argparse import Namespace
from pathlib import Path
from typing import Protocol, runtime_checkable

from etc.logger import StonkSmithAdapter
from etc.paths import stonksmith_path


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
