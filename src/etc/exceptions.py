# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Exceptions shared across the StonkSmith interactive shells.

These live in their own module so that broker sub-packages loaded by file path
and the top-level ``stonksmithdb`` shell raise and catch the *same* class. When
each side defined its own copy, ``back`` from a broker navigator escaped the
handler in ``StonkSmithDBMenu.do_broker`` and tore down the whole shell.
"""


class UserExitedProto(Exception):
    """Raised when the user leaves a sub-shell and returns to the caller."""
