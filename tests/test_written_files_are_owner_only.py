# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Nothing StonkSmith writes is readable by anyone but its owner.

The modes were never set. The account databases, the config, the run log and the
Playwright trace were all born at the process umask -- commonly 0644 -- while the
page captures beside them were 0600, because the only chmod in the codebase lived
in ``etc.browser_connection`` and only captures could reach it. A database holds
every account number, balance and transaction the tool has ever recorded, which is
the thing the keyring was protecting access to.

This file covers the helper itself and the files. Directories are
``tests/test_setup_tool_permissions.py``.

The assertions are unconditional. ``os.name == "nt"`` in etc.paths says Windows is
a supported *runtime*, and ``permissions.restrict`` is best-effort precisely so it
stays one -- but no CI job has ever run on Windows, and a skipUnless here would be
an unexercised branch claiming otherwise. On Windows chmod(0o600) toggles the
read-only bit and st_mode comes back 0o666, so these would fail rather than error,
which is the right way round for a thing nobody is watching. If a Windows job is
ever added, this file is where it lands first.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stonksmith.etc.permissions import (
    OWNER_ONLY_DIR,
    OWNER_ONLY_FILE,
    restrict,
    restrict_dir,
)


class _TempRoot(unittest.TestCase):
    """A throwaway directory for one test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)


class TheHelperTests(_TempRoot):
    def test_a_file_becomes_owner_only(self) -> None:
        target: Path = self.tmp / "capture.html"
        target.write_text(data="<html/>", encoding="utf-8")
        target.chmod(mode=0o644)

        restrict(path=target)

        self.assertEqual(target.stat().st_mode & 0o777, OWNER_ONLY_FILE)

    def test_a_directory_becomes_owner_only(self) -> None:
        # 0700 rather than 0600: clearing the execute bit on a directory makes it
        # untraversable by its owner, which would break the tool rather than
        # protect anything.
        target: Path = self.tmp / "playwright"
        target.mkdir(mode=0o755)

        restrict_dir(path=target)

        self.assertEqual(target.stat().st_mode & 0o777, OWNER_ONLY_DIR)

    def test_a_filesystem_that_refuses_chmod_does_not_fail_the_run(self) -> None:
        # The whole reason both functions suppress OSError. A network mount or a
        # container bind that has no POSIX modes must not turn "the balance was
        # written down" into a failed run.
        target: Path = self.tmp / "capture.html"
        target.write_text(data="<html/>", encoding="utf-8")

        with patch.object(Path, "chmod", side_effect=PermissionError("read-only")):
            restrict(path=target)
            restrict_dir(path=self.tmp)


if __name__ == "__main__":
    unittest.main()
