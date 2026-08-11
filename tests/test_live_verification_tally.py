"""The count above the claims table has to agree with the table.

`docs/live-verification.md` opens with a sentence summarising its own table --
how many claims have been settled, how many confirmed, how many disproved, how
many left. The file's *Recording a result* section tells the next person to
"bring the count above the table into line", and that instruction was the only
thing holding the two together.

It had already failed. fc95819 added *The sheet -- the whole transaction history
reaching a tab* as a twentieth row and left the sentence saying nineteen, so the
file understated its own remaining work by one for four commits. Nothing caught
it, because prose is not executable and a summary that is merely stale looks
exactly like one that is right.

That is worse than carrying no count at all. A reader who trusts the sentence
never counts the rows, which is the entire reason the sentence is there; a
sentence that is sometimes wrong makes them count anyway, and then the sentence
is costing more than it saves.

So the count is derived here and compared. Nothing in this file knows what the
right numbers are -- it reads them off the table and off the prose and asserts
the two agree, which means it keeps working as claims are settled.
"""

import datetime as dt
import re
import unittest
from pathlib import Path

RECORD = Path(__file__).resolve().parent.parent / "docs" / "live-verification.md"

#: The table is found by its header rather than by position, so sections can be
#: added above it. The row that follows is markdown's `| --- |` separator.
TABLE_HEADER = "| Claim | Rests on | Observed live | Settled on |"

#: What a settled row says when the run that settled it was not dated. Two rows
#: say this, and it is a gap rather than a spelling: an age that cannot be
#: computed cannot be checked, which is the objection this project makes to a
#: balance carrying no as-of date.
UNDATED = "not recorded"

#: What an unsettled row's date cell holds. Nothing settled it, so there is no
#: date to carry, and an empty cell would be indistinguishable from a row
#: somebody forgot.
NO_DATE = "—"

#: How long a settled claim stays current. Six months, counted in days because
#: the standard library has no months and a test that guessed at one would be
#: arguing about February. The number is a reading convention rather than a
#: deadline: nothing fails when a claim passes it, the summary just has to say
#: how many have.
STALE_AFTER_DAYS = 183

#: How a verdict in the third column is read. A row that starts "Yes" is
#: confirmed -- "Yes, against real files" is the TSP form, for a broker whose
#: real thing is an issued file rather than a site. "Run, and it cannot" is a
#: claim settled the other way, which the file counts as settled rather than
#: outstanding.
CONFIRMED = "Yes"
DISPROVED = "Run, and it cannot"
OUTSTANDING = "No"

#: Read in three pieces rather than one, so re-wrapping the paragraph or
#: changing its punctuation does not break the test. A guard that breaks on
#: ordinary prose edits gets deleted, and then the drift comes back.
SETTLED_OF_TOTAL = re.compile(r"(\d+) of (\d+) claims have been settled")
CONFIRMED_AND_DISPROVED = re.compile(r"(\d+) confirmed, (\d+) disproved")
REMAINING = re.compile(r"remaining (\d+) rest")

#: The day the summary describes. Everything below is measured against this
#: rather than against today, so the suite cannot go red because a week passed.
#: A test that fails on an untouched repository is one that gets muted, and
#: docs/scheduling.md is this project's own write-up of what muting costs.
AS_OF = re.compile(r"As of (\d{4}-\d{2}-\d{2}):")

#: How many settled claims are older than the reading convention allows, and how
#: many cannot be aged at all.
DUE = re.compile(r"(\d+) of those were settled more than six months")
UNDATED_COUNT = re.compile(r"(\d+) carry no date at all")


def _document() -> str:
    """The record, with its line wrapping collapsed."""

    text: str = RECORD.read_text(encoding="utf-8")

    # The sentence wraps across two lines, and where it wraps is not a fact
    # about the claim it states.
    return re.sub(pattern=r"\s+", repl=" ", string=text)


