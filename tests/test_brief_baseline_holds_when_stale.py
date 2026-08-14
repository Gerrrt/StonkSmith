"""A brief with nothing new does not consume the comparison it could not make.

The subtlest rule in the feature, and the one whose failure is invisible.

The baseline records what the reader was last shown, so the next brief can say
what has changed since. Advance it on every run and a morning where the nightly
scrape did not land does this: the brief reports nothing moved, correctly, and
then records "the reader has seen up to here" about data they were already shown.
The pending movement -- everything between the old baseline and the last real
scrape -- is now behind the baseline. It will not appear in this brief, because
nothing is newer than what it compared against, and it will not appear in the
next one, because the baseline has moved past it.

A day's movement, erased by the act of looking at a screen that said there wasn't
any. Nothing errors, nothing is logged, and the numbers on every subsequent brief
are individually correct. The only evidence is a day that is missing from the
history of what you were told, which is not somewhere anybody looks.

So the baseline advances only when the axis actually moved. `peek` is the same
rule made explicit for a reader who wants to look twice in one day.
"""

import unittest

from stonksmith.etc.brief import Baseline, should_advance

MONDAY: str = "2026-08-10"
TUESDAY: str = "2026-08-11"


class ABriefWithNothingNewHoldsTheBaseline(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = Baseline(taken_on=TUESDAY, totals={"USD": 1000.0})

    def test_it_holds_when_the_axis_has_not_moved(self) -> None:
        # The morning after a nightly run that did not land. Advancing here is
        # the bug: it records Tuesday as seen twice and drops whatever Tuesday
        # was still waiting to be compared against Monday.
        self.assertFalse(
            should_advance(baseline=self.baseline, as_of=TUESDAY),
            "the baseline advanced on a morning with no new scrape, which "
            "discards the pending comparison and hides that movement forever",
        )

    def test_it_advances_when_a_newer_scrape_landed(self) -> None:
        self.assertTrue(should_advance(baseline=self.baseline, as_of="2026-08-12"))

    def test_it_holds_when_the_axis_went_backwards(self) -> None:
        # A workspace restored from a backup, or a database that would not open
        # and took its dates with it. The newest date is older than the baseline,
        # which is not a new scrape however it is spelled -- and an advance here
        # would rewind the watermark and re-report a week of movements as new.
        self.assertFalse(
            should_advance(baseline=self.baseline, as_of=MONDAY),
            "the baseline moved backwards, so the next brief will re-report "
            "movements that have already been shown",
        )

    def test_it_holds_when_there_is_no_axis_at_all(self) -> None:
        # An empty workspace, or one whose every database failed to open.
        # Recording that as a baseline makes the first real scrape look like the
        # entire portfolio arriving in one night.
        self.assertFalse(should_advance(baseline=self.baseline, as_of=""))
        self.assertFalse(should_advance(baseline=None, as_of=""))

    def test_a_first_brief_takes_a_baseline(self) -> None:
        # Nothing to preserve, so nothing is lost by recording one -- and until
        # one exists no brief can report a change at all.
        self.assertTrue(should_advance(baseline=None, as_of=TUESDAY))


if __name__ == "__main__":
    unittest.main()
