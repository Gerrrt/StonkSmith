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
"""

import plistlib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENT = REPO / "scripts" / "com.stonksmith.nightly.plist"
RUNNER = REPO / "scripts" / "stonksmith-nightly.sh"


class TheAgentParses(unittest.TestCase):
    def setUp(self) -> None:
        with open(AGENT, "rb") as handle:
            self.plist = plistlib.load(handle)

    def test_it_is_well_formed(self) -> None:
        # setUp already proved it; this names the reason so a failure here reads
        # as "the plist is malformed" rather than as an error in another test.
        self.assertIsInstance(self.plist, dict)

    def test_it_runs_the_committed_runner(self) -> None:
        argv: list[str] = self.plist["ProgramArguments"]

        self.assertTrue(
            argv[-1].endswith(RUNNER.name),
            f"the agent runs {argv[-1]}, which is not {RUNNER.name}",
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
