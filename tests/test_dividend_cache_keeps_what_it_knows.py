"""A bad night must not cost a figure that was already known.

Four holes the dividend feature shipped with, three of them the same hole. The
refresh rebuilds the whole cache from one pass, so any symbol it could not fetch
was written back as ``found=False`` -- and a rate limit, an HTML block page or a
dropped connection would have downgraded every good figure to "no such fund",
losing the brief's yield entirely until the next clean night.

That is worse than it sounds, because the failure is silent and self-erasing.
The cache after a wiped run is indistinguishable from a portfolio holding
nothing that pays, which is exactly the reading ``found`` was added to prevent
one level down.

So a fetch that fails keeps what was there **with its own date**, not restamped.
A carried figure wearing today's date is the carried-rendered-as-observed
failure the brief's headline exists to prevent, and it would blind the staleness
warning that is supposed to catch a refresh which has stopped running --
``fetched_on`` moves every night whether or not anything was fetched.

The fourth is the parser's: ``dividend_events`` read the exchange offset with
``.get(META, {})`` while guarding the line below it with ``or {}``, so a payload
whose ``meta`` is present and null raised AttributeError out of a function whose
docstring promises QuotesUnavailable. The same shape it was written to avoid,
one line away from the comment saying so.
"""

import datetime as dt
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stonksmith.etc.dividends import (
    CACHE_VERSION,
    Dividends,
    Paid,
    read_cache,
    write_cache,
)
from stonksmith.helpers.quotes import QuotesUnavailable, dividend_events

TODAY: dt.date = dt.date(2026, 8, 14)


class TheParserGuardsTheOffsetItReads(unittest.TestCase):
    def test_a_null_meta_is_refused_rather_than_crashing(self) -> None:
        # The feed states its own offset, and every way that can be wrong ends
        # the same way: ex-dates that cannot be trusted. What must not happen is
        # an AttributeError escaping a function documented to raise
        # QuotesUnavailable, because the caller catches that by name to decide
        # whether a symbol has no quote page.
        with self.assertRaises(QuotesUnavailable):
            dividend_events(
                payload='{"chart":{"error":null,"result":[{"meta":null,'
                '"timestamp":[1],"events":null}]}}'
            )

    def test_a_meta_that_is_not_a_mapping_is_refused(self) -> None:
        with self.assertRaises(QuotesUnavailable):
            dividend_events(
                payload='{"chart":{"error":null,"result":[{"meta":"utc",'
                '"timestamp":[1],"events":null}]}}'
            )

    def test_an_unusable_offset_is_refused(self) -> None:
        with self.assertRaises(QuotesUnavailable):
            dividend_events(
                payload='{"chart":{"error":null,"result":[{'
                '"meta":{"gmtoffset":"east"},"timestamp":[1],"events":null}]}}'
            )

    def test_a_missing_meta_still_reads_as_utc(self) -> None:
        # Absent is not malformed. A payload that never mentions an offset is
        # the ordinary shape, and refusing it would lose every dividend over a
        # field nobody promised.
        self.assertEqual(
            dividend_events(
                payload='{"chart":{"error":null,"result":[{"timestamp":[1],'
                '"events":{"dividends":{"1765555200":{"amount":0.2}}}}]}}'
            ),
            {dt.date(2025, 12, 12): 0.2},
        )


class AHalfWrittenCacheFailsSafe(unittest.TestCase):
    def _read(self, body: str) -> Dividends:
        with TemporaryDirectory() as home:
            path = Path(home) / "dividends.json"
            path.write_text(body, encoding="utf-8")

            return read_cache(path=path)

    def test_a_record_that_is_not_a_mapping_answers_empty(self) -> None:
        # The shape a truncated or hand-edited file takes. This raised
        # AttributeError out of the comprehension, past the guard that only
        # covered the parse, and failed the morning the docstring promises it
        # cannot fail.
        cache = self._read(
            json.dumps({"version": CACHE_VERSION, "paid": {"SWPPX": "0.195"}})
        )

        self.assertEqual(cache.paid, {})

    def test_a_paid_that_is_not_a_mapping_answers_empty(self) -> None:
        self.assertEqual(
            self._read(json.dumps({"version": CACHE_VERSION, "paid": []})).paid, {}
        )

    def test_an_unreadable_amount_answers_empty(self) -> None:
        cache = self._read(
            json.dumps(
                {"version": CACHE_VERSION, "paid": {"SWPPX": {"per_share": "lots"}}}
            )
        )

        self.assertEqual(cache.paid, {})

    def test_a_file_that_is_not_json_answers_empty(self) -> None:
        self.assertEqual(self._read("<html>rate limited</html>").paid, {})

    def test_a_good_file_still_reads(self) -> None:
        # The guard must not be so broad that it swallows the working case.
        with TemporaryDirectory() as home:
            path = Path(home) / "dividends.json"
            write_cache(
                path=path,
                dividends=Dividends(
                    fetched_on="2026-08-14",
                    paid={
                        "SWPPX": Paid(
                            per_share=0.195,
                            covered_days=245,
                            found=True,
                            as_of="2026-08-14",
                        )
                    },
                ),
            )

            self.assertEqual(read_cache(path=path).paid["SWPPX"].per_share, 0.195)
            self.assertEqual(read_cache(path=path).paid["SWPPX"].as_of, "2026-08-14")


class StalenessIsMeasuredOnTheFiguresNotTheWrite(unittest.TestCase):
    def test_a_carried_figure_still_reads_as_old(self) -> None:
        # The whole reason as_of exists. A refresh that reached nothing still
        # writes the file, so fetched_on says today; measuring staleness on that
        # would report month-old numbers as fresh and silence the warning that
        # exists to catch a refresh which has stopped running.
        cache = Dividends(
            fetched_on="2026-08-14",
            paid={"SWPPX": Paid(per_share=0.195, found=True, as_of="2026-07-01")},
        )

        self.assertEqual(cache.age(today=TODAY), 44)

    def test_the_oldest_figure_is_the_one_reported(self) -> None:
        # Not the newest. One symbol refreshing nightly must not vouch for
        # another that has not been reached in a month.
        cache = Dividends(
            fetched_on="2026-08-14",
            paid={
                "SWPPX": Paid(found=True, as_of="2026-08-14"),
                "FSKAX": Paid(found=True, as_of="2026-07-01"),
            },
        )

        self.assertEqual(cache.age(today=TODAY), 44)

    def test_a_cache_written_before_as_of_existed_falls_back(self) -> None:
        # Nothing stored carries a date, which is what the first version's files
        # look like. Falling back to the write date is better than reporting no
        # age at all, and it is what those files used to mean anyway.
        cache = Dividends(
            fetched_on="2026-08-01", paid={"SWPPX": Paid(per_share=0.195, found=True)}
        )

        self.assertEqual(cache.age(today=TODAY), 13)

    def test_nothing_datable_reports_no_age(self) -> None:
        self.assertIsNone(Dividends().age(today=TODAY))


if __name__ == "__main__":
    unittest.main()
