"""`broker <name>` inside a sub-shell switches directly, no `back` needed.

The shell auto-enters `last_used_db` on launch, so a session frequently starts
*inside* a broker. Typing `broker other` there used to be rejected as a
top-level command, which is the same two-level friction in a new disguise.
"""

import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

from etc.broker_nav import BrokerNavigator
from etc.exceptions import SwitchBroker, UserExitedProto
from etc.stonksmithdb import StonkSmithDBMenu


class SubShellRequestsASwitchTests(unittest.TestCase):
    def _navigator(self) -> BrokerNavigator:
        return BrokerNavigator(
            main_menu=MagicMock(), database=MagicMock(), broker_name="fidelity"
        )

    def test_broker_name_raises_a_switch_carrying_the_name(self) -> None:
        with self.assertRaises(SwitchBroker) as caught:
            self._navigator().do_broker("schwab529plan")

        self.assertEqual(caught.exception.broker, "schwab529plan")

    def test_surrounding_whitespace_is_ignored(self) -> None:
        with self.assertRaises(SwitchBroker) as caught:
            self._navigator().do_broker("  schwab529plan  ")

        self.assertEqual(caught.exception.broker, "schwab529plan")

    def test_bare_broker_asks_for_the_listing(self) -> None:
        with self.assertRaises(SwitchBroker) as caught:
            self._navigator().do_broker("")

        self.assertEqual(caught.exception.broker, "")

    def test_brokers_leaves_and_lists(self) -> None:
        with self.assertRaises(SwitchBroker) as caught:
            self._navigator().do_brokers("")

        self.assertEqual(caught.exception.broker, "")

    def test_switch_is_still_an_exit_for_older_handlers(self) -> None:
        # SwitchBroker subclasses UserExitedProto so any handler that only
        # knows how to leave a sub-shell still behaves correctly.
        self.assertTrue(issubclass(SwitchBroker, UserExitedProto))

    def test_back_still_just_leaves(self) -> None:
        with self.assertRaises(UserExitedProto) as caught:
            self._navigator().do_back("")

        self.assertNotIsInstance(caught.exception, SwitchBroker)

    def test_broker_is_no_longer_reported_as_wrong_level(self) -> None:
        # It is a real command here now.
        self.assertNotIn("broker", BrokerNavigator.PARENT_SHELL_COMMANDS)
        self.assertIn("workspace", BrokerNavigator.PARENT_SHELL_COMMANDS)


class MenuHandlesTheSwitchTests(unittest.TestCase):
    def _menu(self) -> StonkSmithDBMenu:
        menu = StonkSmithDBMenu.__new__(StonkSmithDBMenu)
        menu.brokers = {"fidelity": {}, "schwab529plan": {}}
        menu.workspace = "default"
        return menu

    def test_switching_enters_each_broker_in_turn(self) -> None:
        menu = self._menu()
        visited: list[str] = []

        def enter(broker: str) -> str | None:
            visited.append(broker)
            # fidelity asks to switch; schwab ends the session.
            return "schwab529plan" if broker == "fidelity" else None

        menu.enter_broker = enter
        menu.do_broker("fidelity")

        self.assertEqual(visited, ["fidelity", "schwab529plan"])

    def test_switching_loops_rather_than_recursing(self) -> None:
        # Hopping between brokers must not grow the stack.
        menu = self._menu()
        hops = {"n": 0}

        def enter(broker: str) -> str | None:
            hops["n"] += 1
            return "fidelity" if hops["n"] < 500 else None

        menu.enter_broker = enter
        menu.do_broker("fidelity")  # would blow the stack if recursive

        self.assertEqual(hops["n"], 500)

    def test_empty_switch_lists_the_brokers(self) -> None:
        menu = self._menu()
        menu.enter_broker = lambda broker: ""
        menu.list_brokers = MagicMock()

        menu.do_broker("fidelity")

        menu.list_brokers.assert_called_once()

    def test_bare_broker_at_the_top_level_still_lists(self) -> None:
        menu = self._menu()
        buffer = StringIO()
        with patch("sys.stdout", buffer):
            menu.do_broker("")

        self.assertIn("Available brokers", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
