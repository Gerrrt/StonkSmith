#!/usr/bin/env python3
"""
config.py: Module to control running configuration
"""

import configparser
import os
from os.path import join

from paths import data_path, stonksmith_path

stonksmith_default_config = configparser.ConfigParser()
stonksmith_default_config.read(join(data_path, "stonksmith.conf"))

stonksmith_config = configparser.ConfigParser()
stonksmith_config.read(os.path.join(stonksmith_path, "stonksmith.conf"))

if "stonksmith" not in stonksmith_config.sections():
    initial_run_setup()
    stonksmith_config.read(os.path.join(stonksmith_path, "stonksmith.conf"))

for section in stonksmith_default_config.sections():
    for options in stonksmith_default_config.options(section):
        if not stonksmith_config.has_option(section, option):
            stonksmith_logger.display(
                f"Adding missing option '{option}' in config section '"
                f"{section}' to stonksmith.conf"
            )
            stonksmith_config.set(
                section, option, stonksmith_default_config.get(section, option)
            )

            with (open(join(stonksmith_path, "stonksmith.conf"), "w") as
                  configuration:
                stonksmith_config.write(configuration)

stonksmith_workspace = stonksmith_config.get("stonksmith", "workspace",
                                             fallback="default")
pwned_label = stonksmith_config.get("stonksmith", "pwn3d_label",
                                    fallback="Pwn3d!")
audit_mode = stonksmith_config.get("stonksmith", "audit_mode", fallback=False)
config_log = stonksmith_config.getboolean("stonksmith", "log_mode",
                                          fallback=False)
