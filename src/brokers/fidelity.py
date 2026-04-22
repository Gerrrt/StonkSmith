"""
fidelity.py: Fidelity broker class
"""

import json
import traceback
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
from playwright_stealth import StealthConfig, stealth_sync
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
        self.stealth_config = StealthConfig(
            navigator_languages=False,
            navigator_user_agent=False,
            navigator_vendor=False,
        )
        self.getDriver()
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
            return response.ok

        except RequestException as e:
            self.logger.fail(msg=f"Could not connect to {self.broker}: {e}")
            return False

    def plaintext_login(self, username: str, password: str) -> bool:
        """
        Attempt plaintext login for Fidelity broker class
        :param username: account username
        :param password: account password
        :return: bool indicating success of login
        :rtype: bool
        """

        code = ""
        self.logger.highlight(msg=f"Attempting login for {username}")

        step_1, step_2 = self.login_credentials(username=username, password=password)

        if step_1 and step_2:
            self.logger.success(msg=f"Successfully logged in to {self.broker}")
            return True

        elif step_1 and not step_2:
            self.logger.highlight(
                msg=f"2FA required for {self.broker} account {username}"
            )
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

        self.playwright: Playwright = sync_playwright().start()

        if not self.profile_path.exists():
            self.profile_path.touch()
            with open(
                file=str(object=self.profile_path), mode="w", encoding="utf-8"
            ) as f:
                json.dump(obj={}, fp=f)

        self.browser: Browser = self.playwright.firefox.launch(
            headless=True,
            args=["--disable-webgl", "--disable-software-rasterizer"],
        )

        self.context: BrowserContext = self.browser.new_context(
            storage_state=self.profile_path
        )

        self.context.tracing.start(
            name="fidelity_trace", screenshots=True, snapshots=True
        )

        self.page: Page = self.context.new_page()
        stealth_sync(page=self.page, config=self.stealth_config)

    def wait_for_loading_sign(self, timeout: int = 30000) -> None:
        """
        Wait for the loading spinner to disappear on the page.
        :param timeout: Maximum time to wait
        :return: None
        """

        signs: list[Locator] = [
            self.page.locator(
                selector="div:nth-child(2) > .loading-spinner-mask-after"
            ).first,
            self.page.locator(selector=".pvd-spinner__mask-inner").first,
            self.page.locator(selector="pvd-loading-spinner").first,
            self.page.locator(
                selector=".pvd3-spinner-root > .pvd-spinner__spinner > .pvd-spinner__visual > div > .pvd-spinner__mask-inner"
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
            self.page.goto(url=self.login_url)
            self.page.wait_for_timeout(timeout=5000)
            self.page.goto(url=self.login_url)

            # Login page
            self.page.get_by_label(text="Username", exact=True).click()
            self.page.get_by_label(text="Username", exact=True).fill(value=username)
            self.page.get_by_label(text="Password", exact=True).click()
            self.page.get_by_label(text="Password", exact=True).fill(value=password)
            self.page.get_by_role(role="button", name="Log in").click()

            # Wait for loading spinner to disappear
            self.wait_for_loading_sign()
            self.page.wait_for_timeout(timeout=1000)
            self.wait_for_loading_sign()

            if "summary" in self.page.url:
                return True, True

            # Check for 2FA page after login attempt
            if "signin" in self.page.url:
                self.wait_for_loading_sign()
                widget: Locator = self.page.locator(selector="#dom-widget div").first
                widget.wait_for(timeout=5000, state="visible")

                # Check for app push notification page
                if self.page.get_by_role(
                    role="link", name="Try another way"
                ).is_visible():
                    self.page.locator(selector="label").filter(
                        has_text="Don't ask me again on this"
                    ).check()
                    if (
                        not self.page.locator(selector="label")
                        .filter(has_text="Don't ask me again on this")
                        .is_checked()
                    ):
                        raise RuntimeError("Cannot check that box")

                    # Try to get code via text message
                    self.page.get_by_role(role="link", name="Try another way").click()

                # Press the Text me button
                self.page.get_by_role(role="button", name="Text me the code").click()
                self.page.get_by_placeholder(text="XXXXXX").click()

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
            self.page.get_by_placeholder(text="XXXXXX").fill(value=code)

            # Prevent future OTP requirements.
            self.page.locator(selector="label").filter(
                has_text="Don't ask me again on this"
            ).check()
            if (
                not self.page.locator(selector="label")
                .filter(has_text="Don't ask me again on this")
                .is_checked()
            ):
                raise RuntimeError("Cannot check that box")

            self.page.get_by_role(role="button", name="Submit").click()

            self.page.wait_for_url(url=self.summary_url, timeout=5000)

            return True

        except TimeoutError:
            print("Timeout waiting for login page to load.")
            traceback.print_exc()
            return False

        except RuntimeError as e:
            print(f"Error occurred: {e}")
            traceback.print_exc()
            return False
