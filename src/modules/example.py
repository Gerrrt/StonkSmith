# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Module Template"""

from typing import Any, ClassVar

from etc.connection import Connection
from etc.context import Context


class StonkSmithModule:
    """Class Template"""

    name: str = "Example"
    description: str = "Scrape/Clean/etc from an account"
    supported_brokers: ClassVar[list[str]] = ["schwab529plan"]
    opsec_safe: bool = True
    multiple_hosts: bool = False

    def __init__(
        self,
        context: Context | None = None,
        module_options: dict[str, Any] | None = None,
    ) -> None:
        self.context: Context | None = context
        self.module_options: dict[str, Any] | None = module_options

    def options(self, context: Context, module_options: dict[str, Any]) -> None:
        """Required.
        Module options get parsed here.
        Additionally, put the modules usage here as well
        :param context:
        :param module_options:
        """

    def on_login(self, context: Context) -> None:
        """Concurrent.
        Required if on_admin_login is not present. This gets called on each
        authenticated connection
        """
        # Logging best practice
        # Mostly you should use these functions to display information to
        # the user
        context.log.display("I'm doing something")
        # Use this for every normal message ([*] I'm doing something)
        context.log.success("I'm doing something")
        # Use this for when something succeeds ([+] I'm doing something)
        context.log.fail("I'm doing something")
        # Use this for when something fails ([-] I'm doing something),
        # for example a remote registry entry is missing which is needed to
        # proceed
        context.log.highlight("I'm doing something")
        # Use this for when something is important and should be highlighted,
        # printing credentials for example

        # These are for debugging purposes
        context.log.info("I'm doing something")
        # This will only be displayed if the user has specified
        # the --verbose flag, so add additional info that might be useful
        context.log.debug("I'm doing something")
        # This will only be displayed if the user has specified
        # the --debug flag, so add info that you might need for
        # debugging errors

        # These are for more critical error handling
        context.log.error("I'm doing something")
        # This will not be printed in the module context and should only be
        # used for critical errors (e.g. a required Python file is missing)
        try:
            raise ValueError("Example exception for demonstration")
        except ValueError:
            context.log.exception("Exception occurred")
            # This will display an exception traceback screen after an
            # exception was raised and should only be used for critical errors

    def on_admin_login(self, context: Context, connection: Connection) -> None:
        """Concurrent.
        Required if on_login is not present
        This gets called on each authenticated connection with
        Administrative privileges
        """

    def on_request(self, context: Context, request: Any) -> None:
        """Optional.
        If the payload needs to retrieve additional files,
        add this function to the module
        """

    def on_response(self, context: Context, response: Any) -> None:
        """Optional.
        If the payload sends back its output to our server,
        add this function to the module to handle its output
        """

    def on_shutdown(self, context: Context, connection: Connection) -> None:
        """Optional.
        Do something on shutdown
        """
