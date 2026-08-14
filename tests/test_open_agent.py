"""The opening-bell agent parses, and the three agents do not collide.

tests/test_launchd_agent.py makes the parse argument for the nightly agent and
tests/test_morning_agent.py repeats it for the brief. Both hold here for the
same reason: `launchctl bootstrap` refuses a malformed plist and the run simply
never happens, which looks identical to a machine that was asleep.

Worth recording that `plutil -lint` is not the check. It accepts a double hyphen
inside an XML comment; expat, which plistlib uses and which launchd's own parser
agrees with, does not. The morning agent shipped a lint-clean plist that would
not load, and this file caught the same mistake in this one. Reach for the test,
not the command-line linter.

What is new here is the **ordering** case. Three agents now share a weekday and
two of them touch the same files:

    06:30  morning   reads every database in the workspace
    06:35  open      writes every database in the workspace
    18:30  nightly   writes every database in the workspace

The five minutes between the first two are load-bearing rather than tidy. Fire
them together and the brief reports on a workspace caught mid-write -- some
brokers updated, some not, and a headline delta assembled across the seam. It
would not error and it would not look wrong. Brief first is also correct on its
own terms, since a morning brief reports on last night's close, which is exactly
what the databases hold until the opening run touches them.
"""

import plistlib
import unittest
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
AGENT = SCRIPTS / "com.stonksmith.open.plist"
RUNNER = SCRIPTS / "stonksmith-open.sh"

#: Every agent this repository ships, and what each one does to the databases.
#: "writes" agents must not overlap a "reads" agent.
AGENTS: dict[str, str] = {
    "morning": "reads",
    "open": "writes",
    "nightly": "writes",
}


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


def _minutes(plist: dict[str, Any]) -> set[int]:
    """
    When an agent fires, as minutes past midnight.
    :param plist: A parsed agent
    :return: One entry per distinct firing time
    :rtype: set[int]
    """

    return {
        (entry["Hour"] * 60) + entry["Minute"]
        for entry in plist["StartCalendarInterval"]
    }


