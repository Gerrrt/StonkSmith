"""Ally Invest has no login of its own, and that shapes the whole sign-in.

ally.com signs you in to Ally *Bank* at secure.ally.com; the investing site is
reached by clicking through from the bank dashboard and is handed a session it
never asks for. So there is no form to submit at live.invest.ally.com, and what
StonkSmith waits for is arrival on the investing host followed by proof of a
signed-in shell.

Two things the wait must not do:

* end early because the bank page merely *links* to live.invest.ally.com -- the
  markup of the signed-out dashboard contains that string, so anything short of
  a hostname comparison returns before the operator has clicked through
* call being on the right host the same as being signed in on it, since a
  bounced or expired session lands there too
"""

import importlib.util
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

import stonksmith.etc.browser_connection as browser_mod
from package_tree import PACKAGE

BANK_URL = "https://secure.ally.com/dashboard"
INVEST_URL = "https://live.invest.ally.com/accounts/holdings-balances/abc123/overview"

#: The signed-in investing shell, reduced to the marker that proves it.
SIGNED_IN_BODY = (
    '<html><menu-item id="allyNavLogOut">'
    '<button class="button-link" title="Log Out">Log Out</button>'
    "</menu-item></html>"
)

#: The bank login form, which is where an expired session lands.
LOGIN_BODY = (
    '<html><div data-app-id="ally-next-remote-login">'
    '<button data-testid="login-submit">Log In</button></div></html>'
)


