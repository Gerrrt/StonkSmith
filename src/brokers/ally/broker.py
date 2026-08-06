"""
Ally Invest broker class.

What is here is Ally: its two hosts, the markers that tell a signed-in page
from the login form, and a sign-in that is unusual enough to be worth stating
up front.

**There is no direct login to Ally Invest.** ally.com signs you in to the
*bank* at secure.ally.com, and the investing site is reached by clicking
through from there -- live.invest.ally.com is handed a session, it never asks
for one. So the login URL below is the bank's, the sign-in the operator
performs is the bank's, and what StonkSmith waits for is arrival on the
investing host rather than the submission of any form.

Starting, attaching to, persisting and tearing down the browser all live in
etc.browser_connection, shared with Fidelity.

BrokerLoader discovers this package by the presence of this file and imports it
by path, reading the module-level ``Broker`` alias at the bottom. Imports here
must be absolute: the module is executed under the synthetic name "broker" with
no package, so relative imports would fail.
"""

from typing import ClassVar
from urllib.parse import urlparse

from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import TimeoutError

from etc.browser_connection import BrowserConnection, browser_was_closed
from etc.logger import StonkSmithAdapter

#: Where signing in actually happens. Ally Invest has no login page of its own;
#: this is Ally Bank's, and the investing site is entered from it.
LOGIN_URL = "https://secure.ally.com/"

#: The investing site. Matched on hostname rather than by substring: the bank
#: pages link to it, so "live.invest.ally.com" appears in the markup of pages
#: that are not it.
INVEST_HOST = "live.invest.ally.com"

#: Holdings for whichever account is selected. The unqualified path is used on
#: purpose -- the per-account URL carries a 64-character id that is not known
#: until the page has been seen once, while this one redirects to it.
HOLDINGS_URL = "https://live.invest.ally.com/accounts/holdings-balances"

#: Proof of an authenticated investing session: the log-out control. Both are
#: the same component, matched two ways because an id and a title attribute
#: fail differently. Lowercase, because page_body() lowercases what it returns.
SIGNED_IN_MARKERS: tuple[str, ...] = (
    "allynavlogout",
    'title="log out"',
)

#: The bank's login form. Not used to decide "signed in" -- the markers above
#: do that, and requiring positive proof is what makes the check fail closed --
#: but it makes the difference between "bounced to sign-in" and "something else
#: entirely" reportable.
SIGN_IN_MARKERS: tuple[str, ...] = (
    'data-app-id="ally-next-remote-login"',
    'data-testid="login-submit"',
)

#: A human sign-in, plus finding the investing link afterwards, is not fast.
MANUAL_LOGIN_TIMEOUT_MS = 300000

#: Once the investing host is reached, its shell renders quickly.
SIGNED_IN_TIMEOUT_MS = 30000

#: Stand-in username when the session came from a manual sign-in rather than a
#: stored credential.
MANUAL_SESSION_LABEL = "manual session"


def on_invest_host(url: str) -> bool:
    """
    Whether a URL points at the investing site.

    Compares hostnames rather than testing for a substring. The bank's own
    pages link to live.invest.ally.com, so a substring test against the whole
    URL -- or against the page markup -- is true while still on the bank, which
    would end the sign-in wait before the operator had clicked through.
    :param url: The URL to test
    :return: True when the host is the investing site
    :rtype: bool
    """

    return (urlparse(url=url).hostname or "").lower() == INVEST_HOST


