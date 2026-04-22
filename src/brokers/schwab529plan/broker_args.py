"""
Defines the command line arguments for the Schwab529Plan broker module.
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
    Add Schwab529Plan-specific arguments to the CLI.
    :param subparsers: The subparsers action to add the broker parser to
    :param std_parser: The standard parser with common arguments
    :param module_parser: The module parser with module-specific arguments
    :return: The updated subparsers action with the Schwab529Plan parser added
    :rtype: _SubParsersAction[ArgumentParser]
    """

    schwab529plan_parser: ArgumentParser = subparsers.add_parser(
        name="schwab529plan",
        help="College Savings Account at https://www.schwab529plan.com",
        parents=[std_parser, module_parser],
    )

    access_group: _ArgumentGroup = schwab529plan_parser.add_argument_group(
        title="Schwab529plan Options",
        description="Specific flags for Schwab529Plan accounts",
    )

    access_group.add_argument(
        "--account", type=str, help="List high-level details of the account dashboard"
    )

    access_group.add_argument(
        "--site",
        type=str,
        help="Override the default Schwab529Plan URL (rarely needed)",
    )

    return subparsers
