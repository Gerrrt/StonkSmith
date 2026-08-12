# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Valuing a holding from a published price, without asking the broker.

Ally cannot reuse a session -- nine runs settled that, and
docs/live-verification.md records it -- so a daily unattended Ally run cannot
scrape. What it can do is what the TSP module already does: multiply a known
unit count by a published price. The unit count comes from the last run that
did sign in; the price comes from here.

Two things in the feed would each produce a wrong number quietly rather than
an error, and both are pinned below.

**A null close.** A mutual fund's NAV does not exist until after the close, so
for most of the trading day the newest bar has a timestamp and no price. Read
as a zero, that marks the whole position at nothing -- a plausible-looking
$0.00 that no exception announces.

**A timestamp read in the wrong zone.** The feed dates its bars in exchange
time and says which offset that is. Assuming UTC agrees for a US market and
would silently shift every date by one for a market that closes after midnight
UTC, attaching each price to the wrong day.
"""

import datetime as dt
import json
import unittest

from stonksmith.etc.records import Holding
from stonksmith.helpers.quotes import (
    QuotesUnavailable,
    close_on,
    daily_closes,
    repriced,
    value_of,
)

#: 2026-08-05, 2026-08-06 and 2026-08-07 at 09:30 New York.
_STAMPS: tuple[int, ...] = (1785936600, 1786023000, 1786109400)

#: What the real feed answers with mid-session: the newest bar is not priced.
_EDT_OFFSET = -14400


def _payload(
    stamps: tuple[int, ...] = _STAMPS,
    closes: tuple[float | None, ...] = (19.91, 19.88, None),
    offset: int = _EDT_OFFSET,
) -> str:
    return json.dumps(
        obj={
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "USD", "gmtoffset": offset},
                        "timestamp": list(stamps),
                        "indicators": {"quote": [{"close": list(closes)}]},
                    }
                ],
                "error": None,
            }
        }
    )


class NullCloses(unittest.TestCase):
    """The newest bar is empty for most of the day. That is not a zero."""

    def test_an_unpriced_bar_is_dropped(self) -> None:
        prices = daily_closes(payload=_payload())

        self.assertEqual(len(prices), 2)
        self.assertNotIn(dt.date(2026, 8, 7), prices)

    def test_the_prices_around_it_survive(self) -> None:
        prices = daily_closes(payload=_payload())

        self.assertEqual(prices[dt.date(2026, 8, 5)], 19.91)
        self.assertEqual(prices[dt.date(2026, 8, 6)], 19.88)

    def test_a_series_of_nothing_but_nulls_is_empty_not_an_error(self) -> None:
        """A fund that has not priced yet today is ordinary, not broken."""
        prices = daily_closes(payload=_payload(closes=(None, None, None)))

        self.assertEqual(prices, {})

    def test_nothing_is_valued_at_zero(self) -> None:
        """The failure this guards: a null read as 0.00 marks a holding at nothing."""
        prices = daily_closes(payload=_payload(closes=(None, 19.88, None)))

        self.assertNotIn(0.0, prices.values())


class Dating(unittest.TestCase):
    """Bars are stamped in exchange time, and the feed says which."""

    def test_the_stated_offset_is_used(self) -> None:
        prices = daily_closes(payload=_payload())

        self.assertEqual(sorted(prices), [dt.date(2026, 8, 5), dt.date(2026, 8, 6)])

    def test_a_different_offset_moves_the_day(self) -> None:
        """Proof the offset is read rather than ignored. +14h is Kiritimati."""
        far = daily_closes(payload=_payload(offset=50400))

        self.assertNotEqual(sorted(far), [dt.date(2026, 8, 5), dt.date(2026, 8, 6)])

    def test_an_impossible_offset_is_reported_not_raised_raw(self) -> None:
        """A whole day is not a zone. Falling back to UTC would misdate every bar."""
        with self.assertRaises(QuotesUnavailable):
            daily_closes(payload=_payload(offset=-86400))

    def test_a_missing_offset_does_not_raise(self) -> None:
        payload = json.loads(s=_payload())
        del payload["chart"]["result"][0]["meta"]["gmtoffset"]

        self.assertEqual(len(daily_closes(payload=json.dumps(obj=payload))), 2)


class Fallback(unittest.TestCase):
    """A run on a Sunday still has to value the position."""

    def setUp(self) -> None:
        self.prices = daily_closes(payload=_payload())

    def test_an_exact_day_is_returned_as_itself(self) -> None:
        self.assertEqual(
            close_on(prices=self.prices, day=dt.date(2026, 8, 6)),
            (dt.date(2026, 8, 6), 19.88),
        )

    def test_an_unpriced_day_falls_back_to_the_last_real_one(self) -> None:
        """Today, mid-session: the answer is yesterday's, and says so."""
        self.assertEqual(
            close_on(prices=self.prices, day=dt.date(2026, 8, 7)),
            (dt.date(2026, 8, 6), 19.88),
        )

    def test_the_date_comes_back_so_staleness_can_be_reported(self) -> None:
        asked = dt.date(2026, 8, 30)
        found = close_on(prices=self.prices, day=asked)

        # The date comes back with the price, so the caller can subtract.
        self.assertEqual(found, (dt.date(2026, 8, 6), 19.88))
        self.assertEqual((asked - dt.date(2026, 8, 6)).days, 24)

    def test_a_day_before_anything_published_is_none(self) -> None:
        """Guessing forwards would date a price to before it existed."""
        self.assertIsNone(close_on(prices=self.prices, day=dt.date(2026, 8, 1)))

    def test_no_prices_at_all_is_none(self) -> None:
        self.assertIsNone(close_on(prices={}, day=dt.date(2026, 8, 7)))


