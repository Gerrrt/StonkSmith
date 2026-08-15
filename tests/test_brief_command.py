"""The command writes a brief, restricts it, and knows when not to move on.

The unit tests around it pin the rules; this one pins that the command is wired
to them. A `should_advance` that is correct and never called is the same outcome
as one that is wrong, and it is the outcome a test of the rule alone cannot see.

Real databases rather than a stubbed portfolio, on tests/test_staleness_check's
reasoning: the whole path is what is under test -- what the databases hold, what
the rules make of it, what lands on disk, and what the shell exits with.

`webbrowser.open` is patched throughout. Not for speed: without it every one of
these cases opens a browser window on whoever is running the suite, and the point
of the flag being tested is that a scripted caller can decline that.
"""

import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_isolation import UserConfigMixin
from keyring_isolation import MemoryKeyringMixin
from stonksmith.etc.brief import read_baseline
from stonksmith.etc.broker_db import BrokerDatabase
from stonksmith.etc.infrastructure import create_db_engine
from stonksmith.etc.permissions import OWNER_ONLY_FILE
from stonksmith.etc.records import AccountIdentity, Holding
from stonksmith.etc.stonksmithdb import StonkSmithDBMenu


class TheBriefCommand(UserConfigMixin, MemoryKeyringMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "default").mkdir()

        self.reports = self.root / "reports"
        self.baseline = self.root / "brief_baseline.json"

    def _write(self, broker: str, as_of: str, value: float, units: float = 1.0) -> None:
        """
        Record one snapshot for one broker.
        :param broker: The broker name, which becomes the database file stem
        :param as_of: The date the value is for
        :param value: What the account was worth
        :param units: How many units the position held
        """

        db = BrokerDatabase(
            db_engine=create_db_engine(db_path=self.root / "default" / f"{broker}.db"),
            broker=broker,
        )
        db.save_snapshot(
            account=AccountIdentity(
                account_key=f"{broker}-1", display_name=f"{broker} account"
            ),
            # Second-resolution and half the snapshot key, so two writes for one
            # broker need different stamps or the later one replaces the earlier.
            scraped_at=f"{as_of} 18:30:00",
            as_of=as_of,
            value=value,
            currency="USD",
            holdings=[Holding(symbol="VTI", units=units, value=value)],
            transactions=[],
        )
        db.shutdown_db()

    def _run(self, line: str = "--no-open") -> tuple[bool, str]:
        """
        Run `brief` against the built workspace.
        :param line: The command's arguments
        :return: (whether it failed, what it printed)
        :rtype: tuple[bool, str]
        """

        shell = StonkSmithDBMenu.__new__(StonkSmithDBMenu)
        shell.workspace = "default"
        shell.failed = False

        printed: list[str] = []

        with (
            patch("stonksmith.etc.portfolio.workspace_dir", str(object=self.root)),
            patch("stonksmith.etc.paths.reports_path", self.reports),
            patch("stonksmith.etc.paths.baseline_path", self.baseline),
            patch("webbrowser.open"),
            patch(
                "builtins.print",
                side_effect=lambda *a: printed.append(" ".join(map(str, a))),
            ),
        ):
            shell.do_brief(line)

        return shell.failed, "\n".join(printed)

    def _reports(self) -> list[Path]:
        return sorted(self.reports.glob("*.html"))

    def test_it_writes_a_brief_and_takes_a_baseline(self) -> None:
        self._write(broker="tsp", as_of="2026-08-12", value=1000.0)
        failed, output = self._run()

        self.assertFalse(failed, output)
        self.assertEqual(len(self._reports()), 1)

        stored = read_baseline(path=self.baseline)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.taken_on, "2026-08-12")

    def test_the_report_is_owner_only(self) -> None:
        # It states the portfolio total and every account behind it, in a file
        # sitting beside the databases this project already chmods 0600.
        self._write(broker="tsp", as_of="2026-08-12", value=1000.0)
        self._run()

        mode: int = stat.S_IMODE(self._reports()[0].stat().st_mode)

        self.assertEqual(mode, OWNER_ONLY_FILE, f"the brief is mode {mode:04o}")

    def test_a_second_run_with_no_new_scrape_holds_the_baseline(self) -> None:
        # The rule in its live setting. The baseline must still name the date it
        # was taken on, and the command must say out loud that it did not move --
        # a reader who is not told cannot tell this from a genuinely quiet day.
        self._write(broker="tsp", as_of="2026-08-12", value=1000.0)
        self._run()
        _, output = self._run()

        stored = read_baseline(path=self.baseline)
        assert stored is not None

        self.assertEqual(stored.taken_on, "2026-08-12")
        self.assertIn("Baseline held", output)

    def test_a_peek_does_not_take_a_baseline(self) -> None:
        self._write(broker="tsp", as_of="2026-08-12", value=1000.0)
        _, output = self._run(line="peek --no-open")

        self.assertIsNone(
            read_baseline(path=self.baseline),
            "a peek wrote a baseline, so looking at the brief a second time in "
            "one day consumes the comparison the next morning needed",
        )
        self.assertIn("this was a peek", output)

    def test_a_newer_scrape_moves_the_baseline_on(self) -> None:
        self._write(broker="tsp", as_of="2026-08-12", value=1000.0)
        self._run()
        self._write(broker="tsp", as_of="2026-08-13", value=1100.0)
        self._run()

        stored = read_baseline(path=self.baseline)
        assert stored is not None

        self.assertEqual(stored.taken_on, "2026-08-13")

    def test_the_movement_reaches_the_page(self) -> None:
        self._write(broker="tsp", as_of="2026-08-12", value=1000.0)
        self._run()
        self._write(broker="tsp", as_of="2026-08-13", value=1100.0, units=2.0)
        self._run()

        page: str = self._reports()[-1].read_text(encoding="utf-8")

        self.assertIn("$1,100.00", page)
        self.assertIn("$100.00", page)

    def test_an_unreadable_database_fails_the_command(self) -> None:
        # And still writes the brief, carrying the warning at the top of the
        # page. A total short by a broker is the failure that must not be quiet,
        # and the page is where somebody who is not reading a log will see it.
        self._write(broker="tsp", as_of="2026-08-12", value=1000.0)
        (self.root / "default" / "ally.db").write_text(data="not a database")

        failed, output = self._run()

        self.assertTrue(failed, output)
        self.assertIn("could not be read", output)
        self.assertEqual(len(self._reports()), 1)

    def test_a_colour_line_it_could_not_read_is_named(self) -> None:
        # get_account_colors returns the lines it refused and build_brief has
        # nowhere to say so, being the model -- so the command reports them, on
        # the rule the [MANUAL] parser and the alias check already follow. A
        # colour that was not understood leaves the row with no dot, which looks
        # exactly like an owner nobody wrote a line for: silence makes a typo
        # indistinguishable from a decision.
        self._write(broker="tsp", as_of="2026-08-12", value=1000.0)

        with patch(
            "stonksmith.etc.config.get_account_colors",
            return_value=([], ["Sam = chartreuse"]),
        ):
            _failed, output = self._run()

        self.assertIn("chartreuse", output)
        self.assertIn("Unreadable [ACCOUNTS] colors line", output)

    def test_an_unknown_argument_is_refused(self) -> None:
        # Refused rather than ignored: a misspelled "peek" that silently advanced
        # the baseline would consume exactly the comparison it was typed to save.
        self._write(broker="tsp", as_of="2026-08-12", value=1000.0)
        failed, output = self._run(line="--peek")

        self.assertTrue(failed)
        self.assertIn("Not something brief understands", output)
        self.assertEqual(self._reports(), [])

    def test_it_opens_the_report_unless_told_not_to(self) -> None:
        self._write(broker="tsp", as_of="2026-08-12", value=1000.0)

        shell = StonkSmithDBMenu.__new__(StonkSmithDBMenu)
        shell.workspace = "default"
        shell.failed = False

        with (
            patch("stonksmith.etc.portfolio.workspace_dir", str(object=self.root)),
            patch("stonksmith.etc.paths.reports_path", self.reports),
            patch("stonksmith.etc.paths.baseline_path", self.baseline),
            patch("webbrowser.open") as opened,
            patch("builtins.print"),
        ):
            shell.do_brief("")

        opened.assert_called_once()

        # A file:// URL rather than a bare path. webbrowser.open on a path with a
        # space in it does not reliably resolve, and ~/.stonksmith is one
        # rename away from having one.
        self.assertTrue(opened.call_args.kwargs["url"].startswith("file://"))