def _rows() -> list[tuple[str, str]]:
    """(verdict, settled-on) for every row in the claims table."""

    lines: list[str] = RECORD.read_text(encoding="utf-8").splitlines()

    try:
        start: int = lines.index(TABLE_HEADER)
    except ValueError:
        raise AssertionError(
            f"No claims table in {RECORD.name}: nothing matched {TABLE_HEADER!r}. "
            "If the header was reworded, reword TABLE_HEADER with it -- a parse "
            "that finds no rows would let this test pass on an empty count."
        ) from None

    found: list[tuple[str, str]] = []

    # Past the header and past markdown's separator row.
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break

        cells: list[str] = [cell.strip() for cell in line.split("|")]

        # A leading and a trailing empty string, from the outer pipes.
        if len(cells) != 6:
            raise AssertionError(
                f"Could not read a row of the claims table as four cells: "
                f"{line!r}. A cell carrying a literal '|' would do this."
            )

        found.append((cells[3], cells[4]))

    return found


def _verdicts() -> list[str]:
    """The verdict column of every row in the claims table."""

    return [verdict for verdict, _ in _rows()]


def _settled_on() -> list[str]:
    """The date column of every row in the claims table."""

    return [date for _, date in _rows()]


def _counted() -> tuple[int, int, int]:
    """(confirmed, disproved, outstanding), read off the table."""

    confirmed: int = 0
    disproved: int = 0
    outstanding: int = 0

    for verdict in _verdicts():
        if verdict.startswith(CONFIRMED):
            confirmed += 1
        elif DISPROVED in verdict:
            disproved += 1
        elif verdict == OUTSTANDING:
            outstanding += 1
        else:
            raise AssertionError(
                f"Unreadable verdict {verdict!r} in the claims table. Every row "
                "has to land in exactly one of the three counts, so a new "
                "wording needs teaching here rather than being skipped -- a "
                "skipped row is one this test would stop counting."
            )

    return confirmed, disproved, outstanding


#: A date in the Settled on column, which is ISO because everything here is.
_ISO: re.Pattern[str] = re.compile(r"\d{4}-\d{2}-\d{2}")


def _as_of() -> dt.date:
    """The day the summary says it describes."""

    found: re.Match[str] | None = AS_OF.search(_document())

    if found is None:
        raise AssertionError(
            f"The summary in {RECORD.name} no longer says which day it "
            "describes. Every count below is measured against that date, so "
            "without it they are measured against nothing."
        )

    return dt.date.fromisoformat(found.group(1))


def _stated(pattern: re.Pattern[str]) -> tuple[int, ...]:
    """The numbers one part of the summary sentence claims."""

    found: re.Match[str] | None = pattern.search(_document())

    if found is None:
        raise AssertionError(
            f"The summary above the claims table in {RECORD.name} no longer "
            f"matches {pattern.pattern!r}. It is the thing under test, so a "
            "rewording needs the pattern reworded with it."
        )

    return tuple(int(group) for group in found.groups())


class ClaimsTableTests(unittest.TestCase):
    def test_the_table_was_actually_found(self) -> None:
        # Everything else here counts rows. A parse that silently found none
        # would agree with any sentence at all.
        self.assertGreater(len(_verdicts()), 0)

    def test_every_row_is_counted_as_exactly_one_thing(self) -> None:
        confirmed, disproved, outstanding = _counted()
        self.assertEqual(confirmed + disproved + outstanding, len(_verdicts()))


class StatedCountTests(unittest.TestCase):
    def test_the_total_is_the_number_of_rows(self) -> None:
        _, total = _stated(pattern=SETTLED_OF_TOTAL)
        self.assertEqual(
            total,
            len(_verdicts()),
            "The summary states a different number of claims than the table "
            "has rows. This is the drift fc95819 introduced.",
        )

    def test_the_confirmed_count_is_the_rows_that_say_yes(self) -> None:
        confirmed, _ = _stated(pattern=CONFIRMED_AND_DISPROVED)
        self.assertEqual(confirmed, _counted()[0])

    def test_the_disproved_count_is_the_rows_settled_the_other_way(self) -> None:
        _, disproved = _stated(pattern=CONFIRMED_AND_DISPROVED)
        self.assertEqual(disproved, _counted()[1])

    def test_the_remaining_count_is_the_rows_that_say_no(self) -> None:
        (remaining,) = _stated(pattern=REMAINING)
        self.assertEqual(
            remaining,
            _counted()[2],
            "The summary states a different number of outstanding claims than "
            "the table has 'No' rows.",
        )

    def test_settled_is_confirmed_plus_disproved(self) -> None:
        # Stated three times in one sentence, so it can disagree with itself
        # even while agreeing with the table.
        settled, _ = _stated(pattern=SETTLED_OF_TOTAL)
        confirmed, disproved = _stated(pattern=CONFIRMED_AND_DISPROVED)
        self.assertEqual(settled, confirmed + disproved)

    def test_settled_and_remaining_account_for_every_claim(self) -> None:
        settled, total = _stated(pattern=SETTLED_OF_TOTAL)
        (remaining,) = _stated(pattern=REMAINING)
        self.assertEqual(settled + remaining, total)