def _load_ally():
    spec = importlib.util.spec_from_file_location(
        "ally_broker", PACKAGE / "brokers/ally/broker.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ally_mod = _load_ally()


_profile_home: tempfile.TemporaryDirectory | None = None


def setUpModule() -> None:
    """
    Keep the saved browser profile out of the developer's home directory.

    save_session() mkdirs the profile's parent -- ~/.stonksmith/playwright --
    before writing storage state, so driving it with a mock context creates
    that directory for real. The broker reads the path off its own module
    global at construction, so redirecting it here covers every broker built
    below.

    logs_path goes with it: session_is_live() now captures the page when the
    investing host renders no log-out control, and capture_page() writes to
    ~/.stonksmith/logs.
    """

    global _profile_home

    _profile_home = tempfile.TemporaryDirectory()
    browser_mod.playwright_path = Path(_profile_home.name)
    browser_mod.logs_path = Path(_profile_home.name) / "logs"


def tearDownModule() -> None:
    """Remove the temporary profile directory."""

    if _profile_home is not None:
        _profile_home.cleanup()


def _broker(url: str, body: str, attached: bool = False):
    """An Ally broker whose page reports the given URL and markup."""

    broker = ally_mod.Ally()
    broker.args = Namespace()
    broker.logger = MagicMock()
    broker.attached = attached
    broker.page = MagicMock()
    broker.page.url = url
    broker.page.content.return_value = body

    # Playwright's wait_for_selector resolves only when the selector really is
    # in the DOM, and raises TimeoutError otherwise. A bare MagicMock returns a
    # value for any call, which would report every page as signed in --
    # including the empty shell these tests exist to reject.
    def _wait(selector: str, **_: object) -> None:
        markup: str = broker.page.content()

        if selector.removeprefix("#").lower() not in markup.lower():
            raise PlaywrightTimeoutError(f"Timeout waiting for {selector}")

    broker.page.wait_for_selector.side_effect = _wait
    return broker


class InvestHostTests(unittest.TestCase):
    def test_the_investing_host_is_recognised(self) -> None:
        self.assertTrue(ally_mod.on_invest_host(url=INVEST_URL))

    def test_the_bank_is_not_the_investing_host(self) -> None:
        self.assertFalse(ally_mod.on_invest_host(url=BANK_URL))

    def test_a_url_that_merely_mentions_the_host_does_not_count(self) -> None:
        # The bank dashboard links to the investing site, so a substring test
        # against the URL -- or the markup -- is true before any click-through.
        self.assertFalse(
            ally_mod.on_invest_host(
                url="https://secure.ally.com/sso?to=live.invest.ally.com/dashboard"
            )
        )

    def test_a_lookalike_domain_does_not_count(self) -> None:
        self.assertFalse(
            ally_mod.on_invest_host(url="https://live.invest.ally.com.example.test/")
        )

    def test_a_url_with_no_host_is_not_the_investing_site(self) -> None:
        self.assertFalse(ally_mod.on_invest_host(url="about:blank"))


class SessionIsLiveTests(unittest.TestCase):
    def test_a_signed_in_investing_page_is_live(self) -> None:
        broker = _broker(url=INVEST_URL, body=SIGNED_IN_BODY)
        broker.page.goto.side_effect = lambda **_: None

        self.assertTrue(broker.session_is_live())

    def test_a_bounce_to_the_bank_login_is_not_live(self) -> None:
        broker = _broker(url=BANK_URL, body=LOGIN_BODY)

        self.assertFalse(broker.session_is_live())

    def test_the_right_host_without_a_signed_in_shell_is_not_live(self) -> None:
        # Positive proof, not the absence of a login form: an expired session
        # can render an investing URL with no navigation on it at all.
        broker = _broker(url=INVEST_URL, body="<html><body></body></html>")

        self.assertFalse(broker.session_is_live())

    def test_an_unreadable_page_is_not_live(self) -> None:
        broker = _broker(url=INVEST_URL, body=SIGNED_IN_BODY)
        broker.page.content.side_effect = PlaywrightError("target closed")

        self.assertFalse(broker.session_is_live())

    def test_a_navigation_failure_is_not_live(self) -> None:
        broker = _broker(url=INVEST_URL, body=SIGNED_IN_BODY)
        broker.page.goto.side_effect = PlaywrightError("net::ERR_ABORTED")

        self.assertFalse(broker.session_is_live())

    def test_an_attached_browser_is_never_navigated(self) -> None:
        # Driving an unauthenticated page over CDP is what flags the profile
        # with Akamai, and every later sign-in in that profile is refused --
        # including the operator's own.
        broker = _broker(url=BANK_URL, body=LOGIN_BODY, attached=True)

        self.assertFalse(broker.session_is_live())
        broker.page.goto.assert_not_called()

    def test_an_attached_browser_already_on_holdings_is_live(self) -> None:
        broker = _broker(url=INVEST_URL, body=SIGNED_IN_BODY, attached=True)

        self.assertTrue(broker.session_is_live())
        broker.page.goto.assert_not_called()

    def test_a_shell_that_hydrates_after_the_load_event_is_live(self) -> None:
        # The first real Ally run failed here. goto() settles at the load
        # event; Angular renders the nav afterwards. Reading the body at that
        # instant sees an empty root, and because this check demands the
        # log-out control be *present* rather than a login form be absent, an
        # un-rendered page fails it -- so a live session reads as a dead one
        # and the operator is sent to a five-minute sign-in they did not need.
        broker = _broker(url=INVEST_URL, body="<html><app-root></app-root></html>")

        def _hydrate(selector: str, **_: object) -> None:
            broker.page.content.return_value = SIGNED_IN_BODY

        broker.page.wait_for_selector.side_effect = _hydrate

        self.assertTrue(broker.session_is_live())


class SessionRejectionReportTests(unittest.TestCase):
    """Falling back to a manual sign-in must say which failure caused it.

    "It asked me to sign in again" is the same sentence whether the cookies
    expired, the request bounced or the markup moved, and those have three
    different answers. Before this, every rejection was silent and the only
    capture came from the manual-login timeout five minutes later -- a picture
    of the login screen nobody filled in, not of the page that was rejected.
    """

    @staticmethod
    def _said(broker) -> str:
        return " ".join(str(call) for call in broker.logger.display.call_args_list)

    def test_a_bounce_names_where_it_landed_and_what_was_on_it(self) -> None:
        broker = _broker(url=BANK_URL, body=LOGIN_BODY)

        self.assertFalse(broker.session_is_live())
        said: str = self._said(broker=broker)
        self.assertIn("secure.ally.com", said)
        self.assertIn("sign-in form", said)

    def test_a_bounce_to_something_other_than_the_login_says_so(self) -> None:
        # An interstitial or a block page is a different problem from an
        # expired session, and naming the sign-in form when it is not there
        # would send the reader after the wrong one.
        broker = _broker(url=BANK_URL, body="<html><body>maintenance</body></html>")

        self.assertFalse(broker.session_is_live())
        self.assertIn("something else moved", self._said(broker=broker))

    def test_a_navigation_failure_reports_the_error(self) -> None:
        broker = _broker(url=INVEST_URL, body=SIGNED_IN_BODY)
        broker.page.goto.side_effect = PlaywrightError("net::ERR_ABORTED")

        self.assertFalse(broker.session_is_live())
        said: str = self._said(broker=broker)
        self.assertIn("would not load", said)
        self.assertIn("ERR_ABORTED", said)

    def test_a_host_that_never_renders_the_shell_is_captured(self) -> None:
        # The one rejection that cannot be diagnosed from a log line: whether
        # the session is genuinely dead or the markup moved is only decidable
        # from the page itself.
        broker = _broker(url=INVEST_URL, body="<html><body></body></html>")
        broker.capture_page = MagicMock()

        self.assertFalse(broker.session_is_live())
        broker.capture_page.assert_called_once()
        self.assertEqual(
            broker.capture_page.call_args.kwargs.get("reason"), "session-check"
        )

    def test_an_unreadable_page_is_not_reported_as_a_timeout(self) -> None:
        # TimeoutError subclasses PlaywrightError, so order matters: a page
        # that went away mid-wait is unreadable, not unrendered.
        broker = _broker(url=INVEST_URL, body=SIGNED_IN_BODY)
        broker.page.wait_for_selector.side_effect = PlaywrightError("target closed")

        self.assertFalse(broker.session_is_live())
        self.assertIn("could not be read", self._said(broker=broker))


class SignInMarkerTests(unittest.TestCase):
    def test_the_bank_login_form_is_recognised(self) -> None:
        self.assertTrue(_broker(url=BANK_URL, body=LOGIN_BODY).shows_sign_in_form())

    def test_the_investing_shell_is_not_a_login_form(self) -> None:
        broker = _broker(url=INVEST_URL, body=SIGNED_IN_BODY)
        self.assertFalse(broker.shows_sign_in_form())

    def test_every_marker_is_lowercase(self) -> None:
        # page_body() lowercases what it returns, so an uppercase marker never
        # matches anything and the check quietly stops working.
        for marker in ally_mod.SIGNED_IN_MARKERS + ally_mod.SIGN_IN_MARKERS:
            with self.subTest(marker=marker):
                self.assertEqual(marker, marker.lower())


class ManualLoginTests(unittest.TestCase):
    def test_a_live_session_is_reused_without_navigating(self) -> None:
        broker = _broker(url=INVEST_URL, body=SIGNED_IN_BODY, attached=True)

        self.assertTrue(broker.manual_login())
        broker.page.goto.assert_not_called()
        broker.page.wait_for_url.assert_not_called()

    def test_the_wait_is_for_the_host_then_the_signed_in_control(self) -> None:
        broker = _broker(url=BANK_URL, body=LOGIN_BODY)
        broker.context = MagicMock()
        broker.persistent_profile = True

        # wait_for_url returns once the operator has clicked through, which is
        # also the moment the page becomes the investing shell. Modelling that
        # is what lets the log-out wait after it find anything.
        def _signed_in(**_: object) -> None:
            broker.page.url = INVEST_URL
            broker.page.content.return_value = SIGNED_IN_BODY

        broker.page.wait_for_url.side_effect = _signed_in

        self.assertTrue(broker.manual_login())
        # Two navigations, in this order: the holdings probe that decides the
        # saved session is dead, then the bank login the operator is handed.
        self.assertEqual(
            [call.kwargs["url"] for call in broker.page.goto.call_args_list],
            [ally_mod.HOLDINGS_URL, ally_mod.LOGIN_URL],
        )
        broker.page.wait_for_url.assert_called_once()
        broker.page.wait_for_selector.assert_called_once()
        self.assertEqual(
            broker.page.wait_for_selector.call_args.args[0], "#allyNavLogOut"
        )

    def test_the_url_predicate_rejects_the_bank(self) -> None:
        broker = _broker(url=BANK_URL, body=LOGIN_BODY)
        broker.context = MagicMock()
        broker.persistent_profile = True
        broker.manual_login()

        predicate = broker.page.wait_for_url.call_args.kwargs["url"]

        self.assertFalse(predicate(BANK_URL))
        self.assertTrue(predicate(INVEST_URL))

    def test_the_instructions_name_the_click_through(self) -> None:
        # The second step is the surprise: signing in lands on the bank
        # dashboard and StonkSmith is still waiting at that point.
        broker = _broker(url=BANK_URL, body=LOGIN_BODY)
        broker.context = MagicMock()
        broker.persistent_profile = True
        broker.manual_login()

        said = " ".join(
            str(object=call.kwargs.get("msg", ""))
            for call in broker.logger.highlight.call_args_list
        ).lower()

        self.assertIn("investment account", said)

    def test_a_closed_browser_fails_rather_than_reporting_a_session(self) -> None:
        broker = _broker(url=BANK_URL, body=LOGIN_BODY)
        broker.page.wait_for_url.side_effect = PlaywrightError(
            "Target page, context or browser has been closed"
        )

        self.assertFalse(broker.manual_login())


class LoginPathTests(unittest.TestCase):
    def test_login_always_takes_the_human_path(self) -> None:
        # There is no credential flow here to fall back to, so asking for a
        # stored credential would be asking for something this broker never
        # uses.
        broker = _broker(url=INVEST_URL, body=SIGNED_IN_BODY, attached=True)

        self.assertTrue(broker.login())
        self.assertEqual(broker.username, ally_mod.MANUAL_SESSION_LABEL)

    def test_the_login_url_is_the_bank_not_the_investing_site(self) -> None:
        self.assertFalse(ally_mod.on_invest_host(url=ally_mod.LOGIN_URL))


if __name__ == "__main__":
    unittest.main()
