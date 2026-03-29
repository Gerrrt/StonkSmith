#!/usr/bin/env python3

"""
stonksmith.py: Script
"""

import logging
from os.path import join

from etc import (
    config_log,
    create_db_engine,
    gen_cli_args,
    setup_tool,
    stonksmith_logger,
    stonksmith_path,
    stonksmith_workspace,
)
from loaders import ProtocolLoader


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
            args.protocol,)
    stonksmith_logger.debug(f"Protocol Object: {protocol_object}")
    protocol_db_object = getattr(
            p_loader.load_protocol(protocol_db_path),
            "database",)
    stonksmith_logger.debug(f"Protocol DB Object: {protocol_db_object}")

    db_path = join(
            stonksmith_path,
            "workspaces",
            stonksmith_workspace,
            f"{args.protocol}.db")
    stonksmith_logger.debug(f"DB Path: {db_path}")

    db_engine = create_db_engine(db_path)

    db = protocol_db_object(db_engine)

    if __name__ == "__main__":
        main()
