# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""The scrub that reaches a database which has already migrated.

``migrate_plaintext_secrets`` vacuums when it moves a secret, and it moves one
exactly once. So the automatic path cannot reach the databases that have the
problem *now* -- a workspace migrated before that VACUUM existed will never
satisfy the guard again, and is precisely the one still carrying cleared
plaintext in freed pages. This command is the only thing that reaches it.

The size of the fixture is not arbitrary. Whether a cleared password survives is
a function of page layout: with one credential SQLite rewrites the page in place
and the bytes go with it, so a one-row fixture would assert something already
true and pass with the VACUUM reverted. See CREDENTIALS_LEFT_BEHIND below.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stonksmith.etc.stonksmithdb import StonkSmithDBMenu

#: Enough credentials that the cleared plaintext is reliably left behind. One
#: row survives 0 times in 15; ten survives 15 times in 15. Measured before this
#: file existed, because the alternative is a test that proves nothing.
CREDENTIALS_LEFT_BEHIND = 10

PRE_KEYRING = """
CREATE TABLE credentials (
    id INTEGER PRIMARY KEY,
    username TEXT,
    password TEXT,
    type TEXT,
    pillaged_from TEXT
);
"""


class VacuumCommandTests(unittest.TestCase):
    """What the command does to a workspace, and what it does when it cannot."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.workspace = self.root / "default"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self._dir.cleanup()

    def leave_plaintext(self, name: str = "broker.db") -> Path:
        """A database whose passwords were cleared without a rebuild."""

        path: Path = self.workspace / name
        con = sqlite3.connect(path)
        try:
            con.executescript(PRE_KEYRING)
            con.executemany(
                "INSERT INTO credentials (username, password, type, pillaged_from)"
                " VALUES (?, 'hunter2', 'plaintext', 'manual')",
                [(f"someone{i}",) for i in range(CREDENTIALS_LEFT_BEHIND)],
            )
            con.commit()
            # The pre-VACUUM migration, reproduced: one UPDATE per row, which is
            # what leaves the old cell behind in the page.
            for (cred_id,) in con.execute("SELECT id FROM credentials").fetchall():
                con.execute(
                    "UPDATE credentials SET password = NULL WHERE id = ?", (cred_id,)
                )
            con.commit()
        finally:
            con.close()

        return path

    def run_vacuum(self) -> tuple[bool, str]:
        shell = StonkSmithDBMenu.__new__(StonkSmithDBMenu)
        shell.workspace = "default"
        shell.failed = False

        printed: list[str] = []

        with (
            patch("stonksmith.etc.stonksmithdb.workspace_dir", self.root),
            patch(
                "builtins.print",
                side_effect=lambda *a: printed.append(" ".join(map(str, a))),
            ),
        ):
            shell.do_vacuum("")

        return shell.failed, "\n".join(printed)

    def test_the_fixture_really_does_leave_the_plaintext_behind(self) -> None:
        """The premise, asserted rather than assumed.

        Every other test in this file is meaningless if clearing the column
        already removed the bytes -- the VACUUM would then be removing nothing
        and its test would pass either way. This is the row that says the
        problem exists at this fixture size, and it is the one to look at first
        if a SQLite upgrade ever makes the rest of the file go quiet.
        """

        path: Path = self.leave_plaintext()

        self.assertIn(b"hunter2", path.read_bytes())

    def test_the_plaintext_is_gone_afterwards(self) -> None:
        path: Path = self.leave_plaintext()

        failed, _ = self.run_vacuum()

        self.assertFalse(failed)
        self.assertNotIn(b"hunter2", path.read_bytes())

    def test_every_database_in_the_workspace_is_reached(self) -> None:
        """Not a named one. An operator running this does not know which file
        the plaintext is in, and making them guess is how half a workspace gets
        done."""

        first: Path = self.leave_plaintext(name="ally.db")
        second: Path = self.leave_plaintext(name="tsp.db")

        self.run_vacuum()

        self.assertNotIn(b"hunter2", first.read_bytes())
        self.assertNotIn(b"hunter2", second.read_bytes())

    def test_a_database_that_cannot_be_vacuumed_fails_the_run(self) -> None:
        """A scrub that skipped the file and exited 0 would be read downstream
        as a workspace that has been scrubbed."""

        (self.workspace / "broken.db").write_bytes(b"this is not a database")

        failed, printed = self.run_vacuum()

        self.assertTrue(failed, "a database that could not be vacuumed exited 0")
        self.assertIn("broken.db", printed)

    def test_one_bad_database_does_not_strand_the_others(self) -> None:
        (self.workspace / "broken.db").write_bytes(b"this is not a database")
        good: Path = self.leave_plaintext(name="zzz.db")

        failed, _ = self.run_vacuum()

        self.assertTrue(failed)
        self.assertNotIn(
            b"hunter2", good.read_bytes(), "a bad database stopped the sweep"
        )

    def test_the_shell_names_the_command(self) -> None:
        """A command the shell can run is a command the shell names.

        tests/test_shell_advertises_what_it_runs.py exists because `delete
        account` shipped working and invisible -- reachable for anyone who
        already knew it was there, which is nobody. That file derives its check
        from DELETERS, which covers the broker sub-shells; the top-level intro
        is a hand-written string with nothing deriving from it, so a command
        added here and not there repeats the same defect one level up.
        """

        self.assertIn("vacuum", StonkSmithDBMenu.intro)

    def test_an_empty_workspace_says_so_and_does_not_fail(self) -> None:
        failed, printed = self.run_vacuum()

        self.assertFalse(failed, "nothing to do is not a failure")
        self.assertIn("No databases", printed)


if __name__ == "__main__":
    unittest.main()
