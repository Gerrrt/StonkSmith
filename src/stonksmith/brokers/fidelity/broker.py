"""
Fidelity broker class.

What is left here is Fidelity: its URLs, the markers that tell a signed-in page
from a refused one, and its 2FA flow. Starting, attaching to, persisting and
tearing down the browser all live in etc.browser_connection, which Ally and any
other browser-backed broker share.

BrokerLoader discovers this package by the presence of this file and imports it by
path, reading the module-level ``Broker`` alias at the bottom. Imports here must be
absolute: the module is executed under the synthetic name "broker" with no package,
so relative imports would fail.
"""

import warnings
from argparse import Namespace
from contextlib import suppress
from typing import ClassVar
from urllib.parse import urlparse

from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api._generated import Locator

from stonksmith.etc.browser_connection import BrowserConnection, browser_was_closed
from stonksmith.etc.context import BrokerDbProtocol
from stonksmith.etc.logger import StonkSmithAdapter, stonksmith_logger

#: The release this broker is removed in. Stated once because CHANGELOG.md,
#: docs/brokers.md and the subparser help all name it, and a notice promising a
#: different version than the docs is worse than no notice.
REMOVED_IN = "1.0"

#: Said once at the start of every run. Names the thing, the version and the
#: replacement, in that order -- the shape ``_legacy_names._announce`` uses for
#: the other deprecation this project is carrying.
DEPRECATION_NOTICE = (
    f"The fidelity broker is deprecated and will be removed in StonkSmith "
    f"{REMOVED_IN}. Link Fidelity through SnapTrade instead, which also takes it "
    f"from attended to unattended; see docs/brokers.md#snaptrade."
)


def announce_deprecation() -> None:
    """
    Say that this broker is going away, before anything can stop the run saying it.

    Emitted two ways on purpose, for the reasons ``_legacy_names._announce`` gives
    at length: a ``DeprecationWarning`` so a `-W` filter and the tests can see it,
    and an ERROR-level log line because that warning is invisible under Python's
    default filters outside ``__main__`` -- an operator running this from cron
    would otherwise get no signal at all, and ERROR is the level ``--quiet``
    leaves showing.
    """

    # Suppressed, not skipped. Under `-W error` -- and under the suite's own
    # `filterwarnings = ["error"]` -- an unsuppressed warning here raises inside
    # a thread-pool target whose whole contract is to report rather than raise,
    # and the run is reported as having failed. A notice that breaks the thing it
    # describes is worse than no notice. catch_warnings(record=True) still sees
    # it, which is what the tests assert on.
    with suppress(DeprecationWarning):
        warnings.warn(DEPRECATION_NOTICE, DeprecationWarning, stacklevel=2)

    stonksmith_logger.fail(msg=DEPRECATION_NOTICE)


#: Playwright's default is 30s. These steps are optional or fast-failing, so a
#: shorter wait keeps a broken selector from stalling the whole login.
SHORT_TIMEOUT_MS = 5000

#: Label text for Fidelity's "remember this device" checkbox. Split out because
#: it is the kind of copy that changes without notice.
REMEMBER_DEVICE_TEXT = "Don't ask me again on this"

#: Landing on the summary page after submitting a code involves a redirect
#: chain, so it gets a longer budget than the individual clicks.
SUBMIT_TIMEOUT_MS = 15000

#: Fidelity answers a refused sign-in with a generic error page that still lives
#: under /signin and is still titled "Log in to Fidelity", so a URL check alone
#: mistakes it for the 2FA step. These markers identify it.
REFUSED_PAGE_MARKERS: tuple[str, ...] = (
    "dom-sys-err",
    "can't complete this action right now",
)

#: A human sign-in, including 2FA, is not fast. Give it a generous budget.
MANUAL_LOGIN_TIMEOUT_MS = 300000

