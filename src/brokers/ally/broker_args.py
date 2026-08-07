"""
Defines the command line arguments for the Ally Invest broker module.
"""

from argparse import (
    ArgumentParser,
    _ArgumentGroup,  # pyright: ignore
    _SubParsersAction,  # pyright: ignore
)


def broker_args(
    subparsers: _SubParsersAction[ArgumentParser],
    std_parser: ArgumentParser,
    module_parser: ArgumentParser,
) -> _SubParsersAction[ArgumentParser]:
    """
    Add Ally-specific arguments to the CLI.
    :param subparsers: The subparsers action to add the broker parser to
    :param std_parser: The standard parser with common arguments
    :param module_parser: The module parser with module-specific arguments
    :return: The updated subparsers action with the Ally parser added
    :rtype: _SubParsersAction[ArgumentParser]
    """

    ally_parser: ArgumentParser = subparsers.add_parser(
        name="ally",
        help="Brokerage accounts at https://live.invest.ally.com",
        parents=[std_parser, module_parser],
    )

    access_group: _ArgumentGroup = ally_parser.add_argument_group(
        title="Ally Options",
        description="Specific flags for Ally Invest accounts",
    )

    # Only flags that are actually consumed belong here: a declared-but-unread
    # flag silently does nothing. Every one of these is read by
    # etc.browser_connection.
    #
    # There is deliberately no automated-login flag. Ally Invest has no login
    # of its own -- the bank signs you in and hands the investing site your
    # session -- so the human path is the only path, and --manual-login is
    # documented as the default rather than as an option.
    access_group.add_argument(
        "--manual-login",
        action="store_true",
        help=(
            "Sign in by hand in the browser window, then let StonkSmith reuse "
            "that session on later runs. This is what Ally always does; the "
            "flag exists to force --headed for the first run."
        ),
    )

    access_group.add_argument(
        "--headed",
        action="store_true",
        help="Run the browser headed so the login flow can be watched",
    )

    access_group.add_argument(
        "--from-prices",
        action="store_true",
        help=(
            "Value the account from published prices and the units the last "
            "signed-in run recorded, without opening a browser at all. Ally "
            "refuses a restored session however it is stored, so a daily "
            "unattended run cannot scrape -- but units only change when a "
            "deposit lands, and a published price needs no login. Re-run with "
            "--manual-login when the units change; every other day this is "
            "exact and needs nothing from you."
        ),
    )

    access_group.add_argument(
        "--browser",
        choices=("firefox", "cdp", "chromium", "chrome"),
        default="firefox",
        help=(
            "Browser to drive. 'cdp' attaches to a Chrome you started "
            "yourself with --remote-debugging-port and signed into, which is "
            "the path most likely to survive Ally's bot protection (Akamai, "
            "Dynatrace and Transmit all run on the login page). 'chrome' "
            "launches the real Google Chrome binary against a persistent "
            "profile, which fingerprints well but must be installed "
            "(`uv run playwright install chrome`); 'chromium' is the bundled "
            "build, also with a persistent profile."
        ),
    )

    access_group.add_argument(
        "--cdp-url",
        type=str,
        help=(
            "CDP endpoint for --browser cdp. Defaults to "
            "http://127.0.0.1:9222. StonkSmith prints the exact Chrome launch "
            "command if nothing is listening."
        ),
    )

    access_group.add_argument(
        "--profile-dir",
        type=str,
        help=(
            "Persistent profile directory for --browser chromium/chrome. "
            "Defaults to ~/.stonksmith/playwright/chrome-profile. Point it at "
            "a real browser profile only if that browser is closed while "
            "StonkSmith runs."
        ),
    )

    return subparsers
