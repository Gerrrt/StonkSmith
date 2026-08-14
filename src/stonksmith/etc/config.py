"""
config.py: Module to control running configuration

Loading is lazy. Importing this module used to read, merge, and *write*
``~/.stonksmith/stonksmith.conf`` as a side effect, which meant importing any
part of StonkSmith mutated the user's home directory. The config is now read on
first use and cached.
"""

import ast
import configparser
import math
from dataclasses import dataclass
from pathlib import Path

from stonksmith.etc.logger import stonksmith_logger
from stonksmith.etc.paths import etc_path, stonksmith_path

default_cfg_path: Path = etc_path / "stonksmith.conf"
user_cfg_path: Path = stonksmith_path / "stonksmith.conf"

DEFAULT_HOST_INFO_COLORS: tuple[str, ...] = ("green", "red", "yellow", "cyan")

#: Where TSP publishes the share price history. A static object on their CDN:
#: the date range parameters the site's own download form sends are ignored and
#: the response is byte-identical without them, so the bare URL is what actually
#: serves.
DEFAULT_TSP_PRICE_URL = "https://www.tsp.gov/data/fund-price-history.csv"

#: Where DFAS publishes the military basic pay tables. The four grade families
#: hang off this as path segments -- see helpers.dfas.TABLE_PATHS -- so a move
#: only invalidates the base, which is what makes one overridable URL enough to
#: fix all four without a release.
#:
#: "MilitaryMembers" rather than "Military-Members": the hyphenated path is the
#: one DFAS published for years, and it now 301s here. Following the redirect
#: costs a round trip on every fetch and, more to the point, a redirect is a
#: courtesy that gets withdrawn -- the eventual 404 would arrive as "DFAS has no
#: pay table for your grade" rather than as a moved page.
DEFAULT_DFAS_PAY_URL = (
    "https://www.dfas.mil/MilitaryMembers/payentitlements/Pay-Tables/Basic-Pay/"
)

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

    # interpolation=None because a percent sign is a value here, not syntax.
    # ConfigParser's default BasicInterpolation reads "%" as the start of a
    # "%(name)s" reference and raises on anything else -- so a member who wrote
    # the obvious "member_contribution = 5%" got an InterpolationSyntaxError out
    # of a getter that strips a trailing "%" precisely because it expects one.
    # Nothing shipped uses interpolation, so there is nothing to lose by it.
    defaults = configparser.ConfigParser(interpolation=None)
    defaults.read(filenames=default_cfg_path)

    config = configparser.ConfigParser(interpolation=None)
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
        with user_cfg_path.open(mode="w") as f:
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

    try:
        return get_config().getboolean(
            section="STONKSMITH", option="audit_mode", fallback=False
        )

    except ValueError:
        # Anything that is not a boolean is not permission to reveal a secret.
        # getboolean raises rather than falling back, so without this a typo
        # here takes down every command that displays a credential.
        return False


def get_reveal_chars() -> int:
    """
    How many leading characters of a secret audit mode may show.
    :return: A non-negative count
    """

    try:
        configured: int = get_config().getint(
            section="STONKSMITH", option="reveal_chars_of_pwd", fallback=0
        )

    except ValueError:
        # "False" is the shipped default and is not an int; reveal nothing.
        return 0

    # A negative is not a shorter prefix, it is a slice counted from the end:
    # text[:-3] on a secret returns all but the last three characters. Floor it
    # here rather than trusting every caller to guard, which is the promise the
    # return type already makes.
    return max(0, configured)


