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
RUNNER = REPO / "scripts" / "stonksmith-nightly.sh"

#: A fenced block introduced as `cron`. The document has exactly one, and the
#: count is asserted rather than assumed -- a second block added later would
#: otherwise go unchecked, which is the failure this file exists to prevent.
#: `\r?` on both fences because a checkout that converts line endings would
#: otherwise fail this as "no cron block at all", which reads as drift and is
#: not. The lines inside are rstripped by schedule(), so they need no such care.
CRON_FENCE = re.compile(
    r"^```cron[ \t]*\r?\n(?P<body>.*?)^```[ \t]*\r?$", re.MULTILINE | re.DOTALL
)


def schedule(text: str) -> list[str]:
    """
    The lines of a crontab that carry meaning.

    Whole-line comments and blank lines are dropped: the artifact explains
    itself at length and the document cannot, so requiring those to match would
    be requiring the two to be the same document rather than the same schedule.
    A trailing comment on an entry is *kept*, deliberately -- it is part of the
    line cron reads, so two entries differing only in one differ. Trailing
    whitespace goes, since it is invisible in a diff and would fail this test
    in a way nobody could see.
    :param text: A crontab, or the body of a fenced cron block
    :return: The significant lines, in order
    """

    return [
        stripped
        for line in text.splitlines()
        if (stripped := line.rstrip()) and not stripped.lstrip().startswith("#")
    ]


def commands(text: str) -> list[str]:
    """
    The StonkSmith invocations a schedule makes, in order, however it is written.

    A crontab entry carries a time and a `cd` that the shell script does not
    need, and the script carries a `run` wrapper the crontab has no use for. The
    part that has to agree is what is actually invoked and in what order --
    which broker, with which flags, and the two reading steps last.
    :param text: A crontab or the runner script
    :return: The `uv run ...` commands, in order
    """

    found: list[str] = []

    for line in text.splitlines():
        stripped: str = line.strip()

        if stripped.startswith("#") or not stripped:
            continue

        # A crontab entry: everything the shell is handed after the `cd`.
        if "&& uv run " in stripped:
            found.append(stripped.split("&& ", 1)[1].strip())

        # The runner: one invocation per `run` line.
        elif stripped.startswith("run uv run "):
            found.append(stripped[len("run ") :].strip())

    return found


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
        # The absence is the point of the record. StonkSmith stopped shipping a
        # fidelity broker at 1.0 because SnapTrade reaches the same accounts,
        # and scheduling both writes the money twice -- a total that is wrong in
        # the direction that looks correct.
        #
        # Removing the broker did not remove the hazard, which is why this
        # outlives it. docs/brokers.md invites an operator who wants the scraper
        # to keep it under ~/.stonksmith/brokers/, BrokerLoader discovers what it
        # finds there, and a scheduled entry for it double-counts exactly as
        # before. The name is the one an operator would reach for.
        #
        # Only the entries are searched, never the prose around them -- the
        # record still explains the replacement and has to be free to.
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

    def test_the_launchd_runner_makes_the_same_run(self) -> None:
        # A third copy of the schedule, for the platform where cron is the wrong
        # tool -- two steps read the login keychain, which a cron job cannot
        # see. Same commands in the same order, or the two schedules quietly
        # stop being the same nightly run and only one of them gets maintained.
        self.assertEqual(
            commands(RUNNER.read_text(encoding="utf-8")),
            commands(self.artifact_text),
            "scripts/stonksmith-nightly.sh and scripts/stonksmith.cron have "
            "drifted apart; change both in the same pass",
        )

    def test_the_reading_steps_follow_the_writing_ones(self) -> None:
        # Both read what the databases hold at the moment they run, so either
        # one placed early reports on the previous night. The sheet renders
        # them; the freshness check then asks about what the sheet just drew,
        # which is why it comes after the sheet rather than merely after the
        # brokers.
        entries = [
            line
            for line in schedule(self.artifact_text)
            if not line.startswith("PATH=")
        ]

        def only(needle: str) -> int:
            found = [i for i, line in enumerate(entries) if needle in line]
            self.assertEqual(len(found), 1, f"expected exactly one {needle!r} entry")
            return found[0]

        sheet = only("stonksmithdb sheet")
        stale = only("stonksmithdb stale")
        brokers = [i for i, line in enumerate(entries) if " stonksmith " in line]

        self.assertTrue(brokers, "no broker entries found")
        self.assertLess(max(brokers), sheet)
        self.assertLess(sheet, stale)


if __name__ == "__main__":
    unittest.main()
