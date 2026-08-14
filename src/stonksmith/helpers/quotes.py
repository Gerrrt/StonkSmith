# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""
quotes.py: Published closing prices for a symbol, from a chart feed.

Pure -- payload in, prices out -- so the parsing is tested without a network,
the same way helpers.tsp parses the published TSP file. What differs is the
shape of the source: TSP publishes a CSV of every fund on every day, while this
reads one symbol at a time out of JSON.

Two properties of that JSON shaped all of it.

**The newest bar is usually empty.** A mutual fund strikes its NAV once, after
the close, so a run during the trading day gets today's timestamp with a null
price beside it. That is not a gap in the data and not an error -- it is the
ordinary state of affairs for most of the day, and a reader that treats a null
as a zero would mark the position at nothing.

**Timestamps are exchange time, not UTC.** The feed states its own offset, so
that is what converts a bar to a calendar day. Reading the timestamps as UTC
happens to agree for a US market, whose bars land mid-afternoon UTC, and would
quietly disagree for one that does not.
"""

import dataclasses
import datetime as dt
import json
from typing import Any

from stonksmith.etc.records import Holding

#: Where the daily closes live in the payload, and the offset that dates them.
CHART_ROOT = "chart"
INDICATORS = "indicators"
QUOTE = "quote"
CLOSE = "close"
TIMESTAMP = "timestamp"
META = "meta"
GMT_OFFSET = "gmtoffset"

#: Where dividend events live when the request asks for them, and the field
#: inside each one that carries the per-share amount.
EVENTS = "events"
DIVIDENDS = "dividends"
AMOUNT = "amount"


class QuotesUnavailable(Exception):
    """The payload carried no usable prices, and says why."""


def daily_closes(payload: str) -> dict[dt.date, float]:
    """
    Every published close in a chart payload, keyed by the day it belongs to.

    Bars with no price are dropped rather than defaulted. The newest one is
    routinely empty -- a fund's NAV does not exist until after the close -- and
    a zero in its place would value the whole position at nothing. Dropping it
    leaves ``close_on()`` to fall back to the last real price and say that it
    did.
    :param payload: The chart response body
    :return: {date: close}, which is empty when nothing has been published
    :rtype: dict[dt.date, float]
    :raises QuotesUnavailable: when the payload is not a chart, or reports an
        error, or carries no result
    """

    try:
        chart: Any = json.loads(s=payload)[CHART_ROOT]

    except (ValueError, KeyError, TypeError) as e:
        raise QuotesUnavailable(
            f"the price feed did not answer with a chart ({e})"
        ) from e

    # The feed reports its own failures in-band, with a 200 around them.
    if chart.get("error"):
        raise QuotesUnavailable(f"the price feed reported: {chart['error']}")

    results: Any = chart.get("result") or []

    if not results:
        raise QuotesUnavailable("the price feed returned no series for that symbol")

    series: Any = results[0]
    stamps: Any = series.get(TIMESTAMP)

    # Not "or []": a series with no timestamps produces no rows, which would
    # come back as the empty dict that means "nothing published yet". Those are
    # a broken payload and an ordinary mid-session run, and they must not look
    # the same.
    if stamps is None:
        raise QuotesUnavailable("the price series carried no timestamps")

    try:
        closes: list[float | None] = series[INDICATORS][QUOTE][0][CLOSE]

    except KeyError, IndexError, TypeError:
        raise QuotesUnavailable("the price series carried no closes") from None

    # A short array pairs some other day's price with this day's date, which is
    # wrong in the way that looks right.
    if len(stamps) != len(closes):
        raise QuotesUnavailable(
            f"the price series carried {len(stamps)} timestamps "
            f"and {len(closes)} closes"
        )

    # Stated by the feed rather than assumed: see the module docstring. Reading
    # it is inside the guard because every way it can be wrong -- absent, not a
    # number, not a zone, or a meta that is not a mapping at all -- ends the
    # same way: dates that cannot be trusted. Falling back to UTC would date
    # every bar plausibly and wrongly.
    try:
        offset: int = int(series.get(META, {}).get(GMT_OFFSET) or 0)
        zone = dt.timezone(dt.timedelta(seconds=offset))

    except (TypeError, ValueError, AttributeError) as e:
        raise QuotesUnavailable(
            f"the price feed dated its bars with an unusable offset ({e})"
        ) from e

    prices: dict[dt.date, float] = {}

    for stamp, close in zip(stamps, closes, strict=True):
        if close is None:
            continue

        prices[dt.datetime.fromtimestamp(stamp, tz=zone).date()] = float(close)

    return prices


def dividend_events(payload: str) -> dict[dt.date, float]:
    """
    Every dividend a chart payload reports, keyed by the day it went ex.

    Asked for with ``&events=div`` on the same endpoint the closes come from, so
    one request answers both and the two can never disagree about which symbol
    they describe.

    **An empty result is an ordinary answer, not a failure.** Plenty of funds pay
    nothing, and a symbol that paid nothing this year is a fact worth reporting
    rather than an error to raise. What *is* raised is a payload that is not a
    chart at all -- the same distinction daily_closes draws, and for the same
    reason: "this fund pays no dividend" and "the feed did not answer" must not
    arrive as the same empty dict.

    ``events`` comes back **present and null** for symbols that have none, which
    is why every step below is `or {}` rather than `.get(key, {})`. A default
    only applies to a missing key, and the key is not missing.
    :param payload: The chart response body, requested with events=div
    :return: {ex-date: amount per share}, empty when the fund paid nothing
    :rtype: dict[dt.date, float]
    :raises QuotesUnavailable: when the payload is not a chart, or reports an
        error, or carries no result
    """

    try:
        chart: Any = json.loads(s=payload)[CHART_ROOT]

    except (ValueError, KeyError, TypeError) as e:
        raise QuotesUnavailable(
            f"the price feed did not answer with a chart ({e})"
        ) from e

    if chart.get("error"):
        raise QuotesUnavailable(f"the price feed reported: {chart['error']}")

    results: Any = chart.get("result") or []

    if not results:
        raise QuotesUnavailable("the price feed returned no series for that symbol")

    series: Any = results[0]
    offset: int = int(series.get(META, {}).get(GMT_OFFSET) or 0)
    events: Any = (series.get(EVENTS) or {}).get(DIVIDENDS) or {}

    paid: dict[dt.date, float] = {}

    for stamp, event in events.items():
        amount: Any = (event or {}).get(AMOUNT)

        if amount is None:
            continue

        try:
            # Exchange time, not UTC, on daily_closes' reasoning: the feed states
            # its own offset and an ex-date is a calendar day in the market's
            # own zone. Reading these as UTC happens to agree for a US fund and
            # would quietly disagree for one that is not.
            when: dt.date = dt.datetime.fromtimestamp(
                int(stamp) + offset, tz=dt.UTC
            ).date()

        except ValueError, TypeError, OSError:
            continue

        # Summed rather than assigned. Two distributions can share an ex-date --
        # an income distribution and a capital gain, most often in December --
        # and the last one winning would silently drop the other.
        paid[when] = paid.get(when, 0.0) + float(amount)

    return paid


def trailing_dividend(
    paid: dict[dt.date, float], today: dt.date, days: int = 365
) -> tuple[float, int]:
    """
    What one share was paid over the trailing window, and how much of it was real.

    Two returns, and the second is what keeps the first honest. A fund listed
    four months ago has paid four months of dividends, and reporting that sum as
    an annual figure understates its yield by two thirds. The caller states the
    coverage rather than presenting a partial year as a whole one.

    Measured from the oldest payment actually inside the window rather than from
    the window's edge: a fund that has paid once, last month, covers a month of
    income however far back the window reaches.
    :param paid: Ex-dates to per-share amounts
    :param today: The day the window is measured back from
    :param days: How far back to reach
    :return: (per-share total, days of payment history it stands on)
    :rtype: tuple[float, int]
    """

    since: dt.date = today - dt.timedelta(days=days)
    inside: list[dt.date] = [when for when in paid if since <= when <= today]

    if not inside:
        return 0.0, 0

    return (
        round(number=sum(paid[when] for when in inside), ndigits=6),
        min(days, (today - min(inside)).days),
    )


def close_on(
    prices: dict[dt.date, float], day: dt.date
) -> tuple[dt.date, float] | None:
    """
    The close on a day, or the most recent one before it.

    Falls back rather than failing, for the reasons helpers.tsp.price_on does:
    a weekend, a holiday, or a run before the day's price is published all ask
    for a date the feed does not carry. Returns the date as well as the price,
    so a caller can say how old a mark is instead of presenting Friday's number
    as today's.
    :param prices: Parsed closes
    :param day: The date wanted
    :return: (price date, close), or None when nothing was published on or
        before that day
    :rtype: tuple[dt.date, float] | None
    """

    for candidate in sorted(prices, reverse=True):
        if candidate <= day:
            return candidate, prices[candidate]

    return None


def value_of(units: float, price: float) -> float:
    """
    What a holding is worth, rounded the way money is.

    Named rather than written inline at the call site because the rounding is
    the point: units carry far more decimal places than dollars do, and a
    fund's unit count routinely runs to three or four of them.
    :param units: Units held
    :param price: Price per unit
    :return: The value, to the cent
    :rtype: float
    """

    return round(number=units * price, ndigits=2)


def repriced(
    holding: Holding, prices: dict[dt.date, float], day: dt.date
) -> tuple[Holding, dt.date] | None:
    """
    A holding marked at a published close instead of the broker's own.

    The units are the broker's, from whenever it was last read; the price is
    the market's, for the day asked about. That pairing is the whole idea --
    Ally will not reuse a session, but a unit count does not change between
    deposits, and a published price does not need a login.

    The day is a parameter rather than "now" because the answer is not always
    today's close and should not pretend to be: a run before the NAV is struck,
    on a weekend, or over a holiday falls back to the last published price, and
    a past day can be valued at what it was actually worth.

    Returns the date the price came from alongside the holding, so the caller
    can record how old the mark is. Both halves age separately and a run that
    reports neither is asserting a freshness it does not have.

    Nothing is invented. A holding with no units cannot be valued and comes
    back None rather than as a zero, because zero is a real balance and "we do
    not know" is not.
    :param holding: The position as last observed
    :param prices: Published closes for that holding's symbol
    :param day: The date being valued
    :return: (repriced holding, price date), or None when it cannot be valued
    :rtype: tuple[Holding, dt.date] | None
    """

    if holding.units is None:
        return None

    found = close_on(prices=prices, day=day)

    if found is None:
        return None

    when, price = found

    return (
        dataclasses.replace(
            holding, price=price, value=value_of(units=holding.units, price=price)
        ),
        when,
    )
