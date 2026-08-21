"""The session has to outlive the run, and be written before anything closes.

A browser-backed broker is only unattended-schedulable if the session survives a
process exit. That is what `save_session()` is for: cookies and local storage go
to a storage-state file, the next run starts as a returning browser rather than a
new one, and a device-trust cookie earned by getting through 2FA once is not
thrown away nightly.

Two orderings make or break it, and neither is obvious from reading either method
on its own:

* **Save before close.** Cookies set *during* the run -- the device-trust one
  most of all -- live in the context. If `teardown()` closed it first there would
  be nothing left to read, and the failure would be silent: the file still gets
  written, just without the cookie that mattered, so the next run gets a fresh
  2FA challenge and nobody connects it to teardown.
* **Never over the profile.** In persistent-profile mode the cookies are already
  on disk in the profile directory, so writing a jar as well leaves a Firefox run
  loading a Chromium one.

Everything a failure here touches is diagnostic rather than required, so the
failure paths matter as much as the happy one -- a session that cannot be saved,
a context that is not there, tracing a borrowed context refuses to start. Each
must report and carry on rather than end the run, because none of them means the
scrape did not work.

The preflight is included for the same reason. `create_conn_obj()` checks the
site answers over plain HTTP before starting a browser, which is what separates
"the site is down" from "the browser would not start" -- two failures that
otherwise arrive as the same opaque timeout several seconds apart.

All `BrowserConnection`, exercised through Ally.
"""

import importlib.util
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

from playwright.sync_api import Error as PlaywrightError
from requests.exceptions import ConnectionError as RequestsConnectionError

import stonksmith.etc.browser_connection as browser_mod
from package_tree import PACKAGE


