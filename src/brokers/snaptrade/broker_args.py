"""
Defines the command line arguments for the SnapTrade broker module.
"""

from argparse import (
    ArgumentParser,
    _SubParsersAction,  # pyright: ignore
)

#: SnapTrade refreshes holdings once a day by design, so a one-day ceiling would
#: flag healthy accounts on most runs and train the operator into passing
#: --allow-stale permanently -- which would leave every genuinely stale account
#: syncing unnoticed, the one thing the check exists to prevent. A disabled
#: connection is skipped regardless of this flag.
DEFAULT_MAX_AGE_DAYS = 3


def broker_args(
    subparsers: _SubParsersAction[ArgumentParser],
    std_parser: ArgumentParser,
    module_parser: ArgumentParser,
) -> _SubParsersAction[ArgumentParser]:
    """
    Add SnapTrade-specific arguments to the CLI.
    :param subparsers: The subparsers action to add the broker parser to
    :param std_parser: The standard parser with common arguments
    :param module_parser: The module parser with module-specific arguments
    :return: The updated subparsers action with the SnapTrade parser added
    :rtype: _SubParsersAction[ArgumentParser]
    """

    parser: ArgumentParser = subparsers.add_parser(
        name="snaptrade",
        help="Every brokerage connected through https://snaptrade.com",
        parents=[std_parser, module_parser],
    )

    # Only flags that are actually consumed belong here: a declared-but-unread
    # flag silently does nothing. All three are read by modules/snaptrade_module.
    group = parser.add_argument_group(title="SnapTrade Options")

    group.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help=(
            "Skip an account whose holdings last synced more than this many "
            f"days ago (default: {DEFAULT_MAX_AGE_DAYS})"
        ),
    )

    group.add_argument(
        "--allow-stale",
        action="store_true",
        help="Sync accounts that failed the freshness check anyway, marking them",
    )

    group.add_argument(
        "--include-liabilities",
        action="store_true",
        help="Also sync credit cards and other lines of credit, which carry "
        "negative balances",
    )

    return subparsers
