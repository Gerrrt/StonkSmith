"""
Defines the command line arguments for the TSP broker module.
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
    Add TSP-specific arguments to the CLI.
    :param subparsers: The subparsers action to add the broker parser to
    :param std_parser: The standard parser with common arguments
    :param module_parser: The module parser with module-specific arguments
    :return: The updated subparsers action with the TSP parser added
    :rtype: _SubParsersAction[ArgumentParser]
    """

    tsp_parser: ArgumentParser = subparsers.add_parser(
        name="tsp",
        help="Thrift Savings Plan, valued from published share prices",
        parents=[std_parser, module_parser],
    )

    group: _ArgumentGroup = tsp_parser.add_argument_group(
        title="TSP Options",
        description="Specific flags for the Thrift Savings Plan",
    )

    # Only flags that are actually consumed belong here: a declared-but-unread
    # flag silently does nothing. There is no credential flag of any kind,
    # because there is no login -- share prices are public and units come from
    # a statement.
    group.add_argument(
        "--prices",
        type=str,
        help=(
            "Read share prices from this file instead of downloading them. "
            "The published history as saved from tsp.gov. Use this when the "
            "machine cannot reach tsp.gov, or to value the account offline."
        ),
    )

    group.add_argument(
        "--units",
        type=float,
        help=(
            "Unit count to value, overriding the configured one. What a "
            "statement's 'Closing Units' says. Units only change on a "
            "transaction, so this is worth correcting roughly as often as one "
            "happens."
        ),
    )

    group.add_argument(
        "--balance",
        type=float,
        help=(
            "A balance read off the TSP site, which is back-solved into a unit "
            "count against that day's published price. The site states a "
            "balance and a date but never a unit count, so this is the way to "
            "reset the count between statements without downloading one."
        ),
    )

    group.add_argument(
        "--balance-as-of",
        type=str,
        metavar="YYYY-MM-DD",
        help=(
            "The 'Balance as of' date printed beside the balance. Required "
            "with --balance: the same dollars buy a different number of units "
            "on a different day, so a balance without its date cannot be "
            "converted at all."
        ),
    )

    group.add_argument(
        "--pay-table",
        type=str,
        help=(
            "Read DFAS basic pay from this file instead of downloading it. A "
            "published pay table page as saved from dfas.mil. Use this when the "
            "machine cannot reach dfas.mil, or to account for contributions "
            "offline."
        ),
    )

    group.add_argument(
        "--no-accrual",
        action="store_true",
        help=(
            "Value the unit count on its own, ignoring the configured rank, "
            "service date and contribution percentages. Use this for a mark "
            "that must be exact arithmetic with no estimate in it."
        ),
    )

    group.add_argument(
        "--units-as-of",
        type=str,
        metavar="YYYY-MM-DD",
        help=(
            "The date the unit count was true. Reported alongside every mark, "
            "so a value carried on an old count says how old it is rather "
            "than presenting itself as current."
        ),
    )

    return subparsers