def commands(script: Path) -> str:
    """
    A shell script with its comments removed.

    Load-bearing rather than tidy. These runners are documented at length in
    their own comments -- the opening one explains at length why it does *not*
    run the freshness check -- so a test asserting on the raw text matches the
    prose that says a thing is absent and concludes it is present. Both cases
    below were written that way first and both passed for the wrong reason.
    :param script: The runner
    :return: Its executable lines, newline-joined
    :rtype: str
    """

    return "\n".join(
        line
        for line in script.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


AGENT_PLIST, PARSE_ERROR = _load(path=AGENT)


class TheOpenAgentIsWellFormed(unittest.TestCase):
    def test_it_parses(self) -> None:
        self.assertEqual(
            PARSE_ERROR,
            "",
            f"{AGENT.name} is not well-formed, so `launchctl bootstrap` will "
            "refuse it and the opening scrape will silently never run. A double "
            "hyphen inside the XML comment is how this happens, and note that "
            "`plutil -lint` accepts one -- this test is the check.",
        )


class TheOpenAgentMatchesTheSchedule(unittest.TestCase):
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
        weekdays = sorted(e["Weekday"] for e in self.plist["StartCalendarInterval"])

        self.assertEqual(weekdays, [1, 2, 3, 4, 5])

    def test_it_fires_after_the_open_and_before_noon(self) -> None:
        # The market opens 06:30 Pacific. Earlier than that and the scrape
        # predates the first prices of the day; much later and it is not an
        # opening mark at all, it is a midday one.
        for when in _minutes(plist=self.plist):
            self.assertGreaterEqual(when, 6 * 60 + 30, "fires before the open")
            self.assertLess(when, 12 * 60, "fires after midday")

    def test_it_sets_a_path_for_uv(self) -> None:
        self.assertIn("PATH", self.plist["EnvironmentVariables"])

    def test_it_writes_its_own_log(self) -> None:
        # Its own, not the nightly or morning one. Three agents interleaved in
        # one file is how the wrong run gets read during an investigation.
        out: str = self.plist["StandardOutPath"]

        self.assertIn("open", out)
        self.assertNotIn("nightly", out)
        self.assertNotIn("morning", out)


class TheRunnerDoesNotDoubleTheFreshnessAlarm(unittest.TestCase):
    def test_it_does_not_run_stale(self) -> None:
        # The nightly run makes that check twelve hours earlier and nothing can
        # have gone stale since. An alarm that fires more often than it has news
        # is the one that gets muted, which is the failure docs/scheduling.md
        # opens by naming.
        body: str = commands(script=RUNNER)

        self.assertNotIn(
            "stonksmithdb stale",
            body,
            "the opening run repeats the freshness check the evening run "
            "already made, doubling the alarm without doubling what it detects",
        )

    def test_it_writes_the_sheet_once_after_the_brokers(self) -> None:
        # Every broker rewrites the whole sheet when it finishes, so the brokers
        # run --no-sheet and one write follows them. Four full rewrites in
        # thirty seconds spent Google's per-minute quota and it refused the
        # last -- the only one that needed to happen.
        body: str = commands(script=RUNNER)

        self.assertEqual(body.count("stonksmithdb sheet"), 1)

        # The trailing space is what separates a broker line from a shell one:
        # "uv run stonksmithdb" continues with "db" rather than a space, so this
        # counts the brokers and nothing else. Subtracting the shell invocations
        # from it -- which this test did first -- takes them off twice.
        brokers: int = body.count("uv run stonksmith ")

        self.assertEqual(
            body.count("--no-sheet"),
            brokers,
            f"{brokers} brokers run at the open and only "
            f"{body.count('--no-sheet')} pass --no-sheet, so the sheet is "
            "rewritten once per broker and Google refuses the last write",
        )


class TheAgentsDoNotCollide(unittest.TestCase):
    """The invariant that only exists now that three agents share a weekday."""

    def setUp(self) -> None:
        self.loaded: dict[str, dict[str, Any]] = {}

        for name in AGENTS:
            plist, error = _load(path=SCRIPTS / f"com.stonksmith.{name}.plist")

            if error or plist is None:
                self.skipTest(f"com.stonksmith.{name}.plist does not parse")

            self.loaded[name] = plist

    def test_no_two_agents_fire_at_the_same_minute(self) -> None:
        seen: dict[int, str] = {}

        for name, plist in self.loaded.items():
            for when in _minutes(plist=plist):
                clash: str | None = seen.get(when)

                self.assertIsNone(
                    clash,
                    f"{name} and {clash} both fire at {when // 60:02d}:{when % 60:02d}",
                )
                seen[when] = name

    def test_the_brief_runs_before_the_opening_scrape(self) -> None:
        # The ordering this file exists for. The brief reads every database and
        # the opening run writes them, so the brief must finish first -- and a
        # morning brief reports on last night's close, which is what it has
        # until the opening scrape touches anything.
        brief: int = min(_minutes(plist=self.loaded["morning"]))
        scrape: int = min(_minutes(plist=self.loaded["open"]))

        self.assertLess(
            brief,
            scrape,
            "the opening scrape starts before or with the brief, so the brief "
            "reports on a workspace caught mid-write",
        )

    def test_the_gap_is_wide_enough_to_finish_in(self) -> None:
        # The brief reads the databases and renders one file; it takes about a
        # second. Five minutes is not tight, and asserting it stops a later edit
        # from shaving the gap to one minute on the reasoning that it is "only a
        # read" -- a read that is still running when the write starts is the
        # thing being prevented.
        brief: int = min(_minutes(plist=self.loaded["morning"]))
        scrape: int = min(_minutes(plist=self.loaded["open"]))

        self.assertGreaterEqual(scrape - brief, 5, "under five minutes apart")

    def test_the_close_run_is_late_enough_for_tsp(self) -> None:
        # The one that must not drift back to the 13:00 bell. TSP publishes the
        # day's share prices in the evening, so an afternoon run records
        # yesterday's price as today's -- every day, with nothing saying so.
        # scripts/stonksmith.cron:120 is the record for the 18:30 choice.
        for when in _minutes(plist=self.loaded["nightly"]):
            self.assertGreaterEqual(
                when,
                17 * 60,
                "the close run moved earlier than 17:00, which on Pacific is "
                "before TSP publishes -- the TSP mark would be a day stale and "
                "would look current",
            )


if __name__ == "__main__":
    unittest.main()
