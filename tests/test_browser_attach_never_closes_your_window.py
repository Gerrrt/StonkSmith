"""Attaching to a browser somebody else started must never close it.

`--browser cdp` connects to a Chrome the operator launched with
`--remote-debugging-port` and signed into by hand. That window is theirs: it may
hold other tabs, other sessions, work they have not saved. StonkSmith borrows a
page in it and has to give it back untouched.

The rule cuts across the whole lifecycle rather than sitting in one method.
`getDriver()` must reuse the existing context rather than opening a fresh one --
a new context starts with no cookies, which defeats the point of attaching to a
signed-in browser. `teardown()` must close neither the context nor the browser,
and must not write storage state back over a profile it does not own. And
`attached` has to be set *before* the attach is validated, not after: if it were
set only on success, a failure between connecting and finding a window would
run `create_conn_obj()`'s teardown against an operator's live browser with the
flag still False, and close it.

That last one is the reason this file is about the rule rather than about a
method. Every individual step looks correct with `attached` set at the end.

These are `BrowserConnection` behaviours, exercised here through Ally -- the
broker whose sign-in is fronted by Akamai, Dynatrace and Transmit, which is what
makes attaching to a real browser the path most likely to work at all.
"""

import importlib.util
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import stonksmith.etc.browser_connection as browser_mod
from package_tree import PACKAGE


