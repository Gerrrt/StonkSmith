#!/usr/bin/env python3

import shutil
from os import mkdir
from os.path import exists, join

from etc.logger import stonksmith_logger
from etc.paths import config_path, data_path, stonksmith_path, tmp_path


def setup_tool(logger=stonksmith_logger):
    if not exists(tmp_path):
        mkdir(tmp_path)

    if not exists(stonksmith_path):
        logger.display("First time use detected")
        logger.display("Creating home directory structure")
        mkdir(stonksmith_path)

    folders = (
        "logs",
        "modules",
        "protocols",
        "workspaces",
        "obfuscated_scripts",
        "screenshots",
    )

    for folder in folders:
        if not exists(join(stonksmith_path, folder)):
            logger.display(f"Creating missing folder {folder}")
            mkdir(join(stonksmith_path, folder))

    initialize_db(logger)

    if not exists(config_path):
        logger.display("Copying default configuration file")
        default_path = join(data_path, "stonksmith.conf")
        shutil.copy(default_path, stonksmith_path)
