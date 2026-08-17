# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""The complexity ceiling is configured once and described twice.

`max-complexity` lives in pyproject.toml, and two pieces of prose state its
value: the comment directly above it, which explains what the number is (the
score of the worst function in src/), and CONTRIBUTING.md's *Things that are
settled*, which tells the next person not to reopen it without reading why.

Both had drifted. The ceiling was lowered from 16 to 12 when `error_shape`,
`to_amount`, `main` and Ally's `on_login` were split, and CONTRIBUTING.md went on
saying 16 -- under the one heading in that file whose whole purpose is to be
trusted without re-derivation. A reader checking whether their function fits gets
four points of headroom that ruff will not give them, and a reader arguing with
the setting argues with the wrong number.

That is the failure this file converts into a red test, and it is the same one
tests/test_live_verification_tally.py was written for a file over: its docstring
says the instruction to keep the two in step "was the only thing holding them
together", and that "an instruction is not a mechanism". Prose is not executable,
and a summary that is merely stale looks exactly like one that is right.

Nothing here knows what the ceiling ought to be. The setting is read as the
authority and the prose is compared against it, so lowering the ceiling again is
one edit plus two sentences, and forgetting either is a failure rather than a
silence.
"""

import re
import tomllib
import unittest

from package_tree import REPO

CONTRIBUTING = REPO / "CONTRIBUTING.md"
PYPROJECT = REPO / "pyproject.toml"

#: How CONTRIBUTING.md writes the ceiling: inside backticks, in the settled
#: bullet. Every occurrence is collected rather than the first, because the
#: invariant is that the file states one number -- a second mention that
#: disagreed with the first would be the same bug wearing a different hat.
IN_PROSE = re.compile(r"`max-complexity = (\d+)`")

#: How the comment above the setting opens. It names the number as a measurement
#: ("what the worst function in src/ scores today") rather than as a preference,
#: so a comment left behind by a lowering states a score no function has.
IN_COMMENT = re.compile(r"^# (\d+) is what the worst function", re.MULTILINE)


def configured_ceiling() -> int:
    with PYPROJECT.open(mode="rb") as f:
        settings = tomllib.load(f)

    return int(settings["tool"]["ruff"]["lint"]["mccabe"]["max-complexity"])


class ComplexityCeilingTests(unittest.TestCase):
    def test_contributing_states_the_configured_ceiling(self) -> None:
        stated: list[str] = IN_PROSE.findall(
            string=CONTRIBUTING.read_text(encoding="utf-8")
        )

        # An absent mention fails too. The bullet is what stops the ceiling being
        # reopened without reading the reason, so a CONTRIBUTING.md that stopped
        # naming it would pass a test that only checked the numbers it found.
        self.assertTrue(
            stated,
            "CONTRIBUTING.md no longer states `max-complexity = N` under Things "
            "that are settled; the bullet is what points at the reasoning",
        )

        for number in stated:
            with self.subTest(stated=number):
                self.assertEqual(
                    int(number),
                    configured_ceiling(),
                    f"CONTRIBUTING.md says max-complexity = {number}; "
                    f"pyproject.toml says {configured_ceiling()}. The setting is "
                    "the authority -- change the prose, not the ceiling, unless "
                    "you meant to change the ceiling",
                )

    def test_the_comment_above_the_setting_states_it_too(self) -> None:
        # The comment is the reasoning, and it is the copy most likely to be
        # missed: somebody editing the number is looking at the line below it.
        stated: list[str] = IN_COMMENT.findall(
            string=PYPROJECT.read_text(encoding="utf-8")
        )

        self.assertEqual(
            len(stated),
            1,
            "expected exactly one '# N is what the worst function ...' comment in "
            f"pyproject.toml, found {len(stated)}",
        )
        self.assertEqual(
            int(stated[0]),
            configured_ceiling(),
            f"the comment above max-complexity says the worst function scores "
            f"{stated[0]}, but the ceiling is set to {configured_ceiling()}",
        )


if __name__ == "__main__":
    unittest.main()
