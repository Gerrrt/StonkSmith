"""
config.py: Module to control running configuration

Loading is lazy. Importing this module used to read, merge, and *write*
``~/.stonksmith/stonksmith.conf`` as a side effect, which meant importing any
part of StonkSmith mutated the user's home directory. The config is now read on
first use and cached.
"""

import ast
import configparser
from pathlib import Path

from etc.logger import stonksmith_logger
from etc.paths import etc_path, stonksmith_path

default_cfg_path: Path = etc_path / "stonksmith.conf"
user_cfg_path: Path = stonksmith_path / "stonksmith.conf"

DEFAULT_HOST_INFO_COLORS: tuple[str, ...] = ("green", "red", "yellow", "cyan")

_config: configparser.ConfigParser | None = None


def get_config() -> configparser.ConfigParser:
    """
    Read the user config, backfilling any options missing from the shipped
    defaults. The result is cached for the life of the process.
    :return: The merged configuration
    """

    global _config

    if _config is not None:
        return _config

    defaults = configparser.ConfigParser()
    defaults.read(filenames=default_cfg_path)

    config = configparser.ConfigParser()
    config.read(filenames=user_cfg_path)

    backfilled: list[str] = []

    for section in defaults.sections():
        if not config.has_section(section=section):
            config.add_section(section=section)

        for option in defaults.options(section=section):
            if not config.has_option(section=section, option=option):
                config.set(
                    section=section,
                    option=option,
                    value=defaults.get(section=section, option=option),
                )
                backfilled.append(option)

    # Only write when the file already exists: setup_tool() owns creating it, so
    # a missing file means the tool has not been set up yet and this must not be
    # the thing that creates it. Until then the merge stays purely in memory --
    # and stays quiet, since announcing writes that will not happen is noise on
    # every fresh install and in every test.
    if backfilled and user_cfg_path.exists():
        stonksmith_logger.highlight(
            msg=f"Adding missing option(s) to {user_cfg_path}: {', '.join(backfilled)}"
        )
        with open(file=user_cfg_path, mode="w") as f:
            config.write(fp=f)

    _config = config
    return config


def reset_config_cache() -> None:
    """
    Drop the cached config so the next read picks the file up again. Intended
    for tests and for callers that rewrite the file mid-process.
    """

    global _config
    _config = None


def get_workspace() -> str:
    """
    The active workspace name.
    :return: Workspace name, defaulting to "default"
    """

    return get_config().get(
        section="STONKSMITH", option="workspace", fallback="default"
    )


def get_audit_mode() -> bool:
    """
    Whether secrets may be partially revealed on screen.

    NOTE: must be read with getboolean, not get(). ConfigParser.get() returns
    raw strings, so the literal "False" in the shipped config is a truthy str
    and the check would be inverted.
    :return: True when audit mode is enabled
    """

    return get_config().getboolean(
        section="STONKSMITH", option="audit_mode", fallback=False
    )


def get_reveal_chars() -> int:
    """
    How many leading characters of a secret audit mode may show.
    :return: A non-negative count
    """

    try:
        return get_config().getint(
            section="STONKSMITH", option="reveal_chars_of_pwd", fallback=0
        )

    except ValueError:
        # "False" is the shipped default and is not an int; reveal nothing.
        return 0


def get_log_mode() -> bool:
    """
    Whether file logging is enabled by config.
    :return: True when log mode is enabled
    """

    return get_config().getboolean(
        section="STONKSMITH", option="log_mode", fallback=False
    )


def get_host_info_colors() -> list[str]:
    """
    The four colors used for host info output, falling back on anything
    malformed or the wrong length.
    :return: Exactly four color names
    """

    try:
        colors: list[str] = ast.literal_eval(
            node_or_string=get_config().get(
                section="STONKSMITH",
                option="host_info_colors",
                fallback=str(object=list(DEFAULT_HOST_INFO_COLORS)),
            )
        )

    except ValueError, SyntaxError:
        return list(DEFAULT_HOST_INFO_COLORS)

    if len(colors) != 4:
        stonksmith_logger.error(msg="host_info_colors must have 4 values. Defaulting")
        return list(DEFAULT_HOST_INFO_COLORS)

    return list(colors)