class BadPayloads(unittest.TestCase):
    """Every one of these must say what went wrong, not return an empty dict."""

    def test_html_instead_of_json(self) -> None:
        with self.assertRaises(QuotesUnavailable):
            daily_closes(payload="<html>Access Denied</html>")

    def test_an_in_band_error(self) -> None:
        """The feed reports an unknown symbol with a 200 around it."""
        payload = json.dumps(
            obj={"chart": {"result": None, "error": {"code": "Not Found"}}}
        )

        with self.assertRaises(QuotesUnavailable) as caught:
            daily_closes(payload=payload)

        self.assertIn("Not Found", str(object=caught.exception))

    def test_no_series(self) -> None:
        with self.assertRaises(QuotesUnavailable):
            daily_closes(
                payload=json.dumps(obj={"chart": {"result": [], "error": None}})
            )

    def test_a_series_with_no_closes(self) -> None:
        payload = json.dumps(
            obj={
                "chart": {
                    "result": [{"meta": {}, "timestamp": [1], "indicators": {}}],
                    "error": None,
                }
            }
        )

        with self.assertRaises(QuotesUnavailable):
            daily_closes(payload=payload)

    def test_missing_timestamps_are_not_an_empty_day(self) -> None:
        """The empty dict already means "nothing published yet". This is not that."""
        payload = json.loads(s=_payload())
        del payload["chart"]["result"][0]["timestamp"]

        with self.assertRaises(QuotesUnavailable):
            daily_closes(payload=json.dumps(obj=payload))

    def test_more_timestamps_than_closes_is_reported(self) -> None:
        """Pairing by position across a short array dates a price to the wrong day."""
        with self.assertRaises(QuotesUnavailable) as caught:
            daily_closes(payload=_payload(closes=(19.91,)))

        self.assertIn("3 timestamps", str(object=caught.exception))

    def test_more_closes_than_timestamps_is_reported(self) -> None:
        with self.assertRaises(QuotesUnavailable):
            daily_closes(payload=_payload(closes=(19.91, 19.88, 19.7, 19.6)))

    def test_a_non_numeric_offset_is_reported(self) -> None:
        payload = json.loads(s=_payload())
        payload["chart"]["result"][0]["meta"]["gmtoffset"] = "eastern"

        with self.assertRaises(QuotesUnavailable):
            daily_closes(payload=json.dumps(obj=payload))

    def test_a_meta_that_is_not_a_mapping_is_reported(self) -> None:
        payload = json.loads(s=_payload())
        payload["chart"]["result"][0]["meta"] = "USD"

        with self.assertRaises(QuotesUnavailable):
            daily_closes(payload=json.dumps(obj=payload))

    def test_the_symbol_is_not_echoed_into_the_message(self) -> None:
        """Messages reach logs; a holding's identity does not belong in one."""
        with self.assertRaises(QuotesUnavailable) as caught:
            daily_closes(payload="")

        self.assertNotIn("SWPPX", str(object=caught.exception))