#: Path of the authenticated portfolio page. Matched against the URL *path*
#: only: an unauthenticated request bounces to
#: /prgw/digital/signin/retail?AuthRedUrl=...%2Fportfolio%2Fsummary, so a
#: substring test against the whole URL is true on the login page too -- which
#: made a signed-out session look authenticated and skipped the manual sign-in.
SUMMARY_PATH = "/portfolio/summary"

#: Stencil components that only exist on the sign-in form. Their presence means
#: the page is asking for credentials, whatever the URL says.
SIGN_IN_MARKERS: tuple[str, ...] = (
    "signin-pi-login-template",
    "pvdccl-form",
)

#: Stand-in username when the session came from a manual sign-in rather than a
#: stored credential.
MANUAL_SESSION_LABEL = "manual session"


def _is_summary_path(url: str) -> bool:
    """
    Whether a URL points at the portfolio summary endpoint itself.

    Matches the end of the path, so neither the sign-in redirect (which carries
    the summary URL in AuthRedUrl) nor a longer path that merely starts the
    same way -- /portfolio/summary2, /portfolio/summary/extra -- is mistaken
    for it.
    :param url: The URL to test
    :return: True when the path is the summary endpoint
    """

    return urlparse(url=url).path.rstrip("/").endswith(SUMMARY_PATH)


