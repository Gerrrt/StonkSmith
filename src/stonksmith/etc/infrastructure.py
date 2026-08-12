"""
infrastructure.py: Functions for setting up logging levels and db engine.
"""

import logging
from argparse import Namespace
from pathlib import Path
from typing import Any

import sqlalchemy
import sqlalchemy.event

from stonksmith.etc.logger import stonksmith_logger
from stonksmith.etc.permissions import restrict


def create_db_engine(db_path: Path) -> sqlalchemy.Engine:
    """
    Create and return a SQLAlchemy engine.
    :param db_path: Path to the SQLite database file.
    :type db_path: str
    :return: A SQLAlchemy engine instance.
    :rtype: sqlalchemy.engine.Engine
    """

    engine: sqlalchemy.Engine = sqlalchemy.create_engine(
        url=f"sqlite:///{db_path}",
        isolation_level="AUTOCOMMIT",
        future=True,
    )

    @sqlalchemy.event.listens_for(target=engine, identifier="connect")
    def _enforce_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
        """
        Turn on foreign key enforcement, which SQLite leaves off.

        Without this every FOREIGN KEY and ON DELETE CASCADE in the schema is
        decoration: SQLite parses them, records them, and never checks them. A
        snapshot could outlive the account it belongs to and nothing would say
        so.
        """

        del connection_record

        cursor: Any = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")

        finally:
            cursor.close()

    @sqlalchemy.event.listens_for(target=engine, identifier="connect")
    def _restrict_database_file(dbapi_connection: Any, connection_record: Any) -> None:
        """
        Make the database file owner-readable only, from the connect that
        creates it.

        Not in the body above: SQLite creates the file lazily, so at that point
        there is nothing on disk to chmod. Not after metadata.create_all()
        either -- that is one caller of several, and it does no work at all on a
        database whose tables already exist, which is the normal case.
        migrate_plaintext_secrets(), _table_columns() and portfolio's reader all
        open connections without going near it.

        No secrets are in here; those are in the keyring. What is in here is
        every account number, balance, holding and transaction this tool has
        ever recorded -- which is the thing the keyring was protecting access
        to.

        On every connect rather than once, so that a database written by an
        older StonkSmith is tightened the first time this one opens it. A chmod
        to the mode a file already has is a no-op.
        """

        del dbapi_connection, connection_record

        restrict(path=db_path)

    return engine


def set_logging_level(args: Namespace) -> None:
    """
    Sets global log levels based on CLI flags.

    The default is INFO, not ERROR. Every message the tool prints about its own
    progress -- display(), success() and highlight() alike -- is logged at INFO,
    so an ERROR default meant a run that worked said nothing whatsoever: a TSP
    sync could read the statement, write the snapshot to the database and update
    the Google Sheet while printing only a progress bar, and the operator had no
    way to tell that from a run that had done nothing at all.

    That default had already been worked around twice rather than fixed. Both
    workarounds are still in etc.connection, each with a comment explaining that
    it reports at fail level because INFO is hidden. A default under which
    correct messages have to be mis-levelled to be seen is the wrong default.

    --quiet restores it for unattended runs, where only failures are wanted;
    --verbose still forces output on, which is what it is for when a wrapper
    script has hardcoded --quiet.
    :param args:
    :type args:
    :return:
    :rtype:
    """

    # --verbose lands on the same level as the default and is still not
    # redundant: it is ahead of --quiet, so passing both turns output back on.
    # Written this way round because the alternative -- checking --quiet first
    # -- would let a wrapper script's hardcoded --quiet win over a --verbose the
    # operator added on purpose to find out what the script was doing.
    if getattr(args, "debug", False):
        level: int = logging.DEBUG
    elif getattr(args, "verbose", False):
        level: int = logging.INFO
    elif getattr(args, "quiet", False):
        level: int = logging.ERROR
    else:
        level: int = logging.INFO

    logging.getLogger(name="stonksmith").setLevel(level=level)
    stonksmith_logger.logger.setLevel(level=level)

    log_path: Any | None = getattr(args, "log", None)
    if log_path:
        stonksmith_logger.add_file_log(log_file=log_path)
