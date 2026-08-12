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

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import stonksmith.etc.config as etc_config
from config_isolation import UserConfigMixin
from stonksmith.etc.infrastructure import create_db_engine
from stonksmith.etc.logger import StonkSmithAdapter
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


class DatabaseFileTests(_TempRoot):
    def test_the_database_is_owner_only_from_the_first_connect(self) -> None:
        path: Path = self.tmp / "ally.db"
        engine = create_db_engine(db_path=path)
        # dispose() is not optional here: filterwarnings = ["error"] promotes the
        # ResourceWarning from an unclosed pool to a failure, raised during
        # finalisation with no test running to pin it on.
        self.addCleanup(engine.dispose)

        with engine.connect():
            pass

        self.assertEqual(path.stat().st_mode & 0o777, OWNER_ONLY_FILE)

    def test_a_database_an_older_stonksmith_wrote_is_tightened_on_open(self) -> None:
        # The case that matters and the one a create-time-only fix cannot reach:
        # every database that exists today was written before this and is 0644.
        path: Path = self.tmp / "legacy.db"
        first = create_db_engine(db_path=path)
        with first.connect():
            pass
        first.dispose()
        path.chmod(mode=0o644)

        second = create_db_engine(db_path=path)
        self.addCleanup(second.dispose)

        with second.connect():
            pass

        self.assertEqual(path.stat().st_mode & 0o777, OWNER_ONLY_FILE)


class RunLogTests(_TempRoot):
    def _add_handler(self, path: Path) -> None:
        adapter = StonkSmithAdapter(logger=logging.getLogger("stonksmith"))
        before: list[logging.Handler] = list(adapter.logger.handlers)
        self.addCleanup(setattr, adapter.logger, "handlers", before)

        adapter.add_file_log(log_file=path)

        # RotatingFileHandler holds the file open; filterwarnings = ["error"]
        # turns the ResourceWarning from leaving it that way into a failure.
        for handler in adapter.logger.handlers:
            if handler not in before:
                self.addCleanup(handler.close)

    def test_a_log_file_it_creates_is_owner_only(self) -> None:
        # Every line the run printed goes in here, which is every account name
        # and every balance.
        path: Path = self.tmp / "run.log"

        self._add_handler(path=path)

        self.assertEqual(path.stat().st_mode & 0o777, OWNER_ONLY_FILE)

    def test_a_log_file_the_operator_already_had_is_left_alone(self) -> None:
        # --log names a path they chose. One that already exists is theirs, and
        # may be a shared or appended log they set up deliberately.
        path: Path = self.tmp / "theirs.log"
        path.touch()
        path.chmod(mode=0o644)

        self._add_handler(path=path)

        self.assertEqual(path.stat().st_mode & 0o777, 0o644)


class ConfigFileTests(UserConfigMixin, unittest.TestCase):
    config_body = "[STONKSMITH]\nworkspace = mine\n"

    def test_backfilling_the_config_does_not_widen_it(self) -> None:
        # get_config() opens the file "w", which truncates in place and so keeps
        # the mode. That is an accident of how it happens to be written: a future
        # rewrite via tempfile-and-rename would hand the file back at umask, and
        # the protection would be lost without anyone editing a line about
        # permissions.
        path: Path = etc_config.user_cfg_path
        path.chmod(mode=OWNER_ONLY_FILE)

        etc_config.get_config()

        # Load-bearing: without it this passes on a get_config() that did
        # nothing at all, and the mode assertion below would mean nothing.
        self.assertIn("audit_mode", path.read_text(encoding="utf-8"))
        self.assertEqual(path.stat().st_mode & 0o777, OWNER_ONLY_FILE)


if __name__ == "__main__":
    unittest.main()
