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


class SwitchBroker(UserExitedProto):
    """Raised inside a broker sub-shell to move straight to another broker.

    Subclasses UserExitedProto so any handler that only knows how to leave a
    sub-shell still behaves correctly; handlers that understand switching catch
    this first and read the requested name.
    """

    def __init__(self, broker: str = "") -> None:
        """
        Record the broker to switch to.
        :param broker: Name requested, or "" to just list the available brokers
        """

        super().__init__(broker)
        self.broker = broker
