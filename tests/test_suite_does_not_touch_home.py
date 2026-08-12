"""Running the test suite must leave the developer's own state alone.

test_no_import_side_effects.py covers *importing* StonkSmith. That is not the
whole story: get_config() backfills options missing from the shipped defaults
and writes the merged result back whenever the user file already exists, so a
test that merely *calls* it -- directly, or through process_secret() or
get_workspace() -- rewrites the real ~/.stonksmith/stonksmith.conf. Adding a
section to src/stonksmith/etc/stonksmith.conf then shows up as an unexplained
diff in the developer's home directory. Saving a browser session is the same story: it
mkdirs ~/.stonksmith/playwright before writing.

This runs the rest of the suite against a throwaway $HOME and asserts that
everything StonkSmith owns there comes back byte for byte identical.

Only StonkSmith's own state is compared, not all of $HOME: an unrelated tool in
the subprocess (pip, uv, a keyring backend) may legitimately warm a cache there,
and a test that fails on that would be noise. Every home-resident path in
etc.paths is covered -- ~/.stonksmith and everything under it, plus ~/token.json
and ~/credentials.json. Paths outside the home directory, etc.paths.tmp_path in
particular, are out of scope here: a scratch directory under /tmp is not state
the developer would miss.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from home_isolation import isolated_home_env

REPO = Path(__file__).resolve().parents[1]
SELF = Path(__file__)

# A config missing almost everything the shipped defaults carry, so any
# unisolated get_config() call has plenty to backfill -- and rewrites the file.
SEED_CONFIG = "[STONKSMITH]\nworkspace = default\n"

# etc.paths puts the rest under ~/.stonksmith; these two sit in $HOME itself.
HOME_LEVEL_PATHS = ("token.json", "credentials.json")


def _snapshot(root: Path) -> dict[str, tuple[bytes | None, int]]:
    """
    Every path under ``root``, mapped to its contents and its mode.

    The mode is here because contents alone missed a real escape: a test that
    chmods a file changes no bytes, so a snapshot of contents compares equal
    while the permissions on somebody's credentials have been rewritten
    underneath it.
    :param root: Directory to walk; need not exist
    :return: Relative path string -> (contents or None for a directory, mode)
    """

    if not root.exists():
        return {}

    # rglob() yields the children and never the root, so the watched directory's
    # own mode was outside this. That is the one restrict_dir() actually changes
    # -- _restrict_google_credentials() chmods the gspread directory itself --
    # and it would go unseen whenever the files beneath it were already correct.
    return {
        ".": (None, root.stat().st_mode & 0o777),
        **{
            str(path.relative_to(root)): (
                None if path.is_dir() else path.read_bytes(),
                path.stat().st_mode & 0o777,
            )
            for path in sorted(root.rglob(pattern="*"))
        },
    }


class SuiteLeavesHomeAloneTests(unittest.TestCase):
    def test_running_the_suite_does_not_modify_stonksmith_state(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            state = Path(home) / ".stonksmith"
            config_file = state / "stonksmith.conf"
            config_file.parent.mkdir()
            config_file.write_text(data=SEED_CONFIG)

            # gspread keeps a Google refresh token here, outside ~/.stonksmith
            # and so outside everything this test used to watch. Seeded at 0644
            # because the escape being guarded against is a chmod: helpers.sheets
            # tightens these on every open_spreadsheet(), and a test that patches
            # only gspread.oauth reaches the real ones.
            gspread_dir = Path(home) / ".config" / "gspread"
            gspread_dir.mkdir(parents=True)
            for name in ("authorized_user.json", "credentials.json"):
                token = gspread_dir / name
                token.write_text(data="{}")
                token.chmod(mode=0o644)

            before = _snapshot(root=state)
            before_gspread = _snapshot(root=gspread_dir)

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
                env=isolated_home_env(home=home),
                capture_output=True,
                text=True,
                check=False,
                cwd=REPO,
            )

            after = _snapshot(root=state)
            after_gspread = _snapshot(root=gspread_dir)

            # First, not last. A suite that never ran proves nothing about what
            # it touches -- and a nested run that died half way through leaves
            # state that trips the assertions below, so checking it afterwards
            # reports a phantom escape and buries the actual failure. This is
            # the only assertion here whose message wants the nested output;
            # the rest name a specific file and a specific remedy, and the
            # nested run is a page of dots when they fire.
            self.assertEqual(
                result.returncode, 0, result.stdout[-4000:] + result.stderr[-4000:]
            )

            self.assertEqual(
                after_gspread,
                before_gspread,
                "the suite reached ~/.config/gspread; a test that calls "
                "open_spreadsheet() needs GspreadConfigMixin, because patching "
                "gspread.oauth alone still lets _restrict_google_credentials() "
                "chmod the real token",
            )

            contents, _mode = after.get("stonksmith.conf", (None, 0))

            self.assertEqual(
                contents,
                SEED_CONFIG.encode(),
                "the suite rewrote ~/.stonksmith/stonksmith.conf; isolate the "
                "test that reaches get_config() -- patch "
                "stonksmith.etc.config.user_cfg_path and call "
                "stonksmith.etc.config.reset_config_cache(), which drops the "
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


if __name__ == "__main__":
    unittest.main()
