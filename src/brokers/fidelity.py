"""
fidelity.py: Fidelity broker class
"""

import contextlib
import json
import warnings
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError,
    sync_playwright,
)
from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api._generated import Locator
from playwright_stealth import Stealth
from requests import Response
from requests.exceptions import RequestException

from etc.connection import Connection
from etc.logger import StonkSmithAdapter
from etc.paths import logs_path, playwright_path

#: Playwright's default is 30s. These steps are optional or fast-failing, so a
#: shorter wait keeps a broken selector from stalling the whole login.
SHORT_TIMEOUT_MS = 5000

#: Label text for Fidelity's "remember this device" checkbox. Split out because
#: it is the kind of copy that changes without notice.
REMEMBER_DEVICE_TEXT = "Don't ask me again on this"

#: Landing on the summary page after submitting a code involves a redirect
#: chain, so it gets a longer budget than the individual clicks.
SUBMIT_TIMEOUT_MS = 15000

#: Playwright raises TargetClosedError when the browser goes away mid-call, but
#: that class is not exported from playwright.sync_api -- only from a private
#: module. It subclasses the public Error, so it is identified by message.
BROWSER_CLOSED_TEXT = "has been closed"

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

#: --browser values mapped to Playwright channels. "chromium" is the bundled
#: build; "chrome" is the real Google Chrome binary, which fingerprints much
#: better but has to be installed separately.
CHROMIUM_CHANNELS: dict[str, str | None] = {
    "chromium": None,
    "chrome": "chrome",
}

#: Default CDP endpoint. Chrome must be started with --remote-debugging-port,
#: and since Chrome 136 it refuses to expose that on the default profile, so a
#: dedicated --user-data-dir is required too.
CDP_DEFAULT_URL = "http://127.0.0.1:9222"

#: Where the CDP profile lives when StonkSmith prints the launch command.
CDP_PROFILE_DIRNAME = "cdp-profile"

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


def _browser_was_closed(error: Exception) -> bool:
    """
    Whether a Playwright error means the browser went away.
    :param error: The raised Playwright error
    :return: True when the target was closed
    """

    return BROWSER_CLOSED_TEXT in str(object=error)


def _restrict(path: Path) -> None:
    """
    Make a captured file owner-readable only.

    Captures are raw markup from a signed-in brokerage session and can contain
    account numbers, balances, and 2FA context. Default permissions follow the
    process umask, which is commonly world-readable.
    :param path: The file to restrict
    """

    # Best-effort: a filesystem without POSIX permissions must not turn a
    # diagnostic capture into a failure.
    with contextlib.suppress(OSError):
        path.chmod(mode=0o600)


