"""
Navigate database entries for SnapTrade.

BrokerLoader imports this file by path and expects a ``DatabaseNavigator``
symbol; the commands come from etc.broker_nav.BrokerNavigator.

``add creds`` is overridden because this broker has no username/password pair to
store. The shared navigator would prompt for a secret, write a credential row,
and nothing would ever read it -- SnapTrade authenticates with a client id from
the config file and a consumer key from the OS keyring instead.
"""

from stonksmith.etc.broker_nav import BrokerNavigator, DatabaseLike
from stonksmith.etc.logger import stonksmith_logger

SETUP_HINT = (
    "SnapTrade does not use stored username/password credentials. Put your "
    "consumer key in the keyring with:\n"
    "    uv run python scripts/snaptrade_register.py store\n"
    "then set clientId in the [SNAPTRADE] section of "
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
        #
        # Replacing it wholesale rather than editing one line is what dropped
        # both delete commands from this broker, which inherits do_delete and
        # runs them perfectly well. They are listed below. `delete creds` is the
        # one deliberately left out: the line above it already says there are no
        # credentials here, so offering to delete one advertises a no-op.
        # tests/test_shell_advertises_what_it_runs.py holds this list to
        # DELETERS, and names that omission as the single exception.
        self.intro = (
            f"\n[*] {broker_name}:\n"
            "    show accounts            the accounts across every connection\n"
            "    show snapshots [<acct>]  what each account was worth, over time\n"
            "    show holdings [<snap>]   the positions behind a snapshot\n"
            "    show transactions [<acct>]  recorded movements\n"
            "    show deltas              the change between consecutive snapshots\n"
            "    show creds               credentials (there are none; see below)\n"
            "    export creds <file>      write a CSV (never includes secrets)\n"
            "    export <category> <file> also accounts, snapshots, holdings,\n"
            "                             transactions or deltas -- the whole\n"
            "                             table, however long, unlike show\n"
            "    delete snapshot <id>     remove one wrong mark and its holdings\n"
            "    delete account <id>      remove an account and all its history\n"
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
