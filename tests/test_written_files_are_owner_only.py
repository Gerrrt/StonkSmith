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

import contextlib
import logging
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import stonksmith.etc.browser_connection as browser_mod
import stonksmith.etc.config as etc_config
import stonksmith.helpers.sheets as sheets
from config_isolation import UserConfigMixin
from stonksmith.etc.browser_connection import BrowserConnection
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


class TraceAndProfileTests(_TempRoot):
    """The two artifacts StonkSmith does not write but does cause to exist."""

    def setUp(self) -> None:
        super().setUp()
        patcher = patch.object(browser_mod, "playwright_path", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _connection(self) -> BrowserConnection:
        connection = BrowserConnection.__new__(BrowserConnection)
        connection.logger = MagicMock()
        connection.context = MagicMock()
        connection.attached = True
        connection.tracing_started = True
        connection.trace_path = self.tmp / "Fidelity_trace.zip"
        connection.browser = None
        connection.page = None
        connection.playwright = None
        connection.args = Namespace(profile_dir=None)
        return connection

    def test_the_trace_is_owner_only(self) -> None:
        # screenshots=True and snapshots=True: a DOM recording of a signed-in
        # brokerage session, and the largest single file this tool writes.
        connection = self._connection()
        connection.context.tracing.stop.side_effect = lambda path: Path(
            path
        ).write_bytes(b"PK\x03\x04")

        with (
            patch.object(BrowserConnection, "save_response_log"),
            patch.object(BrowserConnection, "save_session"),
        ):
            connection.teardown()

        self.assertEqual(connection.trace_path.stat().st_mode & 0o777, OWNER_ONLY_FILE)

    def test_the_default_profile_directory_is_owner_only(self) -> None:
        connection = self._connection()
        profile: Path = self.tmp / "chrome-profile"
        profile.mkdir(mode=0o755)

        with (
            patch.object(BrowserConnection, "chrome_profile_dir", return_value=profile),
            contextlib.suppress(Exception),
        ):
            connection.start_chromium(headed=False, channel=None)

        self.assertEqual(profile.stat().st_mode & 0o777, OWNER_ONLY_DIR)

    def test_a_profile_directory_the_operator_named_is_left_alone(self) -> None:
        # --profile-dir can point at a real Chrome profile. Tightening that is a
        # change to state this tool did not create, cannot put back, and which
        # another process or another user may legitimately be reaching. This is
        # the test that stops the guard being "simplified" away.
        #
        # Its own temporary directory rather than a named one beside self.tmp:
        # it has to sit outside the patched playwright_path for the guard to be
        # exercised at all, and a fixed name there collides between xdist
        # workers and then races them on cleanup.
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        theirs: Path = Path(outside.name) / "their-chrome-profile"
        theirs.mkdir(mode=0o755)
        connection = self._connection()

        with (
            patch.object(BrowserConnection, "chrome_profile_dir", return_value=theirs),
            contextlib.suppress(Exception),
        ):
            connection.start_chromium(headed=False, channel=None)

        self.assertEqual(theirs.stat().st_mode & 0o777, 0o755)

    def test_a_profile_directory_reached_through_dot_dot_is_left_alone(self) -> None:
        # is_relative_to() reads path components and does not walk them, so
        # `<playwright_path>/../<name>` satisfies it while pointing somewhere
        # else entirely. Spelled the way an operator plausibly would: a profile
        # kept beside StonkSmith's own state rather than inside it.
        #
        # Both directories live inside this test's own temporary root, so the
        # traversal is real and there is still nothing shared between workers.
        nested: Path = self.tmp / "playwright"
        nested.mkdir()
        theirs: Path = self.tmp / "beside-it"
        theirs.mkdir(mode=0o755)

        escaped: Path = nested / ".." / theirs.name
        self.assertTrue(
            escaped.is_relative_to(nested),
            "the lexical check has to pass here, or this test proves nothing",
        )
        self.assertEqual(escaped.resolve(), theirs.resolve())

        connection = self._connection()

        with (
            patch.object(browser_mod, "playwright_path", nested),
            patch.object(BrowserConnection, "chrome_profile_dir", return_value=escaped),
            contextlib.suppress(Exception),
        ):
            connection.start_chromium(headed=False, channel=None)

        self.assertEqual(theirs.stat().st_mode & 0o777, 0o755)


class GoogleCredentialTests(_TempRoot):
    def _seed(self) -> None:
        self.tmp.chmod(mode=0o755)
        for name in ("authorized_user.json", "credentials.json"):
            path: Path = self.tmp / name
            path.write_text(data="{}", encoding="utf-8")
            path.chmod(mode=0o644)

    def test_opening_the_book_tightens_the_stored_credentials(self) -> None:
        # authorized_user.json is a refresh token for the operator's whole Drive,
        # renewable indefinitely. gspread writes it at umask, and it is the
        # highest-value secret on the machine.
        self._seed()

        with (
            patch.object(sheets, "GSPREAD_CONFIG_DIR", str(object=self.tmp)),
            patch("stonksmith.helpers.sheets.gspread.oauth", return_value=MagicMock()),
        ):
            sheets.open_spreadsheet()

        self.assertEqual(self.tmp.stat().st_mode & 0o777, OWNER_ONLY_DIR)
        for name in ("authorized_user.json", "credentials.json"):
            with self.subTest(credential=name):
                self.assertEqual(
                    (self.tmp / name).stat().st_mode & 0o777, OWNER_ONLY_FILE
                )

    def test_a_config_directory_that_is_not_there_is_not_created(self) -> None:
        # An install that has never authorized has no such directory, and making
        # one would be this tool inventing state in another library's namespace.
        absent: Path = self.tmp / "never-authorized"

        with (
            patch.object(sheets, "GSPREAD_CONFIG_DIR", str(object=absent)),
            patch("stonksmith.helpers.sheets.gspread.oauth", return_value=MagicMock()),
        ):
            sheets.open_spreadsheet()

        self.assertFalse(absent.exists())


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