class Fidelity(Connection):
    """
    Fidelity broker class
    """

    def __init__(self) -> None:
        super().__init__()
        self.broker = "Fidelity"
        self.name = "Fidelity"
        self.login_url = "https://digital.fidelity.com/prgw/digital/signin/retail"
        self.summary_url = "https://digital.fidelity.com/ftgw/digital/portfolio/summary"
        self.profile_path: Path = playwright_path / "Fidelity.json"
        self.trace_path: Path = playwright_path / "Fidelity_trace.zip"
        # Leave language/user-agent/vendor untouched so the session looks like
        # the real browser. playwright-stealth 2.x keeps a default *_override
        # for each of these and warns when the evasion is disabled while its
        # override is still set; the override is unused in that case, and the
        # library types it as non-Optional, so the warning is what gets muted.
        with warnings.catch_warnings():
            warnings.filterwarnings(action="ignore", message=".*_override.*")
            self.stealth = Stealth(
                navigator_languages=False,
                navigator_user_agent=False,
                navigator_vendor=False,
            )
        # The browser is NOT started here. Launching Firefox from __init__ meant
        # that even `--list-modules` spawned a browser, and the instance had no
        # owner responsible for closing it. broker_flow() starts it instead, and
        # teardown() always closes it.
        # True once a Chromium-family persistent profile is in use: that
        # directory holds the cookies, so no storage_state file is written.
        self.persistent_profile: bool = False
        # True when attached to a browser somebody else started. Nothing we did
        # not create gets closed.
        self.attached: bool = False
        self.tracing_started: bool = False
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.account_dict: dict[str, str] = {}
        self.source_account: str = ""

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

    def create_conn_obj(self) -> bool:
        """
        Create connection object for Fidelity broker class
        :return: bool
        :rtype: bool
        """

        try:
            response: Response = self.session.get(url=self.login_url, timeout=10)
            if not response.ok:
                # broker_flow() no longer logs a generic connection failure, so
                # this path has to report itself.
                self.logger.fail(
                    msg=(
                        f"{self.broker} sign-in page returned HTTP "
                        f"{response.status_code}."
                    )
                )
                return False

        except RequestException as e:
            self.logger.fail(msg=f"Could not connect to {self.broker}: {e}")
            return False

        try:
            self.getDriver()

        except Exception as e:
            self.logger.fail(msg=f"Could not start browser for {self.broker}: {e}")
            self.teardown()
            return False

        return True

    def teardown(self) -> None:
        """
        Stop tracing and shut down the browser and Playwright driver.

        Called by Connection.__call__ on every exit path. Without this, each run
        left an orphaned Firefox process and a running Playwright driver.
        """

        if self.context is not None:
            # Save before closing: cookies set during this run (including any
            # device-trust cookie) are lost otherwise.
            self.save_session()

            if self.tracing_started:
                try:
                    self.context.tracing.stop(path=str(object=self.trace_path))

                except Exception as e:
                    self.logger.fail(msg=f"Could not write Playwright trace: {e}")

            # Never close a window the operator opened.
            if not self.attached:
                self.context.close()

            self.context = None

        # A persistent context owns its browser, so self.browser is None there
        # and closing the context above already shut the browser down. An
        # attached browser belongs to the operator: disconnecting happens when
        # playwright stops, and closing it would shut their window.
        if self.browser is not None:
            if not self.attached:
                self.browser.close()

            self.browser = None

        if self.playwright is not None:
            self.playwright.stop()
            self.playwright = None

        self.page = None

    def login(self) -> bool:
        """
        Authenticate, either by reusing/obtaining a human session or by the
        normal credential flow.
        :return: True when the browser holds an authenticated session
        """

        if not getattr(self.args, "manual_login", False):
            return super().login()

        return self.manual_login()

    def on_summary_page(self) -> bool:
        """
        Whether the browser is actually on the portfolio summary.
        :return: True when the current path is the summary page
        """

        return _is_summary_path(url=self.active_page.url)

    def page_body(self) -> str | None:
        """
        The current page's markup, lowercased.
        :return: The body, or None if the page could not be read
        """

        try:
            return self.active_page.content().lower()

        except PlaywrightError:
            return None

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

        where: str = (
            "the Chrome window StonkSmith is attached to"
            if self.attached
            else "the browser window that just opened"
        )
        self.logger.highlight(
            msg=(
                f"Sign in to Fidelity in {where}, including any 2FA. StonkSmith "
                "takes over once the portfolio summary loads (waiting up to "
                f"{MANUAL_LOGIN_TIMEOUT_MS // 60000} minutes)."
            )
        )

        try:
            self.active_page.goto(url=self.login_url)
            # A predicate on the path, not a glob over the whole URL: the
            # sign-in URL embeds the summary URL in AuthRedUrl, so "**summary**"
            # matches immediately and the wait returns before any sign-in.
            self.active_page.wait_for_url(
                url=lambda url: _is_summary_path(url=url),
                timeout=MANUAL_LOGIN_TIMEOUT_MS,
            )

        except TimeoutError:
            self.logger.fail(
                msg=(
                    "Timed out waiting for the portfolio summary. If the sign-in "
                    "did complete, the summary URL may have changed."
                )
            )
            return False

        except PlaywrightError as e:
            if _browser_was_closed(error=e):
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

        else:
            self.logger.fail(msg=f"Failed to log in to {self.broker} with 2FA")
            return False

    def getDriver(self) -> None:
        """
        Initializes webdriver for all follow on functions. Create and apply
        stealth settings to playwright context wrapper. Create storage for
        cookies and data.
        """

        self.playwright = sync_playwright().start()

        # --headed exists so the login flow (and its 2FA prompt) can be
        # watched. --manual-login requires it: nobody can sign in to a window
        # they cannot see.
        headed: bool = bool(
            getattr(self.args, "headed", False)
            or getattr(self.args, "manual_login", False)
        )
        browser_name: str = str(object=getattr(self.args, "browser", "firefox"))

        if browser_name == "firefox":
            self.start_firefox(headed=headed)

        elif browser_name == "cdp":
            self.attach_over_cdp()

        elif browser_name in CHROMIUM_CHANNELS:
            self.start_chromium(headed=headed, channel=CHROMIUM_CHANNELS[browser_name])

        else:
            # argparse choices cover the CLI, but a stale config or a
            # programmatic caller deserves a message, not a KeyError.
            known: str = ", ".join(["firefox", "cdp", *CHROMIUM_CHANNELS])
            raise RuntimeError(
                f"Unknown browser {browser_name!r}; choose one of: {known}"
            )

        if self.context is None:
            raise RuntimeError(f"{browser_name} did not produce a browser context")

        try:
            self.context.tracing.start(
                name="fidelity_trace", screenshots=True, snapshots=True
            )

        except PlaywrightError as e:
            # Tracing is a diagnostic, not a requirement, and a context we
            # attached to rather than created may not support it.
            self.tracing_started = False
            self.logger.highlight(msg=f"Tracing unavailable: {e}")

        else:
            self.tracing_started = True

        self.stealth.apply_stealth_sync(self.active_page)

    def start_firefox(self, headed: bool) -> None:
        """
        Launch bundled Firefox with the saved storage state.
        :param headed: Whether to show the window
        """

        if not self.profile_path.exists():
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            with open(
                file=str(object=self.profile_path), mode="w", encoding="utf-8"
            ) as f:
                json.dump(obj={}, fp=f)

        assert self.playwright is not None
        self.browser = self.playwright.firefox.launch(
            headless=not headed,
            args=["--disable-webgl", "--disable-software-rasterizer"],
        )

        self.context = self.browser.new_context(storage_state=self.profile_path)
        self.page = self.context.new_page()

    def start_chromium(self, headed: bool, channel: str | None) -> None:
        """
        Launch a Chromium-family browser against a persistent profile
        directory.

        A persistent profile keeps cookies, history and local storage on disk
        between runs, so the browser presents as one that has been used before
        rather than a fresh install. ``channel="chrome"`` uses the real Google
        Chrome binary, which fingerprints far better than bundled Chromium --
        but it has to be installed.
        :param headed: Whether to show the window
        :param channel: Playwright browser channel, or None for bundled Chromium
        :raises RuntimeError: if the requested channel is not installed
        """

        profile_dir: Path = self.chrome_profile_dir()
        profile_dir.mkdir(parents=True, exist_ok=True)

        assert self.playwright is not None

        try:
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(object=profile_dir),
                channel=channel,
                headless=not headed,
                # The single most-checked automation tell.
                args=["--disable-blink-features=AutomationControlled"],
            )

        except PlaywrightError as e:
            # Playwright words this two ways: "Executable doesn't exist at ..."
            # for a bundled build, "Chromium distribution 'chrome' is not found
            # at ..." for a channel. Both then suggest `playwright install`.
            if not any(
                phrase in str(object=e).lower()
                for phrase in ("executable doesn't exist", "is not found at")
            ):
                raise

            # Playwright downloads browsers separately, and `playwright install
            # firefox` does not bring Chromium along. Name the exact command.
            install: str = "chrome" if channel else "chromium"
            raise RuntimeError(
                f"The {install} browser is not installed. Run "
                f"`uv run playwright install {install}` and try again"
                + (
                    ", or pass --browser chromium to use the bundled build."
                    if channel
                    else "."
                )
            ) from e

        # A persistent context owns its browser; there is no separate handle.
        self.browser = None
        self.persistent_profile = True
        self.page = (
            self.context.pages[0] if self.context.pages else self.context.new_page()
        )

    def attach_over_cdp(self) -> None:
        """
        Attach to a Chrome the operator started and signed into themselves.

        Fidelity's bot protection refuses the login page to a browser that
        automation launched, before any credentials are entered. Attaching
        instead of launching sidesteps that: the page load and the sign-in
        happen in an ordinary browsing session, and StonkSmith only connects
        afterwards to read the DOM.
        :raises RuntimeError: if nothing is listening, or no context is open
        """

        endpoint: str = str(
            object=getattr(self.args, "cdp_url", None) or CDP_DEFAULT_URL
        )

        assert self.playwright is not None

        try:
            self.browser = self.playwright.chromium.connect_over_cdp(endpoint)

        except Exception as e:
            raise RuntimeError(
                f"Nothing is listening for CDP on {endpoint}. Start Chrome with "
                f"remote debugging first:\n\n    {self.cdp_launch_command()}\n\n"
                "then sign in to Fidelity in that window and re-run."
            ) from e

        if not self.browser.contexts:
            raise RuntimeError(
                "Attached, but that Chrome has no open window. Open a tab and "
                "sign in to Fidelity, then re-run."
            )

        # Reuse the existing context: it holds the cookies from the operator's
        # sign-in. A new context would start empty and defeat the whole point.
        self.context = self.browser.contexts[0]
        self.page = (
            self.context.pages[0] if self.context.pages else self.context.new_page()
        )

        self.attached = True
        # The operator's own profile is the cookie store.
        self.persistent_profile = True

    def cdp_launch_command(self) -> str:
        """
        The command that starts Chrome with remote debugging enabled.

        Chrome 136 and later refuse --remote-debugging-port on the default
        profile, so this names a dedicated one. Signing in there once is enough:
        the profile persists.
        :return: A shell command
        """

        profile: Path = playwright_path / CDP_PROFILE_DIRNAME
        port: int = (
            urlparse(
                url=str(object=getattr(self.args, "cdp_url", None) or CDP_DEFAULT_URL)
            ).port
            or 9222
        )

        return (
            '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" '
            f"--remote-debugging-port={port} "
            f'--user-data-dir="{profile}"'
        )

    def chrome_profile_dir(self) -> Path:
        """
        Where the persistent Chromium profile lives.

        Defaults to a directory StonkSmith owns. --profile-dir can point at
        another one, including a real browser profile -- at the cost of that
        browser needing to be closed while StonkSmith runs.
        :return: The user-data directory
        """

        override = getattr(self.args, "profile_dir", None)
        if override:
            return Path(override).expanduser()

        return playwright_path / "chrome-profile"

    @property
    def active_page(self) -> Page:
        """
        The live Playwright page, guaranteed non-None.
        :return: The current page
        :raises RuntimeError: if the browser has not been started
        """

        if self.page is None:
            raise RuntimeError(
                "Browser not started: create_conn_obj() must run before login."
            )

        return self.page

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

        except TimeoutError:
            self.logger.fail(
                msg=f"Timed out during login for {username}; capturing the page."
            )
            self.capture_page(reason="login-timeout")
            return False, False

        except PlaywrightError as e:
            if _browser_was_closed(error=e):
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

        except (TimeoutError, PlaywrightError) as e:
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

    def save_session(self) -> bool:
        """
        Persist cookies and local storage so the next run is a returning
        browser rather than a brand-new one.

        The context was created from ``storage_state`` but the state was never
        written back, so every run started with an empty jar. That defeats the
        "Don't ask me again on this device" checkbox -- the trust cookie it sets
        was discarded on exit -- and makes each login look like a new device.
        :return: True if the session was written
        """

        if self.context is None:
            return False

        if self.persistent_profile:
            # Cookies already live in the profile directory. Writing
            # storage_state as well would leave a Chromium jar behind that the
            # next Firefox run would load as if it were its own.
            return True

        try:
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            self.context.storage_state(path=str(object=self.profile_path))
            # Session cookies: owner-readable only.
            _restrict(path=self.profile_path)

        except Exception as e:
            self.logger.fail(msg=f"Could not save the browser session: {e}")
            return False

        return True

    def capture_page(self, reason: str) -> Path | None:
        """
        Save the current page so selectors can be fixed against real markup.

        Writes the HTML, and a screenshot when possible, from wherever the run
        got stuck -- including inside the login flow, which a module-level
        diagnostic cannot reach because modules only run *after* a successful
        login. modules/fidelity_module.py calls this too when a scrape finds
        nothing.
        :param reason: Short slug describing why the capture happened
        :return: Path to the saved HTML, or None if nothing could be captured
        """

        if self.page is None:
            return None

        stamp: str = datetime.now(tz=UTC).strftime(format="%Y%m%d-%H%M%S")
        target: Path = logs_path / f"fidelity-{reason}-{stamp}.html"

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(data=self.active_page.content(), encoding="utf-8")
            _restrict(path=target)

        except Exception as e:
            self.logger.fail(msg=f"Could not capture the page: {e}")
            return None

        self.logger.fail(msg=f"Saved the page markup to {target}")

        try:
            shot: Path = target.with_suffix(suffix=".png")
            self.active_page.screenshot(path=str(object=shot))
            _restrict(path=shot)
            self.logger.fail(msg=f"Saved a screenshot to {shot}")

        except Exception:
            # A screenshot is a nice-to-have; the HTML is what matters.
            pass

        return target

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

        except TimeoutError:
            self.logger.fail(
                msg=(
                    "Timed out after submitting the 2FA code; the code may have "
                    "been wrong or the page changed."
                )
            )
            self.capture_page(reason="2fa-timeout")
            return False

        except PlaywrightError as e:
            if _browser_was_closed(error=e):
                self.logger.fail(msg="Browser was closed before 2FA completed.")
                return False

            self.logger.fail(msg=f"2FA step failed: {e}")
            self.capture_page(reason="2fa-error")
            return False

        except RuntimeError as e:
            self.logger.fail(msg=f"2FA step failed: {e}")
            return False
