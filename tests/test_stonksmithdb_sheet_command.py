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

from etc.portfolio_sheet import SheetSync
from etc.stonksmithdb import StonkSmithDBMenu
from helpers.sheets import SheetNotOwned


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


if __name__ == "__main__":
    unittest.main()
