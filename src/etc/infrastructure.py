"""
infrastructure.py: Functions for setting up logging levels and db engine.
"""

import logging
from argparse import Namespace
from pathlib import Path
from typing import Any

import sqlalchemy
import sqlalchemy.event

from etc.logger import stonksmith_logger


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

    return engine


def set_logging_level(args: Namespace) -> None:
    """
    Sets global log levels based on CLI flags.
    :param args:
    :type args:
    :return:
    :rtype:
    """

    # --list-modules / --options exist purely to print something. They log at
    # INFO, so at the default ERROR level they produced no output at all.
    wants_listing: bool = bool(
        getattr(args, "list_modules", False)
        or getattr(args, "show_module_options", False)
    )

    if getattr(args, "debug", False):
        level: int = logging.DEBUG
    elif getattr(args, "verbose", False) or wants_listing:
        level: int = logging.INFO
    else:
        level: int = logging.ERROR

    logging.getLogger(name="stonksmith").setLevel(level=level)
    stonksmith_logger.logger.setLevel(level=level)

    log_path: Any | None = getattr(args, "log", None)
    if log_path:
        stonksmith_logger.add_file_log(log_file=log_path)
