#!/usr/bin/env python3

"""
Helper package
"""

__author__ = "Gerrrt"
__email__ = "garrettallen2@gmail.com"
__version__ = "0.1.0"
__status__ = "Development"

from helpers.extra import called_from_cmd_args
from helpers.logger import highlight

__all__ = ["highlight", "called_from_cmd_args"]
