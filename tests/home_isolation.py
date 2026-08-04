"""Point a subprocess's home directory somewhere harmless, on every platform.

Not a test module: the guards that run StonkSmith in a subprocess share this.
"""

import os


def isolated_home_env(home: str, **extra: str) -> dict[str, str]:
    """
    A copy of this process's environment whose home directory is ``home``.

    Overriding HOME alone is a POSIX-only fix. ntpath.expanduser() reads
    USERPROFILE, falls back to HOMEDRIVE + HOMEPATH, and never consults HOME, so
    on Windows a subprocess would resolve ``~`` to the developer's real profile
    -- and a guard watching the temp directory would report green while the real
    ~/.stonksmith was being written to.
    :param home: Directory to use as the subprocess's home
    :param extra: Any further environment variables to set
    :return: An environment mapping ready for subprocess.run(env=...)
    """

    drive, tail = os.path.splitdrive(p=os.path.abspath(path=home))

    return dict(
        os.environ,
        HOME=home,
        USERPROFILE=home,
        HOMEDRIVE=drive,
        HOMEPATH=tail,
        **extra,
    )
