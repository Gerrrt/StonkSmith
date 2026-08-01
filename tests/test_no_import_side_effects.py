"""Importing StonkSmith must not touch the filesystem.

etc.paths used to mkdir into $HOME at import, and etc.config used to read,
merge, and rewrite ~/.stonksmith/stonksmith.conf at import. That made merely
importing the package -- in a test, a REPL, or an editor -- mutate the user's
real home directory. setup_tool() is now the only thing that creates anything.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

IMPORT_EVERYTHING = (
    "import etc.paths, etc.config, etc.connection, etc.stonksmithdb, "
    "loaders.moduleloader, loaders.brokerloader, main; print('ok')"
)


class ImportSideEffectTests(unittest.TestCase):
    def _run(self, code: str, home: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, HOME=home, PYTHONPATH=str(REPO / "src"))
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
            "from etc.config import get_workspace, get_audit_mode; "
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

    def test_setup_tool_still_provisions_everything(self) -> None:
        code = (
            "from etc.logger import stonksmith_logger; "
            "from etc.tool_setup import setup_tool; "
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
