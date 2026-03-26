#!/usr/bin/env python3
"""
Cli module for arguments
"""

import argparse
import importlib.metadata
import sys
from argparse import RawTextHelpFormatter

from helpers import highlight


def gen_cli_args():
    version = importlib.metadata.version("stonksmith")
    codename = "Forrest Gump"

    parser = argparse.ArgumentParser(
        description=rf"""
    ==================================================
    __ _               _     __           _ _   _      
    / _\ |_ ___  _ __ | | __/ _\_ __ ___ (_) |_| |__  
    \ \| __/ _ \| '_ \| |/ /\ \| '_ ` _ \| | __| '__  
    _\ \ || (_) | | | |   < _\ \ | | | | | | |_| | | |
    \__/\__\___/|_| |_|_|\_\___/_| |_| |_|_|\__|_| |_|
    
    ==================================================
            Aggregate everything with one tool
        Great tools are inspired by great memes
                    Written by: @Gerrrt
    
    {highlight('Version', 'red')} : {highlight(version)}
    {highlight('Codename', 'red')}: {highlight(codename)}
""",
        formatter_class=RawTextHelpFormatter,
    )

    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")

    parser.add_argument(
        "--debug", action="store_true", help="Enable debug level information"
    )

    parser.add_argument(
        "--version", action="store_true", help="Display StonkSmith version"
    )

    module_parser = argparse.ArgumentParser(add_help=False)
    group = module_parser.add_mutually_exclusive_group()
    group.add_argument(
        "-M",
        "--module",
        action="append",
        metavar="MODULE",
        help="Module Name",
    )

    module_parser.add_argument(
        "-o",
        metavar="MODULE_OPTION",
        nargs="+",
        default=[],
        dest="module_option",
        help="Module Options",
    )

    module_parser.add_argument(
        "-L",
        "--list-modules",
        action="store_true",
        help="List available modules",
    )

    module_parser.add_argument(
        "--options",
        dest="show_module_options",
        action="store_true",
        help="Display module options",
    )

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    if args.version:
        print(f"{version} - {codename}")
        sys.exit(1)

    return args
