"""
Cli module for arguments
"""

import sys
from argparse import (
    SUPPRESS,
    ArgumentParser,
    Namespace,
    RawTextHelpFormatter,
    _ArgumentGroup,  # pyright: ignore
    _SubParsersAction,  # pyright: ignore
)
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from types import ModuleType

from etc.logger import stonksmith_logger
from helpers.logger import highlight
from loaders.brokerloader import BrokerInfo, BrokerLoader

#: What --version says when the version cannot be established. Not a number:
#: every number this could fall back to would be a guess presented as a fact,
#: and a version is only worth printing if it is the one actually running.
UNKNOWN_VERSION: str = "unknown"

#: The release's name, and the one part of the banner still written by hand.
#: A codename is not derivable from anything -- there is nothing to read it out
#: of -- so it stays here, where it is the only thing to keep in step.
CODENAME: str = "Forrest Gump"


def get_version() -> str:
    """
    The running version, read from the installed distribution.

    Read rather than written, because it used to be written twice: a literal in
    this file beside the one in pyproject.toml, agreeing by luck and checked by
    nothing. Two copies of one fact is the shape of bug this project keeps
    finding, and this one was quiet in the worst way -- a --version that is wrong
    reports it confidently, and the number is what somebody correlates a strange
    database or sheet against.

    pyproject.toml is now the single source, and this is a read of what was built
    from it. That makes a stale install visible rather than invisible: the two
    disagreeing means the venv is behind the file, which is worth knowing and is
    what tests/test_version_single_source.py checks.
    :return: The installed version, or UNKNOWN_VERSION when there is none
    :rtype: str
    """

    try:
        return installed_version(distribution_name="stonksmith")

    except PackageNotFoundError:
        # Running from a source tree that was never installed -- python src/main.py
        # rather than uv run. There is no metadata to read and nothing to guess.
        return UNKNOWN_VERSION


def gen_cli_args() -> Namespace:
    """
    Generate CLI arguments
    :return: Parsed arguments
    :rtype: argparse.Namespace
    """

    version: str = get_version()
    codename: str = CODENAME

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
        "--quiet",
        action="store_true",
        help="Report failures only; say nothing about a run that worked",
    )
    parser.add_argument(
        "--no-sheet",
        action="store_true",
        help=(
            "Skip this run's Google Sheets refresh. Every broker rewrites the "
            "whole sheet, so a batch that runs several back to back rewrites it "
            "several times over and can exhaust the per-minute write quota; "
            "`stonksmithdb sheet` afterwards renders all of them once"
        ),
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

    # --verbose, --debug and --quiet are declared on the top-level parser too,
    # so they work on either side of the broker name: `stonksmith --verbose
    # fidelity` and `stonksmith fidelity --verbose` both do the same thing. Only
    # the former used to parse, which reads as arbitrary next to -M/-u/-p/-id,
    # which only work after it.
    #
    # SUPPRESS is what makes that safe. With a normal `default=False` this
    # parser would set verbose=False whenever the flag was absent here --
    # overwriting a --verbose that had already been parsed before the broker
    # name, and silently turning it off. SUPPRESS leaves the attribute alone
    # unless the flag is actually given.
    for flag, flag_help in (
        ("--verbose", "Enable verbose output"),
        ("--debug", "Enable debug level information"),
        ("--quiet", "Report failures only; say nothing about a run that worked"),
        ("--no-sheet", "Skip this run's Google Sheets refresh"),
    ):
        std_parser.add_argument(
            flag,
            action="store_true",
            default=SUPPRESS,
            help=flag_help,
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
    brokers: dict[str, BrokerInfo] = broker_loader.get_brokers()

    for broker_name, info in brokers.items():
        if "argspath" in info:
            # Deliberately broad. This loop runs before any command is dispatched,
            # so anything a broker raises here reaches every invocation of the
            # tool -- a narrower catch let one half-finished broker under
            # ~/.stonksmith/brokers take down --version and --help too. A broker
            # that cannot register its arguments registers no subparser: it is
            # simply unavailable, and the rest still work.
            try:
                broker_module: ModuleType | None = broker_loader.load_broker(
                    broker_path=info["argspath"],
                    label=f"Broker '{broker_name}'",
                )
                if broker_module is None:
                    # load_broker() has already said which broker and why.
                    continue

                broker_module.broker_args(subparsers, std_parser, module_parser)

            except Exception as e:
                stonksmith_logger.fail(
                    msg=(
                        f"Broker '{broker_name}' could not register its arguments "
                        f"and is unavailable this run: {type(e).__name__}: {e}"
                    ),
                )

    # Outside the loop: a bare invocation must print help even when no broker
    # registered a subparser.
    if len(sys.argv) == 1:
        parser.print_help()
        raise SystemExit(0)

    return parser.parse_args()