def _load_ally():
    spec = importlib.util.spec_from_file_location(
        "ally_broker_session", PACKAGE / "brokers/ally/broker.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ally_mod = _load_ally()


class _IsolatedBrokerTest(unittest.TestCase):
    """Keep every filesystem path these tests touch inside a temp directory.

    save_session() and capture_page() write under ~/.stonksmith by default, so
    without this the suite mutates real user state and fails wherever $HOME is
    not writable.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # capture_page() reads this at call time from the module namespace.
        self._logs_patch = patch.object(browser_mod, "logs_path", self.tmp / "logs")
        self._logs_patch.start()

    def tearDown(self) -> None:
        self._logs_patch.stop()
        self._tmp.cleanup()

    def broker(self, content: str | None = None):
        broker = ally_mod.Ally()
        broker.logger = MagicMock()
        broker.page = MagicMock()
        broker.profile_path = self.tmp / "playwright" / "Ally.json"
        if content is not None:
            broker.active_page.content.return_value = content
        return broker


class SaveSessionTests(_IsolatedBrokerTest):
    def test_storage_state_is_written(self) -> None:
        broker = self.broker()
        broker.context = MagicMock()

        broker.save_session()

        broker.context.storage_state.assert_called_once()
        written = broker.context.storage_state.call_args.kwargs["path"]
        self.assertIn("Ally.json", written)
        self.assertTrue(
            written.startswith(str(self.tmp)), "must not write to the real home"
        )

    def test_no_context_is_a_no_op(self) -> None:
        broker = self.broker()
        broker.context = None

        self.assertFalse(broker.save_session())  # must not raise

    def test_failure_to_save_is_reported_not_raised(self) -> None:
        broker = self.broker()
        broker.context = MagicMock()
        broker.context.storage_state.side_effect = PlaywrightError("nope")

        self.assertFalse(broker.save_session())
        self.assertTrue(broker.logger.fail.called)

    def test_teardown_saves_before_closing(self) -> None:
        # Cookies set during the run -- including any device-trust cookie -- are
        # lost if the context closes first.
        broker = self.broker()
        context = MagicMock()
        broker.context = context
        order: list[str] = []
        context.storage_state.side_effect = lambda **kw: order.append("save")
        context.close.side_effect = lambda: order.append("close")

        broker.teardown()

        self.assertEqual(order, ["save", "close"])

    def test_nothing_is_written_outside_the_temp_directory(self) -> None:
        broker = self.broker()
        broker.context = MagicMock()

        broker.save_session()

        # The only directory created belongs to the temp tree.
        self.assertTrue((self.tmp / "playwright").is_dir())


class PageBodyTests(_IsolatedBrokerTest):
    """Reading the page is how every broker decides what it is looking at."""

    def test_the_body_comes_back_lowercased(self) -> None:
        # Callers match markers against it, so the casing has to be settled in
        # one place rather than at each comparison.
        broker = self.broker(content="<html>Log Out</html>")

        self.assertEqual(broker.page_body(), "<html>log out</html>")

    def test_an_unreadable_page_is_none_rather_than_a_raise(self) -> None:
        # A page that has gone is a fact about the session, not a fault. The
        # caller decides what to do; it must not have to catch Playwright.
        broker = self.broker()
        broker.active_page.content.side_effect = PlaywrightError("gone")

        self.assertIsNone(broker.page_body())


class TracingIsDiagnosticTests(_IsolatedBrokerTest):
    """A context that refuses tracing must not take the run down with it."""

    def _broker_with_context(self):
        broker = ally_mod.Ally()
        broker.logger = MagicMock()
        broker.stealth = MagicMock()
        broker.args = Namespace(
            browser="firefox", headed=False, manual_login=False, profile_dir=None
        )
        return broker

    def _run(self, broker, context):
        playwright = MagicMock()
        playwright.firefox.launch.return_value.new_context.return_value = context

        with patch.object(
            browser_mod,
            "sync_playwright",
            return_value=MagicMock(start=lambda: playwright),
        ):
            broker.getDriver()

    def test_tracing_starts_on_a_context_that_supports_it(self) -> None:
        broker = self._broker_with_context()
        context = MagicMock()

        self._run(broker, context)

        context.tracing.start.assert_called_once()
        self.assertTrue(broker.tracing_started)

    def test_a_context_that_refuses_tracing_still_runs(self) -> None:
        # A context reached by attaching may not support tracing at all, and a
        # diagnostic is not worth failing a scrape for.
        broker = self._broker_with_context()
        context = MagicMock()
        context.tracing.start.side_effect = PlaywrightError("not supported")

        self._run(broker, context)

        self.assertFalse(broker.tracing_started)
        self.assertTrue(broker.logger.highlight.called)


class PreflightSeparatesDownFromBrokenTests(_IsolatedBrokerTest):
    """ "The site is down" and "the browser would not start" are different."""

    def _broker(self):
        broker = ally_mod.Ally()
        broker.logger = MagicMock()
        broker.args = Namespace(from_prices=False)
        broker.session = MagicMock()
        return broker

    def test_an_http_error_stops_before_any_browser_starts(self) -> None:
        broker = self._broker()
        broker.session.get.return_value = MagicMock(ok=False, status_code=503)
        broker.getDriver = MagicMock()

        self.assertFalse(broker.create_conn_obj())

        broker.getDriver.assert_not_called()
        # broker_flow() does not log a generic connection failure, so this path
        # has to report itself or the run ends saying nothing.
        self.assertTrue(broker.logger.fail.called)
        self.assertIn("503", broker.logger.fail.call_args.kwargs["msg"])

    def test_an_unreachable_site_is_reported_by_name(self) -> None:
        broker = self._broker()
        broker.session.get.side_effect = RequestsConnectionError("no route to host")
        broker.getDriver = MagicMock()

        self.assertFalse(broker.create_conn_obj())

        broker.getDriver.assert_not_called()
        self.assertIn("Ally", broker.logger.fail.call_args.kwargs["msg"])

    def test_a_reachable_site_goes_on_to_start_the_browser(self) -> None:
        broker = self._broker()
        broker.session.get.return_value = MagicMock(ok=True)
        broker.getDriver = MagicMock()

        self.assertTrue(broker.create_conn_obj())

        broker.getDriver.assert_called_once()


if __name__ == "__main__":
    unittest.main()
