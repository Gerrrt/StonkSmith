"""
Navigate database entries for SnapTrade.

BrokerLoader imports this file by path and expects a ``DatabaseNavigator``
symbol; the commands come from etc.broker_nav.BrokerNavigator.

``add creds`` is overridden because this broker has no username/password pair to
store. The shared navigator would prompt for a secret, write a credential row,
and nothing would ever read it -- SnapTrade authenticates with a client id and a
user secret held in config and the OS keyring instead.
"""

from etc.broker_nav import BrokerNavigator, DatabaseLike
from etc.logger import stonksmith_logger

SETUP_HINT = (
    "SnapTrade does not use stored username/password credentials. Put your key "
    "material in the keyring with:\n"
    "    uv run python scripts/snaptrade_register.py store --user-id <name>\n"
    "then set clientId and userId in the [SNAPTRADE] section of "
    "~/.stonksmith/stonksmith.conf."
)


class DatabaseNavigator(BrokerNavigator):
    """
    Navigate database entries for SnapTrade.
    """

    def __init__(
        self, main_menu: object, database: DatabaseLike, broker_name: str
    ) -> None:
        super().__init__(main_menu, database, broker_name)

        # The inherited intro advertises `add creds`, which does nothing here.
        self.intro = (
            f"\n[*] {broker_name}:\n"
            "    show accounts            saved balances\n"
            "    show creds               credentials (there are none; see below)\n"
            "    export creds <file>      write a CSV (never includes secrets)\n"
            "    broker <name>            switch straight to another broker\n"
            "    brokers                  leave and list the available brokers\n"
            "    back                     return to the broker list\n"
            "\n    Credentials for this broker live in ~/.stonksmith/stonksmith.conf\n"
            "    and the OS keyring; see scripts/snaptrade_register.py.\n"
        )

    def do_add(self, line: str) -> None:
        """
        Explain that SnapTrade credentials are not stored here.
        Usage: not applicable -- see scripts/snaptrade_register.py
        :param line: The rest of the command line, ignored
        """

        del line

        stonksmith_logger.fail(msg=SETUP_HINT)
