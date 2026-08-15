# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""One shape for what the databases hold, and one way to read it.

Five brokers wrote five unrelated worksheet layouts. Nothing shared a column:
"Balance" and "Value" named the same thing in different tabs, and `Synced`,
`Price date` and `Units as of` were three answers to one question. Each broker
was re-deriving its own projection of a shape the database already had.

So the projection lives here instead, once. Four row types, ordered columns,
and one function that produces them from every broker database in a workspace.

**The columns are append-only.** A new column goes on the end, never in the
middle. Anything reading this -- a worksheet formula most of all -- addresses a
column by position, and a column inserted at the front silently changes what
every one of them points at. `tests/test_portfolio_contract.py` pins the exact
tuples so that shift fails in CI rather than in a spreadsheet.

**Separate row types rather than the one flat view this started out wanting.**
An account's value and the sum of its positions are different numbers:
uninvested cash sits in the balance and in no holding. A single view emitting
positions for accounts that have them and a balance for accounts that do not
would understate every account holding cash while looking like it totalled
correctly. So accounts carry the value, holdings carry the breakdown, and the
two join on (broker, account_key).

Transactions are the third, and the first that is a *log* rather than current
state. Accounts and holdings are both "what is true now" -- one row per account,
one per position behind the newest snapshot, replaced every run. A movement
happened once and stays, so this view carries every movement the database holds
rather than the newest run's worth. That is why the read behind it takes no
limit: a history shown five hundred rows at a time, with nothing saying so, is
the failure this project keeps finding rather than a smaller feature.

The account series is the fourth, and the first that is *constructed* rather
than projected. The other three each render what some source said; this one
renders what the portfolio was worth on a date, which no source ever says
because the sources do not report together. Ally needs a manual sign-in and may
go a week, TSP runs unattended, SnapTrade runs whenever -- so totalling the
stored snapshots by date puts one broker's money on a date only that broker ran
on, and draws a portfolio that repeatedly collapses and recovers while looking
entirely like data. net_worth_history carries each account's last known value
forward instead, so every date sums the same accounts, and every row says
whether its number was read that day or carried onto it. It is unbounded for
the same reason Transactions is, and for one more: a series whose oldest points
have silently fallen off the end is a chart of a shorter history than the one
you have.

**Money is a number here, never a formatted string.** Every saver so far wrote
`format_amount()` output, which puts "$1,234.56" in a cell that cannot then be
added up. Formatting is the cell's job. `None` stays empty rather than becoming
zero, because an account that reported no number at all is not an account worth
nothing -- the database is careful about that distinction and this must not
throw it away.

