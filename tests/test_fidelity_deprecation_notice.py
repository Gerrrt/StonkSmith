# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""The fidelity broker says it is going away, without going away while saying it.

The notice is emitted two ways, and each covers a hole the other leaves. The
``DeprecationWarning`` is what a `-W` filter and these tests can see; the
ERROR-level log line is what a human sees, because ``DeprecationWarning`` is
ignored by Python's default filters outside ``__main__`` and an operator running
this from cron would otherwise get no signal at all.

**Where it fires is the load-bearing decision.** ``Connection.__call__`` is the
thread-pool target `runner.start_run` submits, so ``Fidelity.__call__`` runs once
per invocation and runs *before* the connection and the login. The module's
``on_login`` would have been the obvious spot and is the wrong one: it is reached
only after a login has succeeded, and this broker's login is the half most likely
to fail -- getting past Akamai Bot Manager is the reason it is being retired. A
notice placed there would reach exactly the operators having the least trouble.
``test_a_run_that_never_logs_in_is_still_told`` is what holds that.

The other test that matters is ``test_an_error_filter_does_not_raise``.
This suite sets ``filterwarnings = ["error"]``, so an unsuppressed warning *is* an
exception -- raised inside a thread-pool target whose documented contract is to
report an outcome rather than raise. A deprecation notice that fails the run it is
announcing is worse than no notice, which is the same reasoning
``tests/test_legacy_import_names.py`` records for the other deprecation this
project is carrying.

Asserting only that a warning was raised would pass on exactly those broken
versions -- the warning is raised either way, and what differs is where it fires
and whether the run survives it.
"""

import logging
import unittest
import warnings
from argparse import ArgumentParser, Namespace
from typing import Any
from unittest.mock import MagicMock, patch

from stonksmith.brokers.fidelity.broker import (
    DEPRECATION_NOTICE,
    REMOVED_IN,
    Fidelity,
    announce_deprecation,
)


class _Recorder(logging.Handler):
    """Keeps the ERROR-level records the notice is supposed to leave behind."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class _Capturing:
    """Attach a recorder to the project logger for the length of a test."""

    def setUp(self) -> None:
        self.handler = _Recorder()
        self.logger = logging.getLogger("stonksmith")
        self.logger.addHandler(self.handler)

        self.previous = self.logger.level
        self.logger.setLevel(logging.DEBUG)

        # The notice is meant to be loud in a terminal, not in test output.
        self.propagated = self.logger.propagate
        self.logger.propagate = False

    def tearDown(self) -> None:
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self.previous)
        self.logger.propagate = self.propagated

    @property
    def logged(self) -> list[str]:
        return self.handler.messages

    def said(self, notice: str) -> int:
        """How many logged lines carry ``notice``.

        Containment rather than equality: `StonkSmithAdapter.fail` prefixes the
        message with padding and rich markup, so the record is never the bare
        string. Asserting equality here would fail on a notice that was emitted
        perfectly well.
        """

        return sum(1 for message in self.logged if notice in message)


class TheNoticeTests(_Capturing, unittest.TestCase):
    def test_it_warns_and_logs(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            announce_deprecation()

        deprecations = [
            str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        self.assertIn(DEPRECATION_NOTICE, deprecations)

        # DeprecationWarning is invisible under Python's default filters outside
        # __main__, so the warning alone reaches nobody not running this suite.
        self.assertEqual(self.said(DEPRECATION_NOTICE), 1)

    def test_an_error_filter_does_not_raise(self) -> None:
        # Unsuppressed at the emit site, this raises -- inside a thread-pool
        # target that is contractually not allowed to.
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            announce_deprecation()

        self.assertEqual(self.said(DEPRECATION_NOTICE), 1)


class WhereItFiresTests(_Capturing, unittest.TestCase):
    """Once per run, before the login that is most likely to fail."""

    @staticmethod
    def _run(broker: Fidelity) -> Any:
        """Invoke the broker the way `runner.start_run` does."""

        return broker(Namespace(), MagicMock(), None)

    def test_a_run_that_never_logs_in_is_still_told(self) -> None:
        # The test this file exists for. Fidelity fronts its login with bot
        # detection, so a run dying before on_login is the ordinary case rather
        # than the edge one -- and that operator is the audience.
        broker = Fidelity()

        with (
            patch.object(
                Fidelity, "create_conn_obj", return_value=False
            ) as create_conn,
            patch.object(Fidelity, "login") as login,
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("ignore", DeprecationWarning)
            self._run(broker)

        self.assertEqual(self.said(DEPRECATION_NOTICE), 1)
        self.assertTrue(
            create_conn.called, "the run must have got as far as connecting"
        )
        self.assertFalse(login.called, "this test is about a run that never logs in")

    def test_it_is_said_once_per_run(self) -> None:
        # fail() is the level --quiet leaves showing. Repeated, the loudest line
        # in the output becomes the one that never changes.
        broker = Fidelity()

        with (
            patch.object(Fidelity, "create_conn_obj", return_value=False),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("ignore", DeprecationWarning)
            self._run(broker)

        self.assertEqual(self.said(DEPRECATION_NOTICE), 1)

    def test_constructing_the_broker_says_nothing(self) -> None:
        # __init__ happens in tests and in anything that merely inspects the
        # broker. An ERROR-level line that fires when nobody is running anything
        # is how a notice gets tuned out.
        Fidelity()

        self.assertEqual(self.said(DEPRECATION_NOTICE), 0)

    def test_the_run_still_reports_its_own_outcome(self) -> None:
        # The override delegates; it must not become the return value.
        broker = Fidelity()

        with (
            patch.object(Fidelity, "create_conn_obj", return_value=False),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("ignore", DeprecationWarning)
            result = self._run(broker)

        self.assertFalse(result, "a run that could not connect did not succeed")


class TheWordingTests(unittest.TestCase):
    """What the notice has to say to be worth emitting."""

    def test_it_names_the_removal_version(self) -> None:
        # A deprecation with no version is a complaint rather than a schedule.
        self.assertIn(REMOVED_IN, DEPRECATION_NOTICE)

    def test_it_names_the_replacement(self) -> None:
        # "Stop using this" without "use that instead" leaves the operator with
        # a broker they still need and no way forward.
        self.assertIn("SnapTrade", DEPRECATION_NOTICE)

    def test_it_points_at_a_document_that_exists(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        self.assertIn("docs/brokers.md", DEPRECATION_NOTICE)
        self.assertTrue((root / "docs" / "brokers.md").is_file())


class TheHelpTextTests(unittest.TestCase):
    """`stonksmith --help` has to say it too, without a run."""

    def test_the_subparser_help_leads_with_deprecated(self) -> None:
        from stonksmith.brokers.fidelity.broker_args import broker_args

        parser = ArgumentParser()
        subparsers = parser.add_subparsers(dest="broker")
        broker_args(
            subparsers=subparsers,
            std_parser=ArgumentParser(add_help=False),
            module_parser=ArgumentParser(add_help=False),
        )

        help_text = next(
            action.help
            for action in subparsers._get_subactions()
            if action.dest == "fidelity"
        )

        self.assertTrue(
            str(help_text).startswith("(deprecated)"),
            f"the help column truncates, so it has to lead: {help_text!r}",
        )


if __name__ == "__main__":
    unittest.main()
