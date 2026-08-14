"""The morning LaunchAgent parses, and fires in the morning.

tests/test_launchd_agent.py makes this argument for the nightly agent and it
holds identically here: a plist that is not well-formed is not a broken schedule
that reports itself. `launchctl bootstrap` refuses it and the brief simply never
appears, which is indistinguishable from a morning where nothing had changed --
and this agent's whole job is to be the thing that shows up.

One check the nightly file does not need: that these two do not fire at the same
time. They are separate agents precisely because a scrape belongs after the close
and a reminder belongs when somebody is awake, and an edit that drifted the
morning agent into the evening would produce a brief rendered twelve hours before
anyone opens a laptop. It would still be written, still be correct, and still be
a file rather than a reminder.
"""

import plistlib
import unittest
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
AGENT = REPO / "scripts" / "com.stonksmith.morning.plist"
RUNNER = REPO / "scripts" / "stonksmith-morning.sh"
NIGHTLY = REPO / "scripts" / "com.stonksmith.nightly.plist"


def _load(path: Path) -> tuple[dict[str, Any] | None, str]:
    """
    Parse an agent, keeping any failure as text instead of raising it.
    :param path: The plist
    :return: (the plist, "") or (None, why it could not be read)
    """

    try:
        with path.open("rb") as handle:
            return plistlib.load(handle), ""

    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


AGENT_PLIST, PARSE_ERROR = _load(path=AGENT)


class TheMorningAgentIsWellFormed(unittest.TestCase):
    def test_it_parses(self) -> None:
        self.assertEqual(
            PARSE_ERROR,
            "",
            f"{AGENT.name} is not well-formed, so `launchctl bootstrap` will "
            "refuse it and the brief will silently never appear. A double "
            "hyphen inside the XML comment is the way this usually happens.",
        )


class TheMorningAgentMatchesTheSchedule(unittest.TestCase):
    def setUp(self) -> None:
        if PARSE_ERROR or AGENT_PLIST is None:
            self.skipTest(f"{AGENT.name} does not parse; see the well-formed case")

        self.plist: dict[str, Any] = AGENT_PLIST

    def test_it_runs_the_committed_runner(self) -> None:
        argv: list[str] = self.plist["ProgramArguments"]
        naming: list[str] = [arg for arg in argv if arg.endswith(RUNNER.name)]

        self.assertEqual(
            len(naming),
            1,
            f"expected exactly one argument naming {RUNNER.name}, got {argv}",
        )
        self.assertTrue(RUNNER.exists(), "the runner the agent names is missing")

    def test_it_fires_on_weekdays_only(self) -> None:
        # The nightly run is weekdays, so a Saturday brief would report a
        # carried-forward flat line by construction -- a page that says nothing
        # happened, on a day nothing could have.
        weekdays = sorted(e["Weekday"] for e in self.plist["StartCalendarInterval"])

        self.assertEqual(weekdays, [1, 2, 3, 4, 5])

    def test_every_entry_fires_at_one_time(self) -> None:
        times = {(e["Hour"], e["Minute"]) for e in self.plist["StartCalendarInterval"]}

        self.assertEqual(
            len(times),
            1,
            f"the weekdays do not all fire at the same time: {sorted(times)}",
        )

    def test_it_fires_in_the_morning(self) -> None:
        hours = {e["Hour"] for e in self.plist["StartCalendarInterval"]}

        self.assertTrue(
            all(hour < 12 for hour in hours),
            f"the morning brief is scheduled for {sorted(hours)}, which is not "
            "a time anybody is reading it before the day starts",
        )

    def test_it_does_not_collide_with_the_nightly_run(self) -> None:
        nightly, error = _load(path=NIGHTLY)

        if error or nightly is None:
            self.skipTest("the nightly agent does not parse; see test_launchd_agent")

        mornings = {
            (e["Hour"], e["Minute"]) for e in self.plist["StartCalendarInterval"]
        }
        nights = {(e["Hour"], e["Minute"]) for e in nightly["StartCalendarInterval"]}

        self.assertFalse(
            mornings & nights,
            "the brief fires at the same time as the scrape, so it reports on "
            "the previous evening's data while this evening's is being written",
        )

    def test_it_sets_a_path_for_uv(self) -> None:
        self.assertIn("PATH", self.plist["EnvironmentVariables"])

    def test_it_writes_its_own_log(self) -> None:
        # Its own, not the nightly one. A brief that fails is a different
        # investigation from a scrape that fails, and interleaving them in one
        # file is how the wrong one gets read.
        self.assertNotIn("nightly", self.plist["StandardOutPath"])


if __name__ == "__main__":
    unittest.main()
