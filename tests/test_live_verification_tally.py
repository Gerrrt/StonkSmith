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

import re
import unittest
from pathlib import Path

RECORD = Path(__file__).resolve().parent.parent / "docs" / "live-verification.md"

#: The table is found by its header rather than by position, so sections can be
#: added above it. The row that follows is markdown's `| --- |` separator.
TABLE_HEADER = "| Claim | Rests on | Observed live |"

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


def _document() -> str:
    """The record, with its line wrapping collapsed."""

    text: str = RECORD.read_text(encoding="utf-8")

    # The sentence wraps across two lines, and where it wraps is not a fact
    # about the claim it states.
    return re.sub(pattern=r"\s+", repl=" ", string=text)


def _verdicts() -> list[str]:
    """The third column of every row in the claims table."""

    lines: list[str] = RECORD.read_text(encoding="utf-8").splitlines()

    try:
        start: int = lines.index(TABLE_HEADER)
    except ValueError:
        raise AssertionError(
            f"No claims table in {RECORD.name}: nothing matched {TABLE_HEADER!r}. "
            "If the header was reworded, reword TABLE_HEADER with it -- a parse "
            "that finds no rows would let this test pass on an empty count."
        ) from None

    verdicts: list[str] = []

    # Past the header and past markdown's separator row.
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break

        cells: list[str] = [cell.strip() for cell in line.split("|")]

        # A leading and a trailing empty string, from the outer pipes.
        if len(cells) != 5:
            raise AssertionError(
                f"Could not read a row of the claims table as three cells: "
                f"{line!r}. A cell carrying a literal '|' would do this."
            )

        verdicts.append(cells[3])

    return verdicts


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


if __name__ == "__main__":
    unittest.main()
