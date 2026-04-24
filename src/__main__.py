"""Stonksmith: A modular stock analysis and tracking tool."""

import asyncio
import sys
from argparse import Namespace
from pathlib import Path
from types import ModuleType
from typing import Any

from sqlalchemy import Engine

from etc.cli import gen_cli_args
from etc.config import stonksmith_workspace
from etc.context import BrokerDbProtocol
from etc.infrastructure import create_db_engine, set_logging_level
from etc.logger import stonksmith_logger
from etc.paths import stonksmith_path
from etc.runner import start_run
from etc.tool_setup import setup_tool
from loaders.brokerloader import BrokerLoader
from loaders.moduleloader import ModuleLoader


def main(args: Namespace) -> int:
    """Main function
    :return:
    0: Success
    1: Failure
    """
    # 1. Tool Setup
    setup_tool(logger=stonksmith_logger)

    # 2. Configure logging
    set_logging_level(args=args)

    # 3. Validation: Catch missing broker before continuing
    if not args.broker:
        print("Error: Broker required.")
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

    broker_class = getattr(broker_module, args.broker.capitalize())
    db_class = db_module.Database

    # 5. Database Setup
    db_path: Path = (
        stonksmith_path
        / "workspaces"
        / stonksmith_workspace
        / f"{broker_name}.db"
    )

    db_engine: Engine = create_db_engine(db_path=db_path)
    db: BrokerDbProtocol = db_class(db_engine)

    # 6. Module Handling
    loader: ModuleLoader = ModuleLoader(
        args=args,
        db=db,
        logger=stonksmith_logger,
    )

    if args.list_modules:
        loader.list_available()
        return 0

    if args.module and args.show_module_options:
        loader.show_options()
        return 0

    # 7. Broker Object Preparation
    broker_instance = broker_class()

    if args.module is not None:
        module: Any | None = loader.prepare()
        broker_instance.module = [module] if module is not None else []

    else:
        return 1

    # 8. Execution
    try:
        asyncio.run(
            main=start_run(broker_obj=broker_instance, db=db, args=args),
        )

    except KeyboardInterrupt:
        stonksmith_logger.highlight(msg="Keyboard interrupt.")

    finally:
        db_engine.dispose()

    return 0


if __name__ == "__main__":
    args: Namespace = gen_cli_args()
    exit_code: int = main(args=args)
    sys.exit(exit_code)
