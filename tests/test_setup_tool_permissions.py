# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Every directory StonkSmith creates under its own state is owner-only.

The files were only half the problem. A directory mode is the only control that
reaches a file this tool did not write, and it does not write most of what sits
under ~/.stonksmith/playwright: Playwright saves the trace, Chromium populates the
profile, and the CDP profile is created by a command StonkSmith only prints. The
trace is a DOM recording of a signed-in brokerage session, complete with
screenshots; on the machine this was written on it was 30MB at 0644, reachable
only because that directory happened to be 0700 by accident.

Two things this file exists to pin, both of which the obvious implementation gets
wrong. mkdir(mode=...) is masked by the umask and does nothing at all when the
directory already exists -- so a create-time-only fix repairs no install that has
ever been run, which is every install. And setup_tool() had no in-process test at
all: its only exercise was a subprocess, which pytest-cov cannot see, so its body
sat at 17% while looking covered from the outside.

On the unconditional mode assertions, see the module docstring of
tests/test_written_files_are_owner_only.py.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import stonksmith.etc.tool_setup as tool_setup
from stonksmith.etc.permissions import OWNER_ONLY_DIR, OWNER_ONLY_FILE


class SetupToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        root: Path = Path(self._tmp.name) / ".stonksmith"
        self.root = root
        self.config = root / "stonksmith.conf"

        # A permissive umask would let mkdir(0o700) succeed while proving
        # nothing about the chmod, and a strict one would hide a missing chmod
        # behind the umask. Pin it, and put it back -- a leaked umask silently
        # changes the mode of every temp file every later test creates, and some
        # of those now assert modes.
        previous: int = os.umask(0o022)
        self.addCleanup(os.umask, previous)

        # tool_setup imports these names, so patching the names it holds is what
        # redirects it; patching etc.paths would be too late.
        for name, value in (
            ("stonksmith_path", root),
            ("config_path", self.config),
            ("managed_dirs", (root, root / "workspaces", Path(self._tmp.name) / "tmp")),
        ):
            patcher = patch.object(tool_setup, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        # initialize_db loads every shipped broker by path and builds five
        # databases. The database mode has its own test; this file is about the
        # directories and the config.
        db_patch = patch.object(tool_setup, "initialize_db")
        db_patch.start()
        self.addCleanup(db_patch.stop)

        tool_setup.setup_tool(logger=MagicMock())

    def _directories(self) -> list[Path]:
        return [self.root, *(p for p in sorted(self.root.iterdir()) if p.is_dir())]

    def test_every_directory_it_creates_is_owner_only(self) -> None:
        for path in self._directories():
            with self.subTest(directory=path.name):
                self.assertEqual(path.stat().st_mode & 0o777, OWNER_ONLY_DIR)

    def test_it_creates_the_directories_it_promises(self) -> None:
        # Without this the assertion above passes on a setup_tool() that created
        # nothing at all -- an empty iterdir() satisfies every mode check in it.
        found = {p.name for p in self._directories()}

        for expected in ("logs", "modules", "brokers", "workspaces", "playwright"):
            with self.subTest(directory=expected):
                self.assertIn(expected, found)

    def test_it_tightens_a_directory_that_already_exists(self) -> None:
        # The case mkdir(mode=...) cannot reach, and the only case anyone with
        # data on disk actually has. playwright/ is the one that matters: it
        # holds the traces and the Chrome profiles, and nothing else protects
        # them.
        loosened: Path = self.root / "playwright"
        loosened.chmod(mode=0o755)

        tool_setup.setup_tool(logger=MagicMock())

        self.assertEqual(loosened.stat().st_mode & 0o777, OWNER_ONLY_DIR)

    def test_the_config_it_copies_is_owner_only(self) -> None:
        # shutil.copy carries the source's mode across, and the shipped default
        # is 0644 in the wheel. The operator's copy fills in with a SnapTrade
        # client id, a pay grade and a service date.
        self.assertTrue(self.config.is_file(), "no config was copied")
        self.assertEqual(self.config.stat().st_mode & 0o777, OWNER_ONLY_FILE)

    def test_it_tightens_a_config_that_already_exists(self) -> None:
        self.config.chmod(mode=0o644)

        tool_setup.setup_tool(logger=MagicMock())

        self.assertEqual(self.config.stat().st_mode & 0o777, OWNER_ONLY_FILE)


if __name__ == "__main__":
    unittest.main()