class Valuing(unittest.TestCase):
    """Units carry more decimals than dollars do."""

    def test_it_rounds_to_the_cent(self) -> None:
        self.assertEqual(value_of(units=123.4567, price=19.88), 2454.32)

    def test_a_fractional_unit_count_survives(self) -> None:
        """A $250 automatic purchase never buys a whole number of units."""
        self.assertEqual(value_of(units=12.5754, price=19.88), 250.0)

    def test_no_units_is_no_value(self) -> None:
        self.assertEqual(value_of(units=0.0, price=19.88), 0.0)


class Repricing(unittest.TestCase):
    """The units are the broker's; the price is the market's.

    Ally will not reuse a session, but a unit count does not change between
    deposits and a published price does not need a login. The real position is
    123.519 units of SWPPX, which Ally itself marked at $19.88 for $2,455.56 --
    the same close the feed publishes, to the cent.
    """

    def _swppx(self, units: float | None = 123.519) -> Holding:
        return Holding(
            symbol="SWPPX",
            name="Schwab S&P 500 Index",
            units=units,
            price=19.88,
            value=2455.56,
            cost_basis=2237.74,
        )

    def test_it_agrees_with_the_broker_on_the_broker_s_own_numbers(self) -> None:
        """The check that matters: same units, same close, same total."""
        prices = daily_closes(payload=_payload())
        found = repriced(holding=self._swppx(), prices=prices, day=dt.date(2026, 8, 7))

        self.assertIsNotNone(found)
        self.assertEqual(found[0].value, 2455.56)

    def test_the_price_date_comes_back_with_it(self) -> None:
        """Both halves age separately, so both have to be reportable."""
        prices = daily_closes(payload=_payload())
        found = repriced(holding=self._swppx(), prices=prices, day=dt.date(2026, 8, 7))

        self.assertEqual(found[1], dt.date(2026, 8, 6))

    def test_the_units_are_left_alone(self) -> None:
        """This values a position; it does not pretend to know it changed."""
        prices = daily_closes(payload=_payload())
        found = repriced(holding=self._swppx(), prices=prices, day=dt.date(2026, 8, 7))

        self.assertEqual(found[0].units, 123.519)

    def test_everything_else_survives(self) -> None:
        """A reprice must not quietly drop the cost basis it did not compute."""
        prices = daily_closes(payload=_payload())
        found = repriced(holding=self._swppx(), prices=prices, day=dt.date(2026, 8, 7))

        self.assertEqual(found[0].symbol, "SWPPX")
        self.assertEqual(found[0].cost_basis, 2237.74)

    def test_a_new_price_moves_the_value(self) -> None:
        prices = daily_closes(payload=_payload())
        found = repriced(holding=self._swppx(), prices=prices, day=dt.date(2026, 8, 5))

        self.assertEqual(found[0].price, 19.91)
        self.assertEqual(found[0].value, 2459.26)

    def test_the_original_is_untouched(self) -> None:
        """Holding is frozen; repricing returns a new one."""
        prices = daily_closes(payload=_payload())
        original = self._swppx()
        repriced(holding=original, prices=prices, day=dt.date(2026, 8, 5))

        self.assertEqual(original.price, 19.88)

    def test_unknown_units_is_none_not_zero(self) -> None:
        """Zero is a real balance. "We do not know" is not, and must not
        be made to look like one.
        """
        prices = daily_closes(payload=_payload())

        self.assertIsNone(
            repriced(
                holding=self._swppx(units=None), prices=prices, day=dt.date(2026, 8, 7)
            )
        )

    def test_no_published_price_is_none(self) -> None:
        """Before the fund had a price, it had no value to report."""
        prices = daily_closes(payload=_payload())

        self.assertIsNone(
            repriced(holding=self._swppx(), prices=prices, day=dt.date(2026, 8, 1))
        )


if __name__ == "__main__":
    unittest.main()
