"""The installable crontab and the documented one have to stay the same schedule.

`docs/scheduling.md` works out which brokers can run unattended and prints the
crontab that follows from it. `scripts/stonksmith.cron` is that crontab as a
file, so it can be pasted rather than retyped. Two copies of a schedule is
exactly the arrangement that goes out of step, and going out of step here is
expensive in a particular way: the file is what gets installed, the document is
what gets read, and a reader who checks the document would be reading about a
schedule their machine is not running.

`tests/test_doc_cross_references.py` makes the same trade for links, and its
docstring puts the reason better than this one can -- "an instruction is not a
mechanism". Telling a future editor to change both is an instruction. This is
the mechanism.

What is compared is the schedule itself: the `PATH` assignment and the entries,
with comments and blank lines dropped, since the file carries a long preamble
the fenced block in the document has no room for. What is deliberately *not*
compared is the prose around either one.
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

ARTIFACT = REPO / "scripts" / "stonksmith.cron"
RECORD = REPO / "docs" / "scheduling.md"

#: A fenced block introduced as `cron`. The document has exactly one, and the
#: count is asserted rather than assumed -- a second block added later would
#: otherwise go unchecked, which is the failure this file exists to prevent.
CRON_FENCE = re.compile(r"^```cron\n(?P<body>.*?)^```$", re.MULTILINE | re.DOTALL)


def schedule(text: str) -> list[str]:
    """
    The lines of a crontab that carry meaning.

    Comments and blank lines are dropped: the artifact explains itself at
    length and the document cannot, so requiring those to match would be
    requiring the two to be the same document rather than the same schedule.
    Trailing whitespace goes too, since it is invisible in a diff and would
    fail this test in a way nobody could see.
    :param text: A crontab, or the body of a fenced cron block
    :return: The significant lines, in order
    """

    return [
        stripped
        for line in text.splitlines()
        if (stripped := line.rstrip()) and not stripped.lstrip().startswith("#")
    ]


class TheArtifactMatchesTheRecord(unittest.TestCase):
    def setUp(self) -> None:
        self.artifact_text: str = ARTIFACT.read_text(encoding="utf-8")
        self.record_text: str = RECORD.read_text(encoding="utf-8")

    def cron_block(self) -> str:
        """
        The body of the record's fenced cron block.

        `self.fail()` rather than a bare `assert`, because `python -O` strips
        an assert and a check that disappears under an optimised interpreter is
        worse than no check at all -- it still reads like coverage.
        :return: The block's body, without the fences
        """

        match = CRON_FENCE.search(self.record_text)

        if match is None:
            self.fail("docs/scheduling.md has no fenced cron block to compare against")

        return match.group("body")

    def test_the_document_has_exactly_one_cron_block(self) -> None:
        self.assertEqual(len(CRON_FENCE.findall(self.record_text)), 1)

    def test_the_two_schedules_are_the_same(self) -> None:
        self.assertEqual(
            schedule(self.artifact_text),
            schedule(self.cron_block()),
            "scripts/stonksmith.cron and the cron block in docs/scheduling.md "
            "have drifted apart; change both in the same pass",
        )

    def test_neither_grows_a_fidelity_entry(self) -> None:
        # The absence is the point of the record: Fidelity is browser-backed
        # behind bot detection and 2FA, and SnapTrade covers the same accounts.
        # Running both writes the money twice, and the total that results is
        # wrong in the direction that looks correct.
        #
        # Only the entries are searched, never the prose around them -- the
        # record discusses Fidelity at length and has to be free to.
        for name, text in (
            ("artifact", self.artifact_text),
            ("record", self.cron_block()),
        ):
            with self.subTest(name):
                self.assertFalse(
                    any("fidelity" in line for line in schedule(text)),
                    "a fidelity entry is not an oversight to be corrected",
                )

    def test_the_entries_are_staggered(self) -> None:
        # `scraped_at` is stamped to the second and is half a snapshot's key,
        # so two entries firing in the same minute risk collapsing into one
        # snapshot. Distinct minutes is the property that keeps them apart.
        minutes = [
            line.split()[0]
            for line in schedule(self.artifact_text)
            if not line.startswith("PATH=")
        ]

        self.assertEqual(len(minutes), len(set(minutes)))

    def test_the_sheet_goes_last(self) -> None:
        # It renders what the databases hold when it runs, so a sheet step
        # before a broker step renders that broker's previous night.
        entries = [
            line
            for line in schedule(self.artifact_text)
            if not line.startswith("PATH=")
        ]

        self.assertIn("stonksmithdb sheet", entries[-1])
        self.assertFalse(any("stonksmithdb sheet" in line for line in entries[:-1]))


if __name__ == "__main__":
    unittest.main()
