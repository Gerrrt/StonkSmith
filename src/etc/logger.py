#!/usr/bin/env python3

"""
logger.py: Module to handle output for status messages
"""

import logging
import os.path
import re
import sys
from datetime import datetime
from logging import LogRecord
from logging.handlers import RotatingFileHandler

from rich.logging import RichHandler
from rich.text import Text
from termcolor import colored

from etc.console import stonksmith_console


class STONKSMITHAdapter(logging.LoggerAdapter):
    def __init__(self, extra=None):
        logging.basicConfig(
            format="%(message)s",
            datefmt="[%X]",
            handlers=[
                RichHandler(
                    console=stonksmith_console,
                    rich_tracebacks=True,
                    tracebacks_show_locals=False,
                )
            ],
        )
        self.logger = logging.getLogger("stonksmith")
        self.extra = extra
        self.output_file = None

    def format(self, msg, *args, **kwargs):
        """
        Format message for output if needed
        :param msg:
        :param args:
        :param kwargs:
        :return:
        """
        if self.extra is None:
            return f"{msg}", kwargs

        if "module_name" in self.extra.keys():
            if len(self.extra["module_name"]) > 8:
                self.extra["module_name"] = self.extra["module_name"][:8] + "..."

        if len(self.extra) == 1 and ("module_name" in self.extra.keys()):
            return (
                f"{colored(self.extra['module_name'], 'cyan', attrs=['bold']):<64} {msg}",
                kwargs,
            )

        if (
            len(self.extra) == 2
            and ("module_name" in self.extra.keys())
            and ("host" in self.extra.keys())
        ):
            return (
                f"{colored(self.extra['module_name'], 'cyan', attrs=['bold']):<24} "
                f"{self.extra['host']:<39} "
                f"{msg}",
                kwargs,
            )
