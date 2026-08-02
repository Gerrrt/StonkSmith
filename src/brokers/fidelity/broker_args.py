"""
Defines the command line arguments for the Fidelity broker module.
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
    Add Fidelity-specific arguments to the CLI.
    :param subparsers: The subparsers action to add the broker parser to
    :param std_parser: The standard parser with common arguments
    :param module_parser: The module parser with module-specific arguments
    :return: The updated subparsers action with the Fidelity parser added
    :rtype: _SubParsersAction[ArgumentParser]
    """

    fidelity_parser: ArgumentParser = subparsers.add_parser(
        name="fidelity",
        help="Brokerage and retirement accounts at https://www.fidelity.com",
        parents=[std_parser, module_parser],
    )

    access_group: _ArgumentGroup = fidelity_parser.add_argument_group(
        title="Fidelity Options",
        description="Specific flags for Fidelity accounts",
    )

    # Only flags that are actually consumed belong here: a declared-but-unread
    # flag silently does nothing.
    access_group.add_argument(
        "--manual-login",
        action="store_true",
        help=(
            "Sign in by hand in the browser window, then let StonkSmith reuse "
            "that session on later runs. Fidelity's bot protection rejects "
            "automated sign-in, so this is the supported path. Implies --headed."
        ),
    )

    access_group.add_argument(
        "--headed",
        action="store_true",
        help="Run the browser headed so the login flow can be watched",
    )

    return subparsers
