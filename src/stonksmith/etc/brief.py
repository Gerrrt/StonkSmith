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
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from stonksmith.etc.config import get_asset_classes
from stonksmith.etc.permissions import restrict
from stonksmith.etc.portfolio import (
    OBSERVED,
    STALE_DAYS,
    AccountRow,
    HoldingRow,
    NetWorthRow,
    Portfolio,
    TransactionRow,
    stale_accounts,
    stale_cutoff,
    stale_reason,
)

#: The schema version of the baseline file. Read back and checked rather than
#: assumed: a baseline written by a future version is not a baseline this one can
#: subtract against, and treating it as absent produces a first-brief -- which
#: says so -- instead of a delta computed against fields that moved.
BASELINE_VERSION: int = 1

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
    new_transactions: tuple[TransactionRow, ...] = ()
    allocation: tuple[Allocation, ...] = ()

    #: (account, reason) for everything that cannot be shown to be fresh.
    stale: tuple[tuple[str, str], ...] = ()

    #: (name, reason) for whatever would not open, carried straight through from
    #: the portfolio. The reason ``state`` can be DEGRADED.
    unreadable: tuple[tuple[str, str], ...] = ()

    #: The trailing series the sparkline is drawn from: (date, total, observed).
    series: tuple[tuple[str, float, bool], ...] = ()


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
    rows: Iterable[NetWorthRow], since: str, until: str
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

    Called for accounts and for positions both, and deliberately the one decision
    in this module that is a matter of taste rather than of correctness. Every
    other function here has a right answer that the data settles; this one is
    about what its reader cares to see at half past six in the morning, and the
    portfolio it is reporting on decides that.

    The movers arrive sorted by absolute dollar move, largest first.
    :param moves: Every movement that was non-zero, largest absolute move first
    :param limit: How many rows the brief has room for
    :return: The ones to render, in the order given
    :rtype: tuple[Movement, ...]
    """

    # TODO(Garrett): decide what earns a row here.
    #
    # A dollar floor (abs(delta) > 50) keeps a rounding wiggle on the largest
    # account out, and also hides a 4% day on the smallest one. A percentage
    # floor (abs(pct) > 0.005) does the reverse, and makes a cash account holding
    # twelve dollars the loudest row on the page every single morning. A bare
    # top-N is stable and readable and silently drops a real sixth mover.
    #
    # Whichever it is, note that `pct` is None for an account that arrived since
    # the baseline -- those have no denominator, and a percentage rule has to
    # decide whether an arrival is always worth a row or never one.
    return tuple(moves)[:limit]


def build_brief(
    portfolio: Portfolio,
    baseline: Baseline | None,
    today: dt.date,
    currency: str = "USD",
    limit: int = 8,
    keep: int = 90,
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
        account_movers=(
            ()
            if not since.taken_on
            else significant(
                moves=account_movements(
                    rows=portfolio.net_worth, since=since.taken_on, until=as_of
                ),
                limit=limit,
            )
        ),
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
                classes=get_asset_classes(),
                baseline=since.holdings,
            )
        ),
        stale=_stale_pairs(portfolio=portfolio, today=today),
        unreadable=portfolio.unreadable,
        series=_series(totals=totals, rows=portfolio.net_worth, keep=keep),
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
