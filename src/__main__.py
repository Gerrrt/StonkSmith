# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Stonksmith: A modular stock analysis and tracking tool."""

import asyncio
import sys
from argparse import Namespace
from typing import TYPE_CHECKING, Any

from src.etc.cli import gen_cli_args
from src.etc.config import stonksmith_workspace
from src.etc.infrastructure import create_db_engine, set_logging_level
from src.etc.logger import stonksmith_logger
from src.etc.paths import stonksmith_path
from src.etc.runner import start_run
from src.etc.tool_setup import setup_tool
from src.loaders.brokerloader import BrokerLoader
from src.loaders.moduleloader import ModuleLoader

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from sqlalchemy import Engine

    from src.etc.context import BrokerDbProtocol


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

    broker_class: Any = getattr(broker_module, args.broker.capitalize())
    db_class: Any = db_module.Database

    # 5. Database Setup
    db_path: Path = (
        stonksmith_path / "workspaces" / stonksmith_workspace / f"{broker_name}.db"
    )

    db_engine: Engine = create_db_engine(db_path=db_path)
    db: BrokerDbProtocol = db_class(db_engine)

    # 6. Module Handling
    loader: ModuleLoader = ModuleLoader(args=args, db=db, logger=stonksmith_logger)

    exit_code: int = 0
    if args.list_modules:
        loader.list_available()
    elif args.module and args.show_module_options:
        loader.show_options()
    elif args.module is None:
        exit_code = 1
    else:
        # 7. Broker Object Preparation
        broker_instance: Any = broker_class()
        module: Any | None = loader.prepare()
        broker_instance.module: list[Any] = [module] if module is not None else []

        # 8. Execution
        try:
            asyncio.run(main=start_run(broker_obj=broker_instance, db=db, args=args))
        except KeyboardInterrupt:
            stonksmith_logger.highlight(msg="Keyboard interrupt.")

    db_engine.dispose()
    return exit_code


if __name__ == "__main__":
    args: Namespace = gen_cli_args()
    exit_code: int = main(args=args)
    sys.exit(exit_code)
