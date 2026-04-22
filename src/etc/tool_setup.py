"""
Setup tool
"""

import shutil
from pathlib import Path

from etc.logger import StonkSmithAdapter
from etc.paths import config_path, etc_path, stonksmith_path, tmp_path
from etc.stonksmithdb import initialize_db


def setup_tool(logger: StonkSmithAdapter) -> None:
    """
    Setup tool by creating necessary directories and files
    :param logger:
    :return:
    """

    if not tmp_path.exists():
        tmp_path.mkdir(parents=True, exist_ok=True)

    if not stonksmith_path.exists():
        logger.highlight(msg="[*] First time use detected. Generating directories...")
        stonksmith_path.mkdir(parents=True, exist_ok=True)

    folders = (
        "logs",
        "modules",
        "brokers",
        "workspaces",
        "playwright",
    )

    for folder in folders:
        folder_path: Path = stonksmith_path / folder
        if not folder_path.exists():
            logger.highlight(msg=f"[*] Creating missing folder: {folder}")
            folder_path.mkdir(parents=True, exist_ok=True)

    initialize_db(logger=logger)

    if not config_path.exists():
        logger.highlight(msg="[*] Copying default configuration file...")
        default_config: Path = etc_path / "stonksmith.conf"

        if default_config.exists():
            shutil.copy(src=str(object=default_config), dst=str(object=config_path))
        else:
            logger.fail(msg=f"[-] Could not find default config at {default_config}")
