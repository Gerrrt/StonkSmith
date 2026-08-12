"""
Defines the command line arguments for the Schwab529Plan broker module.
"""

from argparse import (
    ArgumentParser,
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

    # NOTE: this broker deliberately adds no options of its own. --account and
    # --site used to be declared here but nothing ever read them, so passing
    # either silently did nothing. Re-add a flag only alongside the code that
    # consumes it, and list its name in the broker's `cmd_actions` if
    # Connection.call_cmd_args() should dispatch to a same-named method.
    subparsers.add_parser(
        name="schwab529plan",
        help="College Savings Account at https://www.schwab529plan.com",
        parents=[std_parser, module_parser],
    )

    return subparsers