class TheReportsArePruned(UserConfigMixin, MemoryKeyringMixin, unittest.TestCase):
    """Old briefs are deleted by count, so the window means what it says."""

    config_body: str = "[BRIEF]\nkeep_days = 3\n"

    def setUp(self) -> None:
        super().setUp()

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "default").mkdir()
        self.reports = self.root / "reports"
        self.reports.mkdir()

        # Named as the dates they were written on, which is what makes sorting
        # them by name chronological without trusting an mtime that a restore
        # from backup would have rewritten.
        for day in range(1, 7):
            (self.reports / f"2026-08-0{day}.html").write_text(data="old")

    def test_only_the_newest_are_kept(self) -> None:
        shell = StonkSmithDBMenu.__new__(StonkSmithDBMenu)
        shell.workspace = "default"
        shell.failed = False

        with (
            patch("stonksmith.etc.paths.reports_path", self.reports),
            patch("builtins.print"),
        ):
            shell._prune_reports(keep=3)

        self.assertEqual(
            [path.name for path in sorted(self.reports.glob("*.html"))],
            ["2026-08-04.html", "2026-08-05.html", "2026-08-06.html"],
        )

    def test_zero_keeps_everything(self) -> None:
        # A real answer rather than a disabled feature: the rendered files are
        # the only record of what a given morning actually showed, and once the
        # baseline has moved past a date nothing can reconstruct it.
        shell = StonkSmithDBMenu.__new__(StonkSmithDBMenu)

        with patch("stonksmith.etc.paths.reports_path", self.reports):
            shell._prune_reports(keep=0)

        self.assertEqual(len(list(self.reports.glob("*.html"))), 6)


if __name__ == "__main__":
    unittest.main()
