# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""
What each holding pays, fetched once and read from disk thereafter.

**This exists because the brief must not reach the network.** "No login, no
browser, no network" is what makes it cheap enough to schedule every morning and
what stops it failing in any of the ways a broker can -- so a dividend figure it
had to fetch would trade that away for a number. The fetch lives in its own
command, run beside the scrapes, and leaves a file the brief reads the way it
reads the baseline.

What is stored is **dividends per share**, never an income figure. A per-share
amount is a fact about the fund and stays true however many units are held; an
income figure is that multiplied by a unit count, and a stored one would be
wrong the moment a share was bought. The same argument the [MANUAL] broker makes
about units against balances, one level up.

And what comes out of it is an *indicated* figure rather than money received.
The distinction is the whole reason this does not simply overwrite the
transaction-log number: what a fund paid per share over the trailing year, times
what is held today, is a forecast of a full year at the current position -- not a
record of what landed in an account. A reader owed a dividend total is owed both,
labelled.
"""

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stonksmith.etc.permissions import restrict

#: The schema version of the cache. Read back and checked rather than assumed,
#: on the baseline's reasoning: a file written by a future version is not one
#: this can read, and treating it as absent produces no dividend figures -- which
#: the page says out loud -- instead of numbers computed from fields that moved.
CACHE_VERSION: int = 1

#: How stale a cached figure may be before it is worth saying so. Funds
#: distribute quarterly at most, so a fortnight-old file is not wrong; a
#: months-old one means the refresh has stopped running.
STALE_DAYS: int = 14


@dataclass(frozen=True, slots=True)
class Paid:
    """
    What one share of a symbol was paid over the trailing window.

    ``found`` is separate from a zero amount, and the difference is the whole
    value of the record. A fund that pays nothing and a symbol the feed has never
    heard of both produce 0.0, and only one of them is a fact about the money:
    the other is a ticker like FCASH that a quote feed answers with 404. A page
    that rendered them identically would report a cash sweep as a fund yielding
    nothing.
    """

    #: Dividends per share over the window. Never an income figure -- see the
    #: module docstring for why a stored income would be wrong by the next trade.
    per_share: float = 0.0

    #: How many days of payment history that stands on, capped at the window.
    #: A fund listed four months ago has paid four months of dividends, and
    #: reporting that as an annual figure understates its yield by two thirds.
    covered_days: int = 0

    #: Whether the feed answered for this symbol at all.
    found: bool = False

    #: The day this particular figure was fetched, which is not necessarily the
    #: day the file was written. A refresh that could not reach the feed keeps
    #: the last good figure rather than discarding it, and a carried figure
    #: presented under the file's write date would be the carried-rendered-as-
    #: observed failure the brief's headline exists to prevent. Empty on a cache
    #: written before this field existed.
    as_of: str = ""


@dataclass(frozen=True, slots=True)
class Dividends:
    """Every symbol the last refresh asked about, and when it asked."""

    fetched_on: str = ""
    window_days: int = 365
    paid: dict[str, Paid] = field(default_factory=dict)

    def age(self, today: dt.date) -> int | None:
        """
        How old the **oldest figure** is, or None when nothing carries a date.

        Measured from the oldest per-symbol ``as_of`` rather than from
        ``fetched_on``, because a run that could not reach the feed still writes
        the file -- carrying the last good figures forward -- and reading the
        write date would report a cache of month-old numbers as refreshed today.
        The staleness warning exists to catch a refresh that has stopped
        happening, and that is exactly the case it would have gone blind to.

        Falls back to ``fetched_on`` when no entry carries a date, which is what
        a cache written before ``as_of`` existed looks like.
        :param today: The day to measure from
        :return: The age in days, or None
        :rtype: int | None
        """

        stamps: list[dt.date] = []

        for row in self.paid.values():
            try:
                stamps.append(dt.date.fromisoformat(row.as_of))

            except ValueError:
                continue

        try:
            oldest: dt.date = (
                min(stamps) if stamps else dt.date.fromisoformat(self.fetched_on)
            )

        except ValueError:
            return None

        return (today - oldest).days


def read_cache(path: Path) -> Dividends:
    """
    What the last refresh found, or an empty record when there is nothing usable.

    Every failure answers empty, which renders a page saying it has no dividend
    figures -- the honest outcome. The alternative is a yield computed from
    whichever fields survived a half-read file, which is a number rather than a
    message and cannot be told from a real one.
    :param path: Where the cache is stored
    :return: The cached figures, possibly empty
    :rtype: Dividends
    """

    # The guard covers the whole read, not just the parse. A file can be valid
    # JSON and still not be a cache -- `paid` holding a string where a record
    # belongs is the shape a half-written file takes -- and an AttributeError
    # raised out of the comprehension below would have escaped this function and
    # failed the morning, which is precisely what the docstring promises it
    # will not do.
    #
    # Deliberately broad, on read_baseline's reasoning: a file in this position
    # can fail to be a usable cache in more ways than are worth enumerating, and
    # none of them is a reason to fail the morning.
    try:
        stored: Any = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(stored, dict) or stored.get("version") != CACHE_VERSION:
            return Dividends()

        return Dividends(
            fetched_on=str(stored.get("fetched_on", "")),
            window_days=int(stored.get("window_days") or 365),
            paid={
                str(symbol): Paid(
                    per_share=float(row.get("per_share") or 0.0),
                    covered_days=int(row.get("covered_days") or 0),
                    found=bool(row.get("found")),
                    as_of=str(row.get("as_of") or ""),
                )
                for symbol, row in (stored.get("paid") or {}).items()
            },
        )

    except Exception:
        return Dividends()


def write_cache(path: Path, dividends: Dividends) -> None:
    """
    Store what was found, owner-readable only.

    Restricted for the reason the baseline and the reports are: on its own a
    per-share dividend is public, and the *set* of symbols asked about is the
    list of everything the household holds.
    :param path: Where to store it
    :param dividends: What the refresh found
    """

    path.write_text(
        data=json.dumps(
            obj={
                "version": CACHE_VERSION,
                "fetched_on": dividends.fetched_on,
                "window_days": dividends.window_days,
                "paid": {
                    symbol: {
                        "per_share": row.per_share,
                        "covered_days": row.covered_days,
                        "found": row.found,
                        "as_of": row.as_of,
                    }
                    for symbol, row in sorted(dividends.paid.items())
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    restrict(path=path)
