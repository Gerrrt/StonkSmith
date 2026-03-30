#!/usr/bin/env python3

"""
stonksmith.py: Script
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from os.path import join

import sqlalchemy
from rich.progress import Progress

from etc import (
    config_log,
    gen_cli_args,
    setup_tool,
    stonksmith_console,
    stonksmith_logger,
    stonksmith_path,
    stonksmith_workspace,
    )
from etc.config import ignore_opsec
from helpers import highlight
from loaders import ProtocolLoader


def create_db_engine(db_path):
    """
    Create database engine
    :param db_path:
    :return:
    """
    db_engine = sqlalchemy.create_engine(
            f"sqlite:///{db_path}",
            isolation_level="AUTOCOMMIT",
            future=True)
    return db_engine


async def start_run(protocol_obj, args, db, targets):
    """
    Run STONKSMITH
    :param protocol_obj:
    :param args:
    :param db:
    :param targets:
    """
    stonksmith_logger.debug("Creating ThreadPoolExecutor")
    if args.no_progress or len(targets) == 1:
        with ThreadPoolExecutor(max_workers=args.threads + 1) as executor:
            stonksmith_logger.debug(f"Creating thread for {protocol_obj}")
            _ = [executor.submit(
                    protocol_obj,
                    args,
                    db,
                    target) for target in targets]
    else:
        with Progress(console=stonksmith_console) as progress:
            with ThreadPoolExecutor(max_workers=args.threads + 1) as executor:
                current = 0
                total = len(targets)
                tasks = progress.add_task(
                        f"[green]Running STONKSMITH against "
                        f"{total} {'target' if total == 1 else 'targets'}",
                        total=total,
                        )
                stonksmith_logger.debug(f"Creating thread for {protocol_obj}")
                futures = [executor.submit(
                        protocol_obj,
                        args,
                        db,
                        target) for target in targets]
                for _ in as_completed(futures):
                    current += 1
                    progress.update(tasks, completed=current)


def main():
    """
    Main function
    :return:
    """
    setup_tool()
    root_logger = logging.getLogger("root")
    args = gen_cli_args()

    if args.verbose:
        stonksmith_logger.logger.setLevel(logging.INFO)
        root_logger.setLevel(logging.INFO)
    elif args.debug:
        stonksmith_logger.logger.setLevel(logging.DEBUG)
        root_logger.setLevel(logging.DEBUG)
    else:
        stonksmith_logger.logger.setLevel(logging.ERROR)
        root_logger.setLevel(logging.ERROR)

    if config_log:
        stonksmith_logger.add_file_log()
    if hasattr(args, "log") and args.log:
        stonksmith_logger.add_file_log(args.log)

    stonksmith_logger.debug(f"Passed args: {args}")

    if not args.protocol:
        exit(1)

    module_server = None
    targets = []
    server_port_dict = {
        "http": 80,
        "https": 443,
        "smb": 445,
        }

    stonksmith_logger.debug(f"Protocol: {args.protocol}")
    p_loader = ProtocolLoader()
    protocol_path = p_loader.get_protocols()[args.protocol]["path"]
    stonksmith_logger.debug(f"Protocol path: {protocol_path}")
    protocol_db_path = p_loader.get_protocols()[args.protocol]["dbpath"]
    stonksmith_logger.debug(f"Protocol DB Path: {protocol_db_path}")

    protocol_object = getattr(
            p_loader.load_protocol(protocol_path),
            args.protocol, )
    stonksmith_logger.debug(f"Protocol Object: {protocol_object}")
    protocol_db_object = getattr(
            p_loader.load_protocol(protocol_db_path),
            "database", )
    stonksmith_logger.debug(f"Protocol DB Object: {protocol_db_object}")

    db_path = join(
            stonksmith_path,
            "workspaces",
            stonksmith_workspace,
            f"{args.protocol}.db")
    stonksmith_logger.debug(f"DB Path: {db_path}")

    db_engine = create_db_engine(db_path)

    db = protocol_db_object(db_engine)

    if args.module or args.list_modules:
        loader = ModuleLoader(args, db, stonksmith_logger)
        modules = loader.list_modules()

    if args.list_modules:
        for name, props in sorted(modules.items()):
            if args.protocol in props["supported_protocols"]:
                stonksmith_logger.display(f"{name} {props['description']}")
        exit(0)

    elif args.module and args.show_module_options:
        for module in args.module:
            stonksmith_logger.display(
                    f"{module} module options:\n"
                    f"{modules[module]['options']}")
        exit(0)
    elif args.module:
        stonksmith_logger.debug(
                f"Modules to be Loaded: {args.module}, "
                f"{type(args.module)}")
        for m in map(str.lower, args.module):
            if m not in modules:
                stonksmith_logger.error(f"Module not found: {m}")
                exit(1)

            stonksmith_logger.debug(
                    f"Loading module {m} at path "
                    f"{modules[m]['path']}")
            module = loader.init_module(modules[m]["path"])

            if not module.opsec_safe:
                if ignore_opsec:
                    stonksmith_logger.debug(
                            "ignore_opsec is set in the "
                            "configuration, skipping prompt")
                    stonksmith_logger.display(
                            "Ignore OPSEC in "
                            "configuration is set and "
                            "OPSEC unsafe module loaded")
                else:
                    ans = input(
                            highlight(
                                    "[!] Module is not opsec safe, are you "
                                    "sure you want to run this? [Y/n]",
                                    "red",
                                    ),
                            )
                    if ans.lower() not in ["y", "yes", ""]:
                        exit(1)

            stonksmith_logger.debug(
                    f"proto_object: {protocol_object}, "
                    f"type: {type(protocol_object)}")
            stonksmith_logger.debug(
                    f"proto object dir: "
                    f"{dir(protocol_object)}")
            current_modules = getattr(protocol_object, "module", [])
            current_modules.append(module)
            setattr(protocol_object, "module", current_modules)
            stonksmith_logger.debug(
                    f"proto object module after adding: "
                    f"{protocol_object.module}")

            try:
                asyncio.run(start_run(protocol_object, args, db, targets))
            except KeyboardInterrupt:
                stonksmith_logger.debug("Got keyboard interrupt")
            finally:
                if module_server:
                    module_server.shutdown()
                db_engine.dispose()


if __name__ == "__main__":
    main()
