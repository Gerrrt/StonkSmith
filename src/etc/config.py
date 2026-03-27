#!/usr/bin/env python3
"""
config.py: Module to control running configuration
"""

import configparser
import os
from ast import literal_eval
from os.path import join

from etc.logger import stonksmith_logger
from etc.paths import etc_path, stonksmith_path
from etc.tool_setup import setup_tool

stonksmith_default_config = configparser.ConfigParser()
stonksmith_default_config.read(join(etc_path, "stonksmith.conf"))

stonksmith_config = configparser.ConfigParser()
stonksmith_config.read(os.path.join(stonksmith_path, "stonksmith.conf"))

if "stonksmith" not in stonksmith_config.sections():
    setup_tool()
    stonksmith_config.read(os.path.join(stonksmith_path, "stonksmith.conf"))

for section in stonksmith_default_config.sections():
    for option in stonksmith_default_config.options(section):
        if not stonksmith_config.has_option(section, option):
            stonksmith_logger.display(
                f"Adding missing option '{option}' in config section"
                f"{section}' to stonksmith.conf"
            )
            stonksmith_config.set(
                section, option, stonksmith_default_config.get(section, option)
            )

            with open(join(stonksmith_path, "stonksmith.conf"), "w") as configuration:
                stonksmith_config.write(configuration)

stonksmith_workspace = stonksmith_config.get(
    "STONKSMITH", "workspace", fallback="default"
)
pwned_label = stonksmith_config.get("STONKSMITH", "pwn3d_label", fallback="Pwn3d!")
audit_mode = stonksmith_config.get("STONKSMITH", "audit_mode", fallback=False)
reveal_chars_of_pwd = int(
    stonksmith_config.get("STONKSMITH", "reveal_chars_of_pwd", fallback=0)
)
config_log = stonksmith_config.getboolean("STONKSMITH", "log_mode", fallback=False)
ignore_opsec = stonksmith_config.getboolean(
    "STONKSMITH", "ignore_opsec", fallback=False
)
host_info_colors = literal_eval(
    stonksmith_config.get(
        "STONKSMITH", "host_info_colors", fallback=["green", "red", "yellow", "cyan"]
    )
)

if len(host_info_colors) != 4:
    stonksmith_logger.error(
        "Config option host_info_colors must have 4 values. Using default values."
    )
    host_info_colors = stonksmith_default_config.get("STONKSMITH", "host_info_colors")


def process_secret(text):
    hidden = text[:reveal_chars_of_pwd]
    return text if not audit_mode else hidden + audit_mode * 8
