# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""The refusal, run as the command line runs it.

Everything else covering --from-prices drives AllyModule directly with a
MagicMock connection, which proves the module refuses but says nothing about
whether a real invocation reaches the module at all. The claim that matters
here is a negative -- that a price run opens no browser -- and a fake
connection cannot make it, because a MagicMock has a `page` whether or not
Playwright was ever asked for one.

So this runs the console entry point end to end against a real empty database
under a throwaway home, and reads the evidence off the filesystem afterwards.
Two things it checks are not assertions about text:

- ~/.stonksmith/playwright is left empty. First-run setup creates the
  directory, so its existence proves nothing -- but BrowserConnection writes
  Ally.json into it as soon as a session exists, and a run that never started
  one leaves nothing behind. That file is the difference between the two
  branches, on disk.
- accounts and account_snapshots are still empty. A refusal that had already
  written a row would be a worse failure than the invented number this guards
  against, and `saved == []` against a fake database cannot see it.

docs/live-verification.md, Ally step 6, records the run this automates.
"""

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from home_isolation import isolated_home_env

REPO = Path(__file__).resolve().parents[1]

#: Quoted verbatim in docs/live-verification.md and in the README. Both lines
#: are fixed strings; step 6's other three are templates, and pinning a format
#: string against a rendered line is the kind of brittle guard that gets
#: deleted the first time a label changes.
NO_SIGN_IN = "Valuing from published prices; no sign-in needed."
REFUSAL = (
    "No holdings on record to value. Run with --manual-login once so a "
    "signed-in run can record the units."
)

#: Runs the entry point the `stonksmith` console script points at.
INVOKE = (
    "import sys; "
    "sys.argv = ['stonksmith', 'ally', '-M', 'ally', '--from-prices']; "
    "from main import cli_entry; sys.exit(cli_entry())"
)


class TheRefusalOnTheCommandLine(unittest.TestCase):
    #: One invocation for the whole class. The run is read four ways and
    #: changes nothing between them, so per-test setup would be four identical
    #: subprocesses and four first-run database initialisations.
    home: Path
    result: subprocess.CompletedProcess
    said: str

    @classmethod
    def setUpClass(cls) -> None:
        home_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(home_dir.cleanup)
        cls.home = Path(home_dir.name)

        env = isolated_home_env(
            home=str(object=cls.home),
            PYTHONPATH=str(object=REPO / "src"),
            # The same workaround .github/workflows/ci.yml sets: keyring's
            # import-time backend probe can otherwise pick something
            # interactive on a headless runner.
            PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
            COLUMNS="200",
        )

        cls.result = subprocess.run(
            [sys.executable, "-c", INVOKE],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO,
        )

        # Rich renders to a non-TTY here and re-wraps regardless of COLUMNS, so
        # a message can arrive split across lines. Where it wraps is not a fact
        # about the message -- tests/test_live_verification_tally.py collapses
        # whitespace for the same reason.
        cls.said = " ".join((cls.result.stdout + cls.result.stderr).split())

    def test_it_refuses_rather_than_valuing_nothing(self) -> None:
        self.assertIn(REFUSAL, self.said, self.result.stderr)
        self.assertEqual(self.result.returncode, 1, self.said)

    def test_it_gets_as_far_as_the_price_branch(self) -> None:
        """Otherwise the refusal could be some earlier failure wearing its coat."""

        self.assertIn(NO_SIGN_IN, self.said, self.result.stderr)

    def test_no_browser_session_is_left_behind(self) -> None:
        playwright = self.home / ".stonksmith" / "playwright"

        self.assertTrue(playwright.is_dir(), "first-run setup should create it")
        self.assertEqual(
            sorted(p.name for p in playwright.iterdir()),
            [],
            "a price run must not start a browser session",
        )

    def test_it_writes_no_rows_while_refusing(self) -> None:
        db = self.home / ".stonksmith" / "workspaces" / "default" / "ally.db"

        self.assertTrue(db.is_file(), self.said)

        with sqlite3.connect(database=db) as conn:
            counts = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("accounts", "account_snapshots", "holdings")
            }

        self.assertEqual(counts, {"accounts": 0, "account_snapshots": 0, "holdings": 0})


if __name__ == "__main__":
    unittest.main()