class Fidelity(BrowserConnection):
    """
    Fidelity broker class
    """

    #: Names the storage-state and trace files. Capitalized because that is
    #: what shipped: renaming it orphans every existing saved session and
    #: quietly costs the operator their device-trust cookie.
    profile_name: ClassVar[str] = "Fidelity"
    browser_slug: ClassVar[str] = "fidelity"

    def __init__(self) -> None:
        super().__init__()
        self.broker = "Fidelity"
        self.name = "Fidelity"
        self.login_url = "https://digital.fidelity.com/prgw/digital/signin/retail"
        self.summary_url = "https://digital.fidelity.com/ftgw/digital/portfolio/summary"
        self.account_dict: dict[str, str] = {}
        self.source_account: str = ""

    def __call__(
        self, args: Namespace, db: BrokerDbProtocol, host: str | None = None
    ) -> bool:
        """
        Announce the deprecation, then run exactly as the base class does.

        Here rather than in the module's ``on_login``, which is only reached once
        a login has succeeded -- and this broker's login is the part most likely
        to fail, since getting past Akamai Bot Manager is the reason it is being
        retired. An operator whose run dies at the sign-in is the one who most
        needs to hear that there is an API that does not have a sign-in.

        Here rather than in ``__init__`` for the opposite reason: construction
        happens in tests and in any code that merely inspects the broker, and a
        notice at ERROR level that fires when nobody is running anything is how a
        notice gets tuned out.
        :param args: Parsed command-line arguments
        :param db: The broker database this run writes to
        :param host: Optional host override, passed straight through
        :return: Whatever the base class reports for the run
        :rtype: bool
        """

        announce_deprecation()

        return super().__call__(args, db, host)

    def broker_logger(self) -> None:
        """
        Set up logger for Fidelity broker class
        :return: None
        :rtype: None
        """

        self.logger = StonkSmithAdapter(
            extra={
                "broker": "Fidelity",
                "username": self.username,
            },
            logger=self.logger.logger,
        )

    def login(self) -> bool:
        """
        Authenticate, either by reusing/obtaining a human session or by the
        normal credential flow.

        Attaching over CDP means the operator owns the sign-in, so it implies
        the human-session path: requiring a stored credential there would be
        asking for something this flow never uses. create_conn_obj() runs
        before this, so self.attached is already known.
        :return: True when the browser holds an authenticated session
        """

        if self.attached or getattr(self.args, "manual_login", False):
            return self.manual_login()

        return super().login()

    def on_summary_page(self) -> bool:
        """
        Whether the browser is actually on the portfolio summary.
        :return: True when the current path is the summary page
        """

        return _is_summary_path(url=self.active_page.url)

    def shows_sign_in_form(self) -> bool:
        """
        Whether the page is rendering the sign-in form.
        :return: True when credentials are being asked for
        """

        body: str | None = self.page_body()
        return body is not None and any(m in body for m in SIGN_IN_MARKERS)

    def session_is_live(self) -> bool:
        """
        Whether the saved cookies still authenticate: navigating straight to
        the portfolio summary lands there rather than bouncing to sign-in.

        Fails closed. Every uncertain outcome -- navigation error, unreadable
        page -- reports "not live", because the cost of being wrong is asking
        for a sign-in that was not needed, while the opposite mistake scrapes
        the login page and reports it as missing accounts.
        :return: True if already signed in
        """

        # Never navigate an attached browser before the operator has signed in.
        # Driving an unauthenticated page over CDP is what trips Akamai's sensor
        # and flags `_abck` for that profile; every later attempt in the same
        # profile is then refused, including the operator's own manual sign-in.
        # Judge from whatever is already on screen instead.
        if self.attached:
            if not self.on_summary_page():
                return False

        else:
            try:
                self.active_page.goto(url=self.summary_url)

            except PlaywrightError:
                return False

            if not self.on_summary_page():
                return False

        # Read once and judge from that: three separate content() calls could
        # each see a different page, and an unreadable one must not read as
        # authenticated.
        body: str | None = self.page_body()
        if body is None:
            return False

        if any(marker in body for marker in REFUSED_PAGE_MARKERS):
            return False

        # Belt and braces: a future redirect that preserved the path would
        # still be caught by the sign-in form being on screen.
        return not any(marker in body for marker in SIGN_IN_MARKERS)

    def manual_login(self) -> bool:
        """
        Reuse a saved session, or hand the browser over so the operator can
        sign in themselves.

        Fidelity fronts its login with Akamai Bot Manager and ThreatMetrix,
        which reject a scripted sign-in before the form is even rendered. A
        human completing the login in the visible window produces the telemetry
        those systems look for; the resulting cookies are then saved and reused
        until they expire.
        :return: True when the browser holds an authenticated session
        """

        if self.session_is_live():
            self.logger.success(
                msg="Reusing the saved Fidelity session; no sign-in needed."
            )
            self.username = self.username or MANUAL_SESSION_LABEL
            return True

        if self.attached:
            message = (
                "Sign in to Fidelity in the Chrome window and open your "
                "portfolio summary. StonkSmith is waiting and will not touch "
                "the page until you are in -- driving it beforehand is what "
                "gets the profile blocked."
            )
        else:
            message = (
                "Sign in to Fidelity in the browser window that just opened, "
                "including any 2FA."
            )

        self.logger.highlight(
            msg=(
                f"{message} Taking over once the portfolio summary loads "
                f"(waiting up to {MANUAL_LOGIN_TIMEOUT_MS // 60000} minutes)."
            )
        )

        try:
            # Attached: do not navigate. Chrome was told to open the sign-in
            # page itself; touching it from here before the operator signs in
            # is the poisoning step described in session_is_live().
            if not self.attached:
                self.active_page.goto(url=self.login_url)

            # A predicate on the path, not a glob over the whole URL: the
            # sign-in URL embeds the summary URL in AuthRedUrl, so "**summary**"
            # matches immediately and the wait returns before any sign-in.
            self.active_page.wait_for_url(
                url=lambda url: _is_summary_path(url=url),
                timeout=MANUAL_LOGIN_TIMEOUT_MS,
            )

        except PlaywrightTimeoutError:
            self.logger.fail(
                msg=(
                    "Timed out waiting for the portfolio summary. If the sign-in "
                    "did complete, the summary URL may have changed."
                )
            )
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

    def plaintext_login(self, username: str, password: str) -> bool:
        """
        Attempt plaintext login for Fidelity broker class
        :param username: account username
        :param password: account password
        :return: bool indicating success of login
        :rtype: bool
        """

        self.logger.highlight(msg=f"Attempting login for {username}")

        step_1, step_2 = self.login_credentials(username=username, password=password)

        if step_1 and step_2:
            self.logger.success(msg=f"Successfully logged in to {self.broker}")
            return True

        if not step_1:
            # Credentials never landed on a 2FA prompt, so there is no code to
            # submit. Previously this fell through to login_2FA("") and waited
            # out a timeout before reporting the failure.
            self.logger.fail(
                msg=f"Login failed for {username}: could not reach the 2FA step"
            )
            return False

        self.logger.highlight(msg=f"2FA required for {self.broker} account {username}")
        code: str = input("Enter 2FA code: ")

        if self.login_2FA(code=code):
            self.logger.success(msg=f"Successfully logged in to {self.broker} with 2FA")
            return True

        self.logger.fail(msg=f"Failed to log in to {self.broker} with 2FA")
        return False

    def wait_for_loading_sign(self, timeout: int = 30000) -> None:
        """
        Wait for the loading spinner to disappear on the page.
        :param timeout: Maximum time to wait
        :return: None
        """

        signs: list[Locator] = [
            self.active_page.locator(
                selector="div:nth-child(2) > .loading-spinner-mask-after"
            ).first,
            self.active_page.locator(selector=".pvd-spinner__mask-inner").first,
            self.active_page.locator(selector="pvd-loading-spinner").first,
            self.active_page.locator(
                selector=(
                    ".pvd3-spinner-root > .pvd-spinner__spinner > "
                    ".pvd-spinner__visual > div > .pvd-spinner__mask-inner"
                )
            ).first,
        ]

        for sign in signs:
            sign.wait_for(timeout=timeout, state="hidden")

    def login_credentials(self, username: str, password: str) -> tuple[bool, bool]:
        """
        Attempt plaintext login for Fidelity broker class
        :param username: account username
        :param password: account password
        :return: bool indicating success of login
        """

        try:
            # Go to login page
            self.active_page.goto(url=self.login_url)
            self.active_page.wait_for_timeout(timeout=5000)
            self.active_page.goto(url=self.login_url)

            # Login page
            self.active_page.get_by_label(text="Username", exact=True).click()
            self.active_page.get_by_label(text="Username", exact=True).fill(
                value=username
            )
            self.active_page.get_by_label(text="Password", exact=True).click()
            self.active_page.get_by_label(text="Password", exact=True).fill(
                value=password
            )
            self.active_page.get_by_role(role="button", name="Log in").click()

            # Wait for loading spinner to disappear
            self.wait_for_loading_sign()
            self.active_page.wait_for_timeout(timeout=1000)
            self.wait_for_loading_sign()

            if "summary" in self.active_page.url:
                return True, True

            # A refused sign-in also lands under /signin, so rule that out
            # before treating the page as the 2FA step.
            if self.page_was_refused():
                self.capture_page(reason="sign-in-refused")
                self.logger.fail(
                    msg=(
                        "Fidelity refused the sign-in and served its generic "
                        "error page ('we can't complete this action right now'). "
                        "This is not a 2FA prompt and not a stale selector: the "
                        "site rejected the automated session. Check the "
                        "credentials by signing in manually first."
                    )
                )
                return False, False

            # Check for 2FA page after login attempt
            if "signin" in self.active_page.url:
                self.wait_for_loading_sign()
                widget: Locator = self.active_page.locator(
                    selector="#dom-widget div"
                ).first
                widget.wait_for(timeout=5000, state="visible")

                # Check for app push notification page
                if self.active_page.get_by_role(
                    role="link", name="Try another way"
                ).is_visible():
                    self.remember_this_device()

                    # Try to get code via text message
                    self.active_page.get_by_role(
                        role="link", name="Try another way"
                    ).click(timeout=SHORT_TIMEOUT_MS)

                # Press the Text me button
                text_me: Locator = self.active_page.get_by_role(
                    role="button", name="Text me the code"
                )

                if not text_me.count():
                    self.capture_page(reason="no-text-me-button")
                    raise RuntimeError(
                        "Reached the 2FA page but found no 'Text me the code' "
                        "button; the markup has probably changed."
                    )

                text_me.click(timeout=SHORT_TIMEOUT_MS)
                self.active_page.get_by_placeholder(text="XXXXXX").click(
                    timeout=SHORT_TIMEOUT_MS
                )

                return True, False

            # Can't get to summary page or login page.
            self.capture_page(reason="unexpected-page")
            raise RuntimeError(f"Landed on an unexpected page: {self.active_page.url}")

        except PlaywrightTimeoutError:
            self.logger.fail(
                msg=f"Timed out during login for {username}; capturing the page."
            )
            self.capture_page(reason="login-timeout")
            return False, False

        except PlaywrightError as e:
            if browser_was_closed(error=e):
                # Typically the operator closed the headed browser window.
                self.logger.fail(
                    msg="Browser was closed before the login flow finished."
                )
                return False, False

            self.logger.fail(msg=f"Browser error during login: {e}")
            self.capture_page(reason="login-error")
            return False, False

        except RuntimeError as e:
            self.logger.fail(msg=f"Login could not continue: {e}")
            return False, False

    def remember_this_device(self) -> bool:
        """
        Best-effort: tick "Don't ask me again on this device" to suppress future
        OTP prompts.

        This is an optimisation, not a login requirement. It used to be a hard
        step with Playwright's 30s default timeout, so when the label text
        changed the whole login died after half a minute of waiting.
        :return: True if the box ended up checked
        """

        checkbox: Locator = self.active_page.locator(selector="label").filter(
            has_text=REMEMBER_DEVICE_TEXT
        )

        if not checkbox.count():
            self.logger.highlight(
                msg=(
                    "Could not find the 'don't ask again' checkbox; continuing "
                    "without it (2FA will be required again next time)."
                )
            )
            return False

        try:
            checkbox.check(timeout=SHORT_TIMEOUT_MS)

        except (PlaywrightTimeoutError, PlaywrightError) as e:
            self.logger.highlight(msg=f"Could not tick 'don't ask again': {e}")
            return False

        return bool(checkbox.is_checked())

    def page_was_refused(self) -> bool:
        """
        Whether the current page is Fidelity's generic "can't complete this
        action" error rather than a real step in the login flow.
        :return: True when the sign-in was refused
        """

        body: str | None = self.page_body()
        return body is not None and any(m in body for m in REFUSED_PAGE_MARKERS)

    def login_2FA(self, code: str) -> bool:
        """
        Attempt login with 2FA code for Fidelity broker class
        :param code: 2FA code
        :return: bool indicating success of login
        """

        try:
            self.active_page.get_by_placeholder(text="XXXXXX").fill(value=code)

            # Best-effort: suppress future OTP prompts. Never fail the login
            # over it -- the code has already been entered by this point.
            self.remember_this_device()

            self.active_page.get_by_role(role="button", name="Submit").click(
                timeout=SHORT_TIMEOUT_MS
            )

            self.active_page.wait_for_url(
                url=self.summary_url, timeout=SUBMIT_TIMEOUT_MS
            )

            return True

        except PlaywrightTimeoutError:
            self.logger.fail(
                msg=(
                    "Timed out after submitting the 2FA code; the code may have "
                    "been wrong or the page changed."
                )
            )
            self.capture_page(reason="2fa-timeout")
            return False

        except PlaywrightError as e:
            if browser_was_closed(error=e):
                self.logger.fail(msg="Browser was closed before 2FA completed.")
                return False

            self.logger.fail(msg=f"2FA step failed: {e}")
            self.capture_page(reason="2fa-error")
            return False

        except RuntimeError as e:
            self.logger.fail(msg=f"2FA step failed: {e}")
            return False


#: BrokerLoader reads this off the path-loaded module, so the class name is free to
#: diverge from the directory name (e.g. TSP, Schwab529Plan).
Broker = Fidelity
