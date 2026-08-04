"""Attaching to a browser the operator started is the path that works.

Fidelity refuses its login page to a browser automation launched -- before any
credentials -- so nothing that launches a browser can get past it. Attaching
instead means the page load happens in an ordinary session. Verified against
the live site: with CDP attach, navigator.webdriver is False and Fidelity
serves the real sign-in form rather than "we can't complete this action".

The rule this file mostly guards: never close a window somebody else opened.
"""

import importlib.util
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

SRC = Path(__file__).resolve().parents[1] / "src"


def _load_fidelity():
    spec = importlib.util.spec_from_file_location(
        "fidelity_broker_cdp", SRC / "brokers/fidelity/broker.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fidelity_mod = _load_fidelity()


class AttachTests(unittest.TestCase):
    def _broker(self, cdp_url: str | None = None):
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.stealth = MagicMock()
        broker.args = Namespace(
            browser="cdp",
            headed=False,
            manual_login=False,
            cdp_url=cdp_url,
            profile_dir=None,
        )
        return broker

    def _playwright_with_context(self):
        playwright = MagicMock()
        browser = playwright.chromium.connect_over_cdp.return_value
        context = MagicMock()
        browser.contexts = [context]
        context.pages = [MagicMock()]
        return playwright, browser, context

    def _run(self, broker, playwright):
        with patch.object(
            fidelity_mod,
            "sync_playwright",
            return_value=MagicMock(start=lambda: playwright),
        ):
            broker.getDriver()

    def test_reuses_the_existing_context_not_a_new_one(self) -> None:
        # A fresh context would start with no cookies and defeat the point.
        broker = self._broker()
        playwright, browser, context = self._playwright_with_context()

        self._run(broker, playwright)

        self.assertIs(broker.context, context)
        browser.new_context.assert_not_called()

    def test_reuses_an_open_page(self) -> None:
        broker = self._broker()
        playwright, _browser, context = self._playwright_with_context()

        self._run(broker, playwright)

        self.assertIs(broker.page, context.pages[0])
        context.new_page.assert_not_called()

    def test_opens_a_page_only_when_none_exist(self) -> None:
        broker = self._broker()
        playwright, _browser, context = self._playwright_with_context()
        context.pages = []

        self._run(broker, playwright)

        context.new_page.assert_called_once()

    def test_marks_the_session_as_attached_and_persistent(self) -> None:
        broker = self._broker()
        playwright, _browser, _context = self._playwright_with_context()

        self._run(broker, playwright)

        self.assertTrue(broker.attached)
        # The operator's own profile is the cookie store.
        self.assertTrue(broker.persistent_profile)

    def test_custom_endpoint_is_honoured(self) -> None:
        broker = self._broker(cdp_url="http://127.0.0.1:9333")
        playwright, _browser, _context = self._playwright_with_context()

        self._run(broker, playwright)

        self.assertEqual(
            playwright.chromium.connect_over_cdp.call_args.args[0],
            "http://127.0.0.1:9333",
        )


class AttachImpliesHumanSessionTests(unittest.TestCase):
    """Attaching means the operator signed in; do not demand a credential."""

    def _broker(self, attached: bool, manual: bool):
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.attached = attached
        broker.args = Namespace(
            manual_login=manual, cred_id=[], username=[], password=[]
        )
        broker.manual_login = MagicMock(return_value=True)
        return broker

    def test_attached_routes_to_the_human_session_path(self) -> None:
        # Without this, `--browser cdp` alone reported "No credentials
        # supplied" even though the flow never uses one.
        broker = self._broker(attached=True, manual=False)

        self.assertTrue(broker.login())
        broker.manual_login.assert_called_once()

    def test_manual_login_flag_still_works_when_not_attached(self) -> None:
        broker = self._broker(attached=False, manual=True)

        self.assertTrue(broker.login())
        broker.manual_login.assert_called_once()

    def test_neither_falls_back_to_credentials(self) -> None:
        broker = self._broker(attached=False, manual=False)

        # No credentials configured, so the base implementation reports and
        # returns False rather than silently doing nothing.
        self.assertFalse(broker.login())
        broker.manual_login.assert_not_called()


class TeardownProtectsTheOperatorsBrowserTests(unittest.TestCase):
    def _attached_broker(self):
        broker = fidelity_mod.Fidelity()
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
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.stealth = MagicMock()
        broker.args = Namespace(
            browser="cdp",
            headed=False,
            manual_login=False,
            cdp_url=None,
            profile_dir=None,
        )

        playwright = MagicMock()
        playwright.chromium.connect_over_cdp.side_effect = ConnectionRefusedError()

        with (
            patch.object(
                fidelity_mod,
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
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.stealth = MagicMock()
        broker.args = Namespace(
            browser="cdp",
            headed=False,
            manual_login=False,
            cdp_url=None,
            profile_dir=None,
        )

        playwright = MagicMock()
        browser = playwright.chromium.connect_over_cdp.return_value
        browser.contexts = []  # connected, but no window -> raises

        with patch.object(
            fidelity_mod,
            "sync_playwright",
            return_value=MagicMock(start=lambda: playwright),
        ):
            # The real path a user hits: create_conn_obj catches and tears down.
            broker.session.get = MagicMock(return_value=MagicMock(ok=True))
            self.assertFalse(broker.create_conn_obj())

        browser.close.assert_not_called()

    def test_attached_browser_with_no_window_is_reported(self) -> None:
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.stealth = MagicMock()
        broker.args = Namespace(
            browser="cdp",
            headed=False,
            manual_login=False,
            cdp_url=None,
            profile_dir=None,
        )

        playwright = MagicMock()
        playwright.chromium.connect_over_cdp.return_value.contexts = []

        with (
            patch.object(
                fidelity_mod,
                "sync_playwright",
                return_value=MagicMock(start=lambda: playwright),
            ),
            self.assertRaises(RuntimeError) as caught,
        ):
            broker.getDriver()

        self.assertIn("no open window", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
