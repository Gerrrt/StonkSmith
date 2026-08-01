"""
fidelity.py: Fidelity broker class
"""

import json
import traceback
import warnings
from pathlib import Path

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError,
    sync_playwright,
)
from playwright.sync_api._generated import Locator

# Imported from the submodule, not the package root: playwright_stealth's
# __init__ re-exports Stealth implicitly, which strict re-export resolution
# treats as private (it resolves on macOS but not on Linux CI).
from playwright_stealth.stealth import Stealth
from requests import Response
from requests.exceptions import RequestException

from etc.connection import Connection
from etc.logger import StonkSmithAdapter
from etc.paths import playwright_path


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
                    self.active_page.locator(selector="label").filter(
                        has_text="Don't ask me again on this"
                    ).check()
                    if (
                        not self.active_page.locator(selector="label")
                        .filter(has_text="Don't ask me again on this")
                        .is_checked()
                    ):
                        raise RuntimeError("Cannot check that box")

                    # Try to get code via text message
                    self.active_page.get_by_role(
                        role="link", name="Try another way"
                    ).click()

                # Press the Text me button
                self.active_page.get_by_role(
                    role="button", name="Text me the code"
                ).click()
                self.active_page.get_by_placeholder(text="XXXXXX").click()

                return True, False

            # Can't get to summary page or login page.
            raise RuntimeError("Cannot get to login page.")

        except TimeoutError:
            print("Timeout waiting for login page to load.")
            traceback.print_exc()
            return False, False

        except RuntimeError as e:
            print(f"Error occurred: {e}")
            traceback.print_exc()
            return False, False

    def login_2FA(self, code: str) -> bool:
        """
        Attempt login with 2FA code for Fidelity broker class
        :param code: 2FA code
        :return: bool indicating success of login
        """

        try:
            self.active_page.get_by_placeholder(text="XXXXXX").fill(value=code)

            # Prevent future OTP requirements.
            self.active_page.locator(selector="label").filter(
                has_text="Don't ask me again on this"
            ).check()
            if (
                not self.active_page.locator(selector="label")
                .filter(has_text="Don't ask me again on this")
                .is_checked()
            ):
                raise RuntimeError("Cannot check that box")

            self.active_page.get_by_role(role="button", name="Submit").click()

            self.active_page.wait_for_url(url=self.summary_url, timeout=5000)

            return True

        except TimeoutError:
            print("Timeout waiting for login page to load.")
            traceback.print_exc()
            return False

        except RuntimeError as e:
            print(f"Error occurred: {e}")
            traceback.print_exc()
            return False
