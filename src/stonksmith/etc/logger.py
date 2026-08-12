"""
logger.py: Module to handle output for status messages
"""

import logging
import re
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from rich.logging import RichHandler

from etc.console import stonksmith_console
from etc.paths import logs_path


class TermEscapeCodeFormatter(logging.Formatter):
    """
    Strips ANSI escape codes before writing to disk.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Format message
        :param record:
        :type record:
        :return:
        :rtype:
        """

        message = str(object=record.msg)
        escape_re: re.Pattern[str] = re.compile(pattern=r"\x1b\[[0-9;]*[mGKH]")
        record.msg = re.sub(pattern=escape_re, repl="", string=message)
        return super().format(record=record)


class StonkSmithAdapter(logging.LoggerAdapter[logging.Logger]):
    """
    Adapter class to handle STONKSMITH logging output
    """

    def process(self, msg: Any, kwargs: Any) -> tuple[Any, Any]:
        """
        Standard for injecting extra context into LoggerAdapter.
        :param msg:
        :param kwargs:
        :return:
        """

        if not self.extra:
            return msg, kwargs

        module: object = self.extra.get(
            "module_name", self.extra.get("broker", "STONK")
        )

        if len(self.extra) == 1 and "module_name" in self.extra:
            prefix: str = f"[cyan bold]{module}:[/] "
        elif len(self.extra) == 2 and "module_name" in self.extra:
            prefix = f"[red bold]Module: [/] [magenta bold]{module}[/]"
        else:
            prefix = f"[red bold]Broker: [/] [blue bold]{module}[/]"

        return f"{prefix}{msg}", kwargs

    def display(self, msg: Any) -> None:
        """
        Display text to console, formatted for STONKSMITH
        :param msg:
        :return:
        """

        self.info(msg=f"{'':<9}[bold cyan][*][/] {msg}")

    def success(self, msg: Any) -> None:
        """
        Print some sort of success to the user
        :param msg:
        :return:
        """

        self.info(msg=f"{'':4}[bold green][+][/] {msg}")

    def highlight(self, msg: Any) -> None:
        """
        Prints a yellow highlighted message to the user
        :param msg:
        :return:
        """

        self.info(msg=f"{'':<4}[bold yellow][!][/] {msg}")

    def fail(self, msg: Any) -> None:
        """
        Prints a failure that may or may not be an error
        :param msg:
        :return:
        """

        self.error(msg=f"{'':<4}[bold red][-][/] {msg}")

    def add_file_log(self, log_file: Path | None = None) -> None:
        """
        Add a log file to stonksmith
        :param log_file:
        :return:
        """

        output_file: Path = Path(log_file) if log_file else self.init_log_file()

        if not output_file.exists():
            output_file.touch()

        file_handler = RotatingFileHandler(
            filename=output_file, maxBytes=100000, backupCount=5
        )

        file_formatter = TermEscapeCodeFormatter(
            fmt="%(asctime)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(fmt=file_formatter)

        self.logger.addHandler(hdlr=file_handler)
        self.debug(msg=f"Added file handler: {output_file}")

    @staticmethod
    def init_log_file() -> Path:
        """
        Creates and returns the path for a new daily log file.
        :return:
        """

        daily_folder: Path = logs_path / datetime.now(tz=UTC).strftime(
            format="%Y-%m-%d"
        )
        daily_folder.mkdir(parents=True, exist_ok=True)

        filename: str = f"log_{datetime.now(tz=UTC).strftime(format='%H-%M-%S')}.log"
        return daily_folder / filename


_base_logger: logging.Logger = logging.getLogger(name="stonksmith")
_base_logger.setLevel(level=logging.INFO)

_base_logger.propagate = False

if not _base_logger.handlers:
    console_handler = RichHandler(
        console=stonksmith_console,
        show_time=False,
        show_level=False,
        show_path=False,
        markup=True,
    )
    console_handler.setFormatter(fmt=logging.Formatter(fmt="%(message)s"))
    _base_logger.addHandler(hdlr=console_handler)

stonksmith_logger = StonkSmithAdapter(logger=_base_logger)
