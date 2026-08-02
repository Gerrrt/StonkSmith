"""The database shell should explain mistakes instead of printing bare errors.

Typing `show creds` at the top level produced only "*** Unknown syntax", with no
hint that credentials live inside a broker sub-shell -- the most common way to
get stuck in this tool.
"""

import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

from etc.broker_nav import BrokerNavigator
from etc.stonksmithdb import StonkSmithDBMenu


def _menu(brokers: dict[str, dict[str, str]] | None = None) -> StonkSmithDBMenu:
    menu = StonkSmithDBMenu.__new__(StonkSmithDBMenu)
    menu.brokers = (
        brokers
        if brokers is not None
        else {
            "fidelity": {"path": "f.py", "nvpath": "n.py", "dbpath": "d.py"},
            "schwab529plan": {"path": "s.py", "nvpath": "n.py", "dbpath": "d.py"},
        }
    )
    menu.workspace = "default"
    return menu


def _capture(fn, *args, **kwargs) -> str:
    buffer = StringIO()
    with patch("sys.stdout", buffer):
        fn(*args, **kwargs)
    return buffer.getvalue()


class TopLevelGuidanceTests(unittest.TestCase):
    def test_broker_shell_command_explains_it_needs_a_broker(self) -> None:
        output = _capture(_menu().default, "show creds")

        self.assertIn("only works inside a broker", output)
        self.assertIn("broker schwab529plan", output)
        self.assertNotIn("Unknown syntax", output)

    def test_unknown_command_points_at_help(self) -> None:
        output = _capture(_menu().default, "frobnicate")

        self.assertIn("Unknown command", output)
        self.assertIn("help", output)

    def test_bare_broker_lists_the_brokers(self) -> None:
        menu = _menu()
        output = _capture(menu.do_broker, "")

        self.assertIn("Available brokers", output)
        self.assertIn("fidelity", output)
        self.assertIn("schwab529plan", output)

    def test_unknown_broker_name_lists_the_real_ones(self) -> None:
        output = _capture(_menu().do_broker, "schwab")

        self.assertIn("Unknown broker: schwab", output)
        self.assertIn("schwab529plan", output)

    def test_incomplete_broker_is_flagged_in_the_listing(self) -> None:
        menu = _menu(brokers={"lonely": {"path": "l.py"}})
        output = _capture(menu.list_brokers)

        self.assertIn("incomplete", output)

    def test_no_brokers_says_so(self) -> None:
        output = _capture(_menu(brokers={}).list_brokers)

        self.assertIn("No brokers found", output)

    def test_eof_is_hidden_from_help(self) -> None:
        menu = _menu()

        self.assertNotIn("do_EOF", menu.get_names())
        # ...but Ctrl-D still quits.
        self.assertTrue(callable(menu.do_EOF))


class BrokerShellGuidanceTests(unittest.TestCase):
    def _navigator(self) -> BrokerNavigator:
        return BrokerNavigator(
            main_menu=MagicMock(), database=MagicMock(), broker_name="schwab529plan"
        )

    def test_top_level_command_explains_it_needs_back(self) -> None:
        output = _capture(self._navigator().default, "workspace list")

        self.assertIn("belongs to the top level", output)
        self.assertIn("back", output)
        self.assertNotIn("Unknown syntax", output)

    def test_unknown_command_points_at_help(self) -> None:
        output = _capture(self._navigator().default, "frobnicate")

        self.assertIn("Unknown command", output)

    def test_intro_lists_the_credential_commands(self) -> None:
        intro = self._navigator().intro

        for expected in ("add creds", "show creds", "export creds", "back"):
            self.assertIn(expected, intro)

    def test_eof_is_hidden_from_help(self) -> None:
        self.assertNotIn("do_EOF", self._navigator().get_names())


if __name__ == "__main__":
    unittest.main()
