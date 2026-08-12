# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""A config that is nobody's, so tests never read or rewrite the real one.

Not named test_*: this is a helper, and pytest collecting it as a test module
would do nothing useful.

Any test whose code path reaches a config getter needs this. get_config() merges
the shipped defaults into ~/.stonksmith/stonksmith.conf and writes the result
back whenever that file exists, so such a test does two wrong things at once: it
answers out of whatever the developer happens to have configured, and it edits
their file. tests/test_suite_does_not_touch_home.py fails the whole suite for the
second, which is how the first gets caught too.

Pointing at a path in a temp directory covers both. Nothing is created there
unless config_body asks for it, and a config file that does not exist is exactly
what an install that has not been set up looks like -- every getter then answers
out of the shipped defaults, which is the deterministic baseline a test wants.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import stonksmith.etc.config as etc_config


class UserConfigMixin:
    """Point etc.config at a throwaway config for the duration of a TestCase."""

    #: What to write to that config file. Empty means do not create one at all.
    #: Override it on the TestCase to give the code under test real config lines.
    config_body: str = ""

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]

        self._config_home = tempfile.TemporaryDirectory()
        path: Path = Path(self._config_home.name) / "stonksmith.conf"

        if self.config_body:
            path.write_text(data=self.config_body)

        self._config_patch = patch.object(etc_config, "user_cfg_path", path)
        self._config_patch.start()

        # The merged config lives in a process global, so patching the path
        # without dropping the cache reads whatever an earlier test loaded --
        # and leaks this body to whatever runs next.
        etc_config.reset_config_cache()

    def tearDown(self) -> None:
        self._config_patch.stop()
        etc_config.reset_config_cache()
        self._config_home.cleanup()

        super().tearDown()  # type: ignore[misc]
