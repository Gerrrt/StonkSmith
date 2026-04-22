"""
Helper to highlight text for logger module
"""

from termcolor import colored


def highlight(text: object, color: str = "yellow") -> str | object:
    """
    Highlights text for logger module
    :param text:
    :param color:
    :return:
    """
    if color == "yellow":
        return f"{colored(text=text, color='yellow', attrs=['bold'])}"
    elif color == "red":
        return f"{colored(text=text, color='red', attrs=['bold'])}"
    else:
        return text
