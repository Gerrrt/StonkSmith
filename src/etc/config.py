"""
config.py: Module to control running configuration
"""

import ast
import configparser
from pathlib import Path

from etc.logger import stonksmith_logger
from etc.paths import etc_path, stonksmith_path
from etc.tool_setup import setup_tool

default_cfg_path: Path = etc_path / "stonksmith.conf"
user_cfg_path: Path = stonksmith_path / "stonksmith.conf"

stonksmith_default_config = configparser.ConfigParser()
stonksmith_default_config.read(filenames=default_cfg_path)

stonksmith_config = configparser.ConfigParser()
stonksmith_config.read(filenames=user_cfg_path)

if "STONKSMITH" not in stonksmith_config.sections():
    setup_tool(logger=stonksmith_logger)
    stonksmith_config.read(filenames=user_cfg_path)

config_was_updated = False
for section in stonksmith_default_config.sections():
    if not stonksmith_config.has_section(section=section):
        stonksmith_config.add_section(section=section)
        config_was_updated: bool = True

    for option in stonksmith_default_config.options(section=section):
        if not stonksmith_config.has_option(section=section, option=option):
            stonksmith_logger.highlight(
                msg=f"Adding missing option '{option}' to {user_cfg_path}"
            )
            val: str = stonksmith_default_config.get(section=section, option=option)
            stonksmith_config.set(section=section, option=option, value=val)
            config_was_updated: bool = True

if config_was_updated:
    with open(file=user_cfg_path, mode="w") as f:
        stonksmith_config.write(fp=f)

stonksmith_workspace: str = stonksmith_config.get(
    section="STONKSMITH", option="workspace", fallback="default"
)

audit_mode: str | bool = stonksmith_config.get(
    section="STONKSMITH", option="audit_mode", fallback=False
)

reveal_chars_of_pwd: str | bool = stonksmith_config.get(
    section="STONKSMITH", option="reveal_chars_of_pwd", fallback=False
)

config_log: str | bool = stonksmith_config.get(
    section="STONKSMITH", option="log_mode", fallback=False
)

try:
    host_info_colors: list[str] = ast.literal_eval(
        node_or_string=stonksmith_config.get(
            section="STONKSMITH",
            option="host_info_colors",
            fallback="['green', 'red', 'yellow', 'cyan']",
        )
    )

except (ValueError, SyntaxError):
    host_info_colors: list[str] = ["green", "red", "yellow", "cyan"]

if len(host_info_colors) != 4:
    stonksmith_logger.error(msg="host_info_colors must have 4 values. Defaulting")
    host_info_colors: list[str] = ["green", "red", "yellow", "cyan"]


def process_secret(text: str) -> str:
    """
    Masks password based on audit_mode and reveal settings.
    :param text:
    :type text:
    :return:
    :rtype:
    """

    if not audit_mode:
        return text

    visible: str = text[:reveal_chars_of_pwd]
    mask: str = "*" * 8
    return f"{visible}{mask}"
