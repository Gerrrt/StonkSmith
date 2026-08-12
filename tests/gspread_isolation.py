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

    #: Whether to lay down credential files inside it. Off by default: the
    #: directory not existing is what an install that never authorized looks
    #: like, and it is the case most tests want.
    seed_credentials: bool = False

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]

        self._gspread_home = tempfile.TemporaryDirectory()
        self.gspread_dir: Path = Path(self._gspread_home.name) / "gspread"
        self.gspread_dir.mkdir()

        if self.seed_credentials:
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