class SettledOnTests(unittest.TestCase):
    """
    Every settlement is dated, because none of them stays true on its own.

    A run proves what the site was. It proves less about what the site is every
    week that passes, so a column of `Yes` with no dates reads as finished work
    -- which is the one thing this table is not.
    """

    def test_a_settled_row_carries_a_date_or_says_it_has_none(self) -> None:
        for verdict, date in _rows():
            if verdict == OUTSTANDING:
                continue

            with self.subTest(verdict=verdict):
                self.assertTrue(
                    date == UNDATED or _ISO.fullmatch(date),
                    f"a settled row's date is {date!r}. It has to be a date, or "
                    f"{UNDATED!r} to say the run was never dated -- an unreadable "
                    "one cannot be aged, and a row that cannot be aged goes back "
                    "to being a Yes that means nothing in particular.",
                )

    def test_an_unsettled_row_carries_no_date(self) -> None:
        # Nothing settled it, so there is nothing to date. Left blank it would
        # be indistinguishable from a row somebody forgot to fill in.
        for verdict, date in _rows():
            if verdict != OUTSTANDING:
                continue

            with self.subTest(date=date):
                self.assertEqual(date, NO_DATE)

    def test_the_summary_says_which_day_it_describes(self) -> None:
        # The whole point of dating it: a reader arriving a year later can see
        # the summary is a year old rather than trusting it.
        self.assertIsNotNone(AS_OF.search(_document()))

    def test_no_claim_was_settled_after_the_day_the_summary_describes(self) -> None:
        # A date in the future of the summary means the summary was not updated
        # with the row, which is the drift this file keeps finding in itself.
        for date in _settled_on():
            if date in (NO_DATE, UNDATED):
                continue

            with self.subTest(date=date):
                self.assertLessEqual(dt.date.fromisoformat(date), _as_of())

    def test_the_stated_due_count_is_the_rows_past_the_convention(self) -> None:
        # Measured from the stated date, never from today. Counting from today
        # would put this file on a timer: the count would go stale on a morning
        # nobody touched the repository, and a suite that fails for that reason
        # is one that gets muted rather than fixed.
        cutoff: dt.date = _as_of() - dt.timedelta(days=STALE_AFTER_DAYS)
        due: int = len(
            [
                date
                for date in _settled_on()
                if date not in (NO_DATE, UNDATED)
                and dt.date.fromisoformat(date) < cutoff
            ]
        )
        (stated,) = _stated(pattern=DUE)

        self.assertEqual(
            stated,
            due,
            "The summary and the table disagree about how many settled claims "
            "are older than six months. Bring the sentence into line, and while "
            "you are there consider whether those claims want re-running.",
        )

    def test_the_stated_undated_count_is_the_rows_with_no_date(self) -> None:
        (stated,) = _stated(pattern=UNDATED_COUNT)

        self.assertEqual(stated, _settled_on().count(UNDATED))

    def test_the_dated_and_undated_settled_rows_account_for_every_settlement(
        self,
    ) -> None:
        # Guards the arithmetic above against a row that is settled, carries
        # NO_DATE, and so is counted by neither -- which would let a settlement
        # go missing from both halves of the sentence at once.
        confirmed, disproved, _ = _counted()
        dated: int = len(
            [date for date in _settled_on() if date not in (NO_DATE, UNDATED)]
        )

        self.assertEqual(dated + _settled_on().count(UNDATED), confirmed + disproved)


if __name__ == "__main__":
    unittest.main()
