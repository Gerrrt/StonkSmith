#!/usr/bin/env python3

import logging

from etc import config_log, gen_cli_args, setup_tool, stonksmith_logger


def main():
    setup_tool(stonksmith_logger)
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

    if __name__ == "__main__":
        main()
