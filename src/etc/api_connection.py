# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Base class for brokers that authenticate with a stored API key.

StonkSmith's original broker shape is a scraper: it takes a username and a
password, drives a login form, and hands the authenticated session to a module.
``Connection.login()`` encodes that shape -- with no ``-u`` and no ``-id`` it
reports "No credentials supplied" and returns False, and ``broker_flow()``
returns without running a single module.

An API-backed broker has no such credentials to supply. Its key is read from
config and the OS keyring at connection time and there is nothing to type. Left
alone it inherits the credential check, and every run is a silent no-op: no
output, no rows, exit 0. That override lives here rather than being rewritten --
and eventually forgotten -- once per broker.

The split this class fixes on:

* ``create_conn_obj()`` builds the client. Reading config and the keyring
  belongs there: it *is* the connection object. A subclass that cannot build one
  must say why, because ``broker_flow()`` deliberately stays quiet.
* ``login()`` proves the key works, via ``verify_access()``. One cheap
  authenticated call turns a rejected key into a single actionable line before
  any module runs, instead of a traceback from inside one.
"""

from typing import Any

from etc.connection import Connection


class ApiConnection(Connection):
    """
    A broker that authenticates with a stored API key instead of a login.

    Subclasses must override ``create_conn_obj()`` and ``verify_access()``.
    Both must report their own failure: ``broker_flow()`` prints nothing for a
    False return, so a quiet one produces a run that does nothing and says
    nothing about it.
    """

    #: Stands in for the signed-in username in log lines and in ``Context``.
    #: There is no such user here, and leaving it empty makes call_modules()
    #: log "for unknown user" on every line. Fidelity fabricates
    #: MANUAL_SESSION_LABEL for the same reason.
    session_label: str = "api session"

    def __init__(self) -> None:
        super().__init__()
        self.client: Any = None
        self.username = self.session_label

    def create_conn_obj(self) -> bool:
        """
        Build the API client. Subclasses must override.
        :return: True when ``self.client`` is ready to use
        :rtype: bool
        """

        self.logger.fail(
            msg=(
                f"{self.broker} does not implement create_conn_obj(); an API "
                "broker has to build its own client."
            ),
        )

        return False

    def verify_access(self) -> bool:
        """
        Prove the stored key works with one cheap authenticated call.

        Overriding this is what turns a rejected or expired key into one
        actionable line before any module runs.
        :return: True when the API answered
        :rtype: bool
        """

        return True

    def login(self) -> bool:
        """
        Skip the credential flow entirely and verify the stored key.

        Deliberately does not call ``super().login()``: that path demands a
        username and secret this shape never has, and fails the run when it
        cannot find them.
        :return: True when the API accepted the stored key
        :rtype: bool
        """

        if getattr(self.args, "username", None) or getattr(self.args, "cred_id", None):
            # -u/-p/-id come from std_parser, which is a parent of every broker
            # subparser, so they cannot be hidden from this broker's --help.
            # Saying nothing means an operator who passed one watches it be
            # ignored with no explanation.
            self.logger.highlight(
                msg=(
                    f"{self.broker} authenticates with a stored API key; "
                    "credentials passed on the command line are ignored."
                ),
            )

        self.username = self.session_label

        return self.verify_access()

    def teardown(self) -> None:
        """
        Drop the client so its connection pool is not held past the run.
        """

        self.client = None