class Ally(BrowserConnection):
    """
    Ally Invest broker class.
    """

    #: Names the storage-state and trace files.
    profile_name: ClassVar[str] = "Ally"
    browser_slug: ClassVar[str] = "ally"

    def __init__(self) -> None:
        super().__init__()
        self.broker = "Ally"
        self.name = "Ally"
        self.login_url = LOGIN_URL
        self.holdings_url = HOLDINGS_URL

    def broker_logger(self) -> None:
        """
        Set up logger for the Ally broker class.
        :return: None
        :rtype: None
        """

        self.logger = StonkSmithAdapter(
            extra={
                "broker": "Ally",
                "username": self.username,
            },
            logger=self.logger.logger,
        )

    def login(self) -> bool:
        """
        Obtain an authenticated investing session.

        Always the human path. Ally's login is fronted by Akamai, Dynatrace and
        Transmit, and there is no automated flow here to fall back to -- so
        unlike Fidelity, this does not defer to the credential login for some
        cases and the human one for others. A stored credential would be asked
        for and then never used.
        :return: True when the browser holds an authenticated session
        :rtype: bool
        """

        return self.manual_login()

    def on_invest_site(self) -> bool:
        """
        Whether the browser is currently on the investing host.
        :return: True when it is
        :rtype: bool
        """

        return on_invest_host(url=self.active_page.url)

    def shows_sign_in_form(self) -> bool:
        """
        Whether the bank's login form is on screen.
        :return: True when credentials are being asked for
        :rtype: bool
        """

        body: str | None = self.page_body()
        return body is not None and any(m in body for m in SIGN_IN_MARKERS)

    def shows_signed_in_chrome(self) -> bool:
        """
        Whether the investing site's signed-in navigation is rendered.

        The log-out control only exists for an authenticated session, so its
        presence is positive proof rather than the absence of a login form.
        :return: True when the page carries a log-out control
        :rtype: bool
        """

        body: str | None = self.page_body()
        return body is not None and any(m in body for m in SIGNED_IN_MARKERS)

    def session_is_live(self) -> bool:
        """
        Whether the saved cookies still authenticate.

        Fails closed. Every uncertain outcome -- navigation error, unreadable
        page, a page that is on the right host but shows no signed-in
        navigation -- reports "not live", because the cost of being wrong is
        asking for a sign-in that was not needed, while the opposite mistake
        scrapes a logged-out page and reports it as an account with no
        holdings.
        :return: True if already signed in
        :rtype: bool
        """

        # Never navigate an attached browser before the operator has signed in.
        # Driving an unauthenticated page over CDP is what trips Akamai's
        # sensor for that profile; every later attempt in the same profile is
        # then refused, including the operator's own manual sign-in. Judge from
        # whatever is already on screen instead.
        if self.attached:
            if not self.on_invest_site():
                return False

        else:
            try:
                self.active_page.goto(url=self.holdings_url)

            except PlaywrightError:
                return False

            # A bounced request lands back on secure.ally.com, so the host
            # check is the redirect check.
            if not self.on_invest_site():
                return False

        return self.shows_signed_in_chrome()

    def manual_login(self) -> bool:
        """
        Reuse a saved session, or hand the browser over so the operator can
        sign in themselves.

        The instructions name both steps, because the second one is the
        surprise: signing in at ally.com lands on the *bank* dashboard, and
        StonkSmith is still waiting at that point. It has to be, since nothing
        it could click on that page is guaranteed to be the investing link.

        Ally remembers a device once it has seen one, so this is normally a
        first-run cost only: the session is written back on exit and reused
        until it expires.
        :return: True when the browser holds an authenticated session
        :rtype: bool
        """

        if self.session_is_live():
            self.logger.success(
                msg="Reusing the saved Ally session; no sign-in needed."
            )
            self.username = self.username or MANUAL_SESSION_LABEL
            return True

        if self.attached:
            message = (
                "Sign in to Ally in the Chrome window, then open your "
                "investment account. StonkSmith is waiting and will not touch "
                "the page until you are in -- driving it beforehand is what "
                "gets the profile blocked."
            )
        else:
            message = (
                "Sign in to Ally in the browser window that just opened, then "
                "click through to your investment account. Ally has no direct "
                "login for Ally Invest: the bank signs you in and hands the "
                "investing site your session."
            )

        self.logger.highlight(
            msg=(
                f"{message} Taking over once {INVEST_HOST} loads "
                f"(waiting up to {MANUAL_LOGIN_TIMEOUT_MS // 60000} minutes)."
            )
        )

        try:
            # Attached: do not navigate. Chrome was told to open the sign-in
            # page itself; touching it from here before the operator signs in
            # is the poisoning step described in session_is_live().
            if not self.attached:
                self.active_page.goto(url=self.login_url)

            # A predicate on the hostname, not a glob: the bank's pages link to
            # the investing site, so "**invest.ally.com**" matches a URL that
            # merely mentions it.
            self.active_page.wait_for_url(
                url=lambda url: on_invest_host(url=url),
                timeout=MANUAL_LOGIN_TIMEOUT_MS,
            )

            # Landing on the host is not the same as being signed in on it, and
            # the shell hydrates after the URL changes. Wait for the log-out
            # control rather than reading the page the instant it arrives.
            self.active_page.wait_for_selector(
                "#allyNavLogOut", state="attached", timeout=SIGNED_IN_TIMEOUT_MS
            )

        except TimeoutError:
            self.logger.fail(
                msg=(
                    f"Timed out waiting for a signed-in page on {INVEST_HOST}. "
                    "If the sign-in did complete, Ally's navigation markup may "
                    "have changed."
                )
            )
            self.capture_page(reason="manual-login-timeout")
            return False

        except PlaywrightError as e:
            if browser_was_closed(error=e):
                self.logger.fail(msg="Browser was closed before sign-in finished.")
            else:
                self.logger.fail(msg=f"Browser error during manual sign-in: {e}")
            return False

        # Only promise session reuse if the session actually persisted;
        # save_session() reports its own failure and carries on.
        if self.save_session():
            self.logger.success(
                msg="Signed in. Session saved; later runs reuse it until it expires."
            )
        else:
            self.logger.highlight(
                msg=(
                    "Signed in, but the session could not be saved -- the next "
                    "run will ask you to sign in again."
                )
            )

        self.username = self.username or MANUAL_SESSION_LABEL
        return True


#: BrokerLoader reads this off the path-loaded module, so the class name is free
#: to diverge from the directory name (e.g. TSP, Schwab529Plan).
Broker = Ally
