"""Rebuilding the sheet without logging into anything.

The sheet is a view of the databases, so it can be rebuilt from them alone. That
matters because the sheet can now decline to write -- a tab missing its banner,
a tab someone typed in -- and the only other cure would be another scrape. For
Ally and Fidelity that means a human at a sign-in page, which is a steep price
for fixing a spreadsheet tab.
"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from etc.portfolio_sheet import GUARD_CHECK_TAB, GuardCase, SheetSync
from etc.stonksmithdb import StonkSmithDBMenu
from helpers.sheets import SheetNotOwned, SheetsUnavailable


def shell() -> StonkSmithDBMenu:
    """
    The shell, without the config reading and broker discovery its init does.
    :return: A shell whose workspace is "default"
    :rtype: StonkSmithDBMenu
    """

    menu = StonkSmithDBMenu.__new__(StonkSmithDBMenu)
    menu.workspace = "default"
    menu.failed = False

    return menu


def run(menu: StonkSmithDBMenu) -> str:
    """
    Run `sheet` and capture what it printed.
    :param menu: The shell
    :return: Everything printed
    :rtype: str
    """

    out = io.StringIO()

    with redirect_stdout(out):
        menu.do_sheet(line="")

    return out.getvalue()


class SheetCommandTests(unittest.TestCase):
    def test_it_refreshes_the_workspace_the_shell_is_in(self) -> None:
        # Not the configured one. Someone who typed `workspace other` expects
        # `sheet` to render what they are looking at.
        with patch("etc.portfolio_sheet.refresh") as refresh:
            refresh.return_value = SheetSync(brokers_read=("tsp",))
            menu = shell()
            menu.workspace = "other"
            run(menu=menu)

        refresh.assert_called_once_with(workspace="other")

    def test_it_says_what_it_wrote(self) -> None:
        with patch("etc.portfolio_sheet.refresh") as refresh:
            refresh.return_value = SheetSync(
                accounts=4,
                holdings=17,
                transactions=203,
                brokers_read=("ally", "tsp"),
                total=1.0,
            )
            printed = run(menu=shell())

        self.assertIn("4 accounts", printed)
        self.assertIn("17 holdings", printed)
        # Named as well, because a count this report omits is a tab nobody
        # checks -- and the whole point of the tab is that it holds everything.
        self.assertIn("203 movements", printed)
        self.assertIn("ally, tsp", printed)

    def test_a_refused_tab_is_reported_rather_than_raised(self) -> None:
        with patch("etc.portfolio_sheet.refresh") as refresh:
            refresh.side_effect = SheetNotOwned("Tab 'Holdings' holds something")
            printed = run(menu=shell())

        self.assertIn("Holdings", printed)

    def test_an_unexpected_failure_still_names_itself(self) -> None:
        # A bare traceback out of a shell command is the thing helpers/sheets.py
        # was written to stop happening.
        with patch("etc.portfolio_sheet.refresh") as refresh:
            refresh.side_effect = RuntimeError("boom")
            printed = run(menu=shell())

        self.assertIn("RuntimeError", printed)
        self.assertIn("boom", printed)

    def test_a_broker_that_would_not_read_is_named(self) -> None:
        with patch("etc.portfolio_sheet.refresh") as refresh:
            refresh.return_value = SheetSync(
                accounts=1,
                brokers_read=("tsp",),
                unreadable=(("ally", "OSError: no such file"),),
            )
            printed = run(menu=shell())

        self.assertIn("ally could not be read", printed)
        self.assertIn("no such file", printed)

    def test_an_empty_workspace_says_no_brokers_rather_than_nothing(self) -> None:
        with patch("etc.portfolio_sheet.refresh") as refresh:
            refresh.return_value = SheetSync()
            printed = run(menu=shell())

        self.assertIn("no brokers", printed)

    def test_the_command_is_advertised_at_the_top_level(self) -> None:
        self.assertIn("sheet", StonkSmithDBMenu.intro)

    def test_a_refresh_that_worked_reports_no_failure(self) -> None:
        menu = shell()

        with patch("etc.portfolio_sheet.refresh") as refresh:
            refresh.return_value = SheetSync(accounts=4, brokers_read=("tsp",))
            run(menu=menu)

        self.assertFalse(menu.failed)

    def test_an_unavailable_sheet_is_a_failure_a_scheduler_can_see(self) -> None:
        # Printing it is enough for a human watching the shell. It is not enough
        # for cron, which reads one number and nothing else.
        menu = shell()

        with patch("etc.portfolio_sheet.refresh") as refresh:
            refresh.side_effect = SheetNotOwned("Tab 'Holdings' holds something")
            run(menu=menu)

        self.assertTrue(menu.failed)

    def test_an_unexpected_failure_is_one_too(self) -> None:
        menu = shell()

        with patch("etc.portfolio_sheet.refresh") as refresh:
            refresh.side_effect = RuntimeError("boom")
            run(menu=menu)

        self.assertTrue(menu.failed)

    def test_a_broker_that_would_not_read_is_a_failure(self) -> None:
        # The refresh itself worked. What it produced is a total missing a whole
        # broker's money, which is a wrong number rather than a stale one -- the
        # one outcome a schedule must not treat as a good night.
        menu = shell()

        with patch("etc.portfolio_sheet.refresh") as refresh:
            refresh.return_value = SheetSync(
                accounts=1,
                brokers_read=("tsp",),
                unreadable=(("ally", "OSError: no such file"),),
            )
            run(menu=menu)

        self.assertTrue(menu.failed)

    def test_the_writer_is_imported_inside_the_command_not_at_module_scope(
        self,
    ) -> None:
        # It lives inside do_sheet because this shell is mostly used for things
        # that never touch Sheets, and importing it drags gspread and
        # google-auth along.
        import etc.stonksmithdb as shell_module

        self.assertFalse(hasattr(shell_module, "refresh"))


class VerifyCommandTests(unittest.TestCase):
    """The guard check, reported so a failure is impossible to skim past.

    A refusal that did not happen is the finding, not a footnote: it is the shape
    that silently overwrites somebody's work, and it is the one outcome here that
    would otherwise look like a clean run with one odd line in it.
    """

    def _run(self, line: str = "guard") -> str:
        return self._run_on(shell(), line=line)

    def _run_on(self, menu: StonkSmithDBMenu, line: str = "guard") -> str:
        """
        Run `verify` on a given shell, so its failure flag can be read after.
        :param menu: The shell
        :param line: The half to run
        :return: Everything printed
        :rtype: str
        """

        out = io.StringIO()

        with redirect_stdout(out):
            menu.do_verify(line=line)

        return out.getvalue()

    def _cases(self, *passed: bool) -> tuple[GuardCase, ...]:
        return tuple(
            GuardCase(
                name=f"case {index}",
                expected="refused",
                passed=ok,
                detail="" if ok else "the tab was adopted instead",
            )
            for index, ok in enumerate(passed)
        )

    def test_it_says_what_it_is_about_to_do_before_touching_anything(self) -> None:
        # It creates and deletes a tab in the real spreadsheet, which is not
        # something a reader should have to infer from the name of the command.
        with patch("etc.portfolio_sheet.check_ownership_guard") as check:
            check.return_value = self._cases(True, True, True)
            printed = self._run()

        self.assertIn(GUARD_CHECK_TAB, printed)
        self.assertIn("deleting it again", printed)

    def test_a_clean_run_still_says_what_it_did_not_cover(self) -> None:
        # A clean report that implied otherwise would retire a step nobody has
        # done. The guard half's gap is the whole-sync abort.
        with patch("etc.portfolio_sheet.check_ownership_guard") as check:
            check.return_value = self._cases(True, True, True)
            printed = self._run()

        self.assertIn("[*]", printed)
        self.assertIn("live-verification", printed)
        self.assertIn("aborting the whole sync", printed)
        self.assertNotIn("[-]", printed)

    def test_each_half_names_only_the_gap_that_is_its_own(self) -> None:
        # A guard-only run listing the empty-cell gap points at a tab check nobody
        # asked for, and a caveat that does not apply teaches a reader to skim the
        # ones that do.
        with (
            patch("etc.portfolio_sheet.check_ownership_guard") as guard,
            patch("etc.portfolio_sheet.check_tabs") as tabs,
        ):
            guard.return_value = self._cases(True)
            tabs.return_value = self._cases(True)

            guard_only = self._run(line="guard")
            tabs_only = self._run(line="tabs")
            both = self._run(line="")

        self.assertIn("aborting the whole sync", guard_only)
        self.assertNotIn("empty cell", guard_only)

        self.assertIn("empty cell", tabs_only)
        self.assertNotIn("aborting the whole sync", tabs_only)

        self.assertIn("empty cell", both)
        self.assertIn("aborting the whole sync", both)
        self.assertIn("Two things", both)

    def test_each_half_can_be_run_on_its_own(self) -> None:
        with (
            patch("etc.portfolio_sheet.check_ownership_guard") as guard,
            patch("etc.portfolio_sheet.check_tabs") as tabs,
        ):
            guard.return_value = self._cases(True)
            tabs.return_value = self._cases(True)

            self._run(line="guard")
            guard.assert_called_once()
            tabs.assert_not_called()

            guard.reset_mock()
            self._run(line="tabs")
            tabs.assert_called_once()
            guard.assert_not_called()

    def test_bare_verify_runs_both_halves_tabs_first(self) -> None:
        # Tabs first deliberately: the guard half makes and deletes a tab, and
        # reading the four back is the part that says whether the last sync
        # landed. A reader wants that before a scratch tab appears.
        with (
            patch("etc.portfolio_sheet.check_ownership_guard") as guard,
            patch("etc.portfolio_sheet.check_tabs") as tabs,
        ):
            guard.return_value = self._cases(True)
            tabs.return_value = self._cases(True)
            printed = self._run(line="")

        guard.assert_called_once()
        tabs.assert_called_once()
        self.assertLess(
            printed.index("Reading the four tabs back"), printed.index("Making the tab")
        )

    def test_the_tab_half_reads_the_workspace_the_shell_is_in(self) -> None:
        with patch("etc.portfolio_sheet.check_tabs") as tabs:
            tabs.return_value = self._cases(True)
            menu = shell()
            menu.workspace = "other"

            with redirect_stdout(io.StringIO()):
                menu.do_verify(line="tabs")

        tabs.assert_called_once_with(workspace="other")

    def test_an_unknown_argument_is_refused_rather_than_ignored(self) -> None:
        # Silently running both would be worse than saying no: someone who typed
        # "verify tab" wants to know they did.
        with patch("etc.portfolio_sheet.check_ownership_guard") as guard:
            printed = self._run(line="tab")

        guard.assert_not_called()
        self.assertIn("Unknown check", printed)

    def test_a_passing_cases_detail_is_not_printed(self) -> None:
        # A refusal that behaved carries the refusal message as its detail.
        # Printing that under a [+] is several lines saying the expected thing
        # happened, which buries the one line that would not have.
        with patch("etc.portfolio_sheet.check_ownership_guard") as check:
            check.return_value = (
                GuardCase(
                    name="refused it",
                    expected="refused",
                    passed=True,
                    detail="Tab 'x' holds something StonkSmith did not write",
                ),
            )
            printed = self._run()

        self.assertIn("refused it", printed)
        self.assertNotIn("did not write", printed)

    def test_a_guard_that_did_not_behave_is_loud_and_says_what_to_do(self) -> None:
        with patch("etc.portfolio_sheet.check_ownership_guard") as check:
            check.return_value = self._cases(True, False, True)
            printed = self._run()

        self.assertIn("[-]", printed)
        self.assertIn("the tab was adopted instead", printed)
        self.assertIn("1 of 3", printed)
        # And it must not also print the reassuring summary.
        self.assertNotIn("behaved on all", printed)

    def test_a_taken_tab_is_reported_rather_than_raised(self) -> None:
        with patch("etc.portfolio_sheet.check_ownership_guard") as check:
            check.side_effect = SheetsUnavailable("already has a tab named")
            printed = self._run()

        self.assertIn("already has a tab named", printed)

    def test_an_unexpected_failure_still_names_itself(self) -> None:
        with patch("etc.portfolio_sheet.check_ownership_guard") as check:
            check.side_effect = RuntimeError("boom")
            printed = self._run()

        self.assertIn("RuntimeError", printed)
        self.assertIn("boom", printed)

    def test_the_command_is_advertised_at_the_top_level(self) -> None:
        self.assertIn("verify", StonkSmithDBMenu.intro)

    def test_a_check_that_behaved_reports_no_failure(self) -> None:
        menu = shell()

        with patch("etc.portfolio_sheet.check_ownership_guard") as check:
            check.return_value = self._cases(True, True, True)
            self._run_on(menu)

        self.assertFalse(menu.failed)

    def test_a_check_that_did_not_behave_is_a_failure_a_scheduler_can_see(self) -> None:
        # The whole point of the scripted form. A verification that reports
        # "unguarded" and exits 0 is read downstream as a clean run, which is
        # the one reading that must never be available.
        menu = shell()

        with patch("etc.portfolio_sheet.check_ownership_guard") as check:
            check.return_value = self._cases(True, False, True)
            self._run_on(menu)

        self.assertTrue(menu.failed)

    def test_a_half_that_could_not_run_at_all_is_a_failure_too(self) -> None:
        # Not reaching the sheet says nothing about the guard, and "nothing
        # known" must not exit the same way as "checked and clean".
        menu = shell()

        with patch("etc.portfolio_sheet.check_ownership_guard") as check:
            check.side_effect = SheetsUnavailable("no credential")
            self._run_on(menu)

        self.assertTrue(menu.failed)

    def test_an_unknown_argument_does_not_exit_zero(self) -> None:
        # `verify tabz` in a crontab checked nothing at all.
        menu = shell()
        self._run_on(menu, line="tabz")

        self.assertTrue(menu.failed)

    def test_the_check_is_imported_inside_the_command_not_at_module_scope(
        self,
    ) -> None:
        import etc.stonksmithdb as shell_module

        self.assertFalse(hasattr(shell_module, "check_ownership_guard"))


if __name__ == "__main__":
    unittest.main()
