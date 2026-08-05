# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Stonksmith: A modular stock analysis and tracking tool."""

import asyncio
import sys
from argparse import Namespace
from typing import TYPE_CHECKING, Any

from etc.cli import gen_cli_args
from etc.config import get_workspace
from etc.infrastructure import create_db_engine, set_logging_level
from etc.logger import stonksmith_logger
from etc.paths import stonksmith_path
from etc.runner import start_run
from etc.tool_setup import setup_tool
from loaders.brokerloader import BrokerLoader
from loaders.moduleloader import ModuleLoader

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from sqlalchemy import Engine

    from etc.context import BrokerDbProtocol


def main(args: Namespace) -> int:
    """Execute the main entry point for Stonksmith.

    Args:
        args (Namespace): Parsed command-line arguments.

    Returns:
        int: Exit code (0 for success, non-zero for errors).

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
    broker_loader: BrokerLoader = BrokerLoader()
    brokers: dict[str, dict[str, str]] = broker_loader.get_brokers()

    if broker_name not in brokers:
        stonksmith_logger.error(msg=f"Broker '{broker_name}' not found.")
        return 1

    broker_info: dict[str, str] = brokers[broker_name]

    broker_module: ModuleType | None = broker_loader.load_broker(
        broker_path=broker_info["path"],
    )
    if broker_module is None:
        stonksmith_logger.error(
            msg=f"Failed to load broker module: {broker_info['path']}",
        )
        return 1

    if "dbpath" not in broker_info:
        stonksmith_logger.error(
            msg=f"Database module missing for broker '{broker_name}'.",
        )
        return 1

    db_module: ModuleType | None = broker_loader.load_broker(
        broker_path=broker_info["dbpath"],
    )
    if db_module is None or not hasattr(db_module, "Database"):
        stonksmith_logger.error(
            msg=f"Failed to load Database class from: {broker_info['dbpath']}",
        )
        return 1

    # Brokers publish a module-level 'Broker' alias so the class name is free to
    # diverge from the directory name (TSP, Schwab529Plan). Fall back to the
    # capitalized directory name for brokers that predate the alias.
    broker_class: Any = getattr(broker_module, "Broker", None)
    if broker_class is None:
        broker_class = getattr(broker_module, broker_name.capitalize(), None)

    if broker_class is None:
        stonksmith_logger.error(
            msg=(
                f"Broker module '{broker_info['path']}' does not define a "
                f"'Broker' alias or a '{broker_name.capitalize()}' class."
            ),
        )
        return 1

    db_class: Any = db_module.Database

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
        modules: list[Any] = loader.prepare()
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

        broker_instance: Any = broker_class()
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
    """Parse command-line arguments and run Stonksmith.

    Console-script entry point for the ``stonksmith`` command.

    Returns:
        int: Exit code (0 for success, non-zero for errors).

    """
    return main(args=gen_cli_args())


if __name__ == "__main__":
    sys.exit(cli_entry())
