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

import datetime as dt
import json
from typing import Any

#: Where the daily closes live in the payload, and the offset that dates them.
CHART_ROOT = "chart"
INDICATORS = "indicators"
QUOTE = "quote"
CLOSE = "close"
TIMESTAMP = "timestamp"
META = "meta"
GMT_OFFSET = "gmtoffset"


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
    stamps: list[int] = series.get(TIMESTAMP) or []

    try:
        closes: list[float | None] = series[INDICATORS][QUOTE][0][CLOSE]

    except KeyError, IndexError, TypeError:
        raise QuotesUnavailable("the price series carried no closes") from None

    # Stated by the feed rather than assumed: see the module docstring. An
    # offset outside a day is not a zone, and quietly falling back to UTC would
    # date every bar plausibly and wrongly, so it is reported instead.
    offset: int = int(series.get(META, {}).get(GMT_OFFSET) or 0)

    try:
        zone = dt.timezone(dt.timedelta(seconds=offset))

    except ValueError as e:
        raise QuotesUnavailable(
            f"the price feed dated its bars with an impossible offset ({e})"
        ) from e

    prices: dict[dt.date, float] = {}

    for stamp, close in zip(stamps, closes, strict=False):
        if close is None:
            continue

        prices[dt.datetime.fromtimestamp(stamp, tz=zone).date()] = float(close)

    return prices


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
