# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Point helpers.sheets at a throwaway gspread config directory.

Not named test_*: this is a helper, and pytest would collect it.

Any test that reaches ``open_spreadsheet`` needs this, not only the ones about
permissions. It calls ``_restrict_google_credentials()``, which reads the
module-level ``GSPREAD_CONFIG_DIR`` and chmods what it finds -- and unpatched
that is the developer's real ``~/.config/gspread``, holding a live Google refresh
token for their whole Drive.

That is exactly what happened: patching ``gspread.oauth`` is enough to keep a
test off the network, so two files did only that, and running them tightened the
real directory. Only ever tightening, so nothing was harmed -- but a suite that
reaches outside its temporary directories at all is one edit away from a change
that does harm, and ``tests/test_suite_does_not_touch_home.py`` did not catch it
because ``~/.config/gspread`` was outside everything it watched.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import stonksmith.helpers.sheets as sheets


class GspreadConfigMixin:
    """Redirect GSPREAD_CONFIG_DIR for the duration of a TestCase."""

    #: Whether to lay down a gspread config directory with credentials in it.
    #: Off by default, and off means the directory does not exist at all --
    #: which is what an install that never authorized looks like, and is the
    #: baseline most tests want. Same shape as UserConfigMixin.config_body,
    #: which writes no file unless it is given one.
    seed_credentials: bool = False

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]

        self._gspread_home = tempfile.TemporaryDirectory()
        self.gspread_dir: Path = Path(self._gspread_home.name) / "gspread"

        # Created only when seeding. Leaving it absent is not merely tidier:
        # _restrict_google_credentials() returns early on a directory that is
        # not there, so this is the branch a test which never authorized should
        # be taking, rather than one that chmods an empty directory it was
        # handed for no reason.
        if self.seed_credentials:
            self.gspread_dir.mkdir()

            for name in ("authorized_user.json", "credentials.json"):
                path: Path = self.gspread_dir / name
                path.write_text(data="{}", encoding="utf-8")
                path.chmod(mode=0o644)

        self._gspread_patch = patch.object(
            sheets, "GSPREAD_CONFIG_DIR", str(object=self.gspread_dir)
        )
        self._gspread_patch.start()

    def tearDown(self) -> None:
        self._gspread_patch.stop()
        self._gspread_home.cleanup()

        super().tearDown()  # type: ignore[misc]
