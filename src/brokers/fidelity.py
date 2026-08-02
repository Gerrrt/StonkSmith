"""
fidelity.py: Fidelity broker class
"""

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path

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


def _browser_was_closed(error: Exception) -> bool:
    """
    Whether a Playwright error means the browser went away.
    :param error: The raised Playwright error
    :return: True when the target was closed
    """

    return BROWSER_CLOSED_TEXT in str(object=error)


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
            try:
                self.context.tracing.stop(path=str(object=self.trace_path))

            except Exception as e:
                self.logger.fail(msg=f"Could not write Playwright trace: {e}")

            self.context.close()
            self.context = None

        if self.browser is not None:
            self.browser.close()
            self.browser = None

        if self.playwright is not None:
            self.playwright.stop()
            self.playwright = None

        self.page = None

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

        if not self.profile_path.exists():
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            with open(
                file=str(object=self.profile_path), mode="w", encoding="utf-8"
            ) as f:
                json.dump(obj={}, fp=f)

        # --headed exists so the login flow (and its 2FA prompt) can be watched.
        headed: bool = bool(getattr(self.args, "headed", False))

        self.browser = self.playwright.firefox.launch(
            headless=not headed,
            args=["--disable-webgl", "--disable-software-rasterizer"],
        )

        self.context = self.browser.new_context(storage_state=self.profile_path)

        self.context.tracing.start(
            name="fidelity_trace", screenshots=True, snapshots=True
        )

        self.page = self.context.new_page()
        self.stealth.apply_stealth_sync(self.page)

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

    def capture_page(self, reason: str) -> Path | None:
        """
        Save the current page so selectors can be fixed against real markup.

        The module-level DEBUG_DUMP option is useless for login problems,
        because modules only run *after* a successful login. This writes the
        HTML (and a screenshot when possible) from inside the login flow.
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

        except Exception as e:
            self.logger.fail(msg=f"Could not capture the page: {e}")
            return None

        self.logger.fail(msg=f"Saved the page markup to {target}")

        try:
            shot: Path = target.with_suffix(suffix=".png")
            self.active_page.screenshot(path=str(object=shot))
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
