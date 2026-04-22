"""
Cli module for arguments
"""

import sys
from argparse import (
    ArgumentParser,
    Namespace,
    RawTextHelpFormatter,
    _ArgumentGroup,  # pyright: ignore
    _SubParsersAction,  # pyright: ignore
)
from types import ModuleType

from etc.logger import stonksmith_logger
from helpers.logger import highlight
from loaders.brokerloader import BrokerLoader


def gen_cli_args() -> Namespace:
    """
    Generate CLI arguments
    :return: Parsed arguments
    :rtype: argparse.Namespace
    """

    version: str = "0.1.0"
    codename: str = "Forrest Gump"

    parser = ArgumentParser(
        description=rf"""
==================================================
__ _               _     __           _ _   _
/ _\ |_ ___  _ __ | | __/ _\_ __ ___ (_) |_| |__
\ \| __/ _ \| '_ \| |/ /\ \| '_ ` _ \| | __| '__
_\ \ || (_) | | | |   < _\ \ | | | | | | |_| | | |
\__/\__\___/|_| |_|_|\_\___/_| |_| |_|_|\__|_| |_|

==================================================
        Aggregate everything in one dashboard
        Written by: @Gerrrt

{highlight(text="Version", color="red")} : {highlight(text=version)}
{highlight(text="Codename", color="red")}: {highlight(text=codename)}
""",
        formatter_class=RawTextHelpFormatter,
    )

    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug level information"
    )
    parser.add_argument(
        "--version", action="version", version=f"{version} - {codename}"
    )

    module_parser = ArgumentParser(add_help=False)
    module_group: _ArgumentGroup = module_parser.add_argument_group(
        title="Module Options"
    )

    module_group.add_argument(
        "-M",
        "--module",
        action="append",
        metavar="MODULE",
        help="Module Name",
    )

    module_group.add_argument(
        "-o",
        metavar="MODULE_OPTION",
        nargs="+",
        default=[],
        dest="module_option",
        help="Module Options",
    )
    module_group.add_argument(
        "-L",
        "--list-modules",
        action="store_true",
        help="List available modules",
    )
    module_group.add_argument(
        "--options",
        dest="show_module_options",
        action="store_true",
        help="Display module options",
    )

    std_parser = ArgumentParser(add_help=False)
    std_parser.add_argument(
        "-id",
        metavar="CRED_ID",
        nargs="+",
        default=[],
        type=str,
        dest="cred_id",
        help="database credential ID(s) to use for authentication",
    )
    std_parser.add_argument(
        "--log",
        metavar="LOG",
        help="Export result into a custom file",
    )
    std_parser.add_argument(
        "--module-run-markers",
        action="store_true",
        help="Show start/finish markers around module execution",
    )

    auth_group: _ArgumentGroup = std_parser.add_argument_group(title="Authentication")
    auth_group.add_argument(
        "-u",
        metavar="USERNAME",
        dest="username",
        nargs="+",
        default=[],
        help="Username to use for authentication",
    )
    auth_group.add_argument(
        "-p",
        metavar="PASSWORD",
        dest="password",
        nargs="+",
        default=[],
        help="Password to use for authentication",
    )

    subparsers: _SubParsersAction[ArgumentParser] = parser.add_subparsers(
        title="Brokers", dest="broker", description="Available Brokers"
    )

    broker_loader = BrokerLoader()
    brokers: dict[str, dict[str, str]] = broker_loader.get_brokers()

    for broker_name, info in brokers.items():
        if "argspath" in info:
            try:
                broker_module: ModuleType | None = broker_loader.load_broker(
                    broker_path=info["argspath"]
                )
                if broker_module is not None:
                    broker_module.broker_args(subparsers, std_parser, module_parser)

            except (ImportError, AttributeError, TypeError) as e:
                stonksmith_logger.error(
                    msg=f"DEBUG: Could not load args for {broker_name}: {e}"
                )

        if len(sys.argv) == 1:
            parser.print_help()
            raise SystemExit(0)

    return parser.parse_args()
