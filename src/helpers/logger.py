#!/usr/bin/env python3

"""
Helper to highlight text for logger module
"""

from termcolor import colored


def highlight(text, color="yellow"):
    """
    Highlight text for logger module
    :param text:
    :param color:
    :return:
    """
    if color == "yellow":
        return f"{colored(text, 'yellow', attrs=['bold'])}"
    elif color == "red":
        return f"{colored(text, 'red', attrs=['bold'])}"
    else:
        return text
