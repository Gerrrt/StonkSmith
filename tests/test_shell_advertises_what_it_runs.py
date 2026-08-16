"""A command the shell can run is a command the shell names.

`delete account` shipped working and invisible. `DELETERS` grew a third entry,
`do_delete` grew the branch that reports what it cascaded away, and the two
places that list the commands to an operator were left saying there were two of
them. The command was reachable for anyone who already knew it existed, which is
nobody, since nothing in the tool or the docs said so.

Nothing caught it because the two halves are written differently. do_delete's
usage line is *generated* -- ``' | '.join(f'delete {name} <id>' for name in
DELETERS)`` -- so it started naming the third command the moment the dict did.
Each ``self.intro`` is a hand-written string, and there are two of them: the
shared one in broker_nav and SnapTrade's, which replaces it wholesale to drop
`add creds`. Adding to the dict updated the derived half and neither prose half,
and SnapTrade's had already fallen further behind -- it named no delete command
at all, for the broker whose database the request came from.

So the check is derived rather than restated, the way test_live_verification_tally
derives its count off the table it checks. Every navigator the loader can hand
back is asked whether it names every word DELETERS answers to. A fourth deleter,
or a new broker with an intro of its own, is covered on the day it lands.

The one exception is listed rather than assumed away, and asserted to still *be*
an exception -- an excuse that has stopped being needed is the same drift in the
other direction.
"""

import unittest
from unittest.mock import MagicMock, patch

from package_tree import BROKERS, REPO
from stonksmith.etc.broker_nav import DELETERS, BrokerNavigator
from stonksmith.loaders.brokerloader import BrokerLoader

#: (broker, deleter) pairs an intro is allowed not to name, and why.
#:
#: SnapTrade authenticates with a client id from the config file and a consumer
#: key from the keyring, so there is no credential row to remove. Its intro says
#: as much one line up -- `show creds  credentials (there are none; see below)`
#: -- and offering to delete one of them would advertise a no-op.
EXCUSED: dict[tuple[str, str], str] = {
    ("snaptrade", "creds"): "this broker stores no credentials to delete",
}


def _loader() -> BrokerLoader:
    """A loader that cannot see the developer's own brokers.

    BrokerLoader.__init__ hardcodes ~/.stonksmith as its second search root, so
    without this the set under test is whatever happens to be installed there.
    """

    loader = BrokerLoader()
    loader.stonksmith_path = REPO / "absent"
    return loader


def _navigators() -> dict[str, BrokerNavigator]:
    """Every shipped broker's navigator, built against mocks.

    navigator_class() returns BrokerNavigator for a broker that ships no
    db_navigator.py, which is all of them but SnapTrade -- so the shared intro
    is covered by the same loop, under the brokers that actually use it.
    """

    built: dict[str, BrokerNavigator] = {}

    for name in _loader().get_brokers():
        navigator = _loader().navigator_class(name=name)
        assert navigator is not None, f"{name} ships a navigator that will not load"

        built[name] = navigator(MagicMock(), MagicMock(), name)

    return built


class EveryDeleterIsAdvertised(unittest.TestCase):
    def test_there_are_navigators_to_check(self) -> None:
        # Without this the two loops below pass over an empty mapping, which is
        # how a path-based discovery test stops testing anything and says
        # nothing about it.
        self.assertTrue(_navigators(), "no navigators were discovered")
        self.assertTrue(DELETERS, "DELETERS is empty")

    def test_every_intro_names_every_deleter(self) -> None:
        for broker, navigator in sorted(_navigators().items()):
            for word in DELETERS:
                if (broker, word) in EXCUSED:
                    continue

                with self.subTest(broker=broker, deleter=word):
                    self.assertIn(
                        f"delete {word}",
                        navigator.intro,
                        f"{broker} runs `delete {word}` and does not say so",
                    )

    def test_each_excuse_is_still_needed(self) -> None:
        # An exception nobody removed after the reason for it went away reads
        # like a rule, and the next person copies it.
        for (broker, word), reason in EXCUSED.items():
            with self.subTest(broker=broker, deleter=word):
                navigator = _navigators().get(broker)
                self.assertIsNotNone(navigator, f"{broker} no longer exists")
                assert navigator is not None

                self.assertNotIn(
                    f"delete {word}",
                    navigator.intro,
                    f"{broker} now names `delete {word}`; drop the excuse "
                    f"recorded as {reason!r}",
                )


class TheUsageLineAgreesWithTheIntro(unittest.TestCase):
    """The generated half and the written half, made to meet.

    Typing `delete` with no target prints a usage line built from DELETERS, so
    it cannot fall behind the dict. The shared intro excuses nothing, which
    makes the two lists the same list -- and the whole of this bug was them not
    being.
    """

    def setUp(self) -> None:
        self.nav = BrokerNavigator(
            main_menu=MagicMock(), database=MagicMock(), broker_name="tsp"
        )

    def _usage(self) -> str:
        with patch("stonksmith.etc.broker_nav.stonksmith_logger") as log:
            self.nav.do_delete("")

        return str(object=log.fail.call_args)

    def test_the_usage_line_names_every_deleter(self) -> None:
        # The half that cannot drift, pinned so the comparison below has a
        # fixed side.
        for word in DELETERS:
            with self.subTest(deleter=word):
                self.assertIn(f"delete {word}", self._usage())

    def test_the_shared_intro_names_everything_the_usage_line_does(self) -> None:
        usage = self._usage()

        for word in DELETERS:
            with self.subTest(deleter=word):
                self.assertEqual(
                    f"delete {word}" in usage,
                    f"delete {word}" in self.nav.intro,
                    f"the usage line and the shared intro disagree about "
                    f"`delete {word}`",
                )


class TheNavigatorFilesAreWhereThisThinks(unittest.TestCase):
    def test_snaptrade_is_the_only_broker_with_an_intro_of_its_own(self) -> None:
        # Not a rule, a record: if a second one appears, EXCUSED above is the
        # thing to look at, because its keys name brokers.
        overriding = {path.parent.name for path in BROKERS.glob("*/db_navigator.py")}

        self.assertEqual(overriding, {"snaptrade"})


if __name__ == "__main__":
    unittest.main()
