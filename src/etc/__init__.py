#!/usr/bin/env python3

"""
Etc package containing configuration modules for StonkSmith
"""

__author__ = "Gerrrt"
__email__ = "garrettallen2@gmail.com"
__version__ = "0.1.0"
__status__ = "Development"

from etc import paths
from etc.cli import gen_cli_args
from etc.console import stonksmith_console
from etc.context import Context
from etc.tool_setup import setup_tool

__all__ = [
    "gen_cli_args",
    "paths",
    "stonksmith_console",
    "setup_tool",
    "Context",
]
