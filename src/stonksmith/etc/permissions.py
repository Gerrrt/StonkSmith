# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""
Owner-only permissions for everything StonkSmith writes.

This lived in ``etc.browser_connection``, where the only way to reach a chmod was
to import Playwright. Page captures were never the only files that needed one:
the account databases hold every balance and account number this tool has ever
recorded, the config holds a SnapTrade client id and a pay grade, the run log
holds whatever the run printed, and the Playwright trace is a DOM recording of a
signed-in brokerage session. None of those layers can import a browser driver.

Every call is best-effort. A filesystem without POSIX permissions -- a Windows
volume, a network mount, a container bind -- must not turn "the balance was
written down" into a failed run. That is a deliberate trade rather than an
oversight: this hardens the common case and is not a guarantee, and SECURITY.md
says so rather than implying otherwise.
"""

import contextlib
from pathlib import Path

#: A file only its owner may read or write.
OWNER_ONLY_FILE = 0o600

#: A directory only its owner may enter, list or write.
#:
#: The load-bearing one. A directory mode is the only control that reaches a file
#: this tool did not write -- a Playwright trace that Playwright saved, a Chrome
#: profile that Chromium populated, a CDP profile created by a command we only
#: printed. Denying traversal covers all of them without knowing they exist.
OWNER_ONLY_DIR = 0o700


def restrict(path: Path) -> None:
    """
    Make a file owner-readable only.

    Captures are raw markup from a signed-in brokerage session and can contain
    account numbers, balances, and 2FA context; a database holds the same
    history over time. Default permissions follow the process umask, which is
    commonly world-readable.
    :param path: The file to restrict
    """

    # Best-effort: a filesystem without POSIX permissions must not turn a
    # diagnostic capture into a failure.
    with contextlib.suppress(OSError):
        path.chmod(mode=OWNER_ONLY_FILE)


def restrict_dir(path: Path) -> None:
    """
    Make a directory owner-enterable only.

    Separate from ``restrict`` because the mode differs and the reason differs.
    0600 on a directory clears the execute bit, which makes it untraversable by
    its own owner; and a directory is restricted to cover files some other
    program wrote inside it, not to protect the directory itself.
    :param path: The directory to restrict
    """

    with contextlib.suppress(OSError):
        path.chmod(mode=OWNER_ONLY_DIR)
