#!/usr/bin/env python3

"""
Etc package containing configuration modules for StonkSmith
"""

__author__ = "Gerrrt"
__email__ = "garrettallen2@gmail.com"
__version__ = "0.1.0"
__status__ = "Development"

import paths
from cli import gen_cli_args
from console import stonksmith_console

__all__ = ["gen_cli_args", "stonksmith_console", "paths"]
