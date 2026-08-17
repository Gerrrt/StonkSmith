# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""The coverage floor is written in four files and has to be one number.

`--cov-fail-under` is not configured anywhere central. It is passed on the
command line, deliberately -- the comment in .github/workflows/ci.yml explains
that putting it in [tool.coverage.report] would make `pytest --cov` over a
handful of files fail locally on a number meant for the whole suite.

The cost of that choice is four copies. ci.yml runs it on every pull request,
release.yml runs it again against the tagged tree, and CONTRIBUTING.md and
README.md both quote the four gates verbatim so a contributor can paste them.
Only the first two are executable. The other two are prose that looks executable,
which is worse than prose that does not: somebody pastes the README's block,
watches it pass, and pushes to a CI that was holding a different line.

Raising the floor is the moment this breaks, and it is the moment it is least
likely to be noticed -- the number goes up because coverage went up, so every
copy still passes locally whether or not it was edited. A stale copy is only
ever discovered by someone whose work sits between the two numbers.

CONTRIBUTING.md says to raise the floor when the real number moves and never to
lower it to make CI pass. That is the instruction; this file is the mechanism,
and it is the one this project keeps having to write -- see
tests/test_live_verification_tally.py, whose docstring records a count that
disagreed with its own table for four commits, and
tests/test_the_complexity_ceiling_is_one_number.py, written the same day as this
one for the same defect against a different number.

Nothing here knows what the floor ought to be. It reads every copy and asserts
they agree, so raising it stays a four-file edit that fails loudly when it is a
three-file edit.
"""

import re
import unittest

from package_tree import REPO

#: Every file that states the floor. The two workflows are what actually enforce
#: it; the two markdown files quote the gates for a reader to run by hand, which
#: is why a disagreement between them is a contributor running the wrong gate
#: rather than a typo in a document.
STATED_IN = (
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    "CONTRIBUTING.md",
    "README.md",
)

#: The flag as it is written everywhere -- on a `run:` line in the workflows and
#: inside a fenced bash block in the markdown. One pattern covers both because
#: the command is quoted verbatim rather than paraphrased, which is the property
#: that makes a contributor's paste-and-run work at all.
FLOOR = re.compile(r"--cov-fail-under=(\d+)")

#: ci.yml's comment names the measured baseline the floor is rounded down from.
#: It is checked separately: a baseline left behind by a raise does not break any
#: gate, it just tells the next person the suite covers less than it does.
BASELINE = re.compile(
    r"^\s*# The floor is the measured baseline \((\d+)\.(\d+)%\)", re.MULTILINE
)


def stated_floors() -> dict[str, list[str]]:
    return {
        name: FLOOR.findall(string=(REPO / name).read_text(encoding="utf-8"))
        for name in STATED_IN
    }


class CoverageFloorTests(unittest.TestCase):
    def test_every_file_states_the_floor(self) -> None:
        # A file that stopped mentioning it fails here rather than silently
        # dropping out of the comparison below, where a missing copy and an
        # agreeing copy are indistinguishable.
        for name, found in stated_floors().items():
            with self.subTest(file=name):
                self.assertTrue(
                    found,
                    f"{name} no longer states --cov-fail-under; either the gate "
                    "moved or this test is now checking three files and saying "
                    "four",
                )

    def test_the_four_copies_agree(self) -> None:
        found = stated_floors()
        numbers: set[str] = {n for copies in found.values() for n in copies}

        self.assertEqual(
            len(numbers),
            1,
            "the coverage floor disagrees between the files that state it: "
            + ", ".join(
                f"{name} says {'/'.join(copies)}" for name, copies in found.items()
            )
            + ". The workflows are what run; the markdown is what a contributor "
            "pastes, and a contributor running a lower floor than CI finds out "
            "from a red pull request",
        )

    def test_the_baseline_comment_is_above_the_floor_it_explains(self) -> None:
        # The comment says the floor is that baseline "rounded down", so the two
        # are not independent: a baseline below the floor describes a gate that
        # could not have been passing when it was written.
        ci = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        match = BASELINE.search(string=ci)

        self.assertIsNotNone(
            match, "ci.yml no longer records the measured baseline the floor came from"
        )
        assert match is not None

        # Not FLOOR.findall(...)[0] straight into int(). The condition this test
        # helps catch is the flag going missing from ci.yml, and indexing an empty
        # list for it raises IndexError -- a traceback naming this file rather
        # than the workflow, from a test whose message would have said which. The
        # check above catches it too, but relying on that is relying on test
        # order, which unittest does not promise.
        baseline = float(f"{match.group(1)}.{match.group(2)}")
        floors: list[str] = FLOOR.findall(string=ci)

        self.assertTrue(
            floors,
            "ci.yml no longer passes --cov-fail-under, so there is no floor for "
            "its baseline comment to be rounded down from",
        )

        floor = int(floors[0])

        self.assertGreaterEqual(
            baseline,
            float(floor),
            f"ci.yml says the measured baseline is {baseline}% and the floor is "
            f"{floor}%. The floor is the baseline rounded down, so a baseline "
            "under it is a stale comment from before the last raise",
        )
        self.assertLess(
            baseline - float(floor),
            1.0,
            f"ci.yml's baseline of {baseline}% is more than a point above the "
            f"floor of {floor}%. Rounded down means the next integer below, so "
            "the floor has stopped tracking the number it is derived from",
        )


if __name__ == "__main__":
    unittest.main()
