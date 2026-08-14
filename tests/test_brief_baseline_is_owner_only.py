"""The baseline is written owner-only, and survives a round trip intact.

Two claims about one file, kept together because they fail for the same reason:
somebody adding a field and writing it out without thinking about either.

The permission first. The baseline records what the portfolio totalled and what
every position in it was worth -- the same information the databases hold, which
this project already chmods 0600 for, and rather more concentrated. It is created
by write_baseline rather than by setup_tool, so a file created at the process
umask stays world-readable until somebody notices, and nothing else would.

The round trip second. Holdings are keyed on a (broker, account_key, symbol)
tuple in memory and JSON has only string keys, so they go out as a list of
records and come back rebuilt. Anything that loses that mapping does not error --
it produces a baseline whose holdings match nothing, and the next brief reports
every position in the portfolio as newly arrived. A page saying you bought
everything you own, overnight.
"""

import stat
import tempfile
import unittest
from pathlib import Path

from stonksmith.etc.brief import Baseline, Mark, read_baseline, write_baseline
from stonksmith.etc.permissions import OWNER_ONLY_FILE

BASELINE: Baseline = Baseline(
    taken_on="2026-08-13",
    shown_at="2026-08-14T06:30:00+00:00",
    seen_through="2026-08-13T18:30:00",
    totals={"USD": 132500.0, "EUR": 200.0},
    holdings={
        ("tsp", "t1", "C Fund"): Mark(value=91500.0, units=1200.0),
        ("ally", "a1", "VTI"): Mark(value=41000.0, units=100.0),
        # A position the source valued but never counted, which is the ordinary
        # shape for a scraped 529: None has to survive as None rather than
        # arriving back as 0.0, or the next brief reports units that were sold.
        ("schwab529plan", "s1", "2040 Portfolio"): Mark(value=8000.0, units=None),
    },
)


class TheBaselineIsWrittenOwnerOnly(unittest.TestCase):
    def setUp(self) -> None:
        self._home = tempfile.TemporaryDirectory()
        self.path = Path(self._home.name) / "brief_baseline.json"
        write_baseline(path=self.path, baseline=BASELINE)

    def tearDown(self) -> None:
        self._home.cleanup()

    def test_nobody_else_can_read_it(self) -> None:
        mode: int = stat.S_IMODE(self.path.stat().st_mode)

        self.assertEqual(
            mode,
            OWNER_ONLY_FILE,
            f"the baseline is mode {mode:04o}: it holds every account's value "
            "and the portfolio total, and nothing else will restrict it",
        )

    def test_it_comes_back_the_way_it_went_in(self) -> None:
        restored = read_baseline(path=self.path)

        self.assertIsNotNone(restored)
        assert restored is not None

        self.assertEqual(restored.taken_on, BASELINE.taken_on)
        self.assertEqual(restored.seen_through, BASELINE.seen_through)
        self.assertEqual(restored.totals, BASELINE.totals)

    def test_the_holding_keys_survive_the_json_round_trip(self) -> None:
        restored = read_baseline(path=self.path)
        assert restored is not None

        self.assertEqual(
            restored.holdings,
            BASELINE.holdings,
            "a holding key did not survive being written and read back, so the "
            "next brief compares against nothing and reports the whole "
            "portfolio as bought overnight",
        )

    def test_an_uncounted_position_stays_uncounted(self) -> None:
        restored = read_baseline(path=self.path)
        assert restored is not None

        self.assertIsNone(
            restored.holdings[("schwab529plan", "s1", "2040 Portfolio")].units,
            "a unit count the source never gave came back as a number, which "
            "the next brief will read as units having changed",
        )


if __name__ == "__main__":
    unittest.main()
