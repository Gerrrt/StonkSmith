"""`stonksmithdb sheet` from a crontab, and what it exits.

The sheet is the last step of every schedule -- a `--from-prices` run does not
touch it, and a scrape that wrote its balances can still fail to render them --
but `sheet` lived only inside the shell's command loop. Piping into it worked,
because do_EOF quits cleanly, and it exited 0 however the refresh went.

That is the failure this whole feature is written against: a scheduled step
that cannot report failure stops working silently, and a portfolio stops
updating with nothing to say so. These tests pin the argv form and its status.
"""

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from stonksmith.etc.stonksmithdb import StonkSmithDBMenu, main


def run_main(args: list[str], failed: bool) -> tuple[int, str]:
    """
    Run the entry point with a faked shell and a faked setup.
    :param args: The words after the command name
    :param failed: What the shell reports about the command it ran
    :return: The exit status and everything printed
    :rtype: tuple[int, str]
    """

    shell = MagicMock()
    shell.failed = failed
    out = io.StringIO()

    with (
        patch("stonksmith.etc.tool_setup.setup_tool"),
        patch("stonksmith.etc.stonksmithdb.argv", ["stonksmithdb", *args]),
        patch("stonksmith.etc.stonksmithdb.config_path", "stonksmith.conf"),
        patch.object(Path, "exists", return_value=True),
        patch(
            "stonksmith.etc.stonksmithdb.StonkSmithDBMenu", return_value=shell
        ) as menu,
        redirect_stdout(out),
    ):
        try:
            main()
            status = 0

        except SystemExit as e:
            status = int(e.code or 0)

    run_main.menu = menu  # type: ignore[attr-defined]
    run_main.shell = shell  # type: ignore[attr-defined]

    return status, out.getvalue()


class ScriptedFormTests(unittest.TestCase):
    def test_a_command_that_worked_exits_zero(self) -> None:
        status, _ = run_main(args=["sheet"], failed=False)

        self.assertEqual(status, 0)

    def test_stale_reports_through_the_same_status(self) -> None:
        # The point of `stale` is the exit code -- it is what a crontab reads,
        # and the command is useless if the status does not carry. Pinned here
        # beside `sheet` because both are argv forms a schedule calls, and both
        # exist because a scheduled step that cannot fail stops working quietly.
        self.assertEqual(run_main(args=["stale"], failed=False)[0], 0)
        self.assertEqual(run_main(args=["stale"], failed=True)[0], 1)
        self.assertEqual(run_main(args=["stale", "1"], failed=True)[0], 1)

    def test_a_command_that_failed_exits_one(self) -> None:
        status, _ = run_main(args=["sheet"], failed=True)

        self.assertEqual(status, 1)

    def test_the_command_is_the_words_after_the_program_name(self) -> None:
        run_main(args=["workspace", "list"], failed=False)

        run_main.shell.onecmd.assert_called_once_with(line="workspace list")  # type: ignore[attr-defined]

    def test_it_does_not_reopen_the_last_broker(self) -> None:
        # Entering a broker runs that broker's own command loop, so a scripted
        # `sheet` would sit at a sub-prompt and never reach the sheet.
        run_main(args=["sheet"], failed=False)

        _, kwargs = run_main.menu.call_args  # type: ignore[attr-defined]
        self.assertFalse(kwargs["resume_last_broker"])

    def test_no_arguments_still_opens_the_shell(self) -> None:
        run_main(args=[], failed=False)

        run_main.shell.cmdloop.assert_called_once()  # type: ignore[attr-defined]
        run_main.shell.onecmd.assert_not_called()  # type: ignore[attr-defined]

    def test_the_interactive_shell_still_resumes_the_last_broker(self) -> None:
        run_main(args=[], failed=False)

        _, kwargs = run_main.menu.call_args  # type: ignore[attr-defined]
        self.assertTrue(kwargs["resume_last_broker"])


class UnknownCommandTests(unittest.TestCase):
    def menu(self) -> StonkSmithDBMenu:
        """
        A shell with no brokers, without the init that discovers them.
        :return: The shell
        :rtype: StonkSmithDBMenu
        """

        shell = StonkSmithDBMenu.__new__(StonkSmithDBMenu)
        shell.brokers = {}
        shell.failed = False

        return shell

    def test_a_typo_in_a_crontab_does_not_exit_zero(self) -> None:
        shell = self.menu()

        with redirect_stdout(io.StringIO()):
            shell.default(line="shet")

        self.assertTrue(shell.failed)

    def test_a_broker_only_command_at_the_top_level_is_a_failure_too(self) -> None:
        shell = self.menu()

        with redirect_stdout(io.StringIO()):
            shell.default(line="show creds")

        self.assertTrue(shell.failed)


if __name__ == "__main__":
    unittest.main()
