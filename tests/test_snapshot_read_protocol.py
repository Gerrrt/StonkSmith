# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""A database a module can read back, not only write to.

Every protocol before this one is about handing the database something. This
is the first that asks for anything in return, and it exists because a broker
turned up whose session cannot be reused: Ally refuses a restored session
however it is stored, so a daily run cannot scrape. A unit count does not
change between deposits and a published price needs no login, so the position
can still be valued -- but only by reading what the last run that *did* sign in
observed.

It is a third protocol rather than three more methods on BrokerDbProtocol,
following the reasoning SnapshotDbProtocol already records: modules under
~/.stonksmith/modules were written against the smaller interface, and a
database that implements only it is not broken. Widening the base would make
every one of them fail an isinstance check they currently pass.
"""

import unittest
from typing import Any

from stonksmith.etc.broker_db import BrokerDatabase
from stonksmith.etc.context import (
    BrokerDbProtocol,
    SnapshotDbProtocol,
    SnapshotReadDbProtocol,
)


class WriteOnlyDb:
    """A database that predates history: it takes, but does not give back."""

    def get_credentials(self, filter_term: str | None = None) -> list[tuple[str, ...]]:
        return []

    def save_account_data(
        self, account_name: str | None, balance: str | None, timestamp: str
    ) -> None:
        return None

    def shutdown_db(self) -> None:
        return None


class ReadableDb(WriteOnlyDb):
    """One that answers as well."""

    def save_snapshot(self, *args: Any, **kwargs: Any) -> int:
        return 1

    def save_transactions(self, *args: Any, **kwargs: Any) -> int:
        return 0

    def get_snapshots(
        self, account_id: int | None = None, limit: int = 100
    ) -> list[tuple[Any, ...]]:
        return []

    def get_holdings(
        self, snapshot_id: int | None = None, limit: int = 500
    ) -> list[tuple[Any, ...]]:
        return []


class TheRealDatabase(unittest.TestCase):
    """Whatever the protocols say, the shipped database has to satisfy them."""

    def test_it_satisfies_all_three(self) -> None:
        for protocol in (
            BrokerDbProtocol,
            SnapshotDbProtocol,
            SnapshotReadDbProtocol,
        ):
            self.assertTrue(issubclass(BrokerDatabase, protocol), protocol.__name__)


class TheOlderInterfaces(unittest.TestCase):
    """The point of a third protocol is that the first two keep their meaning."""

    def test_a_write_only_database_is_still_a_broker_database(self) -> None:
        """Widening the base protocol would have broken exactly this."""
        self.assertIsInstance(WriteOnlyDb(), BrokerDbProtocol)

    def test_but_it_cannot_be_read_back(self) -> None:
        self.assertNotIsInstance(WriteOnlyDb(), SnapshotReadDbProtocol)

    def test_a_readable_one_is_recognised(self) -> None:
        self.assertIsInstance(ReadableDb(), SnapshotReadDbProtocol)

    def test_reading_implies_the_history_it_reads(self) -> None:
        """There is nothing to read back without snapshots to read."""
        self.assertIsInstance(ReadableDb(), SnapshotDbProtocol)


if __name__ == "__main__":
    unittest.main()
