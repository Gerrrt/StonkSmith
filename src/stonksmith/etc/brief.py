# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""
What changed since the last time anybody looked.

The databases have always known this and nothing has ever asked them. The sheet
shows what is true now, and `stale` reports what has stopped moving. Neither
answers the question a person actually opens a dashboard with -- what moved
since I last looked -- because answering it needs a baseline, and "last time I
looked" is not a property of the data. It is a fact about the reader, so it is
recorded here rather than derived.

**The delta is built on Portfolio.net_worth, never on a per-broker read.**
BrokerDatabase.get_daily_change() computes a LAG over one broker's snapshots,
and summing five of those re-creates exactly the bug net_worth_history() exists
to prevent: brokers do not scrape on the same day, so a date on which only TSP
ran carries TSP's movement and four brokers' worth of silence, and the silence
reads as a fall. The series already carries every account forward onto every
observed date so that every date sums the same set of accounts. That is the only
axis on which two dates can honestly be subtracted, so it is the only one used.

Which makes the observed/carried split the thing this module must not drop. A
night when only TSP ran produces a real movement for one account and a carried
number for the others, and reporting the sum as "the portfolio moved" asserts a
precision the reading does not have. Every Movement says which it is and the
Brief counts both, so the render has no way to show one without the other.
"""

import datetime as dt
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from stonksmith.etc.config import (
    get_account_colors,
    get_asset_classes,
    get_brief_fund_link,
)
from stonksmith.etc.dividends import Dividends, Paid
from stonksmith.etc.permissions import restrict
from stonksmith.etc.portfolio import (
    OBSERVED,
    STALE_DAYS,
    AccountRow,
    HoldingRow,
    NetWorthRow,
    Portfolio,
    TransactionRow,
    as_date,
    stale_accounts,
    stale_cutoff,
    stale_reason,
)

#: The schema version of the baseline file. Read back and checked rather than
#: assumed: a baseline written by a future version is not a baseline this one can
#: subtract against, and treating it as absent produces a first-brief -- which
#: says so -- instead of a delta computed against fields that moved.
BASELINE_VERSION: int = 1

#: What a symbol has to look like before it is linked to a quote page.
#:
#: One to five **ASCII** letters, and the ASCII part is load-bearing rather than
#: pedantic: str.isalpha() is true of Cyrillic and full-width characters too, so
#: a scraped symbol could otherwise put arbitrary text into a URL. Constrained
#: this tightly, there is nothing left to inject with.
#:
#: It is also what keeps a link off the holdings that have no public page.
#: "Q4R7" is a 401k fund code, "70310" a 529 portfolio number and "L 2060" a TSP
#: fund -- real positions, none of them findable on a quote site, and a link that
#: 404s is worse than no link because the reader has to click to learn that.
_TICKER: re.Pattern[str] = re.compile(pattern=r"^[A-Za-z]{1,5}$")

#: What an unclassified position is grouped under. The same wording the config
#: comment uses for the sheet's allocation block, because a reader comparing the
#: two should not have to work out whether they mean the same slice.
UNCLASSIFIED: str = "(unclassified)"


class BriefState(StrEnum):
    """
    What kind of morning this is, decided once so the render never re-derives it.

    Four states rather than a bool, because "there is nothing to report" has
    three genuinely different causes and they call for different words. A first
    brief has no baseline, a stalled one has a baseline nothing has moved past,
    and a degraded one is missing a broker's money -- which is not a quiet day,
    it is a wrong total. Collapsing them would produce the one screen this whole
    feature exists to avoid: a calm dashboard over a scraper that stopped.
    """

    #: No baseline yet. Movers are absent because nothing can be compared, which
    #: is not the same as nothing having moved.
    FIRST = "first"

    #: A baseline, and a newer scrape to compare it against. The ordinary day.
    FRESH = "fresh"

    #: A baseline, and nothing newer. The nightly run did not land.
    NO_NEW_SCRAPE = "no new scrape"

    #: At least one broker's database would not open, so the total is short by
    #: whatever it held. Outranks the other three: a number that is wrong matters
    #: more than a number that is old.
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class Mark:
    """
    One position as the last brief was shown it.

    Units as well as value, because the two move for different reasons and the
    difference is the whole story of a row. A position whose value rose on
    unchanged units was repriced by the market; one whose units rose was bought.
    Storing value alone would render those identically, and the second is the one
    worth a reader's attention.
    """

    value: float | None = None
    units: float | None = None


@dataclass(frozen=True, slots=True)
class Baseline:
    """
    What the last brief was shown, so the next one can say what changed.

    Persisted rather than derived, and that is the point of the feature. The
    stateless alternative -- compare the two newest dates on the axis -- answers
    a different question: it reports the last scrape rather than everything since
    the reader last looked. On a Tuesday those agree. On a Monday the stateless
    form silently drops the weekend, and on a morning the reader skipped it drops
    that day forever, because the run it would have been compared against has
    itself become the baseline.
    """

    #: The newest net-worth date the last brief reported on. What decides whether
    #: anything has happened since.
    taken_on: str = ""

    #: When that brief was rendered. Displayed, never compared -- see
    #: ``seen_through`` for why a wall clock is the wrong thing to compare.
    shown_at: str = ""

    #: The high-water mark of ``transactions.first_seen`` at that moment.
    #:
    #: A watermark taken from the column it filters rather than from a clock.
    #: ``shown_at`` is this process's idea of now and ``first_seen`` is whatever
    #: the database wrote, and comparing the two makes correctness depend on the
    #: two agreeing about format and timezone forever. Compared against itself,
    #: the filter is exact whatever either of them looks like.
    seen_through: str = ""

    #: What the portfolio totalled, per currency.
    totals: dict[str, float] = field(default_factory=dict)

    #: Every position, keyed (broker, account_key, symbol).
    holdings: dict[tuple[str, str, str], Mark] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Movement:
    """
    One account or one position, and what it did since the baseline.

    ``basis`` carries whether the *after* number was observed on its date or
    carried onto it, which is the field that keeps a mover list honest. A row
    reading "+$412" off a value nobody read today is a statement about the last
    day somebody did, and a list that renders it identically to a fresh reading
    invites exactly the wrong conclusion.
    """

    label: str
    broker: str
    before: float | None = None
    after: float | None = None
    delta: float = 0.0

    #: The move as a fraction of ``before``. None when ``before`` was zero or
    #: absent: an account going from nothing to something has no percentage, and
    #: reporting one -- or a zero -- would invent a denominator.
    pct: float | None = None

    #: OBSERVED or CARRIED, from the series row this was read off.
    basis: str = OBSERVED

    #: How the position's quantity moved, for holdings. None for accounts and
    #: for a position whose units did not change.
    units_delta: float | None = None

    #: Whose account this is, as a colour name from [ACCOUNTS] colors. Empty
    #: when nothing matched, which renders no dot rather than a default one.
    color: str = ""


@dataclass(frozen=True, slots=True)
class Allocation:
    """One asset class, at what it is worth now and what it was worth before."""

    label: str
    value: float = 0.0
    share: float = 0.0

    #: The share of the portfolio this class held at the baseline, or None when
    #: there is no baseline to compare against. Absent rather than zero, on the
    #: rule the row shapes already follow: a class that was not measured is not a
    #: class that was measured at nothing.
    was: float | None = None


#: How far back the dividend figures reach. A trailing year rather than a
#: calendar one, so the number means the same thing every morning instead of
#: collapsing to nothing each January and climbing back over twelve months.
DIVIDEND_DAYS: int = 365

#: What a transaction type has to contain to count as a dividend. Matched
#: case-insensitively on a substring because the sources disagree and always
#: will -- SnapTrade says "DIVIDEND", a 529 statement says "Dividend Reinvest",
#: and a reinvested dividend is still income received.
DIVIDEND_MARKERS: tuple[str, ...] = ("DIVIDEND", "DIV ", "DISTRIBUTION")


@dataclass(frozen=True, slots=True)
class Position:
    """
    One holding, with everything a performance table wants to say about it.

    Wider than HoldingRow on purpose, and a different kind of thing. That one is
    what a source reported; this is what follows from it -- gain, growth, yield,
    the day's move. Keeping them apart is what stops a derived number from being
    mistaken for a reported one, which matters most for the fields that are
    routinely absent: a position whose source never gave a cost basis has no
    gain, and no amount of arithmetic will produce one.
    """

    symbol: str
    broker: str
    account: str
    name: str | None = None

    #: From the operator's [ALLOCATION] table, or UNCLASSIFIED. The closest
    #: thing to the sheet's "Industry" column that any source here can support:
    #: no broker reports a sector, so this is what was declared rather than what
    #: was looked up.
    asset_class: str = UNCLASSIFIED

    units: float | None = None
    price: float | None = None
    value: float | None = None
    currency: str = "USD"

    #: What was paid, where the source says. SnapTrade does; TSP and the scraped
    #: 529 do not, and every field below that divides by it is None for them.
    cost_basis: float | None = None

    #: cost_basis / units -- the sheet's "Purchase" column. Derived rather than
    #: reported: no source states an average purchase price, and inverting the
    #: two numbers that are stated is exact.
    purchase_price: float | None = None

    gain: float | None = None
    growth: float | None = None

    #: The move since the previous snapshot of this same position, as a
    #: fraction. None when there is no earlier snapshot to compare against --
    #: which is every position on the first run, and is not a zero-percent day.
    day_change: float | None = None

    #: Trailing-twelve-month income attributed to this position, from the
    #: transaction log rather than from a quoted yield. Money that arrived.
    div_income: float | None = None

    #: What a year at this position would pay: the fund's trailing per-share
    #: distributions times the units held. A forecast, not a record -- see
    #: etc.dividends for why the two are carried apart rather than merged.
    #: None when the feed has nothing for this symbol, which is not zero.
    indicated_income: float | None = None
    indicated_yield: float | None = None
    current_yield: float | None = None
    yield_on_cost: float | None = None

    #: The value series behind this position, oldest first, for the trend.
    trend: tuple[float, ...] = ()

    #: Whose account holds this, as a colour name from [ACCOUNTS] colors.
    color: str = ""

    #: Where this symbol's quote page is, or empty when it has none. A 401k fund
    #: code and a 529 portfolio number are real holdings with nothing to link to.
    url: str = ""

    #: How the quantity moved since the last brief, where it moved at all.
    #:
    #: On the position rather than in a movers list, which is where it used to
    #: live. The list was replaced by the full holdings table, and this is the
    #: one thing it said that the table does not: a row whose value rose on an
    #: unchanged count was repriced by the market, and one whose count rose was
    #: bought. Those are different events and the second is the one worth a
    #: reader's morning. None when nothing moved, so an ordinary repricing
    #: carries no note -- a "0 units" line on every row would bury the handful
    #: that are trades.
    units_delta: float | None = None

    @property
    def winning(self) -> bool | None:
        """
        Whether this position is ahead of what was paid for it.

        Three-valued rather than two. A position with no cost basis is neither a
        win nor a loss, and the sheet's W/L column has no spelling for that --
        so None is rendered as a dash rather than defaulting to "L", which would
        report every TSP and 529 holding as losing money.
        :return: True, False, or None where nothing was paid that anyone recorded
        :rtype: bool | None
        """

        return None if self.gain is None else self.gain >= 0


@dataclass(frozen=True, slots=True)
class Performance:
    """
    The portfolio as a whole: what it is worth, what it cost, what it earns.

    The six-tile summary, and three fields that exist to keep it honest. ``cost``
    is the sum over positions that *have* a cost basis, which on this workspace
    is not all of them -- so ``priced`` and ``unpriced`` travel with it, and the
    render states them. A gain computed over nine of twelve positions is a real
    number about part of a portfolio, and presenting it as the portfolio's gain
    is the same error the observed/carried split exists to prevent one screen up.
    """

    #: What the *accounts* say the money is -- the same number the headline
    #: reports, deliberately. Summing the positions instead gives a different
    #: figure, and a page carrying two numbers both fairly called "portfolio
    #: value" is one a reader has to reconcile by hand.
    value: float = 0.0
    currency: str = "USD"

    #: What the positions account for. Lower than ``value`` by whatever is
    #: sitting uninvested in a balance and in no holding, which is a real fact
    #: about the portfolio rather than a discrepancy -- so both are carried and
    #: the render states the difference instead of hiding it.
    invested: float = 0.0

    cost: float | None = None
    gain: float | None = None
    growth: float | None = None

    #: How many positions carried a cost basis, and how many did not.
    priced: int = 0
    unpriced: int = 0

    holdings: int = 0

    dividend_income: float = 0.0
    dividend_yield: float | None = None

    #: How many days of transaction log the dividend figure actually stands on,
    #: capped at DIVIDEND_DAYS. A "yearly" income built from four months of log
    #: is a quarter of a year's dividends called a year's, and the only way to
    #: tell is to say so.
    dividend_days: int = 0

    #: What a year at the current positions would pay, and over how many of
    #: them it is known. The coverage travels with the figure for the reason the
    #: priced/unpriced split does: on this workspace a 401k, a TSP fund and a 529
    #: are two thirds of the money and none has a public ticker, so a blended
    #: yield across all twelve positions understates the six that are known.
    indicated_income: float = 0.0
    indicated_yield: float | None = None
    indicated_over: int = 0
    indicated_value: float = 0.0

    #: Whether any dividend was found at all.
    #:
    #: Distinct from ``dividend_income == 0`` because the two mean different
    #: things and the render says different words for them. Zero income across a
    #: year of log is a portfolio that pays nothing. No dividend rows *at all* is
    #: a transaction log that has never carried one -- which is this workspace,
    #: where the sources report contributions and transfers and the income
    #: arrives as a reinvestment nobody itemised. The second is not a fact about
    #: the money and must not be rendered as one.
    dividends_seen: bool = False

    #: The sheet's Total Win / Total Loss pair: gains and losses summed
    #: separately rather than netted, because the net hides both.
    total_win: float = 0.0
    total_loss: float = 0.0


@dataclass(frozen=True, slots=True)
class Brief:
    """
    Everything one morning's brief has to say, assembled before anything renders.

    Frozen and computed in one pass for the reason the row shapes in
    etc.portfolio are: the render is a second consumer of this data, not a second
    place that decides what it means. A template that reached back into the
    portfolio to work out its own totals would be free to disagree with the
    headline it sits under.
    """

    state: BriefState = BriefState.FIRST

    #: The newest date on the series axis -- the day this brief reports on.
    as_of: str = ""

    #: The baseline's date, so the render can say what window it covers.
    since: str = ""

    currency: str = "USD"
    total: float = 0.0
    delta: float = 0.0
    pct: float | None = None

    #: How many of the accounts behind ``total`` were read on ``as_of``, and how
    #: many were carried onto it. Rendered together, always.
    observed: int = 0
    carried: int = 0

    account_movers: tuple[Movement, ...] = ()
    holding_movers: tuple[Movement, ...] = ()

    #: How many accounts moved but did not fit in ``account_movers``.
    #:
    #: Carried so the page can say so. A ranking capped at eight ends without
    #: comment on the ninth, which reports the eighth as the smallest thing that
    #: moved -- the quiet truncation this project names about get_transactions,
    #: whose five-hundred-row limit is precisely why that read cannot back a
    #: sheet. Zero on any ordinary morning, and the line is absent then.
    account_movers_dropped: int = 0
    new_transactions: tuple[TransactionRow, ...] = ()
    allocation: tuple[Allocation, ...] = ()

    #: (account, reason) for everything that cannot be shown to be fresh.
    stale: tuple[tuple[str, str], ...] = ()

    #: (name, reason) for whatever would not open, carried straight through from
    #: the portfolio. The reason ``state`` can be DEGRADED.
    unreadable: tuple[tuple[str, str], ...] = ()

    #: The trailing series the sparkline is drawn from: (date, total, observed).
    series: tuple[tuple[str, float, bool], ...] = ()

    #: Every position held, largest first. Not a movers list -- the whole book,
    #: less anything under [BRIEF] min_position.
    positions: tuple[Position, ...] = ()

    #: How many positions were held but too small to earn a row.
    #:
    #: Display only, and every total still counts them: the portfolio value, the
    #: invested figure and the cash line are unaffected. A row removed from a
    #: page is a presentation choice; a dollar removed from a total is a lie, and
    #: this project's rule about silent truncation is why the count is carried
    #: rather than the rows simply vanishing.
    positions_hidden: int = 0

    #: What the book is worth, cost and earns.
    performance: Performance = field(default_factory=Performance)


def totals_by_date(
    rows: Iterable[NetWorthRow], currency: str = "USD"
) -> dict[str, float]:
    """
    What the portfolio was worth on each date the series covers.

    The delta engine, and the only place a portfolio total per date is computed.
    Summing the series rather than the snapshots is the whole correctness claim:
    net_worth_history has already carried every account onto every observed date,
    so each key here totals the same set of accounts as every other key. Summing
    account_snapshots by date instead would total whoever happened to run.

    One currency at a time, for Portfolio.total's reason -- adding a dollar to a
    euro produces a number that is not wrong so much as meaningless, and nothing
    here knows a rate.
    :param rows: The account series, in any order
    :param currency: The currency to total
    :return: Date to portfolio total, for every date the series places
    :rtype: dict[str, float]
    """

    totals: dict[str, float] = {}

    for row in rows:
        if row.value is None or row.currency != currency:
            continue

        # Started from the running total rather than a defaultdict so a date that
        # exists in the series always exists here, at whatever it summed to --
        # including 0.0, which is a real answer and not a missing one.
        totals[row.date] = totals.get(row.date, 0.0) + row.value

    return totals


def _pct(before: float | None, delta: float) -> float | None:
    """
    A move as a fraction of what it moved from, where that means anything.

    None rather than zero when there is nothing to divide by. An account that
    appeared since the baseline moved by its whole value and by no percentage at
    all, and a zero there would render as "unchanged" -- the one reading of a new
    account that is definitely wrong.
    :param before: The value moved from
    :param delta: The move
    :return: The fraction, or None when there is no denominator
    :rtype: float | None
    """

    if not before:
        return None

    return delta / abs(before)


def _account_marks(
    rows: Iterable[NetWorthRow], on: str
) -> dict[tuple[str, str], NetWorthRow]:
    """
    Every account's series row for one date, keyed by identity.

    Keyed (broker, account_key) rather than on the display name, for the reason
    net_worth_history groups on it: a name is free to change between runs and
    does, so an account renamed since the baseline would compare against nothing
    and appear as one account closing and another opening.
    :param rows: The account series
    :param on: The date to take
    :return: (broker, account_key) to that account's row on that date
    :rtype: dict[tuple[str, str], NetWorthRow]
    """

    return {(row.broker, row.account_key): row for row in rows if row.date == on}


def account_movements(
    rows: Iterable[NetWorthRow],
    since: str,
    until: str,
    palette: Iterable[tuple[str, str]] = (),
) -> list[Movement]:
    """
    What each account did between two dates on the series axis.

    Read off the series rather than off the accounts, which is what makes the
    comparison well-defined: an account absent from ``until`` was not read that
    day *and* could not be carried onto it, so it has dropped past the carry
    horizon and genuinely has no value there. One absent from ``since`` did not
    exist yet, and is reported as an arrival rather than as a rise from zero.
    :param rows: The account series
    :param since: The baseline date
    :param until: The date being reported on
    :return: One movement per account that moved, largest absolute move first
    :rtype: list[Movement]
    """

    series: list[NetWorthRow] = list(rows)
    before: dict[tuple[str, str], NetWorthRow] = _account_marks(rows=series, on=since)
    after: dict[tuple[str, str], NetWorthRow] = _account_marks(rows=series, on=until)

    moves: list[Movement] = []

    for key, row in after.items():
        was: NetWorthRow | None = before.get(key)
        prior: float | None = None if was is None else was.value
        delta: float = (row.value or 0.0) - (prior or 0.0)

        if not delta:
            continue

        moves.append(
            Movement(
                label=row.account,
                broker=row.broker,
                before=prior,
                after=row.value,
                delta=delta,
                pct=_pct(before=prior, delta=delta),
                basis=row.basis,
                color=owner_color(name=row.account, palette=palette),
            )
        )

    return sorted(moves, key=lambda move: abs(move.delta), reverse=True)


def holding_key(row: HoldingRow) -> tuple[str, str, str]:
    """
    How one position is identified across briefs.

    The symbol rather than the position's ordinal, even though the database keys
    holdings on ``position``. That ordinal is identity *within* a snapshot -- it
    is what lets two rows of the same fund stay two rows -- and it is not stable
    between snapshots, so a broker that reorders its table would report every
    position as having been sold and a different one bought.
    :param row: A position
    :return: Its (broker, account_key, symbol) identity
    :rtype: tuple[str, str, str]
    """

    return (row.broker, row.account_key, row.symbol or "")


def mark_holdings(rows: Iterable[HoldingRow]) -> dict[tuple[str, str, str], Mark]:
    """
    Every position as it stands now, ready to be stored as a baseline.

    Positions sharing an identity are summed rather than overwriting each other.
    Two rows of the same fund in one account are two rows to the database and one
    holding to a reader, and letting the last one win would report the difference
    between them as a move the next morning.
    :param rows: The current positions
    :return: Identity to its mark
    :rtype: dict[tuple[str, str, str], Mark]
    """

    marks: dict[tuple[str, str, str], Mark] = {}

    for row in rows:
        key: tuple[str, str, str] = holding_key(row=row)
        held: Mark = marks.get(key, Mark(value=None, units=None))

        marks[key] = Mark(
            value=_add(left=held.value, right=row.value),
            units=_add(left=held.units, right=row.units),
        )

    return marks


def _add(left: float | None, right: float | None) -> float | None:
    """
    Add two numbers either of which the source may never have given.

    None plus a number is that number, and None plus None stays None. Treating an
    absent value as zero would turn "the source said nothing" into "the source
    said none", which is the distinction the whole row-shape contract is built
    to keep.
    :param left: The running total, or None
    :param right: The addend, or None
    :return: Their sum, or None when neither was given
    :rtype: float | None
    """

    if left is None:
        return right

    if right is None:
        return left

    return left + right


def holding_movements(
    rows: Iterable[HoldingRow], baseline: dict[tuple[str, str, str], Mark]
) -> list[Movement]:
    """
    What each position did since the baseline was taken.

    Compared against the stored baseline rather than against an earlier snapshot,
    because there is no earlier snapshot to read: the canonical read returns each
    account's *newest* positions only, and holdings are replaced wholesale by
    every run. The baseline file has to exist for the account delta regardless,
    so carrying positions in it costs one more key and no new database surface.
    :param rows: The current positions
    :param baseline: What those positions were worth when the last brief ran
    :return: One movement per position that moved, largest absolute move first
    :rtype: list[Movement]
    """

    moves: list[Movement] = []

    for key, mark in mark_holdings(rows=rows).items():
        was: Mark | None = baseline.get(key)

        if was is None:
            # A position held now and absent from the baseline is an arrival, and
            # its whole value is the move. Skipped only when it is worth nothing,
            # which is a row the source reported rather than an event.
            was = Mark(value=None, units=None)

        delta: float = (mark.value or 0.0) - (was.value or 0.0)
        units: float = (mark.units or 0.0) - (was.units or 0.0)

        if not delta and not units:
            continue

        moves.append(
            Movement(
                label=key[2] or "(no symbol)",
                broker=key[0],
                before=was.value,
                after=mark.value,
                delta=delta,
                pct=_pct(before=was.value, delta=delta),
                # Units are reported only when they moved. A position repriced on
                # an unchanged count would otherwise carry a "0 units" note,
                # which reads as a fact about a trade rather than the absence of
                # one.
                units_delta=units or None,
            )
        )

    return sorted(moves, key=lambda move: abs(move.delta), reverse=True)


def allocation_breakdown(
    rows: Iterable[HoldingRow],
    classes: dict[str, str],
    baseline: dict[tuple[str, str, str], Mark],
) -> list[Allocation]:
    """
    What the portfolio holds, by the asset classes the operator declared.

    No source states an asset class -- SnapTrade gives a ticker, a scraped 529 a
    fund code, TSP a fund -- so this groups by the one hand-kept table there is
    and names the rest rather than guessing. A position whose symbol is not
    listed lands under UNCLASSIFIED instead of being dropped, because a breakdown
    that silently omits a holding is one whose shares no longer add up.
    :param rows: The current positions
    :param classes: Symbol to asset class, from the config
    :param baseline: What those positions were worth when the last brief ran
    :return: One entry per class, largest first, or none when nothing is declared
    :rtype: list[Allocation]
    """

    if not classes:
        # Nothing declared, so nothing to break down. The same rule the sheet's
        # allocation block follows, and the config comment states it: a chart
        # that is one 100% "(unclassified)" slice tells a reader nothing, and
        # drawing it wastes the one section of this page most likely to be the
        # reason somebody scrolled.
        return []

    now: dict[str, float] = {}
    then: dict[str, float] = {}

    for key, mark in mark_holdings(rows=rows).items():
        label: str = classes.get(key[2], UNCLASSIFIED)
        now[label] = now.get(label, 0.0) + (mark.value or 0.0)

        was: Mark | None = baseline.get(key)
        then[label] = then.get(label, 0.0) + (
            0.0 if was is None else (was.value or 0.0)
        )

    total: float = sum(now.values())
    prior: float = sum(then.values())

    return sorted(
        (
            Allocation(
                label=label,
                value=value,
                share=value / total if total else 0.0,
                # None rather than zero when there was no baseline to measure
                # against, so a class that has always been 4% is not rendered as
                # one that has just grown from nothing.
                was=(then[label] / prior) if prior else None,
            )
            for label, value in now.items()
        ),
        key=lambda entry: entry.value,
        reverse=True,
    )


def new_transactions(
    rows: Iterable[TransactionRow], seen_through: str
) -> list[TransactionRow]:
    """
    Every movement recorded since the baseline was taken.

    Filtered on ``first_seen``, which is the run that saw a movement *first* and
    never moves again once written. ``scraped_at`` -- the field the account and
    holding views sort on -- moves every sync, so filtering on it would re-report
    the same dividend every morning for as long as it stayed in the scraped
    window.
    :param rows: Every movement the workspace holds
    :param seen_through: The baseline's high-water mark
    :return: The new movements, newest first
    :rtype: list[TransactionRow]
    """

    fresh: list[TransactionRow] = [
        row for row in rows if row.first_seen and row.first_seen > seen_through
    ]

    return sorted(fresh, key=lambda row: row.first_seen, reverse=True)


def watermark(rows: Iterable[TransactionRow]) -> str:
    """
    The newest ``first_seen`` in the workspace, or empty when there are none.

    Empty rather than a floor date on an empty workspace: every real first_seen
    sorts above "", so the first brief to see a movement reports it. A synthetic
    floor would have to be older than every timestamp any database might hold,
    which is a guess about the past that nothing can check.
    :param rows: Every movement the workspace holds
    :return: The high-water mark
    :rtype: str
    """

    return max((row.first_seen for row in rows if row.first_seen), default="")


def _is_dividend(tx_type: str | None) -> bool:
    """
    Whether a movement is income received rather than a trade or a transfer.
    :param tx_type: What the source called it
    :return: True when it looks like a dividend or distribution
    :rtype: bool
    """

    if not tx_type:
        return False

    upper: str = tx_type.upper()

    return any(marker in upper for marker in DIVIDEND_MARKERS)


def dividends(
    rows: Iterable[TransactionRow], today: dt.date, days: int = DIVIDEND_DAYS
) -> tuple[dict[str, float], int]:
    """
    Trailing income per symbol, and how much log that figure actually stands on.

    Two returns rather than one, and the second is the point. A workspace whose
    transaction log begins four months ago produces a perfectly good sum that is
    four months of dividends -- and calling it "yearly income" makes it look like
    a portfolio yielding a third of what it does. Nothing in the number itself
    reveals that, so the span comes back beside it and the render says so.

    Attributed by symbol, so a movement the source recorded without one is
    counted in the portfolio total and against no position. That is the honest
    place for it: the money was received, and which holding paid it is a fact
    nobody wrote down.
    :param rows: Every movement the workspace holds
    :param today: The day the window is measured back from
    :param days: How far back to reach
    :return: (symbol to income, days of log the figure covers)
    :rtype: tuple[dict[str, float], int]
    """

    since: dt.date = today - dt.timedelta(days=days)
    income: dict[str, float] = {}
    earliest: dt.date | None = None

    for row in rows:
        # processed_on rather than first_seen. The watermark question is "has
        # this reader seen it", which first_seen answers; this one is "when was
        # the money paid", and only the source's own date knows that. A window
        # cut on first_seen would drop every dividend on the morning after a
        # workspace was rebuilt, because they were all first seen today.
        paid: dt.date | None = as_date(as_of=row.processed_on or row.traded_on)

        if (
            paid is None
            or paid < since
            or paid > today
            or not _is_dividend(tx_type=row.tx_type)
        ):
            continue

        if earliest is None or paid < earliest:
            earliest = paid

        income[row.symbol or ""] = income.get(row.symbol or "", 0.0) + (
            row.value or 0.0
        )

    # Measured from the oldest dividend actually seen, not from the oldest row
    # in the log. A log that reaches back two years but whose first dividend
    # landed last month covers a month of income, and the span that matters is
    # the one the number was built from.
    covered: int = 0 if earliest is None else min(days, (today - earliest).days)

    return income, covered


def trends(rows: Iterable[HoldingRow]) -> dict[tuple[str, str, str], list[float]]:
    """
    Each position's value series, oldest first.

    Built from the holdings history rather than from the account series, because
    a position is not an account: two holdings inside one account move
    differently and summing them would draw the account's line under both.

    Snapshots are keyed on ``scraped_at`` rather than on the date, so two runs
    on one day are two points here -- which is the opposite of what the net worth
    axis does, and deliberate. That axis exists so every date sums the same
    accounts, which requires one point per date. This is one position's own
    history, where nothing has to line up with anything, so an intraday mark is
    simply another reading.
    :param rows: Every position from every snapshot, oldest first
    :return: Identity to its value series
    :rtype: dict[tuple[str, str, str], list[float]]
    """

    series: dict[tuple[str, str, str], dict[str, float]] = {}

    for row in rows:
        if row.value is None:
            continue

        when: str = row.scraped_at or row.as_of or ""

        if not when:
            continue

        # Summed within a reading, for mark_holdings' reason: two rows of the
        # same fund in one snapshot are two rows to the database and one holding
        # to a reader.
        marks: dict[str, float] = series.setdefault(holding_key(row=row), {})
        marks[when] = marks.get(when, 0.0) + row.value

    return {
        key: [marks[when] for when in sorted(marks)] for key, marks in series.items()
    }


def _series(
    totals: dict[str, float], rows: Iterable[NetWorthRow], keep: int
) -> tuple[tuple[str, float, bool], ...]:
    """
    The trailing portfolio series, each point saying whether anything read it.

    A point is observed when *any* account was read on its date, because that is
    the claim the sparkline actually makes -- that the line moved because
    something was measured. A date on which every account was carried is a
    straight segment drawn between two readings, and it is marked so the render
    can draw it as one.
    :param totals: Date to portfolio total
    :param rows: The account series
    :param keep: How many trailing points to keep
    :return: (date, total, observed) oldest first
    :rtype: tuple[tuple[str, float, bool], ...]
    """

    read: set[str] = {row.date for row in rows if row.basis == OBSERVED}

    return tuple(
        (on, totals[on], on in read) for on in sorted(totals)[-keep:] if keep > 0
    )


def _stale_pairs(portfolio: Portfolio, today: dt.date) -> tuple[tuple[str, str], ...]:
    """
    Every account that cannot be shown to be fresh, with why, in reading order.

    Delegates to etc.portfolio rather than re-deciding: the dashboard panel, the
    `stale` command and this brief must not come to disagree about an account,
    and a rule evaluated in three places is three chances to.
    :param portfolio: What the workspace holds
    :param today: The day freshness is measured from
    :return: (account, reason) pairs
    :rtype: tuple[tuple[str, str], ...]
    """

    cutoff: str = stale_cutoff(today=today, days=STALE_DAYS)
    rows: tuple[AccountRow, ...] = stale_accounts(portfolio=portfolio, cutoff=cutoff)

    return tuple(
        (
            f"{row.broker} / {row.account}",
            stale_reason(as_of=row.as_of, today=today),
        )
        for row in rows
    )


def _state(
    baseline: Baseline | None, as_of: str, unreadable: tuple[tuple[str, str], ...]
) -> BriefState:
    """
    Which kind of morning this is.

    DEGRADED is checked first and outranks everything, including a perfectly
    fresh scrape. A workspace missing a broker produces a total that is short by
    whatever that broker held, and a wrong number reported calmly is worse than
    an old one reported loudly -- the failure this project keeps rediscovering is
    the run that reported success because from its side nothing went wrong.
    :param baseline: What the last brief was shown, or None
    :param as_of: The newest date on the axis
    :param unreadable: Whatever would not open
    :return: The state
    :rtype: BriefState
    """

    if unreadable:
        return BriefState.DEGRADED

    if baseline is None or not baseline.taken_on:
        return BriefState.FIRST

    return BriefState.FRESH if as_of > baseline.taken_on else BriefState.NO_NEW_SCRAPE


def significant(moves: Iterable[Movement], limit: int) -> tuple[Movement, ...]:
    """
    Which of the movers are worth putting in front of a reader.

    **The largest by dollar, capped at ``[BRIEF] movers``.** A ranking rather
    than a threshold, and that is the settled choice among three that were all
    defensible:

    - A **dollar floor** -- ``abs(delta) > 50`` -- keeps a rounding wiggle on the
      largest account off the page, and also hides a four percent day on the
      smallest one. On a book where one 401k is two thirds of the money, that
      floor is simultaneously too low for the big account and too high for
      every other.
    - A **percentage floor** -- ``abs(pct) > 0.005`` -- does the reverse, and
      makes a cash account holding twelve dollars the loudest row on the page
      every single morning. It also has nothing to say about an account that
      arrived since the baseline: ``pct`` is None for those, because there is no
      denominator, so a percentage rule has to decide whether an arrival is
      always worth a row or never one, and neither answer is right.
    - A **ranking** has no threshold to be wrong about. It shows the same number
      of rows every day, which is what makes it readable at half past six, and
      it is invariant to the size of the portfolio -- the one property a floor of
      either kind loses the moment the book grows.

    The cost is that it can drop a real mover, and a list that silently ends at
    eight reports the eighth as the smallest thing that moved -- the
    quiet-truncation failure this project already names about `get_transactions`,
    whose five-hundred-row limit is why that read cannot back a sheet.

    **This function does not report what it dropped.** It returns the rows that
    fit and nothing else, and the caller counts the difference: build_brief sets
    ``Brief.account_movers_dropped`` from the same list it passes here, and
    brief_html states it under the table. Kept that way rather than returning a
    pair, because the count is only meaningful against the list this was given
    and build_brief is holding that list already -- returning it from here would
    be the same subtraction done twice, in two places free to disagree about how
    many accounts moved.

    Dollars rather than percent for the ranking itself, because the reader's
    question at that hour is what moved the portfolio, and a portfolio is moved
    by dollars. The percentage is on the row beside it for the ones that make
    the cut.
    :param moves: Every movement that was non-zero, largest absolute move first
    :param limit: How many rows the brief has room for
    :return: The ones to render, in the order given
    :rtype: tuple[Movement, ...]
    """

    return tuple(moves)[:limit]


def fund_url(symbol: str, template: str) -> str:
    """
    Where a symbol's quote page is, or empty when it has none to point at.

    Two gates, and both refuse rather than guess. The symbol has to look like a
    public ticker, which excludes every fund code in this workspace that has no
    page; and the template has to have survived the config's https check, which
    is what makes writing the result into an href safe.

    Empty for anything else, which renders plain text. A symbol that is not
    linked looks exactly like one that is not linkable, which is the truth.
    :param symbol: The holding's symbol, as the source spelled it
    :param template: A validated URL template containing {symbol}
    :return: The URL, or ""
    :rtype: str
    """

    if not template or not _TICKER.match(string=symbol):
        return ""

    return template.replace("{symbol}", symbol.upper())


def owner_color(name: str, palette: Iterable[tuple[str, str]]) -> str:
    """
    Whose account this is, as a colour name, or empty when nothing claims it.

    First match wins, which is why the palette arrives as ordered pairs rather
    than a mapping: the match is a substring of the display name, so "Joint"
    and "Alex" can both be true of one account and the order in the config
    is what decides. A dict would preserve that order in practice and document
    nothing about depending on it.

    Empty rather than a default colour for an account nothing matched. A default
    would put a dot on a row that has no owner declared, which reads as an owner
    the reader has forgotten rather than a line they have not written.
    :param name: The account's display name, after aliases
    :param palette: (match, colour) pairs, in the order configured
    :return: The colour name, or ""
    :rtype: str
    """

    folded: str = name.casefold()

    for match, color in palette:
        if match.casefold() in folded:
            return color

    return ""


def _ratio(top: float | None, bottom: float | None) -> float | None:
    """
    One number over another, where that means anything.
    :param top: The numerator
    :param bottom: The denominator
    :return: The ratio, or None when there is nothing to divide by
    :rtype: float | None
    """

    if top is None or not bottom:
        return None

    return top / bottom


def positions(
    portfolio: Portfolio,
    classes: dict[str, str],
    income: dict[str, float],
    history: dict[tuple[str, str, str], list[float]],
    baseline: dict[tuple[str, str, str], Mark] | None = None,
    palette: Iterable[tuple[str, str]] = (),
    link: str = "",
    paid: dict[str, Paid] | None = None,
) -> list[Position]:
    """
    Every holding, with what follows from what the source reported.

    Positions sharing an identity are folded together first, on mark_holdings'
    reasoning -- two rows of the same fund in one account are one holding to a
    reader, and a table listing them twice invites the sum to be done by eye and
    got wrong.

    Everything derived here divides by something that may be absent, and every
    one of those answers None rather than zero. A position whose source never
    stated a cost basis has no gain, no growth, no purchase price and no yield
    on cost; rendering those as 0.00 would report a holding that has made
    exactly nothing, which is a claim, rather than a holding nobody knows the
    cost of, which is the truth.
    :param portfolio: What the workspace holds
    :param classes: Symbol to asset class, from the config
    :param income: Symbol to trailing dividend income
    :param history: Identity to value series, for the trend
    :param baseline: What each position held when the last brief ran, for the
        units note. None on a first brief, where nothing can be compared
    :return: One entry per holding, largest value first
    :rtype: list[Position]
    """

    marks: dict[tuple[str, str, str], Mark] = baseline or {}
    pays: dict[str, Paid] = paid or {}
    folded: dict[tuple[str, str, str], list[HoldingRow]] = {}

    for row in portfolio.holdings:
        folded.setdefault(holding_key(row=row), []).append(row)

    built: list[Position] = []

    for key, rows in folded.items():
        first: HoldingRow = rows[0]
        units: float | None = _sum(values=[row.units for row in rows])
        value: float | None = _sum(values=[row.value for row in rows])
        cost: float | None = _sum(values=[row.cost_basis for row in rows])
        gain: float | None = None if cost is None or value is None else value - cost
        trend: list[float] = history.get(key, [])
        received: float | None = income.get(key[2])

        # None rather than zero when the feed has nothing for this symbol. A
        # fund that pays nothing and a 401k fund code no quote page has ever
        # heard of both come to 0.0, and only the first is a fact about money.
        rate: Paid | None = pays.get(key[2])
        forecast: float | None = (
            None
            if rate is None or not rate.found or units is None
            else round(number=rate.per_share * units, ndigits=2)
        )

        # None rather than the whole count when there is no baseline. A first
        # brief has nothing to compare against, and reporting every holding as
        # newly bought is the invented-change failure the state machine exists
        # to prevent one level up.
        was: Mark | None = marks.get(key)
        moved: float | None = (
            None
            if was is None or was.units is None or units is None
            else (units - was.units) or None
        )

        built.append(
            Position(
                symbol=key[2] or "(no symbol)",
                broker=first.broker,
                account=first.account,
                name=first.name,
                asset_class=classes.get(key[2], UNCLASSIFIED),
                color=owner_color(name=first.account, palette=palette),
                url=fund_url(symbol=key[2] or "", template=link),
                units=units,
                # The price the source stated, not value/units. They agree when
                # both are given, and where they disagree the source's own
                # number is the one it stands behind.
                price=first.price,
                value=value,
                currency=first.currency,
                cost_basis=cost,
                purchase_price=_ratio(top=cost, bottom=units),
                gain=gain,
                growth=_ratio(top=gain, bottom=cost),
                # From this position's own last two readings. None on a single
                # reading, which is not a flat day -- it is a position nobody has
                # measured twice.
                day_change=(
                    _ratio(top=trend[-1] - trend[-2], bottom=trend[-2])
                    if len(trend) >= 2
                    else None
                ),
                div_income=received,
                current_yield=_ratio(top=received, bottom=value),
                yield_on_cost=_ratio(top=received, bottom=cost),
                indicated_income=forecast,
                indicated_yield=_ratio(top=forecast, bottom=value),
                trend=tuple(trend),
                units_delta=moved,
            )
        )

    return sorted(built, key=lambda held: held.value or 0.0, reverse=True)


def _sum(values: Iterable[float | None]) -> float | None:
    """
    Add what was given, keeping "nobody said" distinct from "zero".

    None when *nothing* in the group carried a number, and the sum of whichever
    did otherwise. The asymmetry is deliberate: a fund reported in two lots where
    only one states a cost basis has a partly-known cost, and reporting the half
    that is known is better than discarding it -- but a fund where neither lot
    states one has no cost at all, and a 0.0 there would become a gain equal to
    the whole position.
    :param values: The numbers, any of which may be absent
    :return: Their sum, or None when every one was absent
    :rtype: float | None
    """

    given: list[float] = [value for value in values if value is not None]

    return sum(given) if given else None


def performance(
    held: Iterable[Position],
    income: dict[str, float],
    covered: int,
    currency: str,
    total: float,
) -> Performance:
    """
    The six-tile summary, and the fields that keep it honest.
    :param held: Every position
    :param income: Symbol to trailing dividend income
    :param covered: How many days of log the income figure stands on
    :param currency: The currency to report in
    :param total: What the accounts say the money is, which is not what the
        positions sum to -- the difference is uninvested cash
    :return: The summary
    :rtype: Performance
    """

    rows: list[Position] = [row for row in held if row.currency == currency]
    invested: float = sum(row.value or 0.0 for row in rows)

    priced: list[Position] = [row for row in rows if row.cost_basis is not None]
    cost: float | None = (
        sum(row.cost_basis or 0.0 for row in priced) if priced else None
    )
    gain: float | None = (
        None if cost is None else sum(row.gain or 0.0 for row in priced)
    )

    # Every dividend in the window, including any the source recorded without a
    # symbol -- that money was received whether or not anyone wrote down which
    # holding paid it, and a portfolio total that dropped it would be short.
    earned: float = sum(income.values())

    # Summed only over the positions the feed answered for, and the count and
    # their value travel with it. A yield divided by the whole portfolio would
    # report six known funds against twelve positions' worth of money.
    known: list[Position] = [row for row in rows if row.indicated_income is not None]
    forecast: float = sum(row.indicated_income or 0.0 for row in known)
    # Named apart from the "covered" parameter, which is a day count. ty caught
    # the shadow: it would have made dividend_days a float without a word.
    covered_value: float = sum(row.value or 0.0 for row in known)

    return Performance(
        value=total,
        invested=invested,
        currency=currency,
        cost=cost,
        gain=gain,
        growth=_ratio(top=gain, bottom=cost),
        priced=len(priced),
        unpriced=len(rows) - len(priced),
        holdings=len(rows),
        dividend_income=earned,
        # Over what the positions are worth rather than over the account total.
        # A yield is what the holdings pay on the holdings; dividing by a figure
        # that includes uninvested cash would report a portfolio yielding less
        # the more of it is sitting in a settlement balance.
        dividend_yield=_ratio(top=earned, bottom=invested),
        dividend_days=covered,
        dividends_seen=bool(income),
        indicated_income=forecast,
        indicated_yield=_ratio(top=forecast, bottom=covered_value),
        indicated_over=len(known),
        indicated_value=covered_value,
        # Summed separately rather than netted. A book that is $4,331 ahead on
        # eight positions and $507 behind on one is a different book from one
        # quietly $3,824 ahead overall, and the net is the number that hides it.
        total_win=sum(row.gain or 0.0 for row in priced if (row.gain or 0.0) > 0),
        total_loss=sum(row.gain or 0.0 for row in priced if (row.gain or 0.0) < 0),
    )


def build_brief(
    portfolio: Portfolio,
    baseline: Baseline | None,
    today: dt.date,
    currency: str = "USD",
    limit: int = 8,
    keep: int = 90,
    floor: float = 0.0,
    rates: Dividends | None = None,
) -> Brief:
    """
    Everything one morning has to say, decided once.

    Assembled here rather than in the render for the reason the row shapes exist:
    a template free to work out its own totals is a template free to disagree
    with the headline it sits under.
    :param portfolio: What the workspace holds
    :param baseline: What the last brief was shown, or None for the first
    :param today: The day freshness is measured from
    :param currency: The currency to report in
    :param limit: How many movers of each kind to render
    :param keep: How many trailing points the sparkline covers
    :param floor: The smallest position that earns a row. Display only -- every
        total still counts what falls below it
    :param rates: What each symbol pays per share, from the cache. None reads as
        an empty cache, which renders no indicated figures rather than zeroes
    :return: The assembled brief
    :rtype: Brief
    """

    totals: dict[str, float] = totals_by_date(
        rows=portfolio.net_worth, currency=currency
    )
    as_of: str = max(totals, default="")
    state: BriefState = _state(
        baseline=baseline, as_of=as_of, unreadable=portfolio.unreadable
    )

    # An empty baseline rather than a branch per field. Every comparison below
    # then reads the same way whether or not there is a baseline, and a first
    # brief falls out as "nothing to compare against" instead of as a separate
    # path that has to be kept in step with this one.
    since: Baseline = baseline or Baseline()
    prior: float = since.totals.get(currency, 0.0)
    total: float = totals.get(as_of, 0.0)
    delta: float = total - prior if since.taken_on else 0.0

    on_date: list[NetWorthRow] = [
        row
        for row in portfolio.net_worth
        if row.date == as_of and row.currency == currency
    ]

    classes: dict[str, str] = get_asset_classes()
    # The refused lines are dropped here and reported by the command, on the
    # rule the aliases follow: this function is the model and has nowhere to say
    # anything. etc.stonksmithdb.do_brief asks get_account_colors() again --
    # the config is cached, so that is a dictionary lookup -- and names each one.
    palette, _ = get_account_colors()
    link: str = get_brief_fund_link()
    pays: dict[str, Paid] = (rates or Dividends()).paid
    income, covered = dividends(rows=portfolio.transactions, today=today)

    # Computed once rather than inside the Brief() call, because two fields now
    # depend on it: the rows that fit and the count that did not. Deriving the
    # second from a second call would be two chances to disagree about how many
    # accounts moved.
    moved: list[Movement] = (
        account_movements(
            rows=portfolio.net_worth,
            since=since.taken_on,
            until=as_of,
            palette=palette,
        )
        if since.taken_on
        else []
    )
    held: list[Position] = positions(
        portfolio=portfolio,
        classes=classes,
        income=income,
        history=trends(rows=portfolio.holdings_history),
        baseline=since.holdings if since.taken_on else None,
        palette=palette,
        link=link,
        paid=pays,
    )

    # Split for display only. `held` stays whole and is what performance()
    # totals, so hiding a row cannot move a number.
    #
    # A position the source never valued is kept, not hidden. `row.value or 0.0`
    # reads None as zero and puts it under every floor above zero -- which is the
    # absent-is-not-zero conflation this project forbids everywhere else, and the
    # worst place to make it: a holding nobody could price is exactly the one a
    # reader needs to see, and it would disappear precisely because nothing is
    # known about it.
    shown: list[Position] = [
        row for row in held if row.value is None or abs(row.value) >= floor
    ]

    return Brief(
        state=state,
        as_of=as_of,
        since=since.taken_on,
        currency=currency,
        total=total,
        delta=delta,
        pct=_pct(before=prior, delta=delta) if since.taken_on else None,
        observed=sum(1 for row in on_date if row.basis == OBSERVED),
        carried=sum(1 for row in on_date if row.basis != OBSERVED),
        account_movers=significant(moves=moved, limit=limit),
        # What the cap left out, so the page can say so rather than ending on
        # the eighth row as though it were the last thing that moved.
        account_movers_dropped=max(0, len(moved) - limit),
        holding_movers=(
            ()
            if not since.taken_on
            else significant(
                moves=holding_movements(
                    rows=portfolio.holdings, baseline=since.holdings
                ),
                limit=limit,
            )
        ),
        new_transactions=(
            ()
            if not since.taken_on
            else tuple(
                new_transactions(
                    rows=portfolio.transactions, seen_through=since.seen_through
                )
            )
        ),
        allocation=tuple(
            allocation_breakdown(
                rows=portfolio.holdings,
                classes=classes,
                baseline=since.holdings,
            )
        ),
        stale=_stale_pairs(portfolio=portfolio, today=today),
        unreadable=portfolio.unreadable,
        series=_series(totals=totals, rows=portfolio.net_worth, keep=keep),
        positions=tuple(shown),
        positions_hidden=len(held) - len(shown),
        performance=performance(
            held=held,
            income=income,
            covered=covered,
            currency=currency,
            total=total,
        ),
    )


def take_baseline(portfolio: Portfolio, as_of: str, now: dt.datetime) -> Baseline:
    """
    Record what this brief showed, so the next one can say what changed.
    :param portfolio: What the workspace holds
    :param as_of: The newest date on the axis
    :param now: When this brief was rendered
    :return: The baseline to store
    :rtype: Baseline
    """

    return Baseline(
        taken_on=as_of,
        shown_at=now.isoformat(),
        seen_through=watermark(rows=portfolio.transactions),
        # Every currency the series carries, not just the reported one. The
        # brief renders one currency at a time because a total may only add
        # like to like, but the baseline is a record rather than a view -- and a
        # record that stored only USD would report a euro account's whole value
        # as a move on the morning somebody switched the brief to euros.
        totals={
            currency: totals_by_date(rows=portfolio.net_worth, currency=currency).get(
                as_of, 0.0
            )
            for currency in {row.currency for row in portfolio.net_worth}
        },
        holdings=mark_holdings(rows=portfolio.holdings),
    )


def read_baseline(path: Path) -> Baseline | None:
    """
    What the last brief was shown, or None when there is nothing usable.

    Every failure answers None, which renders a first brief -- a screen that says
    it has nothing to compare against. The alternative is a delta computed
    against a half-read file, which produces a number rather than a message and
    so cannot be told apart from a real one.
    :param path: Where the baseline is stored
    :return: The baseline, or None
    :rtype: Baseline | None
    """

    try:
        stored: Any = json.loads(path.read_text(encoding="utf-8"))

    # Deliberately broad, on read_databases' reasoning. A file in this position
    # can fail to be a usable baseline in more ways than are worth enumerating --
    # absent, truncated, not JSON, JSON of the wrong shape -- and none of them is
    # a reason to fail the morning rather than to report a first brief.
    except Exception:
        return None

    if not isinstance(stored, dict) or stored.get("version") != BASELINE_VERSION:
        return None

    return Baseline(
        taken_on=str(stored.get("taken_on", "")),
        shown_at=str(stored.get("shown_at", "")),
        seen_through=str(stored.get("seen_through", "")),
        totals={str(k): float(v) for k, v in (stored.get("totals") or {}).items()},
        holdings={
            (str(row["broker"]), str(row["account_key"]), str(row["symbol"])): Mark(
                value=row.get("value"), units=row.get("units")
            )
            for row in (stored.get("holdings") or [])
        },
    )


def write_baseline(path: Path, baseline: Baseline) -> None:
    """
    Store the baseline, owner-readable only.

    Restricted for the reason the databases and the config are: this file records
    what the portfolio totalled and what every position in it was worth, which is
    the same information those hold and no less worth keeping to one account.

    Holdings go out as a list of records rather than as an object keyed by the
    identity tuple. JSON has only string keys, so the tuple would have to be
    flattened into one with a separator -- and a separator is a character that a
    symbol is then forbidden to contain, enforced nowhere and discovered by the
    first fund code that contains it.
    :param path: Where to store it
    :param baseline: What this brief was shown
    """

    path.write_text(
        data=json.dumps(
            obj={
                "version": BASELINE_VERSION,
                "taken_on": baseline.taken_on,
                "shown_at": baseline.shown_at,
                "seen_through": baseline.seen_through,
                "totals": baseline.totals,
                "holdings": [
                    {
                        "broker": broker,
                        "account_key": key,
                        "symbol": symbol,
                        "value": mark.value,
                        "units": mark.units,
                    }
                    for (broker, key, symbol), mark in sorted(baseline.holdings.items())
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    restrict(path=path)


def should_advance(baseline: Baseline | None, as_of: str) -> bool:
    """
    Whether this brief has earned the right to become the next one's baseline.

    **Only when the axis actually moved**, and this is the subtlest rule in the
    feature. A morning with no new scrape has nothing new to report, so advancing
    would record "the reader has seen up to here" about data they have already
    been shown -- and discard the still-pending comparison against the run before
    it. The movement would then never appear in any brief: not this one, because
    nothing is newer than the baseline, and not the next one, because the
    baseline has moved past it. A day's movement erased by the act of looking at
    a screen that said there wasn't one.
    :param baseline: What the last brief was shown, or None
    :param as_of: The newest date on the axis
    :return: True when the baseline should be replaced
    :rtype: bool
    """

    if not as_of:
        # Nothing on the axis at all: an empty workspace, or one whose databases
        # would not open. Recording it as a baseline would make the first real
        # scrape look like the whole portfolio arriving at once.
        return False

    return baseline is None or as_of > baseline.taken_on
