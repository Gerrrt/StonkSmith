"""The LaunchAgent has to parse, because launchd will not say that it does not.

A plist that is not well-formed is not a broken schedule that reports itself --
`launchctl bootstrap` refuses it and the nightly run simply never happens, which
looks identical to a machine that was asleep. Nothing else in this repository
reads the file, so without this it is checked only by being installed.

The failure that prompted it is one XML forbids and prose invites: a comment
cannot contain a double hyphen, and the comment in that file documents a runner
whose output is prefixed with one. Editing the guidance broke the agent, the
suite stayed green, and the only symptom would have been a schedule that quietly
stopped running.

Parsed once at import rather than per test, and the failure kept as a message
rather than raised. A malformed plist is one fact about one file: it should read
as a single failure saying so, not as the same traceback under every assertion
that then could not run.
"""

import plistlib
import unittest
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
AGENT = REPO / "scripts" / "com.stonksmith.nightly.plist"
RUNNER = REPO / "scripts" / "stonksmith-nightly.sh"


def _load() -> tuple[dict[str, Any] | None, str]:
    """
    Parse the agent, keeping any failure as text instead of raising it.
    :return: (the plist, "") or (None, why it could not be read)
    """

    try:
        with open(AGENT, "rb") as handle:
            return plistlib.load(handle), ""

    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


AGENT_PLIST, PARSE_ERROR = _load()


class TheAgentIsWellFormed(unittest.TestCase):
    def test_it_parses(self) -> None:
        self.assertEqual(
            PARSE_ERROR,
            "",
            f"{AGENT.name} is not well-formed, so `launchctl bootstrap` will "
            "refuse it and the schedule will silently never run. A double "
            "hyphen inside the XML comment is the way this usually happens, "
            "and the runner's own output is full of them.",
        )


class TheAgentMatchesTheSchedule(unittest.TestCase):
    def setUp(self) -> None:
        if PARSE_ERROR or AGENT_PLIST is None:
            # One failure, above, rather than this one repeated five times.
            self.skipTest(f"{AGENT.name} does not parse; see TheAgentIsWellFormed")

        self.plist: dict[str, Any] = AGENT_PLIST

    def test_it_runs_the_committed_runner(self) -> None:
        # By presence rather than by position: a plist that grows an argument
        # after the script is still correct, and a test that reads argv[-1]
        # would call it broken.
        argv: list[str] = self.plist["ProgramArguments"]
        naming: list[str] = [arg for arg in argv if arg.endswith(RUNNER.name)]

        self.assertEqual(
            len(naming),
            1,
            f"expected exactly one argument naming {RUNNER.name}, got {argv}",
        )
        self.assertTrue(RUNNER.exists(), "the runner the agent names is missing")

    def test_it_fires_on_weekdays_only(self) -> None:
        # The schedule the crontab keeps in cron syntax, in launchd's. Weekday 1
        # is Monday and 0 and 7 are both Sunday, so a weekend entry is a typo
        # rather than a preference.
        weekdays = sorted(e["Weekday"] for e in self.plist["StartCalendarInterval"])

        self.assertEqual(weekdays, [1, 2, 3, 4, 5])

    def test_every_entry_fires_at_one_time(self) -> None:
        times = {(e["Hour"], e["Minute"]) for e in self.plist["StartCalendarInterval"]}

        self.assertEqual(
            len(times),
            1,
            f"the weekdays do not all fire at the same time: {sorted(times)}",
        )

    def test_it_sets_a_path_for_uv(self) -> None:
        # Not which directory -- that is the operator's to edit -- only that the
        # key is there to edit. launchd hands an agent almost nothing otherwise.
        self.assertIn("PATH", self.plist["EnvironmentVariables"])


if __name__ == "__main__":
    unittest.main()