Identity is per-broker. `account_key` is unique within one broker's database and
means nothing outside it: the same real-world 529 is "Schwab - Beneficiary A 529
Plan" to SnapTrade and "Beneficiary A" to the Schwab scraper, with no stored
field linking them. Nothing here can dedupe across brokers, which is why the
`[SNAPTRADE] exclude_accounts` setting is still the thing that decides who owns
an account.
"""

import datetime as dt
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from stonksmith.etc.broker_db import BrokerDatabase
from stonksmith.etc.config import (
    get_account_aliases,
    get_account_costs,
    get_workspace,
)
from stonksmith.etc.context import PortfolioDbProtocol
from stonksmith.etc.infrastructure import create_db_engine
from stonksmith.etc.paths import workspace_dir
from stonksmith.helpers.normalize import to_iso_date

#: The account view, in order. One row per account, across every broker. The
#: sum of its Value column is the portfolio total; nothing else here totals.
ACCOUNT_COLUMNS: tuple[str, ...] = (
    "Broker",
    "Source",
    "Account",
    "Account Key",
    "Kind",
    "Beneficiary",
    "Value",
    "Currency",
    "As Of",
    "Scraped At",
)

#: The holding view, in order. One row per position behind each account's newest
#: snapshot. The first four columns are the same identity prefix the account
#: view carries, so the two join on Broker + Account Key.
HOLDING_COLUMNS: tuple[str, ...] = (
    "Broker",
    "Source",
    "Account",
    "Account Key",
    "Symbol",
    "Name",
    "Units",
    "Price",
    "Value",
    "Cost Basis",
    "Principal",
    "Earnings",
    "Currency",
    "As Of",
    "Scraped At",
    #: Appended, not slotted in beside "As Of", and not a replacement for it.
    #: A position's value is as of one date and its quantity can be as of an
    #: older one -- TSP's price is today's while its units are as old as the
    #: last statement. Two facts, so two columns.
    "Units As Of",
)

#: The transaction view, in order. One row per stored movement, across every
#: broker -- not per snapshot, because a movement is recorded once and deduped
#: on its natural key thereafter. The same identity prefix as the other two, so
#: all three join on Broker + Account Key.
#:
#: Which columns a source fills says something about the source, exactly as it
#: does for holdings. SnapTrade supplies Symbol, Description and a real External
#: Id; the Schwab 529 scraper's table has six columns and supplies none of the
#: three, so those cells are blank for it. Blank means the source said nothing,
#: which is the distinction _cell() exists to keep.
TRANSACTION_COLUMNS: tuple[str, ...] = (
    "Broker",
    "Source",
    "Account",
    "Account Key",
    "Type",
    "Symbol",
    "Description",
    "Units",
    "Price",
    "Value",
    "Currency",
    #: Two columns rather than one, for the reason "Units As Of" is a column: a
    #: movement carries a settlement date and a trade date, which are two facts
    #: about one row and are routinely days apart. Neither is spelled "As Of".
    #: That name means "the date the source says the *value* is for" on the
    #: other two views, and a third answer to that question is the thing this
    #: contract was written to stop.
    "Processed On",
    "Traded On",
    #: Not "Scraped At", which is what the other two views call the run that
    #: observed them and moves every sync. This is ``transactions.first_seen``:
    #: the run that saw the movement *first*, which never moves again, because
    #: a re-scrape of an overlapping window conflicts on the natural key and
    #: does nothing. Two meanings, so two names.
    "First Seen",
    "External Id",
)

#: How long an account's last known value may be carried forward before the
#: account drops out of the series rather than persisting at a stale number.
#:
#: Not the dashboard's STALE_DAYS, which is seven. That one answers "should a
#: human look at this account", and a week is right for it. This one answers
#: "may this account still be counted in a total", and a week is wrong for it:
#: Ally needs a manual sign-in and routinely goes longer, so a seven-day horizon
#: would drop a live account out of the series and restore it a run later. A
#: chart built that way collapses and recovers while looking entirely like data,
#: which is the failure this whole shape exists to avoid. Thirty days carries a
#: monthly cadence without carrying a broker that has genuinely stopped.
CARRY_DAYS: int = 30

#: The account series, in order. One row per account per date on which anything
#: in the workspace was observed -- not one per snapshot, because the whole
#: point is that brokers do not scrape on the same day.
#:
#: The first four columns are the same identity prefix the other three views
#: carry, so all four join on Broker + Account Key.
NET_WORTH_COLUMNS: tuple[str, ...] = (
    "Broker",
    "Source",
    "Account",
    "Account Key",
    #: The date this row stands on, which is the one column here no source ever
    #: claimed. It is not "As Of": that means "the date the source says the
    #: value is for", and on a carried row the source never said anything about
    #: this date at all. Two meanings, so two names -- the same rule that keeps
    #: "Units As Of" and "Processed On" off "As Of".
    "Date",
    "Value",
    "Currency",
    #: Whether this row's number was read on its Date or carried onto it. The
    #: reason the tab can exist honestly: a point that is nine parts observed
    #: and one part carried forward is not the same fact as one where everything
    #: was observed, and a chart rendering them identically asserts a precision
    #: it does not have.
    #:
    #: Two words, "observed" and "carried", rather than a blank for one of them.
    #: A blank cell means the source said nothing, everywhere else in this
    #: contract, and this column is computed here rather than reported by
    #: anyone -- so it always has an answer and always says it.
    #:
    #: Not a second spelling of "Cost Basis" on the holdings view. That one is
    #: what was paid for a position; this is whether a number is a reading or a
    #: carry. Neither name appears in the other's tuple, which the contract test
    #: pins.
    "Basis",
    #: The date the value was actually read for -- equal to Date on an observed
    #: row, and older on a carried one. The difference is how stale the point is,
    #: which is the question "Basis" answers yes-or-no and this one answers in
    #: days.
    "Observed On",
    #: What the source itself said, blank when it said nothing, exactly as on the
    #: account view. Beside "Observed On" rather than instead of it: "Observed
    #: On" always has a date because it falls back to the run's own, and the
    #: difference between the two is whether that date is the source's claim or
    #: StonkSmith's clock.
    "As Of",
    "Scraped At",
)


def _cell(value: Any) -> Any:
    """
    Render one value for a grid, leaving an absent one absent.

    None becomes an empty cell rather than 0 or "None". A source that reported
    no number is saying something different from one that reported zero, and a
    view that cannot tell them apart is the reason the database stores a
    nullable value in the first place.
    :param value: The stored value
    :return: The value, or "" when there is none
    """

    return "" if value is None else value


#: What a date this view has normalized looks like. _iso() below produces either
#: exactly this or the source's own text handed back untouched, so matching it is
#: how anything downstream tells a date that was read from one that was not.
ISO_DATE_PATTERN: str = r"^\d{4}-\d{2}-\d{2}$"

_ISO_DATE: re.Pattern[str] = re.compile(pattern=ISO_DATE_PATTERN)

#: An account whose As Of is older than this, or missing, is stale: listed on the
#: dashboard rather than quietly counted at full value, and reported by
#: `stonksmithdb stale` with an exit status a scheduler can act on.
#:
#: Here rather than in portfolio_sheet, where it used to live, because two things
#: now ask the question and they must not come to disagree about it. The panel
#: renders the rule as a Sheets QUERY and the check evaluates it in Python; a
#: number defined twice is a panel saying one thing while the alarm says another.
STALE_DAYS: int = 7


#: Runs of whitespace around the "/" in an account label, so a hand-typed
#: separator matches a generated one.
_SEPARATOR: re.Pattern[str] = re.compile(pattern=r"\s*/\s*")


def normalize_label(label: str) -> str:
    """
    Reduce an account label to something two sources can agree on.

    One side of the comparison is typed into a config file by hand, the other is
    built from whatever a source returned. Requiring those to match byte for
    byte means a config line silently does nothing over a capital letter or a
    doubled space -- and "silently does nothing" restores whatever the line was
    written to stop.

    The separator gets its own rule because it is the one piece of punctuation
    this format demands and therefore the one a person retypes: "Schwab /
    Beneficiary A 529 Plan" and "Schwab/Beneficiary A 529 Plan" are plainly the
    same account, and collapsing whitespace alone leaves them different strings.
    Every slash is treated the same way, on both sides, so a name that contains
    one is not a special case.

    Nothing else is touched. "Individual - TOD" and "Individual TOD" are not
    obviously the same account, and guessing wrong drops a real one -- the
    opposite failure, and the worse of the two.

    Here rather than in modules.snaptrade_module, where it was written, because
    two settings now identify an account by the same label: ``exclude_accounts``
    decides whether to write one and ``[ACCOUNTS] aliases`` decides what to call
    it. A label that matches one and not the other would be the worst kind of
    surprise -- an operator copying a working line from one option into the
    other and watching it do nothing -- so there is one rule and both import it.
    :param label: A "Source / Account" label, from either side
    :return: The label, case-folded, whitespace collapsed, separators evened out
    :rtype: str
    """

    return _SEPARATOR.sub(repl=" / ", string=" ".join(label.split())).casefold()


def as_date(as_of: str | None) -> dt.date | None:
    """
    An As Of as a real date, or None when it is not one.

    Public, unlike most of the helpers here, because a second module now needs
    exactly this judgement and must not arrive at its own. The brief cuts its
    dividend window on a source's date, and a window that admitted a spelling
    the staleness rule rejects would count income the panel beside it calls
    undated. A rule evaluated in two places is two chances for them to disagree
    about the same row, which is the argument STALE_DAYS already makes.

    Two gates, and both are load-bearing.

    The pattern first, because everything downstream compares these as *text*:
    the dashboard's staleness QUERY does a string comparison, and
    date.fromisoformat accepts spellings that do not compare that way --
    "20260810" parses and sorts below every hyphenated date. Admitting one here
    would make the panel and the check disagree about the same account, which is
    the single thing this rule exists to prevent.

    Then the parse, because a pattern is not a parse. "2026-13-45" matches
    ^\\d{4}-\\d{2}-\\d{2}$ and is not a date, and the shape check alone let it
    through: string-compared it sorts above the cutoff and read as *fresh*, so an
    account whose dates had gone wrong looked like the healthiest one owned. That
    is the failure this function was written to catch, surviving inside it.

    Whitespace is deliberately not stripped. A padded value is not tidied here
    because nothing tidies it on the tab either -- the panel compares what is
    stored -- so accepting " 2026-08-10 " as fresh would announce it as stale on
    the dashboard and fresh in the check. Reporting it is the conservative half
    of that choice and says something true: whatever wrote it skipped a
    normalization.
    :param as_of: The date the source says the value is for
    :return: The date, or None when it cannot be read as one
    :rtype: dt.date | None
    """

    if not as_of or not _ISO_DATE.match(string=as_of):
        return None

    try:
        return dt.date.fromisoformat(as_of)

    except ValueError:
        # Shaped like a date and not one: month 13, day 30 of February, zeroes.
        return None


def is_stale(as_of: str | None, cutoff: str) -> bool:
    """
    Whether an account's As Of has gone stale, failing closed three ways.

    Missing is stale: a number with no date attached is a claim about no
    particular day, and the dashboard's staleness panel exists to say so rather
    than count it at face value.

    Older than the cutoff is stale, which is the ordinary case.

    **Unparseable is stale, and this is the one a string comparison gets
    backwards.** "whenever" < "2026-08-04" is False, so a date the view could not
    normalize sorts above every real one and reads as fresher than today. The
    dashboard's QUERY has exactly this hole -- it is the same reason
    _date_cases() matches Processed On against ISO_DATE_PATTERN rather than
    trusting an ordering -- and Python can close it here. as_date is what
    decides, because matching the shape is not the same as being a date.
    :param as_of: The date the source says the value is for
    :param cutoff: The oldest date that still counts as fresh, ISO
    :return: True when the account cannot be shown to be fresh
    :rtype: bool
    """

    if as_date(as_of=as_of) is None:
        return True

    # Compared as text rather than as dates, because as_date has already
    # guaranteed both are YYYY-MM-DD -- which is the form the dashboard's QUERY
    # compares, so the two cannot part company over an account.
    return (as_of or "") < cutoff


def stale_reason(as_of: str | None, today: dt.date) -> str:
    """
    Why an account counts as stale, in the words a person needs.

    One phrasing per state is_stale rejects, beside it rather than at the call
    site: a reader who is told "stale" and not which of the three kinds is being
    sent to look at the wrong thing. An unparseable date in particular is not an
    old number -- it is a parser that stopped matching its source, and saying
    "42 days old" about it would be inventing an age from text that has none.
    :param as_of: The date the source says the value is for
    :param today: The day freshness is measured from
    :return: A phrase such as "as of 2026-01-31, 192 days old"
    :rtype: str
    """

    if not as_of:
        return "no as-of date"

    dated: dt.date | None = as_date(as_of=as_of)

    if dated is None:
        return f"an as-of date nothing could read: {as_of!r}"

    return f"as of {as_of}, {(today - dated).days} days old"


def stale_cutoff(today: dt.date, days: int = STALE_DAYS) -> str:
    """
    The oldest As Of that still counts as fresh.

    One derivation, shared by the panel and the check. _bands() bakes this into
    its QUERY rather than writing TEXT(TODAY()-7,...), so the formula is pinnable
    and free of TEXT's locale-dependent format string -- which means the two
    would silently disagree if each did its own arithmetic.
    :param today: The day freshness is measured from
    :param days: How many days old an As Of may be
    :return: The cutoff, ISO
    :rtype: str
    """

    return (today - dt.timedelta(days=days)).isoformat()


def _iso(date: str | None) -> str | None:
    """
    Render a stored transaction date as YYYY-MM-DD.

    The one place this view rewrites what the database holds, and it is not
    cosmetic. ``processed_on`` and ``traded_on`` are stored as the source wrote
    them, and the sources disagree: SnapTrade normalizes to ISO, while the 529
    scraper stores "12/30/2025" because its natural key is built from that text
    and normalizing at the producer would make every already-stored row look new.
    Two formats in one column sort wrong -- "12/30/2025" lands above
    "01/15/2026" -- so a tab ordered on it, and a dashboard cell reporting the
    newest movement, would both look right and be wrong.

    Normalizing here fixes that without touching a stored key. Anything that
    will not parse is handed back unchanged rather than blanked: an unreadable
    date is still evidence, and dropping it would hide the one row worth looking
    at.
    :param date: The date as the source wrote it
    :return: The date as YYYY-MM-DD, the original text if it will not parse, or
        None when there was none
    :rtype: str | None
    """

    if not date:
        return None

    return to_iso_date(text=date) or date


def _sortable(date: str | None) -> str:
    """
    The key a movement's date sorts on, which is not always the date itself.

    _iso keeps text it could not parse, because an unreadable date is still
    evidence and blanking it would hide the one row worth looking at. Sorting on
    that text is a different question, and the obvious answer is wrong: anything
    beginning with a letter compares above every digit, so a single "whenever"
    would sit at the top of the tab and be reported as the newest movement --
    turning a preserved oddity into a confident false statement.

    So a date that did not parse sorts as though it had none, which puts it at
    the far end rather than the near one. It keeps its cell; it just stops
    claiming to be the newest thing that happened.
    :param date: The date as this view renders it
    :return: The date when it is one, otherwise ""
    :rtype: str
    """

    return date if date and _ISO_DATE.match(string=date) else ""


def _observed_on(as_of: str | None, scraped_at: str) -> str:
    """
    The date one snapshot is evidence about.

    Two facts arrive per snapshot and neither alone answers this. ``as_of`` is
    the date the source says the value is for, and several sources never say it;
    ``scraped_at`` is when the run happened, and it is always there because
    StonkSmith writes it. So the source's own date is preferred and the run's
    date is the fallback, which is the same order of preference the dashboard's
    staleness panel already applies.

    Only a date that parses counts. _iso hands back text it could not read --
    deliberately, because an unreadable date is still evidence -- but a series
    cannot place a point on "whenever", and comparing that text to a real date
    puts it above every digit. So an unparseable ``as_of`` costs its snapshot
    the source's date and falls through to the run's, rather than costing it the
    row: the value was still observed, just on the day StonkSmith looked.
    :param as_of: The date the source says the value is for, if it said one
    :param scraped_at: The run timestamp, "YYYY-MM-DD HH:MM:SS"
    :return: A YYYY-MM-DD date, or "" when neither field holds one
    :rtype: str
    """

    claimed: str = _sortable(date=_iso(date=as_of))

    if claimed:
        return claimed

    # The date half of the run timestamp. Sliced rather than parsed because the
    # format is StonkSmith's own and fixed -- but still checked, so a database
    # holding something else does not put a point on a date-shaped nothing.
    return _sortable(date=str(object=scraped_at or "")[:10])


def _date(text: str) -> dt.date:
    """
    One YYYY-MM-DD string as a date, for measuring the gap a carry crosses.

    Only ever called on text _observed_on produced, which is why it can be this
    blunt: that function returns either a string _ISO_DATE matched or "", and
    the callers here drop the empty case before they get this far.
    :param text: A YYYY-MM-DD date
    :return: The date it spells
    :rtype: dt.date
    """

    return dt.date.fromisoformat(text)


def _reason(error: Exception) -> str:
    """
    Describe a failure in a way that always says something.

    An exception raised with no arguments stringifies to "" -- OSError() and
    sqlite3.DatabaseError() both do -- so str(e) alone can hand back a blank
    reason. A blank reason is worse than no field at all: it is a report that a
    broker could not be read, offering nothing about why, which is precisely the
    silence this field exists to break. The class name is always there.
    :param error: The exception to describe
    :return: A non-empty description
    :rtype: str
    """

    detail: str = str(object=error).strip()
    name: str = type(error).__name__

    return f"{name}: {detail}" if detail else name


@dataclass(frozen=True, slots=True)
class AccountRow:
    """
    One account, at whatever it was last observed to be worth.

    Frozen for the same reason the records in etc.records are: this is produced
    by a read and handed to a consumer, and nothing downstream should be editing
    it in place.
    """

    #: Which StonkSmith broker produced this -- "fidelity", "snaptrade", "tsp".
    broker: str

    #: The brokerage behind it, for an aggregator that names one. Falls back to
    #: the broker, so the column is never blank and can always be grouped on.
    source: str

    #: What to show a human. Free to change between runs; not identity.
    account: str

    #: Stable identity within this broker. What a formula should key on, and
    #: what the holding rows join back to.
    account_key: str

    kind: str | None = None
    beneficiary: str | None = None

    #: The value as a number, or None when the source reported none.
    value: float | None = None
    currency: str = "USD"

    #: The date the source says the value is for. Not when the run happened,
    #: and frequently absent -- several sources never say.
    as_of: str | None = None

    #: When the run that observed it happened.
    scraped_at: str = ""

    def cells(self) -> list[Any]:
        """
        This row in ACCOUNT_COLUMNS order.
        :return: One value per column
        :rtype: list[Any]
        """

        return [
            self.broker,
            self.source,
            self.account,
            self.account_key,
            _cell(self.kind),
            _cell(self.beneficiary),
            _cell(self.value),
            self.currency,
            _cell(self.as_of),
            _cell(self.scraped_at),
        ]


@dataclass(frozen=True, slots=True)
class HoldingRow:
    """
    One position behind one account's newest snapshot.

    Every position field is optional because the shapes this carries overlap
    only partly -- a scraped 529 fills fund code, principal and earnings; an API
    position fills symbol and cost basis. Neither filling the other's columns is
    normal rather than an error.
    """

    broker: str
    source: str
    account: str
    account_key: str

    #: The ticker, or the fund code for sources that do not trade in tickers.
    symbol: str | None = None
    name: str | None = None

    units: float | None = None
    price: float | None = None
    value: float | None = None
    cost_basis: float | None = None

    #: 529 plans report contributions and growth separately.
    principal: float | None = None
    earnings: float | None = None

    currency: str = "USD"
    as_of: str | None = None
    scraped_at: str = ""

    #: The date the unit count was true, where the source dates a quantity apart
    #: from its value. ``as_of`` above stays the value's date.
    units_as_of: str | None = None

    def cells(self) -> list[Any]:
        """
        This row in HOLDING_COLUMNS order.
        :return: One value per column
        :rtype: list[Any]
        """

        return [
            self.broker,
            self.source,
            self.account,
            self.account_key,
            _cell(self.symbol),
            _cell(self.name),
            _cell(self.units),
            _cell(self.price),
            _cell(self.value),
            _cell(self.cost_basis),
            _cell(self.principal),
            _cell(self.earnings),
            self.currency,
            _cell(self.as_of),
            _cell(self.scraped_at),
            _cell(self.units_as_of),
        ]


@dataclass(frozen=True, slots=True)
class TransactionRow:
    """
    One movement recorded against one account.

    Not tied to a snapshot, unlike HoldingRow. A holding is what an account held
    at one observation and is replaced wholesale by the next; a movement happened
    once, is keyed so a re-scrape of the same window records it once, and stays.
    So this carries every movement the database holds rather than the newest
    run's worth -- which is the whole point of the tab, and the reason the read
    behind it takes no limit.
    """

    broker: str
    source: str
    account: str
    account_key: str

    #: "Contribution", "BUY", "DIVIDEND" -- whatever the source calls it.
    tx_type: str | None = None

    #: Filled by sources that trade in tickers. A scraped 529 table has neither
    #: this nor a description.
    symbol: str | None = None
    description: str | None = None

    units: float | None = None
    price: float | None = None
    value: float | None = None
    currency: str = "USD"

    #: Settlement and trade date, normalized to ISO on the way out of the
    #: database. Two dates for one movement, days apart in the ordinary case.
    processed_on: str | None = None
    traded_on: str | None = None

    #: When StonkSmith first observed this movement. Deliberately not called
    #: "Scraped At": that moves every sync on the other two views, and this
    #: never moves again once written.
    first_seen: str = ""

    #: The source's own transaction id, where it has one.
    external_id: str | None = None

    def cells(self) -> list[Any]:
        """
        This row in TRANSACTION_COLUMNS order.
        :return: One value per column
        :rtype: list[Any]
        """

        return [
            self.broker,
            self.source,
            self.account,
            self.account_key,
            _cell(self.tx_type),
            _cell(self.symbol),
            _cell(self.description),
            _cell(self.units),
            _cell(self.price),
            _cell(self.value),
            self.currency,
            _cell(self.processed_on),
            _cell(self.traded_on),
            _cell(self.first_seen),
            _cell(self.external_id),
        ]


#: What the "Basis" column says of a value read on the date it sits on.
OBSERVED: str = "observed"

#: What it says of a value carried onto a date nobody read it on.
CARRIED: str = "carried"


@dataclass(frozen=True, slots=True)
class NetWorthRow:
    """
    One account on one date, at the last value anything knew it to be.

    The fourth shape, and the only one that is neither current state nor a log.
    Accounts and holdings are "what is true now"; transactions are "what
    happened". This is a *series*, and a series over sources that do not report
    together has to be constructed rather than read: see net_worth_history below
    for why summing snapshots by date instead would undercount.

    Which makes ``basis`` the load-bearing field. Every other row shape here
    carries only what a source said. This one carries some numbers that were
    read on their date and some that were carried onto it, and the column that
    tells them apart is what keeps that honest rather than merely convenient.
    """

    #: The same identity prefix the other three carry.
    broker: str
    source: str
    account: str
    account_key: str

    #: The date this row stands on. Always a date -- a row is never emitted for
    #: a date the series could not place.
    date: str = ""

    #: What the account was worth, as of ``observed_on`` rather than ``date``.
    #: Never None: an account with no value to carry is absent from the date
    #: rather than present at nothing, which is the row-shape rule one step on.
    #: A value the source never gave stays empty on the account view; here it
    #: does not become a row at all, because a series point with an empty value
    #: would be counted as a gap in a total rather than read as a silence.
    value: float | None = None

    currency: str = "USD"

    #: OBSERVED or CARRIED. See the column comment.
    basis: str = OBSERVED

    #: The date ``value`` was read for. Equal to ``date`` when observed.
    observed_on: str = ""

    #: The source's own date for that reading, where it gave one.
    as_of: str | None = None

    #: The run that took that reading.
    scraped_at: str = ""

    def cells(self) -> list[Any]:
        """
        This row in NET_WORTH_COLUMNS order.
        :return: One value per column
        :rtype: list[Any]
        """

        return [
            self.broker,
            self.source,
            self.account,
            self.account_key,
            self.date,
            _cell(self.value),
            self.currency,
            self.basis,
            self.observed_on,
            _cell(self.as_of),
            _cell(self.scraped_at),
        ]


@dataclass(frozen=True, slots=True)
class Portfolio:
    """
    Everything the workspace's databases currently say, and what could not be
    asked.

    ``unreadable`` is not decoration. A read that quietly returns four brokers
    when five were expected produces a total that is wrong by a whole account
    and looks perfectly reasonable, which is the failure this project keeps
    finding: the run reported success because from its side nothing went wrong.
    """

    accounts: tuple[AccountRow, ...] = ()
    holdings: tuple[HoldingRow, ...] = ()

    #: Every movement every broker holds, not the newest run's worth.
    transactions: tuple[TransactionRow, ...] = ()

    #: Brokers whose database was opened and read, in the order read.
    brokers_read: tuple[str, ...] = ()

    #: (name, reason) for anything that could not be read -- normally a broker,
    #: or the workspace itself when the whole directory is missing.
    unreadable: tuple[tuple[str, str], ...] = ()

    #: The account series: every account on every date anything was observed.
    #: Appended after ``unreadable`` rather than slotted in beside the three row
    #: tuples it belongs with, on the same instinct the columns follow -- every
    #: construction of this class is by keyword, so nothing breaks either way,
    #: and a field that has always been fifth is easier to reason about later
    #: than one that used to be fourth.
    net_worth: tuple[NetWorthRow, ...] = ()

    #: Every position every snapshot held, when the read asked for it, and empty
    #: otherwise. Appended last, on the rule above.
    #:
    #: **Empty here does not mean the portfolio holds nothing.** It means nobody
    #: asked -- read_databases only fills this under ``with_history``, because it
    #: is an order of magnitude larger than the other tuples and only the brief's
    #: trend column reads it. A consumer that inferred "no history" from an empty
    #: tuple would be reading a decision about cost as a fact about the money,
    #: which is why this comment is longer than the field.
    holdings_history: tuple[HoldingRow, ...] = ()

    #: `[ACCOUNTS] cost_basis` lines that were not used, each with the reason.
    #:
    #: Carried on the record rather than recomputed by the caller, unlike the
    #: alias check beside it, because after the costs are filled in the fact is
    #: gone: a holding whose cost this supplied and one whose broker reported it
    #: are indistinguishable by then, and "that line was ignored" is exactly the
    #: distinction. A reason that cannot be re-derived has to be carried out --
    #: the argument ``unreadable`` already makes one field up.
    unused_costs: tuple[str, ...] = ()

    def total(self, currency: str = "USD") -> float:
        """
        What the accounts in one currency add up to.

        Only accounts, never holdings, and only one currency at a time: adding a
        dollar to a euro produces a number that is not wrong so much as
        meaningless, and nothing here knows a rate.
        :param currency: The currency to total
        :return: The sum of the matching accounts' values
        :rtype: float
        """

        # Started at 0.0 rather than sum()'s implicit int 0, so a portfolio with
        # nothing in it returns the same type as one with something in it. A
        # total that is an int only when it is empty is the kind of thing that
        # works everywhere until it reaches the one caller that checks.
        return sum(
            (
                row.value
                for row in self.accounts
                if row.value is not None and row.currency == currency
            ),
            0.0,
        )

    def invested(self, currency: str = "USD") -> float:
        """
        What the positions in one currency add up to.

        The other half of the pair, and never a substitute for it. ``total`` is
        what the accounts say the money is; this is what the positions account
        for, and the two differ by whatever is sitting uninvested in a balance
        and in no holding. Anything drawing a breakdown of the portfolio needs
        both, because a share computed over this number alone silently leaves
        the cash out and still adds to 100%.

        Same currency rule as ``total``, for the same reason, and the same 0.0
        start so an empty portfolio returns the type a full one does.
        :param currency: The currency to total
        :return: The sum of the matching holdings' values
        :rtype: float
        """

        return sum(
            (
                row.value
                for row in self.holdings
                if row.value is not None and row.currency == currency
            ),
            0.0,
        )


def _account_row(broker: str, row: tuple[Any, ...]) -> AccountRow:
    """
    Project one account tuple into the account view's shape.

    Shared by read_broker and read_history because the two reads behind them
    return the same nine columns deliberately -- get_account_history is
    get_current_accounts with its newest-snapshot restriction taken off. One
    mapping rather than two means the fallbacks below cannot drift apart, which
    would show an account under one name on one tab and another on the next.
    :param broker: The broker name, which becomes the Broker column
    :param row: One row in get_current_accounts() order
    :return: The account as this view spells it
    :rtype: AccountRow
    """

    (
        account_key,
        source,
        display_name,
        beneficiary,
        kind,
        value,
        currency,
        as_of,
        scraped_at,
    ) = row

    return AccountRow(
        broker=broker,
        # Only an aggregator fills this; a direct scraper is its own source.
        source=str(object=source or "").strip() or broker,
        account=display_name,
        account_key=account_key,
        kind=kind,
        beneficiary=beneficiary,
        value=value,
        currency=currency or "USD",
        as_of=as_of,
        scraped_at=scraped_at or "",
    )


def _cost_from_principal(value: Any, principal: Any, earnings: Any) -> float | None:
    """
    Principal read as a cost basis, but only where the row proves it is one.

    A 529 states contributions and growth rather than an average purchase price,
    and principal is the same fact under the other name -- so where a source
    fills that and not ``cost_basis``, the cost was being shown as a dash with
    the number sitting one column over.

    **The check is not defensive padding.** ``helpers.schwab529plan`` says it
    outright: principal and earnings are *table-level totals repeated onto every
    row*, because the page never splits them per fund. So on an account holding
    two funds, both rows carry the whole account's principal -- and reading that
    unconditionally would give each position the entire account's cost, roughly
    doubling the basis and inverting the gain. Inventing a per-position number
    from an account-level one, which is the thing this codebase keeps refusing
    to do.

    The source hands over the means to tell the two apart. It states earnings as
    well, so ``value - principal`` has to reproduce it: true on the row that owns
    the whole account, false on any row that is one fund of several. Where it
    does not hold, the cost stays absent -- a dash, which is honest -- rather than
    becoming a number nobody can check.

    The comparison is in whole cents, allowed to be one out; the reason for each
    of those is at the line itself.
    :param value: What the position is worth
    :param principal: What the source says was put in
    :param earnings: What the source says was made on it
    :return: The cost basis, or None where the row cannot vouch for it
    :rtype: float | None
    """

    if value is None or principal is None or earnings is None:
        return None

    try:
        # Compared as whole cents, and allowed to be one out.
        #
        # Both halves of that are deliberate. Cents because the float form was
        # not the check its own comment described: 2200.00 - 2040.01 - 159.98 is
        # 0.010000000000019327 in binary floating point, so `> 0.01` *rejected* a
        # row exactly a cent out, while a different triple a cent out would pass.
        # A boundary that moves with the values is not a boundary. Those three
        # numbers are the ones test_a_row_a_single_cent_out_is_still_read uses,
        # and they are chosen rather than illustrative -- a triple that does not
        # land the wrong side of 0.01 demonstrates nothing, which is exactly how
        # this comment came to cite one that did not.
        #
        # One cent because the page rounds all three figures independently, so
        # the identity can legitimately land a cent from zero. Nothing is given
        # away by allowing it: the case being screened for -- an account total
        # stamped onto one fund of several -- misses by hundreds, not by pennies.
        if (
            abs(
                round(float(value) * 100)
                - round(float(principal) * 100)
                - round(float(earnings) * 100)
            )
            > 1
        ):
            return None

        return float(principal)

    except TypeError, ValueError:
        return None


def _holding_row(
    broker: str, row: tuple[Any, ...], by_key: dict[str, AccountRow]
) -> HoldingRow:
    """
    Project one position tuple into the holding view's shape.

    Shared by read_broker and read_holdings_history for the reason _account_row
    is shared by read_broker and read_history: the two reads behind them return
    the same fifteen columns deliberately, get_holdings_history being
    get_current_holdings with its newest-snapshot restriction taken off. One
    mapping rather than two means the fallbacks below cannot drift apart, which
    would show a position under one name in the holdings table and another in
    the trend drawn beside it.
    :param broker: The broker name, which becomes the Broker column
    :param row: One row in get_current_holdings() order
    :param by_key: The accounts this broker returned, keyed by account_key
    :return: The position as this view spells it
    :rtype: HoldingRow
    """

    (
        account_key,
        _position,
        symbol,
        fund_code,
        name,
        units,
        price,
        value,
        principal,
        earnings,
        cost_basis,
        currency,
        as_of,
        scraped_at,
        units_as_of,
    ) = row

    parent: AccountRow | None = by_key.get(account_key)

    return HoldingRow(
        broker=broker,
        # A position whose account did not come back is not something the real
        # query can produce -- it joins through accounts. It is still carried
        # rather than dropped, keyed by the one identity it definitely has,
        # because losing a position silently is worse than showing one whose
        # name is a key.
        source=parent.source if parent else broker,
        account=parent.account if parent else account_key,
        account_key=account_key,
        # Which of the two a source fills is a fact about the source; the column
        # shows whichever there is.
        symbol=symbol or fund_code,
        name=name,
        units=units,
        price=price,
        value=value,
        # Read here rather than left to each consumer. Everything downstream --
        # purchase price, gain, growth, yield on cost, the win/loss flag -- is
        # computed from cost_basis, so a source reporting its cost under another
        # name was showing a dash on all five while the number sat in the column
        # beside them. Both fields are still carried out unchanged; this fills
        # the one that was empty, and never the reverse, since a source stating
        # both means them separately. _cost_from_principal has the rule, and the
        # reason it is a rule rather than a plain fallback.
        cost_basis=(
            cost_basis
            if cost_basis is not None
            else _cost_from_principal(
                value=value, principal=principal, earnings=earnings
            )
        ),
        principal=principal,
        earnings=earnings,
        currency=currency or "USD",
        # The snapshot's date, still: what the position is worth is as of when
        # its value was struck. The quantity's own date rides separately,
        # because for TSP they are weeks apart.
        as_of=as_of,
        scraped_at=scraped_at or "",
        units_as_of=units_as_of,
    )


def read_broker(
    broker: str, db: PortfolioDbProtocol
) -> tuple[list[AccountRow], list[HoldingRow], list[TransactionRow]]:
    """
    Project one already-open broker database into the canonical rows.

    Separate from read_workspace, which does the opening, so that this -- the
    part with the mapping decisions in it -- can be tested against literals.
    :param broker: The broker name, which becomes the Broker column
    :param db: An open database
    :return: Its accounts, their positions, and every movement recorded
    :rtype: tuple[list[AccountRow], list[HoldingRow], list[TransactionRow]]
    """

    accounts: list[AccountRow] = []
    by_key: dict[str, AccountRow] = {}

    for current in db.get_current_accounts():
        row: AccountRow = _account_row(broker=broker, row=current)
        accounts.append(row)
        by_key[row.account_key] = row

    holdings: list[HoldingRow] = [
        _holding_row(broker=broker, row=current, by_key=by_key)
        for current in db.get_current_holdings()
    ]

    transactions: list[TransactionRow] = []

    for (
        account_key,
        tx_type,
        symbol,
        description,
        units,
        price,
        value,
        currency,
        processed_on,
        traded_on,
        first_seen,
        external_id,
    ) in db.get_current_transactions():
        parent = by_key.get(account_key)

        transactions.append(
            TransactionRow(
                broker=broker,
                # Same fallback as the holdings loop, for the same reason: a
                # movement whose account did not come back is carried by the one
                # identity it definitely has rather than dropped.
                source=parent.source if parent else broker,
                account=parent.account if parent else account_key,
                account_key=account_key,
                tx_type=tx_type,
                symbol=symbol,
                description=description,
                units=units,
                price=price,
                value=value,
                currency=currency or "USD",
                processed_on=_iso(date=processed_on),
                traded_on=_iso(date=traded_on),
                first_seen=first_seen or "",
                external_id=external_id,
            )
        )

    # Ordered here rather than in SQL, which is where the other two views are
    # ordered, because the column being sorted is only comparable once _iso has
    # been over it -- see the note there. Two stable sorts rather than one key:
    # the dates go newest-first, then the accounts group without disturbing
    # them, and the reader's own tie-break survives underneath both.
    transactions.sort(key=lambda row: _sortable(date=row.processed_on), reverse=True)
    transactions.sort(key=lambda row: (row.source, row.account))

    return accounts, holdings, transactions


def read_history(broker: str, db: PortfolioDbProtocol) -> list[AccountRow]:
    """
    Every snapshot one broker holds, as account rows rather than as the newest.

    Separate from read_broker rather than a fourth element of its return,
    because what comes back here is not a fourth tab. It is the input to
    net_worth_history, which cannot run per broker: the dates a broker's
    accounts have to be carried onto belong to the *other* brokers, and a
    function that only ever sees one database cannot know them.

    An AccountRow per snapshot rather than a shape of its own. An observation is
    an account row -- the same nine facts about the same account -- and the only
    thing distinguishing it from the one on the Accounts tab is that a newer one
    exists. Inventing a near-identical record to say that would be the
    duplication etc.portfolio was written to end.
    :param broker: The broker name, which becomes the Broker column
    :param db: An open database
    :return: One row per stored snapshot, oldest first within each account
    :rtype: list[AccountRow]
    """

    return [_account_row(broker=broker, row=row) for row in db.get_account_history()]


def read_holdings_history(broker: str, db: PortfolioDbProtocol) -> list[HoldingRow]:
    """
    Every position one broker has ever recorded, oldest snapshot first.

    The counterpart to read_history, and separate from read_broker for the same
    reason that one is: what comes back is not a fourth tab, it is the input to
    a trend. A HoldingRow per snapshot rather than a shape of its own, because a
    past position *is* a holding row -- the same facts about the same position,
    distinguished only by a newer one existing.

    Read on request rather than always, unlike read_history. The account series
    is one row per snapshot and every consumer of a Portfolio needs it; this is
    one row per *position* per snapshot, so on a workspace with a dozen holdings
    it is an order of magnitude larger and only the brief's trend column wants
    it. The sheet sync runs on every broker run and would pay for it every time.
    :param broker: The broker name, which becomes the Broker column
    :param db: An open database
    :return: One row per position per snapshot, oldest first
    :rtype: list[HoldingRow]
    """

    by_key: dict[str, AccountRow] = {
        row.account_key: row
        for row in (
            _account_row(broker=broker, row=current)
            for current in db.get_current_accounts()
        )
    }

    return [
        _holding_row(broker=broker, row=past, by_key=by_key)
        for past in db.get_holdings_history()
    ]


def net_worth_history(
    observations: Iterable[AccountRow], horizon_days: int = CARRY_DAYS
) -> list[NetWorthRow]:
    """
    The account series, built so that every date sums the same set of accounts.

    **The problem this exists to solve is not plumbing.** Brokers do not scrape
    on the same day: Ally needs a manual sign-in and may go a week, TSP runs
    unattended, SnapTrade runs whenever. Group the stored snapshots by date and
    total them, and a date on which only one broker ran has one broker's money
    on it. The resulting chart shows a portfolio that repeatedly collapses and
    recovers -- while looking entirely like data, which is what makes it worse
    than no chart.

    So each account's last known value is carried forward onto every later date,
    and every point sums the same accounts. That is the correct construction and
    it is also partly made up, which is why three things are true of it:

    - **A carried value says it was carried.** ``basis`` is OBSERVED or CARRIED
      on every row, and ``observed_on`` says how far the carry reached. The same
      argument "As Of" and "Scraped At" already settle: two different facts, two
      names, and nothing rendering them identically.
    - **A carry does not reach forever.** Past ``horizon_days`` the account drops
      out of the series rather than persisting at a stale value. Crossing a
      weekend is not crossing a quarter.
    - **An account that did not exist yet is absent, not zero.** No row is
      emitted for a date before that account's first reading. Zero and absent
      are different, and the row-shape rules already say a value the source never
      gave stays empty rather than becoming 0 -- because an account that
      reported no number is not an account worth nothing. A back-filled zero
      would be that same mistake with a number invented on top.

    The dates are the ones something was actually read on, not every day on the
    calendar. A point exists because a broker ran, so nothing here invents a
    date any more than it invents a value -- and the tab grows with the number
    of runs rather than with the passage of time.
    :param observations: Every snapshot from every broker, in any order
    :param horizon_days: How long a value may be carried before its account
        drops out of the series
    :return: One row per account per date it can be placed on, oldest first
        within each account
    :rtype: list[NetWorthRow]
    """

    # Keyed on (broker, account_key) because identity is per-broker: account_key
    # is unique inside one broker's database and means nothing outside it, so
    # two brokers sharing a key are two accounts and must not merge into one
    # series. Same reason nothing here dedupes a 529 held under two names.
    readings: dict[tuple[str, str], dict[str, AccountRow]] = {}

    for row in observations:
        # A snapshot with no value is the source declining to say, which is not
        # a reading. It cannot become a carried value, it does not reset a carry
        # that is already running, and it does not put a date on the axis --
        # a date whose only event was a silence would be a point on which every
        # account was carried, which is a chart of nothing pretending otherwise.
        if row.value is None:
            continue

        on: str = _observed_on(as_of=row.as_of, scraped_at=row.scraped_at)

        if not on:
            continue

        # Last one wins within a date. The read comes back ordered by
        # scraped_at, so that is the latest reading of that account that day --
        # the same rule get_current_accounts applies across all dates.
        readings.setdefault((row.broker, row.account_key), {})[on] = row

    axis: list[str] = sorted({on for dates in readings.values() for on in dates})

    if not axis:
        return []

    horizon: dt.timedelta = dt.timedelta(days=horizon_days)
    series: list[NetWorthRow] = []

    def label(key: tuple[str, str]) -> tuple[str, str, str, str]:
        """
        Where one account's block of the series sorts.

        Read off the account's *newest* reading, not off each row. Every row
        carries the source and display name of whichever reading it carries,
        and a display name is explicitly not identity -- it is free to change,
        and does. Sorting the rows on it would put an account renamed halfway
        through its history in two separate blocks of the tab, each internally
        in order and neither one the account. So the ordering is decided once
        per account, on the name it goes by now, and the rows underneath keep
        the order they were built in.
        :param key: The (broker, account_key) this account is grouped under
        :return: Its sort position
        :rtype: tuple[str, str, str, str]
        """

        newest: AccountRow = readings[key][max(readings[key])]

        # Broker and key break the tie, so two accounts that display the same
        # still order deterministically rather than by dictionary order.
        return (newest.source, newest.account, *key)

    # Ordered here rather than by sorting the finished rows, which is also why
    # nothing sorts them afterwards: each account's block is emitted in axis
    # order, which is ascending, and the blocks are emitted in this one.
    #
    # Forward in time within each, not newest-first like Transactions. That one
    # is a log, where the last thing that happened is the thing you came to
    # read; this is a series, which is read in the direction it was lived.
    for dates in [readings[key] for key in sorted(readings, key=label)]:
        # Walked in step with the axis rather than searched per date: both are
        # sorted, so one pass over each is enough and a workspace with years of
        # runs does not turn into a quadratic scan.
        observed: list[str] = sorted(dates)
        at: int = 0
        carried: AccountRow | None = None

        for date in axis:
            while at < len(observed) and observed[at] <= date:
                carried = dates[observed[at]]
                at += 1

            # Nothing read at or before this date. The account did not exist
            # yet, as far as anything here can know, so it is absent.
            if carried is None:
                continue

            on = _observed_on(as_of=carried.as_of, scraped_at=carried.scraped_at)

            if _date(text=date) - _date(text=on) > horizon:
                continue

            series.append(
                NetWorthRow(
                    broker=carried.broker,
                    source=carried.source,
                    account=carried.account,
                    account_key=carried.account_key,
                    date=date,
                    value=carried.value,
                    # The carried reading's own currency, never a converted one.
                    # Portfolio.total refuses to add a dollar to a euro and this
                    # must not do quietly what that declines to do loudly.
                    currency=carried.currency,
                    basis=OBSERVED if on == date else CARRIED,
                    observed_on=on,
                    as_of=carried.as_of,
                    scraped_at=carried.scraped_at,
                )
            )

    return series


def workspace_path(workspace: str | None = None, root: Path | None = None) -> Path:
    """
    Where a workspace's broker databases live.
    :param workspace: The workspace name, or None for the configured one
    :param root: The directory workspaces live in, for tests
    :return: The workspace directory, which may not exist
    :rtype: Path
    """

    return Path(root or workspace_dir) / (workspace or get_workspace())


def account_label(row: AccountRow | HoldingRow | TransactionRow | NetWorthRow) -> str:
    """
    The "Source / Account" label a config line names an account by.

    The same spelling the SnapTrade sync prints and ``exclude_accounts`` matches
    on, so a label copied out of a run works in either setting.
    :param row: Any row carrying the identity prefix
    :return: The label
    :rtype: str
    """

    return f"{row.source} / {row.account}"


def apply_aliases(portfolio: Portfolio, aliases: dict[str, str]) -> Portfolio:
    """
    Rewrite the display name of every row whose account the operator renamed.

    Applied once here, on the way out of the databases, rather than at each
    consumer. The sheet and the brief are two views of one read, and an account
    that is "Robin 401(k)" on one and "ACME CORPORATION SAVINGS PLUS
    401(K) PLAN" on the other is two accounts to anybody comparing them.

    Every row shape carries the name, not just the account view -- holdings and
    movements repeat it, and a holdings table still saying the broker's wording
    under a renamed account is the same inconsistency one table further down.

    Nothing stored changes. This is a display name, and the identity every join
    and every baseline uses is ``account_key``, which is untouched. That is what
    makes renaming safe to do and to undo: an alias added, changed or removed
    tonight does not orphan a single stored row.
    :param portfolio: What the workspace holds
    :param aliases: Label to display name, from the config
    :return: The same portfolio under the operator's own names
    :rtype: Portfolio
    """

    if not aliases:
        return portfolio

    named: dict[str, str] = {
        normalize_label(label=label): name for label, name in aliases.items()
    }

    def rename[RowT: AccountRow | HoldingRow | TransactionRow | NetWorthRow](
        rows: tuple[RowT, ...],
    ) -> tuple[RowT, ...]:
        renamed: list[RowT] = []

        for row in rows:
            # Normalized once and looked up with get(), rather than normalized
            # for the test and again for the subscript. holdings_history is one
            # row per position per snapshot, so this runs tens of thousands of
            # times on a workspace with any history behind it.
            alias: str | None = named.get(normalize_label(label=account_label(row=row)))
            renamed.append(replace(row, account=alias) if alias else row)

        return tuple(renamed)

    return replace(
        portfolio,
        accounts=rename(portfolio.accounts),
        holdings=rename(portfolio.holdings),
        transactions=rename(portfolio.transactions),
        net_worth=rename(portfolio.net_worth),
        holdings_history=rename(portfolio.holdings_history),
    )


def apply_costs(portfolio: Portfolio, costs: dict[str, float]) -> Portfolio:
    """
    Fill in what the operator paid, where the source reported no cost basis.

    Applied **before** the aliases, deliberately: both settings name an account
    by the label the broker gave, and renaming first would leave every stated
    cost looking for an account under a name it no longer has. That is the same
    ordering trap ``unmatched_aliases`` documents from the other side.

    **A stated cost never overwrites a reported one.** What SnapTrade returns is
    a real average over real lots; what a config line carries is a figure typed
    off a statement. Where both exist the source wins and the line is reported
    as unused, because silently preferring the typed number would let a stale
    config quietly diverge from a broker that has been right all along.

    Assigned only when the account has exactly **one** uncosted holding. Every
    account this exists for holds a single position, and an account holding
    three would need the lump sum split between them -- which cannot be done
    from a total without inventing the per-position gains that the split
    decides. Refused and reported instead, which is the same answer
    ``get_account_costs`` gives a line it cannot parse.
    :param portfolio: What the workspace holds
    :param costs: Label to cost, from the config
    :return: The portfolio with stated costs filled in, carrying the lines that
        were not used and why
    :rtype: Portfolio
    """

    if not costs:
        return portfolio

    stated: dict[str, float] = {
        normalize_label(label=label): cost for label, cost in costs.items()
    }

    #: Which holdings each named account has, and how many of them still want a
    #: cost. Counted over the whole account before anything is assigned, since
    #: "exactly one" is a fact about the account rather than about the row.
    wanting: dict[str, list[int]] = {}
    holdings: list[HoldingRow] = list(portfolio.holdings)

    for index, row in enumerate(holdings):
        label: str = normalize_label(label=account_label(row=row))

        if label in stated and row.cost_basis is None:
            wanting.setdefault(label, []).append(index)

    #: Every account the config names that the workspace actually has, whether
    #: or not it wanted a cost. Separates "no such account" from "that account
    #: already reports its own cost", which are different mistakes.
    present: set[str] = {
        normalize_label(label=account_label(row=row)) for row in portfolio.holdings
    }
    unused: list[str] = []

    for label, cost in costs.items():
        key: str = normalize_label(label=label)
        rows: list[int] = wanting.get(key, [])

        if not rows:
            unused.append(
                f"{label} (already reports its own cost basis)"
                if key in present
                else f"{label} (no holding in this workspace)"
            )
            continue

        if len(rows) > 1:
            unused.append(
                f"{label} ({len(rows)} holdings report no cost basis, so a single "
                "total cannot be divided between them without inventing the split)"
            )
            continue

        holdings[rows[0]] = replace(holdings[rows[0]], cost_basis=cost)

    return replace(portfolio, holdings=tuple(holdings), unused_costs=tuple(unused))


def unmatched_aliases(portfolio: Portfolio, aliases: dict[str, str]) -> list[str]:
    """
    Alias lines that name no account in the workspace.

    Reported rather than ignored, on the rule the asset class table already
    follows: a line that quietly matches nothing is a typo that looks like a
    working setting. It is also how a broker renaming an account surfaces --
    the alias stops landing, and the account silently reverting to the broker's
    own wording is exactly the outcome the alias was added to prevent.
    :param portfolio: What the workspace holds
    :param aliases: Label to display name, from the config
    :return: The labels that matched nothing, in the order given
    :rtype: list[str]
    """

    present: set[str] = {
        normalize_label(label=account_label(row=row)) for row in portfolio.accounts
    }
    missing: list[str] = []

    for label, name in aliases.items():
        if normalize_label(label=label) in present:
            continue

        # **The portfolio has usually already been renamed by the time anything
        # asks.** read_databases applies the aliases on the way out, so the
        # accounts carry the new names and not one original label matches -- and
        # a check that stopped at the line above would report every *working*
        # alias as broken, every morning. An alarm that is wrong whenever the
        # feature is working is worse than no alarm.
        #
        # So a label also counts as matched when the account it names is present
        # under the name this alias gives it: the source half of the original,
        # with the new name on the end.
        #
        # Split on the *first* slash, not the last. The separator is the one
        # between source and account, and an account name may itself contain one
        # -- "Fidelity / Individual / TOD" is a real shape and normalize_label
        # supports it deliberately. Taking the last slash makes the source
        # "Fidelity / Individual" there, so the rebuilt label matches nothing and
        # a working alias reports as broken.
        source: str = label.partition("/")[0].strip()

        if normalize_label(label=f"{source} / {name}") in present:
            continue

        missing.append(label)

    return missing


def read_databases(paths: Iterable[Path], with_history: bool = False) -> Portfolio:
    """
    Read the given broker databases into one set of canonical rows.

    The broker name is the file stem, which is how main.py names them in the
    first place. Databases are opened directly as BrokerDatabase rather than
    through each broker's Database subclass: those subclasses do nothing but set
    the name this already knows, and going through BrokerLoader would import
    five broker packages -- and their optional dependencies -- to run a read.

    Opening is not free of writes. BrokerDatabase applies its pending
    migrations on open, so a database written before account history is upgraded
    by being read. That is deliberate: the alternative is a read path that
    cannot see the oldest data. It does mean a sheet sync of one broker upgrades
    every broker in the workspace, which is worth knowing rather than surprising.

    Each engine is disposed as well as its session closed. shutdown_db() ends
    the session; the engine's pool holds the SQLite file handle open regardless,
    and this now runs on every broker run rather than only from the shell.
    :param paths: Database files, one per broker
    :param with_history: Also read every position from every snapshot. Off by
        default because it is an order of magnitude more rows than the current
        positions and only the brief's trend column wants them -- the sheet sync
        runs on every broker run and would otherwise pay for it every time.
    :return: Their accounts and positions, and whatever would not open
    :rtype: Portfolio
    """

    accounts: list[AccountRow] = []
    holdings: list[HoldingRow] = []
    transactions: list[TransactionRow] = []
    observations: list[AccountRow] = []
    positions: list[HoldingRow] = []
    read: list[str] = []
    unreadable: list[tuple[str, str]] = []

    for path in paths:
        broker: str = path.stem
        db: BrokerDatabase | None = None
        engine: Engine | None = None

        try:
            engine = create_db_engine(db_path=path)
            db = BrokerDatabase(db_engine=engine, broker=broker)
            broker_accounts, broker_holdings, broker_transactions = read_broker(
                broker=broker, db=db
            )
            broker_observations: list[AccountRow] = read_history(broker=broker, db=db)
            broker_positions: list[HoldingRow] = (
                read_holdings_history(broker=broker, db=db) if with_history else []
            )

        # Deliberately broad. A file in this directory can fail to be a usable
        # database in more ways than are worth enumerating -- corrupt, truncated,
        # unreadable, or simply not SQLite -- and one bad file must not cost the
        # caller the other four brokers. What it must not do is vanish, so the
        # reason is carried out rather than logged and forgotten.
        except Exception as e:
            unreadable.append((broker, _reason(e)))
            continue

        finally:
            if db is not None:
                db.shutdown_db()

            if engine is not None:
                engine.dispose()

        accounts.extend(broker_accounts)
        holdings.extend(broker_holdings)
        transactions.extend(broker_transactions)
        observations.extend(broker_observations)
        positions.extend(broker_positions)
        read.append(broker)

    return apply_aliases(
        # Costs first, aliases second, and the order is load-bearing. Both
        # settings name an account by the label the broker gave, so renaming
        # first would leave every stated cost hunting for an account under a
        # name it no longer has -- and reporting each working line as unused,
        # which is the failure mode unmatched_aliases had to be written around.
        portfolio=apply_costs(
            portfolio=Portfolio(
                accounts=tuple(accounts),
                holdings=tuple(holdings),
                transactions=tuple(transactions),
                brokers_read=tuple(read),
                unreadable=tuple(unreadable),
                # Built here rather than inside the loop, and that is the whole
                # design. The dates one broker's accounts must be carried onto are
                # the dates the *other* brokers ran on, so the series cannot be
                # assembled a database at a time -- a per-broker series would each
                # be right on its own and sum to a portfolio that collapses every
                # day only one of them scraped.
                net_worth=tuple(net_worth_history(observations=observations)),
                holdings_history=tuple(positions),
            ),
            costs=get_account_costs()[0],
        ),
        # Read here rather than passed in, so every consumer of the canonical
        # read gets the operator's names without having to know they exist.
        aliases=get_account_aliases(),
    )


def read_workspace(
    workspace: str | None = None,
    root: Path | None = None,
    with_history: bool = False,
) -> Portfolio:
    """
    Every account, position and movement across every broker in one workspace.

    This is the single read path out of the databases: a worksheet sync, a
    dashboard, or anything else that wants to show what is held consumes this
    rather than reaching into a broker's tables and inventing its own shape.
    :param workspace: The workspace name, or None for the configured one
    :param root: The directory workspaces live in, for tests
    :param with_history: Also read every position from every snapshot
    :return: What the workspace holds, and whatever would not open
    :rtype: Portfolio
    """

    directory: Path = workspace_path(workspace=workspace, root=root)

    if not directory.is_dir():
        # Reported rather than returned as an empty portfolio, which reads
        # identically to a workspace whose brokers have simply never run.
        return Portfolio(
            unreadable=((directory.name, f"no workspace directory at {directory}"),)
        )

    return read_databases(
        paths=sorted(directory.glob(pattern="*.db")), with_history=with_history
    )


def stale_accounts(portfolio: Portfolio, cutoff: str) -> tuple[AccountRow, ...]:
    """
    Every account that cannot be shown to be fresh: no date first, then oldest.

    The two that carry no age come first as a group -- a missing date and one
    nothing could read are both "no evidence" rather than old evidence, and
    sorting them in among real dates by their text would rank 'whenever' as
    younger than a genuine January. Below them, ISO dates sort chronologically
    because they sort as text, the same property the dashboard leans on when it
    sorts dates rather than MAXing them.
    :param portfolio: What the workspace holds
    :param cutoff: The oldest As Of that still counts as fresh, ISO
    :return: The stale accounts, the least dated first
    :rtype: tuple[AccountRow, ...]
    """

    found: list[AccountRow] = [
        row for row in portfolio.accounts if is_stale(as_of=row.as_of, cutoff=cutoff)
    ]

    def order(row: AccountRow) -> tuple[int, str, str]:
        # The same parse is_stale and stale_reason use, not the shape alone: a
        # row reported as carrying no readable date must not then be sorted in
        # among the ones that do, or the list contradicts its own entries.
        dated: bool = as_date(as_of=row.as_of) is not None

        return (1 if dated else 0, row.as_of or "", row.broker)

    return tuple(sorted(found, key=order))