def _load_ally():
    spec = importlib.util.spec_from_file_location(
        "ally_broker_attach", PACKAGE / "brokers/ally/broker.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ally_mod = _load_ally()


_profile_home: tempfile.TemporaryDirectory | None = None


def setUpModule() -> None:
    """
    Keep anything the browser writes out of the developer's home directory.

    teardown() and save_session() both reach for ~/.stonksmith/playwright, and
    a mock context is enough to make them create it for real.
    tests/test_suite_does_not_touch_home.py re-runs the suite under a throwaway
    $HOME and would report that; this keeps it from happening in the first
    place.
    """

    global _profile_home

    _profile_home = tempfile.TemporaryDirectory()
    browser_mod.playwright_path = Path(_profile_home.name)
    browser_mod.logs_path = Path(_profile_home.name) / "logs"


def tearDownModule() -> None:
    """Remove the temporary profile directory."""

    if _profile_home is not None:
        _profile_home.cleanup()


def _cdp_broker(cdp_url: str | None = None):
    """An Ally broker configured to attach over CDP."""

    broker = ally_mod.Ally()
    broker.logger = MagicMock()
    broker.stealth = MagicMock()
    broker.args = Namespace(
        browser="cdp",
        headed=False,
        manual_login=False,
        cdp_url=cdp_url,
        profile_dir=None,
        from_prices=False,
    )
    return broker


def _playwright_with_context():
    """A Playwright double whose CDP connection has one window open."""

    playwright = MagicMock()
    browser = playwright.chromium.connect_over_cdp.return_value
    context = MagicMock()
    browser.contexts = [context]
    context.pages = [MagicMock()]
    return playwright, browser, context


def _run(broker, playwright) -> None:
    """Drive getDriver() against the given Playwright double."""

    with patch.object(
        browser_mod,
        "sync_playwright",
        return_value=MagicMock(start=lambda: playwright),
    ):
        broker.getDriver()


class AttachReusesWhatIsAlreadyOpenTests(unittest.TestCase):
    def test_reuses_the_existing_context_not_a_new_one(self) -> None:
        # A fresh context would start with no cookies and defeat the point.
        broker = _cdp_broker()
        playwright, browser, context = _playwright_with_context()

        _run(broker, playwright)

        self.assertIs(broker.context, context)
        browser.new_context.assert_not_called()

    def test_reuses_an_open_page(self) -> None:
        broker = _cdp_broker()
        playwright, _browser, context = _playwright_with_context()

        _run(broker, playwright)

        self.assertIs(broker.page, context.pages[0])
        context.new_page.assert_not_called()

    def test_opens_a_page_only_when_none_exist(self) -> None:
        broker = _cdp_broker()
        playwright, _browser, context = _playwright_with_context()
        context.pages = []

        _run(broker, playwright)

        context.new_page.assert_called_once()

    def test_marks_the_session_as_attached_and_persistent(self) -> None:
        broker = _cdp_broker()
        playwright, _browser, _context = _playwright_with_context()

        _run(broker, playwright)

        self.assertTrue(broker.attached)
        # The operator's own profile is the cookie store.
        self.assertTrue(broker.persistent_profile)

    def test_custom_endpoint_is_honoured(self) -> None:
        broker = _cdp_broker(cdp_url="http://127.0.0.1:9333")
        playwright, _browser, _context = _playwright_with_context()

        _run(broker, playwright)

        self.assertEqual(
            playwright.chromium.connect_over_cdp.call_args.args[0],
            "http://127.0.0.1:9333",
        )


class TeardownProtectsTheOperatorsBrowserTests(unittest.TestCase):
    def _attached_broker(self):
        broker = ally_mod.Ally()
        broker.logger = MagicMock()
        broker.attached = True
        broker.persistent_profile = True
        broker.tracing_started = True
        broker.context = MagicMock()
        broker.browser = MagicMock()
        broker.playwright = MagicMock()
        broker.page = MagicMock()
        return broker

    def test_attached_context_is_not_closed(self) -> None:
        broker = self._attached_broker()
        context = broker.context

        broker.teardown()

        context.close.assert_not_called()

    def test_attached_browser_is_not_closed(self) -> None:
        # Closing it would shut the operator's window mid-session.
        broker = self._attached_broker()
        browser = broker.browser

        broker.teardown()

        browser.close.assert_not_called()

    def test_playwright_still_disconnects(self) -> None:
        broker = self._attached_broker()
        playwright = broker.playwright

        broker.teardown()

        playwright.stop.assert_called_once()
        self.assertIsNone(broker.context)
        self.assertIsNone(broker.browser)

    def test_launched_browser_is_still_closed(self) -> None:
        # The protection must apply only to attached sessions.
        broker = self._attached_broker()
        broker.attached = False
        context, browser = broker.context, broker.browser

        broker.teardown()

        context.close.assert_called_once()
        browser.close.assert_called_once()

    def test_no_storage_state_is_written_for_an_attached_session(self) -> None:
        broker = self._attached_broker()
        context = broker.context  # teardown() clears the handle

        broker.teardown()

        context.storage_state.assert_not_called()


class MissingEndpointGuidanceTests(unittest.TestCase):
    def test_names_the_chrome_launch_command(self) -> None:
        broker = _cdp_broker()

        playwright = MagicMock()
        playwright.chromium.connect_over_cdp.side_effect = ConnectionRefusedError()

        with (
            patch.object(
                browser_mod,
                "sync_playwright",
                return_value=MagicMock(start=lambda: playwright),
            ),
            self.assertRaises(RuntimeError) as caught,
        ):
            broker.getDriver()

        message = str(caught.exception)
        self.assertIn("--remote-debugging-port", message)
        # Chrome 136+ refuses remote debugging on the default profile.
        self.assertIn("--user-data-dir", message)

    def test_failing_after_connect_does_not_close_the_operators_browser(self) -> None:
        # create_conn_obj() calls teardown() when getDriver() raises. If the
        # attached flag were set only at the end of a successful attach, this
        # path would close a window the operator opened.
        broker = _cdp_broker()

        playwright = MagicMock()
        browser = playwright.chromium.connect_over_cdp.return_value
        browser.contexts = []  # connected, but no window -> raises

        with patch.object(
            browser_mod,
            "sync_playwright",
            return_value=MagicMock(start=lambda: playwright),
        ):
            # The real path a user hits: create_conn_obj catches and tears down.
            broker.session.get = MagicMock(return_value=MagicMock(ok=True))
            self.assertFalse(broker.create_conn_obj())

        browser.close.assert_not_called()

    def test_attached_browser_with_no_window_is_reported(self) -> None:
        broker = _cdp_broker()

        playwright = MagicMock()
        playwright.chromium.connect_over_cdp.return_value.contexts = []

        with (
            patch.object(
                browser_mod,
                "sync_playwright",
                return_value=MagicMock(start=lambda: playwright),
            ),
            self.assertRaises(RuntimeError) as caught,
        ):
            broker.getDriver()

        self.assertIn("no open window", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