def get_log_mode() -> bool:
    """
    Whether file logging is enabled by config.
    :return: True when log mode is enabled
    """

    try:
        return get_config().getboolean(
            section="STONKSMITH", option="log_mode", fallback=False
        )

    except ValueError:
        # As with audit_mode: an unreadable value means "not enabled", not a
        # crash on the way to doing the work the user asked for.
        return False


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

    # The isinstance check guards the len(), rather than a TypeError catching it
    # afterwards: "host_info_colors = 5" is a perfectly good literal, so
    # literal_eval returns it happily and len() is what raises -- a TypeError
    # out of a getter documented to fall back on anything malformed. Something
    # uncountable fails the four-name contract the same way a three-item list
    # does, so it takes the same exit.
    if not isinstance(colors, list | tuple) or len(colors) != 4:
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

    Overridable in config because this is the one part of the broker that TSP
    can move without warning, and a URL in a config file is fixable without a
    release. But it ships with a working value, because the broker exists to run
    unattended and a URL nobody has filled in makes that impossible.

    Blank counts as unset, not as "download nothing". Installs predating the
    default already carry a literal ``price_url =`` line -- ``get_config()``
    backfills only options that are *absent* -- so keying off emptiness rather
    than presence is what lets them pick the default up.
    :return: The configured URL, or the published default when unset
    :rtype: str
    """

    configured: str = (
        get_config().get(section="TSP", option="price_url", fallback="").strip()
    )

    return configured or DEFAULT_TSP_PRICE_URL


def get_tsp_rank() -> str:
    """
    The member's pay grade, which picks a row out of the DFAS pay tables.

    Returned as written rather than validated here. helpers.dfas.normalize_grade
    owns what a grade may look like, and it is the broker that has to report an
    unusable one -- a getter that quietly returned "" for "Sergeant" would leave
    the run saying no rank was configured when one plainly was.
    :return: The grade as configured, or "" when unset
    :rtype: str
    """

    return get_config().get(section="TSP", option="rank", fallback="").strip()


def get_tsp_basd() -> str:
    """
    Basic Active Service Date, from which time in service is counted.

    A string, not a date, for the same reason units_as_of is one: a caller that
    parses it can say "Unreadable basd 'Jan 5 2019'; expected YYYY-MM-DD", where
    a getter returning None cannot tell a typo from an empty line.
    :return: The date as written, or "" when unset
    :rtype: str
    """

    return get_config().get(section="TSP", option="basd", fallback="").strip()


def get_tsp_contributions() -> tuple[float | None, float | None]:
    """
    What share of basic pay the member and their agency contribute.

    Percentages, because that is what a member elects and what an agency match
    is expressed as -- and because it needs no LES to know. Both, always: they
    buy units together each month and reporting one without the other would
    understate the account by exactly the other one.

    A malformed figure is None rather than 0.0, the same rule get_tsp_units()
    follows. A typo must not read as "contributed nothing", which values the
    accrual at zero and looks like a real answer.
    :return: (member percent, agency percent); either is None when unset or
        unreadable
    :rtype: tuple[float | None, float | None]
    """

    config = get_config()

    def percent(option: str) -> float | None:
        raw: str = config.get(section="TSP", option=option, fallback="").strip()

        try:
            return float(raw.rstrip("%")) if raw else None

        except ValueError:
            return None

    return percent(option="member_contribution"), percent(option="agency_contribution")


def get_tsp_contribution_day() -> int | None:
    """
    Which day of the month a contribution posts.

    Configurable because when the money lands is a fact about the member's pay
    cycle rather than about TSP, and because the price it buys at is the price
    on that day. Blank means the last day of the month, which is what the
    accrual uses when this is unset.

    A day past the end of a short month is clamped by the caller rather than
    refused here, so "31" is a usable answer in February.
    :return: A day of the month, or None when unset or unreadable
    :rtype: int | None
    """

    raw: str = (
        get_config().get(section="TSP", option="contribution_day", fallback="").strip()
    )

    try:
        day = int(raw) if raw else None

    except ValueError:
        return None

    return day if day is None or 1 <= day <= 31 else None


def get_tsp_pay_table_url() -> str:
    """
    Where the published basic pay tables live.

    Overridable for the same reason price_url is: this is a URL on somebody
    else's site, and a config line is fixable without waiting for a release.
    Blank counts as unset rather than as "download nothing", so an install that
    backfilled an empty line still picks the default up.
    :return: The configured base URL, or the published default when unset
    :rtype: str
    """

    configured: str = (
        get_config().get(section="TSP", option="pay_table_url", fallback="").strip()
    )

    return configured or DEFAULT_DFAS_PAY_URL


def get_asset_classes() -> dict[str, str]:
    """
    Which symbol belongs to which asset class, as the operator declared it.

    No source StonkSmith reads supplies an asset class: SnapTrade gives a ticker,
    a scraped 529 gives a fund code, TSP gives a fund. They are the same field --
    HoldingRow.symbol is "the ticker, or the fund code for sources that do not
    trade in tickers" -- which is what makes one hand-kept table enough to cover
    all five brokers. Deriving the class instead would take an external lookup or
    a guess, and a guess buried in a dashboard formula is worse than a dimension
    the tab does not claim to have.

    Config rather than a flag, for the reason exclude_accounts is: which fund is
    which asset class is a standing fact about the portfolio, and a run from cron
    has nobody to remember it.

    One "SYMBOL = Class" per line. Split on the first "=" so a class name may
    contain one; a line without a separator is dropped rather than guessed at.
    Keys keep the case they were typed in, because they are matched against the
    symbol exactly as the source spelled it -- which is also why this is parsed
    out of one option's value rather than read as a section of options, since
    ConfigParser lower-cases option names and "VTI" would arrive as "vti".
    :return: Symbol to class name, later duplicates winning
    :rtype: dict[str, str]
    """

    raw: str = get_config().get(
        section="ALLOCATION", option="asset_classes", fallback=""
    )

    classes: dict[str, str] = {}

    for line in raw.splitlines():
        symbol, sep, name = line.partition("=")

        if not sep or not symbol.strip() or not name.strip():
            continue

        classes[symbol.strip()] = name.strip()

    return classes


@dataclass(frozen=True, slots=True)
class ManualHolding:
    """
    One account valued from a unit count the operator supplies.

    Units and a symbol rather than a balance, on the rule the [TSP] comment
    states: a balance is true for one day and would silently rot, while a unit
    count only moves when money does. ``units_as_of`` rides along because an
    account priced from an old count is right if nothing has been paid in and
    wrong by exactly what has -- and the date is the only way to tell.
    """

    name: str
    symbol: str
    units: float
    units_as_of: str

    #: What was paid, where the operator knows it. Optional because most
    #: portals that cannot be scraped cannot be asked this either -- and None
    #: rather than zero, so the brief renders a dash instead of reporting a
    #: position that has made exactly its whole value.
    cost_basis: float | None = None


def get_manual_accounts() -> tuple[list[ManualHolding], list[str]]:
    """
    Accounts that can be seen but not scraped, and the lines that made no sense.

    Two returns, because a line that does not parse must not be dropped in
    silence. This is hand-typed configuration for an account no source will ever
    correct: a mistyped unit count produces a plausible number and a mistyped
    line produces nothing at all, and the second one is only distinguishable
    from "no manual accounts configured" if somebody says so.

    Four fields split on "|" rather than on whitespace, because an account name
    has spaces in it and a fund symbol does not have a pipe. A fifth is
    optional and carries what was paid, so an account that knows its cost basis
    reports a gain rather than the dash every unpriced holding shows.
    :return: (the accounts, the lines that could not be read)
    :rtype: tuple[list[ManualHolding], list[str]]
    """

    raw: str = get_config().get(section="MANUAL", option="accounts", fallback="")
    accounts: list[ManualHolding] = []
    refused: list[str] = []

    for line in raw.splitlines():
        if not line.strip():
            continue

        fields: list[str] = [field.strip() for field in line.split("|")]

        # Four required, a fifth optional. The required ones must all be filled
        # in: a blank symbol or a blank date is a half-written line, and half a
        # line is the shape a copy-paste leaves behind.
        if len(fields) not in (4, 5) or not all(fields[:4]):
            refused.append(line.strip())
            continue

        name, symbol, units, as_of = fields[:4]
        paid: str = fields[4] if len(fields) == 5 else ""

        try:
            held = float(units)
            cost: float | None = float(paid) if paid else None

        except ValueError:
            refused.append(line.strip())
            continue

        # A negative unit count is not a short position here -- nothing in this
        # format can express one -- it is a typo that would subtract from the
        # portfolio while looking like a holding. A negative cost is the same
        # kind of mistake and would report a gain larger than the position.
        if held < 0 or (cost is not None and cost < 0):
            refused.append(line.strip())
            continue

        accounts.append(
            ManualHolding(
                name=name,
                symbol=symbol,
                units=held,
                units_as_of=as_of,
                cost_basis=cost,
            )
        )

    return accounts, refused


def get_account_aliases() -> dict[str, str]:
    """
    What the operator calls each account, where that differs from the broker.

    Keyed on the "Source / Account" label rather than on the account key, which
    is the one debatable choice here. The key is the stable identity and the
    display name is explicitly not -- so keying on the name means a broker
    renaming an account drops its alias.

    The label wins anyway, for two reasons. It is the spelling
    ``exclude_accounts`` already uses, so a label copied out of a run works in
    either option and an operator does not have to learn that two adjacent
    settings identify the same account differently. And an account key is an
    opaque SnapTrade identifier that appears nowhere a person reads; asking
    somebody to find one in order to rename an account is asking them not to
    bother. The dropped-alias case is handled by reporting a line that matched
    nothing, which is a better outcome than a silent revert either way.

    Split on the last "=" rather than the first, unlike the asset class table:
    an account name may contain one and a class name is far less likely to. A
    line without a separator is dropped rather than guessed at.
    :return: Label to display name, later duplicates winning
    :rtype: dict[str, str]
    """

    raw: str = get_config().get(section="ACCOUNTS", option="aliases", fallback="")
    aliases: dict[str, str] = {}

    for line in raw.splitlines():
        label, sep, name = line.rpartition("=")

        if not sep or not label.strip() or not name.strip():
            continue

        aliases[label.strip()] = name.strip()

    return aliases


def get_account_costs() -> tuple[dict[str, float], list[str]]:
    """
    What the operator paid, for accounts whose source will not say.

    Three real holdings report no cost basis and each refuses for its own
    reason, which is why this is stated rather than derived. A Fidelity 401k
    reaches SnapTrade as ``kind: "other"`` carrying units and price and nothing
    else -- not even eligible for tax lots. A Schwab 529 arrives as a bare
    balance with no symbol at all. And the TSP unit count is anchored to a
    figure typed off a quarterly statement, so the only units whose cost is
    known are the ones accrued since; reporting *those* as the basis would put
    a five-figure balance against a few hundred dollars and print a gain of
    some two thousand percent. A partial cost basis is worse than none.

    Keyed on the "Source / Account" label, and read against the label the
    *broker* gave -- the same spelling ``exclude_accounts`` matches and
    ``[ACCOUNTS] aliases`` renames from. Under `[ACCOUNTS]` beside them rather
    than in a section of its own for that reason: three settings identify an
    account, and one rule for saying which is what stops a line that works in
    one from doing nothing in another.

    Refusals are returned rather than raised. A cost that will not parse is a
    typo in a config file, and the honest outcome is a holding that still shows
    a dash plus a line saying why -- not a failed morning, and emphatically not
    a zero, which would report the position's whole value as gain.
    :return: (label to cost, the lines that were refused)
    :rtype: tuple[dict[str, float], list[str]]
    """

    raw: str = get_config().get(section="ACCOUNTS", option="cost_basis", fallback="")
    costs: dict[str, float] = {}
    refused: list[str] = []

    for line in raw.splitlines():
        label, sep, amount = line.rpartition("=")

        if not sep or not label.strip() or not amount.strip():
            continue

        # Punctuation stripped before parsing, since a figure copied off a
        # statement arrives as "$1,300.00" and refusing that would be pedantry
        # about a value nobody could misread.
        try:
            cost = float(amount.strip().lstrip("$").replace(",", "").replace("_", ""))

        except ValueError:
            refused.append(f"{line.strip()} (not an amount)")
            continue

        # Checked before the sign, because the sign test cannot see these.
        # float() accepts "nan", "inf" and anything that overflows to one --
        # "1e400" parses to inf -- and `nan < 0` is False, so a NaN would sail
        # through the line below and land in the cost basis. From there it
        # propagates: the gain is nan, the growth is nan, the win/loss flag
        # compares false against everything, and the tile renders the word.
        # Silent, contagious, and not obviously traceable to a config file.
        if not math.isfinite(cost):
            refused.append(f"{line.strip()} (not a finite amount)")
            continue

        # Negative is refused rather than clamped. A cost basis below zero is
        # not a number anybody meant, and passing it through would report a
        # growth percentage with the sign inverted.
        if cost < 0:
            refused.append(f"{line.strip()} (a cost cannot be negative)")
            continue

        costs[label.strip()] = cost

    return costs, refused


#: The colours an account may be tagged with.
#:
#: A closed set, and that is a safety property rather than a style guide: the
#: value is written into an HTML class attribute, and a config file is not a
#: stylesheet. Anything outside this is reported and dropped, so a typo produces
#: an uncoloured row and a line of output rather than markup nobody wrote.
ACCOUNT_COLORS: frozenset[str] = frozenset(
    {"green", "pink", "blue", "yellow", "orange", "purple", "grey"}
)


def get_account_colors() -> tuple[list[tuple[str, str]], list[str]]:
    """
    Whose account is whose, for the brief to colour by.

    A list of pairs rather than a dict, because the order is part of the rule:
    the match is a substring of the display name and the first line that matches
    wins, so "Joint = yellow" written above "Garrett = green" would colour a
    joint account Garrett holds. A dict would keep the order in practice and say
    nothing about depending on it.

    Substring rather than exact, so one line covers every account a person
    holds -- "Garrett" catches the IRA, the brokerage and the 401(k) without
    naming each. Matched against the display name *after* aliases are applied,
    which is the name a reader sees and therefore the one they would write here.
    :return: (the (match, colour) pairs in order, the lines that were refused)
    :rtype: tuple[list[tuple[str, str]], list[str]]
    """

    raw: str = get_config().get(section="ACCOUNTS", option="colors", fallback="")
    pairs: list[tuple[str, str]] = []
    refused: list[str] = []

    for line in raw.splitlines():
        match, sep, color = line.rpartition("=")

        if not sep or not match.strip() or not color.strip():
            if line.strip():
                refused.append(line.strip())
            continue

        chosen: str = color.strip().casefold()

        if chosen not in ACCOUNT_COLORS:
            # Named rather than silently dropped: an unrecognised colour leaves
            # a row uncoloured, which looks exactly like an account nobody wrote
            # a line for.
            refused.append(line.strip())
            continue

        pairs.append((match.strip(), chosen))

    return pairs, refused


def get_brief_open_browser() -> bool:
    """
    Whether the morning brief opens itself once it is written.

    True by default, which is the opposite of how the rest of this tool behaves
    and is the whole point of the feature: a brief nobody opens is a file, and
    the thing being automated here is the remembering. `brief --no-open` overrides
    it for a scripted run, so the default is about the LaunchAgent rather than
    about every invocation.
    :return: True when the rendered file should be opened
    :rtype: bool
    """

    try:
        return get_config().getboolean(
            section="BRIEF", option="open_browser", fallback=True
        )

    except ValueError:
        # As with audit_mode and log_mode: an unreadable value is not a reason to
        # take down the command on its way to doing the work asked of it. The
        # brief is still rendered and its path still printed.
        return True


def get_brief_keep_days() -> int:
    """
    How many days of rendered briefs to keep.

    Zero means keep everything, and is a real answer rather than a disabled
    feature: the rendered files are the only record of what a given morning
    actually showed, and once the baseline has moved past a date the databases
    cannot reconstruct it.

    A negative is treated as zero. It would otherwise put the cutoff in the
    future and delete every brief including the one just written, which is not a
    tidier policy but a broken one -- the same reasoning `stale` applies to a
    negative day count.
    :return: A non-negative day count
    :rtype: int
    """

    try:
        configured: int = get_config().getint(
            section="BRIEF", option="keep_days", fallback=90
        )

    except ValueError:
        return 90

    return max(0, configured)


#: Where a symbol's quote page lives. Yahoo rather than each fund company's own
#: site, and deliberately: the project already reads prices from
#: query1.finance.yahoo.com for Ally's --from-prices and the manual broker, so
#: this is the human-facing page of a source already trusted for the numbers.
#: Linking Schwab funds to schwab.com and Fidelity funds to fidelity.com would
#: mean a table of per-brokerage URL shapes, each restyled on somebody else's
#: schedule, to reach pages carrying the same figures.
DEFAULT_FUND_LINK = "https://finance.yahoo.com/quote/{symbol}"


def get_brief_fund_link() -> str:
    """
    The URL template a holding's symbol links to.

    **Refused unless it is https**, because the value is written into an href and
    a config file is not a place to put "javascript:". A template that is not a
    URL is reported by the caller and the links are simply absent, which is the
    same outcome as not configuring one.

    Blank counts as unset rather than as "no links", so an install that
    backfilled an empty line picks the default up -- the rule the TSP price_url
    already follows.
    :return: A template containing {symbol}, or "" when it was refused
    :rtype: str
    """

    configured: str = (
        get_config().get(section="BRIEF", option="fund_link", fallback="").strip()
    )
    template: str = configured or DEFAULT_FUND_LINK

    if not template.lower().startswith("https://") or "{symbol}" not in template:
        return ""

    return template


def get_brief_min_position() -> float:
    """
    The smallest position worth a row in the holdings table.

    A settlement account leaves eight cents of a sweep fund sitting beside a
    real holding, and it renders as a full row with a dash in every derived
    column. It is not wrong -- the money is there -- it is just not a holding
    anybody is tracking, and a table where one row in twelve is noise is a table
    that gets skimmed.

    Display only. Whatever falls below this is still counted in every total, so
    the portfolio value, the invested figure and the cash line are unchanged by
    it -- and the count of what was hidden is stated under the table, on the same
    rule the movers cap follows. A row removed from a page is a presentation
    choice; a dollar removed from a total is a lie.

    Zero shows everything, which is a real answer rather than a disabled feature.
    :return: A non-negative floor in the account's currency
    :rtype: float
    """

    try:
        configured: float = get_config().getfloat(
            section="BRIEF", option="min_position", fallback=1.0
        )

    except ValueError:
        return 1.0

    return max(0.0, configured)


def get_brief_movers() -> int:
    """
    How many accounts and positions the brief has room for.

    Floored at one rather than at zero. A brief rendering no movers at all is
    indistinguishable from one where nothing moved, and this feature exists
    precisely to keep those two apart.
    :return: A positive row count
    :rtype: int
    """

    try:
        configured: int = get_config().getint(
            section="BRIEF", option="movers", fallback=8
        )

    except ValueError:
        return 8

    return max(1, configured)
