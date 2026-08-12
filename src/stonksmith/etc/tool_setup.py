"""
Setup tool
"""

import shutil
from pathlib import Path

from stonksmith.etc.logger import StonkSmithAdapter
from stonksmith.etc.paths import config_path, etc_path, managed_dirs, stonksmith_path
from stonksmith.etc.permissions import OWNER_ONLY_DIR, restrict, restrict_dir
from stonksmith.etc.stonksmithdb import initialize_db


def setup_tool(logger: StonkSmithAdapter) -> None:
    """
    Setup tool by creating necessary directories and files.

    This is the only place StonkSmith creates anything on disk. etc.paths names
    the locations but no longer creates them at import time.
    :param logger:
    :return:
    """

    if not stonksmith_path.exists():
        logger.highlight(msg="[*] First time use detected. Generating directories...")

    # Both halves are needed. mkdir(mode=) is masked by the umask, applies only
    # to the final component -- parents=True creates the rest at 0777 & ~umask --
    # and is a silent no-op under exist_ok=True. So a create-time fix alone
    # repairs no install that already exists, which is every install. The
    # restrict_dir() is what does that work, and main.py calls setup_tool() on
    # every invocation, so it is self-healing rather than one-shot.
    #
    # All of them, not a sensitive-only subset: brokers/ and modules/ hold
    # operator-written Python that this tool imports and executes, which is
    # exactly where a hardcoded API key ends up; logs/ holds the run log; and
    # tmp_path sits in a world-writable directory. A rule with exceptions gets
    # re-argued by whoever adds the next directory, and they are the person least
    # likely to be thinking about it.
    for directory in managed_dirs:
        directory.mkdir(mode=OWNER_ONLY_DIR, parents=True, exist_ok=True)
        restrict_dir(path=directory)

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
            folder_path.mkdir(mode=OWNER_ONLY_DIR, parents=True, exist_ok=True)

        # Outside the branch: playwright/ is the one that matters most and it
        # already exists on every install. It holds the Chrome profiles and the
        # Playwright traces, neither of which this tool writes -- so the
        # directory mode is the only control that reaches them.
        restrict_dir(path=folder_path)

    initialize_db(logger=logger)

    if not config_path.exists():
        logger.highlight(msg="[*] Copying default configuration file...")
        default_config: Path = etc_path / "stonksmith.conf"

        if default_config.exists():
            shutil.copy(src=str(object=default_config), dst=str(object=config_path))
        else:
            logger.fail(msg=f"[-] Could not find default config at {default_config}")

    # Outside the branch above, so an existing 0644 config is repaired rather
    # than left as whatever the install that created it happened to produce.
    #
    # shutil.copy carries the source's mode across, and the shipped default is
    # 0644 in the wheel -- a fact about how the package was built, not a decision
    # anyone made about the operator's file. The shipped one has only empty value
    # slots; theirs fills in with a SnapTrade client id, a pay grade and a
    # service date.
    if config_path.exists():
        restrict(path=config_path)
