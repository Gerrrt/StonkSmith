"""Importing StonkSmith must not touch the filesystem.

etc.paths used to mkdir into $HOME at import, and etc.config used to read,
merge, and rewrite ~/.stonksmith/stonksmith.conf at import. That made merely
importing the package -- in a test, a REPL, or an editor -- mutate the user's
real home directory. setup_tool() is now the only thing that creates anything.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from home_isolation import isolated_home_env

REPO = Path(__file__).resolve().parents[1]

IMPORT_EVERYTHING = (
    "import stonksmith.etc.paths, stonksmith.etc.config, "
    "stonksmith.etc.connection, stonksmith.etc.stonksmithdb, "
    # Imported by all five modules on every run, and it pulls gspread and
    # google-auth in behind it. Neither may reach for a token at import.
    "stonksmith.etc.portfolio, stonksmith.etc.portfolio_sheet, "
    "stonksmith.loaders.moduleloader, stonksmith.loaders.brokerloader, "
    "stonksmith.main; print('ok')"
)


class ImportSideEffectTests(unittest.TestCase):
    def _run(self, code: str, home: str) -> subprocess.CompletedProcess:
        env = isolated_home_env(home=home, PYTHONPATH=str(object=REPO / "src"))
        return subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO,
        )

    def test_importing_the_package_creates_nothing_in_home(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            result = self._run(IMPORT_EVERYTHING, home)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                sorted(p.name for p in Path(home).iterdir()),
                [],
                "importing StonkSmith must not create anything under $HOME",
            )

    def test_reading_config_does_not_create_the_config_file(self) -> None:
        # get_config() falls back to the packaged defaults when the user file is
        # absent; it must not be the thing that writes it.
        code = (
            "from stonksmith.etc.config import get_workspace, get_audit_mode; "
            "print(get_workspace(), get_audit_mode())"
        )

        with tempfile.TemporaryDirectory() as home:
            result = self._run(code, home)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("default", result.stdout)
            self.assertFalse(
                (Path(home) / ".stonksmith").exists(),
                "reading config must not create ~/.stonksmith",
            )

    def test_fresh_install_does_not_announce_a_write_it_will_not_do(self) -> None:
        # get_config() backfills missing options in memory, but only writes (and
        # only reports) when the file already exists. Logging on a fresh install
        # claimed a write that never happened.
        code = "from stonksmith.etc.config import get_workspace; print(get_workspace())"

        with tempfile.TemporaryDirectory() as home:
            result = self._run(code, home)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Adding missing option", result.stdout + result.stderr)

    def test_existing_config_is_backfilled_and_reported(self) -> None:
        code = "from stonksmith.etc.config import get_workspace; print(get_workspace())"

        with tempfile.TemporaryDirectory() as home:
            config_dir = Path(home) / ".stonksmith"
            config_dir.mkdir()
            config_file = config_dir / "stonksmith.conf"
            config_file.write_text("[STONKSMITH]\nworkspace = mine\n")

            result = self._run(code, home)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("mine", result.stdout)
            self.assertIn("Adding missing option", result.stdout + result.stderr)
            self.assertIn("audit_mode", config_file.read_text())

    def test_setup_tool_still_provisions_everything(self) -> None:
        code = (
            "from stonksmith.etc.logger import stonksmith_logger; "
            "from stonksmith.etc.tool_setup import setup_tool; "
            "setup_tool(logger=stonksmith_logger); print('ok')"
        )

        with tempfile.TemporaryDirectory() as home:
            result = self._run(code, home)

            self.assertEqual(result.returncode, 0, result.stderr)

            root = Path(home) / ".stonksmith"
            self.assertTrue(root.is_dir())
            for expected in ("logs", "modules", "brokers", "workspaces", "playwright"):
                self.assertTrue((root / expected).is_dir(), f"missing {expected}")
            self.assertTrue((root / "stonksmith.conf").is_file())


if __name__ == "__main__":
    unittest.main()
