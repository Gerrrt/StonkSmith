# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Shared test setup, and the reason the helper modules next door are importable.

``home_isolation``, ``config_isolation`` and ``keyring_isolation`` sit beside the
tests and are imported by bare name. That works today only because pytest's
default "prepend" import mode puts each test file's own directory on sys.path --
an implicit favour that disappears under ``--import-mode=importlib`` and the
moment anyone adds a tests/__init__.py. Both are things a future change might do
for unrelated reasons, and the failure would look like the helpers vanishing.
Putting this directory on sys.path here states the dependency instead of
inheriting it.

The fixtures below are the pytest spelling of the mixins in those modules. The
suite is unittest.TestCase throughout and there is no plan to convert it -- the
mixins stay, and stay the right answer for a TestCase. These exist so a new test
can be written in pytest style without giving up the isolation, and so the two
styles can sit in the same directory without a second set of setup rules.
"""

import sys
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import keyring

import etc.config
from keyring_isolation import MemoryKeyring


@pytest.fixture
def memory_keyring() -> Iterator[MemoryKeyring]:
    """
    Swap in an in-memory keyring for one test.

    Needed by any test that opens a broker Database, not just the credential
    ones: opening a database runs migrate_plaintext_secrets(), which writes any
    legacy plaintext password it finds into whatever backend is installed.
    :return: The backing keyring, whose ``store`` dict the test may assert on
    """

    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)

    yield backend

    keyring.set_keyring(previous)


@pytest.fixture
def user_config() -> Iterator[Callable[[str], Path]]:
    """
    Point etc.config at a throwaway config file for one test.

    The returned callable writes a config body and hands back its path; calling
    it with "" leaves no file at all, which is what an install that has never
    been set up looks like and is the deterministic baseline most tests want.

    Without this a test that reaches a config getter both answers out of the
    developer's own ~/.stonksmith/stonksmith.conf and rewrites it, because
    get_config() merges the shipped defaults back into that file whenever it
    exists.
    :return: A callable taking the config body and returning the config path
    """

    with tempfile.TemporaryDirectory() as home:
        path = Path(home) / "stonksmith.conf"

        with patch.object(etc.config, "user_cfg_path", path):
            # The merged config lives in a process global. Patching the path
            # without dropping the cache reads whatever an earlier test loaded,
            # and leaks this body to whatever runs next.
            etc.config.reset_config_cache()

            def write(body: str = "") -> Path:
                if body:
                    path.write_text(data=body)
                etc.config.reset_config_cache()
                return path

            yield write

            etc.config.reset_config_cache()
