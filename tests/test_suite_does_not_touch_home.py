"""Running the test suite must leave the developer's own state alone.

test_no_import_side_effects.py covers *importing* StonkSmith. That is not the
whole story: get_config() backfills options missing from the shipped defaults
and writes the merged result back whenever the user file already exists, so a
test that merely *calls* it -- directly, or through process_secret() or
get_workspace() -- rewrites the real ~/.stonksmith/stonksmith.conf. Adding a
section to src/etc/stonksmith.conf then shows up as an unexplained diff in the
developer's home directory. Saving a browser session is the same story: it
mkdirs ~/.stonksmith/playwright before writing.

This runs the rest of the suite against a throwaway $HOME and asserts that
everything StonkSmith owns there comes back byte for byte identical.

Only StonkSmith's own state is compared, not all of $HOME: an unrelated tool in
the subprocess (pip, uv, a keyring backend) may legitimately warm a cache there,
and a test that fails on that would be noise. Every path StonkSmith writes to is
listed in etc.paths, and all of them are checked here.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SELF = Path(__file__)

# A config missing almost everything the shipped defaults carry, so any
# unisolated get_config() call has plenty to backfill -- and rewrites the file.
SEED_CONFIG = "[STONKSMITH]\nworkspace = default\n"

# etc.paths puts the rest under ~/.stonksmith; these two sit in $HOME itself.
HOME_LEVEL_PATHS = ("token.json", "credentials.json")


def _snapshot(root: Path) -> dict[str, bytes | None]:
    """
    Every path under ``root``, mapped to file contents (None for directories).
    :param root: Directory to walk; need not exist
    :return: Relative path string -> contents
    """

    if not root.exists():
        return {}

    return {
        str(path.relative_to(root)): None if path.is_dir() else path.read_bytes()
        for path in sorted(root.rglob(pattern="*"))
    }


class SuiteLeavesHomeAloneTests(unittest.TestCase):
    def test_running_the_suite_does_not_modify_stonksmith_state(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            state = Path(home) / ".stonksmith"
            config_file = state / "stonksmith.conf"
            config_file.parent.mkdir()
            config_file.write_text(data=SEED_CONFIG)

            before = _snapshot(root=state)

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    # Without this the nested run recurses into this test.
                    f"--ignore={SELF}",
                    # Keep the nested run from writing over our own cache.
                    "-p",
                    "no:cacheprovider",
                    str(REPO / "tests"),
                ],
                env=dict(os.environ, HOME=home),
                capture_output=True,
                text=True,
                check=False,
                cwd=REPO,
            )

            after = _snapshot(root=state)

            self.assertEqual(
                after.get("stonksmith.conf"),
                SEED_CONFIG.encode(),
                "the suite rewrote ~/.stonksmith/stonksmith.conf; isolate the "
                "test that reaches get_config() -- patch etc.config.user_cfg_path "
                "and call etc.config.reset_config_cache(), which drops the "
                "process-global cache the patch is otherwise powerless against",
            )
            self.assertEqual(
                sorted(after),
                sorted(before),
                "the suite created something under ~/.stonksmith",
            )
            self.assertEqual(after, before, "the suite changed a file it does not own")

            for name in HOME_LEVEL_PATHS:
                self.assertFalse(
                    (Path(home) / name).exists(), f"the suite created ~/{name}"
                )

            # A suite that never ran proves nothing about what it touches.
            self.assertEqual(
                result.returncode, 0, result.stdout[-4000:] + result.stderr[-4000:]
            )


if __name__ == "__main__":
    unittest.main()
