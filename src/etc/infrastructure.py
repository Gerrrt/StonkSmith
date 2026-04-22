"""
infrastructure.py: Functions for setting up logging levels and db engine.
"""

import logging
from argparse import Namespace
from pathlib import Path
from typing import Any

import sqlalchemy

from etc.logger import stonksmith_logger


def create_db_engine(db_path: Path) -> sqlalchemy.Engine:
    """
    Create and return a SQLAlchemy engine.
    :param db_path: Path to the SQLite database file.
    :type db_path: str
    :return: A SQLAlchemy engine instance.
    :rtype: sqlalchemy.engine.Engine
    """

    return sqlalchemy.create_engine(
        url=f"sqlite:///{db_path}",
        isolation_level="AUTOCOMMIT",
        future=True,
    )


def set_logging_level(args: Namespace) -> None:
    """
    Sets global log levels based on CLI flags.
    :param args:
    :type args:
    :return:
    :rtype:
    """

    if getattr(args, "debug", False):
        level: int = logging.DEBUG
    elif getattr(args, "verbose", False):
        level: int = logging.INFO
    else:
        level: int = logging.ERROR

    logging.getLogger(name="stonksmith").setLevel(level=level)
    stonksmith_logger.logger.setLevel(level=level)

    log_path: Any | None = getattr(args, "log", None)
    if log_path:
        stonksmith_logger.add_file_log(log_file=log_path)
