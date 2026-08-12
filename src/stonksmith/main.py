# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Stonksmith: A modular stock analysis and tracking tool."""

import asyncio
import sys
from argparse import Namespace
from typing import TYPE_CHECKING, cast

from stonksmith.etc.cli import gen_cli_args
from stonksmith.etc.config import get_workspace
from stonksmith.etc.infrastructure import create_db_engine, set_logging_level
from stonksmith.etc.logger import stonksmith_logger
from stonksmith.etc.paths import stonksmith_path
from stonksmith.etc.runner import start_run
from stonksmith.etc.tool_setup import setup_tool
from stonksmith.loaders.brokerloader import BrokerInfo, BrokerLoader
from stonksmith.loaders.moduleloader import ModuleLoader

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType

    from sqlalchemy import Engine

    from stonksmith.etc.context import BrokerDbProtocol, BrokerProtocol, ModuleProtocol


def broker_class_of(
    module: ModuleType, broker_name: str
) -> Callable[[], BrokerProtocol] | None:
    """
    The login class a broker module publishes.

    Brokers publish a module-level ``Broker`` alias so the class name is free to
    diverge from the directory name (TSP, Schwab529Plan). Falls back to the
    capitalized directory name for brokers that predate the alias.

    cast, not a check: this comes out of a file loaded by path, so nothing
    static can confirm the shape. What the cast buys is the other end -- every
    use of the result is checked against the protocol, and a broker missing
    ``name`` or not callable is caught by ty at the call site rather than by a
    thread pool at runtime.
    :param module: The loaded broker module
    :param broker_name: The directory the broker was found in
    :return: The class, or None when the module publishes neither
    :rtype: Callable[[], BrokerProtocol] | None
    """

    # callable(), not "is not None": the result is called immediately, so
    # `Broker = "..."` would reach `broker_class()` and raise TypeError instead
    # of the message below. Falling through to the second name rather than
    # refusing outright, because a module with a junk alias and a real class is
    # still a broker somebody can run.
    for attribute in ("Broker", broker_name.capitalize()):
        found: object = getattr(module, attribute, None)

        if callable(found):
            return cast("Callable[[], BrokerProtocol]", found)

    return None


#: What a broker resolves to: the class that logs in, and the class that stores
#: what it finds.
type _Resolved = tuple[
    Callable[[], BrokerProtocol], Callable[[Engine, str], BrokerDbProtocol]
]


def resolve_broker(broker_name: str) -> _Resolved | None:
    """
    Work out what to run for a broker, or say why nothing can be.

    Split from ``main`` at the seam between deciding and doing: everything here
    can fail and every failure is the same outcome -- a message and exit 1 --
    which is what made ``main`` a column of early returns with the actual run
    buried underneath them.
    :param broker_name: The broker, lowercased
    :return: The login class and the store class, or None after reporting
    :rtype: _Resolved | None
    """

    broker_loader: BrokerLoader = BrokerLoader()
    brokers: dict[str, BrokerInfo] = broker_loader.get_brokers()

    if broker_name not in brokers:
        stonksmith_logger.error(msg=f"Broker '{broker_name}' not found.")
        return None

    broker_info: BrokerInfo = brokers[broker_name]
    broker_module: ModuleType | None = broker_loader.load_broker(
        broker_path=broker_info["path"],
    )

    if broker_module is None:
        stonksmith_logger.error(
            msg=f"Failed to load broker module: {broker_info['path']}",
        )
        return None

    # No "is there a database.py" branch: a broker without one takes
    # BrokerDatabase, which is what all five of them used to subclass and
    # nothing more. None here means the broker shipped one and it does not
    # work, which the loader has already said out loud.
    database: type | None = broker_loader.database_class(name=broker_name)

    if database is None:
        return None

    broker_class: Callable[[], BrokerProtocol] | None = broker_class_of(
        module=broker_module, broker_name=broker_name
    )

    if broker_class is None:
        stonksmith_logger.error(
            msg=(
                f"Broker module '{broker_info['path']}' does not define a "
                f"'Broker' alias or a '{broker_name.capitalize()}' class."
            ),
        )
        return None

    return broker_class, cast("Callable[[Engine, str], BrokerDbProtocol]", database)


def main(args: Namespace) -> int:
    """
    Execute the main entry point for Stonksmith.
    :param args: Parsed command-line arguments
    :return: Exit code (0 for success, non-zero for errors)
    """

    # 1. Tool Setup
    setup_tool(logger=stonksmith_logger)

    # 2. Configure logging
    set_logging_level(args=args)

    # 3. Validation: Catch missing broker before continuing
    if not args.broker:
        stonksmith_logger.error(
            msg="No broker specified. Provide a broker with --broker <BROKER_NAME>",
        )
        return 1

    # 4. Broker Data Setup
    broker_name: str = args.broker.lower()
    resolved: _Resolved | None = resolve_broker(broker_name=broker_name)

    if resolved is None:
        return 1

    broker_class, db_class = resolved

    # 5. Database Setup
    db_path: Path = (
        stonksmith_path / "workspaces" / get_workspace() / f"{broker_name}.db"
    )

    db_engine: Engine = create_db_engine(db_path=db_path)
    db: BrokerDbProtocol = db_class(db_engine, broker_name)

    # 6. Module Handling
    loader: ModuleLoader = ModuleLoader(args=args, db=db, logger=stonksmith_logger)

    exit_code: int = 0
    if args.list_modules:
        loader.list_available()
    elif args.module and args.show_module_options:
        loader.show_options()
    elif args.module is None:
        # This was a bare `exit_code = 1` with no message. A run that exits
        # non-zero and says nothing is as hard to schedule around as one that
        # exits zero and lies.
        stonksmith_logger.error(
            msg="No module specified. Provide one with --module <MODULE_NAME>",
        )
        exit_code = 1
    else:
        # 7. Broker Object Preparation
        requested: list[str] = list(args.module)
        modules: list[ModuleProtocol] = loader.prepare()
        if not modules:
            stonksmith_logger.error(msg="No modules could be loaded. Nothing to run.")
            db_engine.dispose()
            return 1

        if len(modules) != len(requested):
            # prepare() logs each miss and drops it; the requested-vs-prepared
            # count was the only signal left, and it was discarded. The run
            # still does what it can -- partial data beats none, and refusing
            # would turn one typo into a wholly missed sync -- but it must not
            # report success.
            stonksmith_logger.error(
                msg=(
                    f"Only {len(modules)} of {len(requested)} requested module(s) "
                    "loaded; this run is incomplete."
                ),
            )
            exit_code = 1

        broker_instance: BrokerProtocol = broker_class()
        broker_instance.module = modules

        # 8. Execution
        try:
            run_ok: bool = asyncio.run(
                main=start_run(broker_obj=broker_instance, db=db, args=args)
            )
            if not run_ok:
                exit_code = 1

        except KeyboardInterrupt:
            # 128 + SIGINT, the shell convention, and distinguishable from the 1
            # a real failure returns: a scheduler should page on 1 and shrug at
            # 130. Reported at fail level because highlight is INFO, which the
            # default level hides -- a cancelled run used to leave no trace at
            # all and still exit 0.
            stonksmith_logger.fail(msg="Keyboard interrupt: the run was cancelled.")
            exit_code = 130

    db_engine.dispose()
    return exit_code


def cli_entry() -> int:
    """
    Parse command-line arguments and run Stonksmith.

    Console-script entry point for the ``stonksmith`` command.
    :return: Exit code (0 for success, non-zero for errors)
    """

    return main(args=gen_cli_args())


if __name__ == "__main__":
    sys.exit(cli_entry())