def get_snaptrade_client_id() -> str:
    """
    The SnapTrade client id, prefixed PERS- on the free personal tier.

    Not a secret: it is half of a pair, and the consumer key it pairs with lives
    in the OS keyring. Together they are the whole of a personal-tier identity --
    there is no userId or userSecret, because SnapTrade resolves the user from
    the key itself.

    NOTE: ConfigParser lower-cases option names on both write and lookup, so
    "clientId" here resolves against a file containing either spelling.
    :return: The client id, or "" when unset
    """

    return get_config().get(section="SNAPTRADE", option="clientId", fallback="").strip()


def get_snaptrade_excluded_accounts() -> list[str]:
    """
    Accounts the SnapTrade sync must leave to another broker.

    An account reachable both through SnapTrade and through a dedicated broker
    -- a Schwab-held 529 that schwab529plan already scrapes -- is otherwise
    written twice, into two databases and two worksheet tabs. Nothing in
    StonkSmith adds those tabs together, so it corrupts nothing on its own; a
    dashboard that sums them counts the money twice and says nothing.

    Config rather than a flag alone: which broker owns which account is a
    standing fact about the setup, and a run from cron has nobody to remember
    it. ``--exclude`` adds to this rather than replacing it.

    One label per line, in the "Brokerage / Account" form the sync already
    prints in its skip messages, so what to paste here is whatever the run
    called the account.
    :return: Labels to skip, with blank lines and surrounding space removed
    :rtype: list[str]
    """

    raw: str = get_config().get(
        section="SNAPTRADE", option="exclude_accounts", fallback=""
    )

    return [line.strip() for line in raw.splitlines() if line.strip()]


def process_secret(text: str | None) -> str:
    """
    Mask a secret for display.

    Secrets are fully masked unless audit mode is enabled, in which case the
    first ``reveal_chars_of_pwd`` characters are shown so an operator can tell
    two credentials apart without exposing either one.
    :param text: The secret to mask, or None
    :return: A display-safe string that never contains the full secret
    """

    mask: str = "*" * 8

    if not text:
        return ""

    reveal: int = get_reveal_chars()

    if not get_audit_mode() or reveal <= 0:
        return mask

    return f"{text[:reveal]}{mask}"


def get_tsp_fund() -> str:
    """
    Which TSP fund the account holds.

    One fund, not an allocation: TSP reports units per fund and a member in a
    single Lifecycle fund -- the common case -- has exactly one unit count.
    Multi-fund support belongs in the statement importer, which already reads a
    row per fund, rather than in a config string nobody can keep in sync.
    :return: The fund name as the price file spells it, or "" when unset
    :rtype: str
    """

    return get_config().get(section="TSP", option="fund", fallback="").strip()


def get_tsp_units() -> tuple[float | None, str]:
    """
    The unit count to value, and the date it was true.

    Both, always. A TSP mark is units times a share price and the two are true
    as of different days -- the price is today's, the units are as old as the
    last statement. Returning the count alone would leave every caller free to
    present a three-month-old number as current, which is the failure this
    broker exists to avoid.
    :return: (units, as-of date as written); units is None when unset
    :rtype: tuple[float | None, str]
    """

    config = get_config()
    raw: str = config.get(section="TSP", option="units", fallback="").strip()
    as_of: str = config.get(section="TSP", option="units_as_of", fallback="").strip()

    try:
        return (float(raw) if raw else None), as_of

    except ValueError:
        # A typo must not read as zero units, which would value the account at
        # nothing and look like a real answer.
        return None, as_of


def get_tsp_price_url() -> str:
    """
    Where the published share price history lives.

    Config rather than a constant because it is the one part of this broker
    that TSP can move without warning, and a URL in a config file is fixable
    without a release. ``--prices`` reads a downloaded copy instead, which is
    also the path for a machine that cannot reach tsp.gov at all.
    :return: The URL, or "" when unset
    :rtype: str
    """

    return get_config().get(section="TSP", option="price_url", fallback="").strip()
