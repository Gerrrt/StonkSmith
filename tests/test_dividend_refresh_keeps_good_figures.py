"""A night the feed refuses must not erase what a good night learned.

`dividends` rebuilds the whole cache from a single pass, which made every
failure destructive: a symbol it could not fetch was written back as
``found=False``, and the next morning's brief lost its yield. One rate limit, one
HTML block page, one dropped connection.

The failure is silent and self-erasing, which is what makes it worth a file of
its own. A wiped cache is indistinguishable from a portfolio holding nothing that
pays -- precisely the reading ``found`` was introduced to prevent one level down
-- and the next clean night repairs it, so nobody ever sees the morning it broke.

So a fetch that fails keeps what was already there. Three things have to be true
of that, and each is a way the fix could be wrong rather than merely absent:

**A carried figure keeps its own date.** Restamping it with today's would make
the staleness warning blind, because ``fetched_on`` moves every night whether or
not anything was fetched. Carried-rendered-as-observed, one file over from the
headline rule that exists to stop exactly that.

**A symbol with nothing to keep is still recorded.** A ticker the feed genuinely
has no page for -- FCASH, here -- must come out as ``found=False`` rather than
being dropped, or the brief cannot say how many of its positions it covered.

**A successful fetch still overwrites.** A carry that outlived a good answer
would freeze the figure forever, which is the opposite failure and just as quiet.
"""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_isolation import UserConfigMixin
from keyring_isolation import MemoryKeyringMixin
from stonksmith.etc.broker_db import BrokerDatabase
from stonksmith.etc.dividends import (
    CACHE_VERSION,
    Dividends,
    Paid,
    read_cache,
    write_cache,
)
from stonksmith.etc.infrastructure import create_db_engine
from stonksmith.etc.records import AccountIdentity, Holding
from stonksmith.etc.stonksmithdb import StonkSmithDBMenu

#: A chart payload carrying one distribution, which is what a good night looks
#: like. The ex-date is inside the trailing year of the date the command reads
#: from the clock, so the figure it produces is non-zero whenever this runs.
PAYING: str = (
    '{"chart":{"error":null,"result":[{"meta":{"gmtoffset":0},"timestamp":[1],'
    '"events":{"dividends":{"%d":{"amount":0.25}}}}]}}'
)

#: What a rate limit or a block page actually looks like coming back: a 200 with
#: something that is not a chart in it. It raises QuotesUnavailable, the same
#: exception a genuine 404 raises -- which is the whole reason neither is allowed
#: to overwrite a good figure.
BLOCKED: str = "<html><body>Too Many Requests</body></html>"


