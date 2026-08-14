"""
Defines the command line arguments for the manual broker module.
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
    Add manual-broker arguments to the CLI.
    :param subparsers: The subparsers action to add the broker parser to
    :param std_parser: The standard parser with common arguments
    :param module_parser: The module parser with module-specific arguments
    :return: The updated subparsers action with the manual parser added
    :rtype: _SubParsersAction[ArgumentParser]
    """

    manual_parser: ArgumentParser = subparsers.add_parser(
        name="manual",
        help="Accounts you can see but cannot scrape, valued from published prices",
        parents=[std_parser, module_parser],
    )

    group: _ArgumentGroup = manual_parser.add_argument_group(
        title="Manual Options",
        description="Specific flags for hand-kept accounts",
    )

    # Only flags that are actually consumed belong here: a declared-but-unread
    # flag silently does nothing. There is no credential flag of any kind,
    # because there is nothing to log in to -- that is the entire premise of
    # this broker.
    group.add_argument(
        "--prices",
        type=str,
        help=(
            "Read published closes from this file instead of downloading them. "
            "A chart payload as saved from the quote feed. Use this when the "
            "feed is unreachable from wherever StonkSmith runs, or to value an "
            "account against a payload captured earlier. One file, so it only "
            "makes sense with a single configured symbol."
        ),
    )

    return subparsers