class TheRefreshKeepsWhatItCannotCheck(
    UserConfigMixin, MemoryKeyringMixin, unittest.TestCase
):
    def setUp(self) -> None:
        super().setUp()

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "default").mkdir()

        self.cache = self.root / "dividends.json"

        db = BrokerDatabase(
            db_engine=create_db_engine(db_path=self.root / "default" / "b.db"),
            broker="b",
        )
        db.save_snapshot(
            account=AccountIdentity(account_key="b-1", display_name="An Account"),
            scraped_at="2026-08-12 18:30:00",
            as_of="2026-08-12",
            value=3000.0,
            currency="USD",
            holdings=[
                Holding(symbol="SWPPX", units=100.0, value=2000.0),
                # No quote page at all. Present so the failing cases cannot pass
                # by accident on a workspace where every symbol behaves alike.
                Holding(symbol="FCASH", units=1000.0, value=1000.0),
            ],
            transactions=[],
        )
        db.shutdown_db()

    def _run(self, body: str) -> str:
        """
        Run `dividends` with every request answering the same body.
        :param body: What the feed returns for every symbol
        :return: What the command printed
        :rtype: str
        """

        printed: list[str] = []
        today: dt.date = dt.datetime.now(tz=dt.UTC).date()
        stamp: int = int(
            dt.datetime.combine(
                today - dt.timedelta(days=30), dt.time(), tzinfo=dt.UTC
            ).timestamp()
        )

        shell = StonkSmithDBMenu.__new__(StonkSmithDBMenu)
        shell.workspace = "default"
        shell.failed = False

        with (
            patch("stonksmith.etc.portfolio.workspace_dir", str(object=self.root)),
            patch("stonksmith.etc.paths.dividends_path", self.cache),
            patch("requests.get") as fetch,
            patch(
                "builtins.print",
                side_effect=lambda *a: printed.append(" ".join(map(str, a))),
            ),
        ):
            fetch.return_value.text = body % stamp if "%d" in body else body
            shell.do_dividends("")

        return "\n".join(printed)

    def _seed(self, as_of: str = "2026-08-01") -> None:
        """
        Put a good figure in the cache, as a successful night would have.
        :param as_of: The day that figure was fetched
        """

        write_cache(
            path=self.cache,
            dividends=Dividends(
                fetched_on=as_of,
                paid={
                    "SWPPX": Paid(
                        per_share=0.195, covered_days=245, found=True, as_of=as_of
                    )
                },
            ),
        )

    def test_a_blocked_feed_does_not_erase_a_good_figure(self) -> None:
        # The whole point. Before the fix this wrote Paid(found=False) over a
        # working figure and the next brief reported no yield at all.
        self._seed()
        self._run(body=BLOCKED)

        kept = read_cache(path=self.cache).paid["SWPPX"]

        self.assertTrue(kept.found)
        self.assertEqual(kept.per_share, 0.195)

    def test_the_kept_figure_is_not_restamped_with_today(self) -> None:
        # Restamping would hide the staleness. `fetched_on` says today either
        # way -- the file was written -- so the per-symbol date is the only
        # thing left that can report a refresh which has stopped working.
        self._seed(as_of="2026-08-01")
        self._run(body=BLOCKED)

        self.assertEqual(read_cache(path=self.cache).paid["SWPPX"].as_of, "2026-08-01")

    def test_it_says_out_loud_which_figures_were_carried(self) -> None:
        # A run that carried everything is a refresh that is no longer
        # refreshing, and it looks identical to a good run in the counts alone.
        self._seed()
        output: str = self._run(body=BLOCKED)

        self.assertIn("older figures kept", output)
        self.assertIn("SWPPX", output)

    def test_a_symbol_with_nothing_to_keep_is_still_recorded(self) -> None:
        # FCASH has no cached figure and no quote page. It has to come out as
        # found=False rather than absent, or the brief cannot say how many of
        # its positions the yield covered.
        self._seed()
        self._run(body=BLOCKED)

        cached = read_cache(path=self.cache).paid

        self.assertIn("FCASH", cached)
        self.assertFalse(cached["FCASH"].found)

    def test_nothing_cached_and_nothing_fetched_stays_empty(self) -> None:
        # No cache to carry from. This must not invent a figure, and it must not
        # crash on the missing entry either.
        self._run(body=BLOCKED)

        cached = read_cache(path=self.cache).paid

        self.assertFalse(cached["SWPPX"].found)
        self.assertEqual(cached["SWPPX"].per_share, 0.0)

    def test_a_figure_from_before_as_of_existed_is_dated_from_the_file(self) -> None:
        # The upgrade path, and the one night it matters. A cache written before
        # `as_of` existed carries no per-symbol date, so carrying its entries
        # unchanged left nothing in the file dated at all -- age() fell back to
        # `fetched_on`, which this very run sets to today, and a six-week-old
        # figure reported as fetched this morning. Once, on the first blocked
        # night after the upgrade, which is exactly when the warning is owed.
        #
        # Before as_of existed a run rewrote every symbol, so the file's own
        # date is genuinely the day this figure came from.
        self.cache.write_text(
            json.dumps(
                {
                    "version": CACHE_VERSION,
                    "fetched_on": "2026-07-01",
                    "window_days": 365,
                    "paid": {
                        "SWPPX": {
                            "per_share": 0.195,
                            "covered_days": 245,
                            "found": True,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        self._run(body=BLOCKED)

        cached = read_cache(path=self.cache)

        self.assertEqual(cached.paid["SWPPX"].as_of, "2026-07-01")
        self.assertEqual(
            cached.age(today=dt.date(2026, 8, 14)),
            44,
            "a carried figure with no date of its own reads as fetched today",
        )

    def test_a_good_fetch_still_overwrites_the_carried_figure(self) -> None:
        # The opposite failure, and just as quiet: a carry that outlived a real
        # answer would freeze the figure forever.
        self._seed()
        self._run(body=PAYING)

        fresh = read_cache(path=self.cache).paid["SWPPX"]
        today: str = dt.datetime.now(tz=dt.UTC).date().isoformat()

        self.assertTrue(fresh.found)
        self.assertEqual(fresh.per_share, 0.25)
        self.assertEqual(fresh.as_of, today)

    def test_a_fund_that_pays_nothing_is_not_carried(self) -> None:
        # A successful answer of zero is a fact about the fund, and it must
        # replace an older non-zero figure rather than being mistaken for a
        # failed fetch.
        self._seed()
        self._run(
            body='{"chart":{"error":null,"result":[{"meta":{"gmtoffset":0},'
            '"timestamp":[1],"events":null}]}}'
        )

        quiet = read_cache(path=self.cache).paid["SWPPX"]

        self.assertTrue(quiet.found)
        self.assertEqual(quiet.per_share, 0.0)


if __name__ == "__main__":
    unittest.main()
