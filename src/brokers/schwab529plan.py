"""
schwab529plan.py: Schwab529plan broker class
"""

from bs4 import BeautifulSoup
from bs4.element import AttributeValueList
from requests import Response
from requests.exceptions import RequestException

from etc.connection import Connection
from etc.logger import StonkSmithAdapter
from helpers.schwab529plan import get_value


class Schwab529plan(Connection):
    """
    Schwab529 broker class
    """

    def __init__(self) -> None:
        super().__init__()
        self.broker = "Schwab529plan"
        self.name = "Schwab529plan"
        self.login_url = "https://www.schwab529plan.com/swatpl/aggregator/sessionCreate/collectAggrCredentials.cs"

    def broker_logger(self) -> None:
        """
        Set up logger for Schwab529Plan broker class
        :return:
        :rtype:
        """

        self.logger = StonkSmithAdapter(
            extra={
                "broker": "Schwab529plan",
                "username": self.username,
            },
            logger=self.logger.logger,
        )

    def create_conn_obj(self) -> bool:
        """
        Create connection object for Schwab529plan broker class
        :return:
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
        Attempt plaintext login for Schwab529plan broker class
        :param username:
        :param password:
        :return: bool
        """

        self.logger.highlight(msg=f"Attempting login for {username}")

        try:
            landing: Response = self.session.get(url=self.login_url, timeout=10)

            html = BeautifulSoup(markup=landing.text, features="html.parser")

            struts_token_name: str | AttributeValueList | None = get_value(
                html=html, name="struts.token.name"
            )
            token: str | AttributeValueList | None = get_value(html=html, name="token")
            tplcb: str | AttributeValueList | None = get_value(html=html, name="tplcb")

            if not struts_token_name or not token:
                self.logger.fail(
                    msg=f"Login failed for {username}: missing expected login form fields"
                )
                return False

            payload: dict[str, str | AttributeValueList | None] = {
                "struts.token.name": struts_token_name,
                "token": token,
                "tplcb": tplcb,
                "username": username,
                "passcode": password,
            }

            post_response: Response = self.session.post(
                url=self.login_url,
                data=payload,
                timeout=10,
            )

            # Match the known working flow: follow the resulting URL and verify
            # that we landed on an authenticated page, not just an HTTP 200.
            login_response: Response = self.session.get(
                url=str(object=post_response.url), timeout=10
            )

            if self._is_authenticated_response(response=login_response):
                self.logger.success(msg=f"Login successful for {username}")
                return True

            self.logger.fail(
                msg=(
                    f"Login failed for {username}: authentication did not reach "
                    f"dashboard (url={login_response.url})"
                )
            )
            return False

        except RequestException as e:
            self.logger.fail(msg=f"Login failed for {username}: {e}")
            return False

    def _is_authenticated_response(self, response: Response) -> bool:
        """Detect whether a response represents an authenticated Schwab529 session."""

        if not response.ok:
            return False

        response_url = str(object=response.url)
        response_url_lc: str = response_url.lower()

        if "viewaggroverview.cs" in response_url_lc:
            return True

        if "collectaggrcredentials.cs" in response_url_lc:
            return False

        body_lc: str = response.text.lower()
        has_known_dashboard_marker: bool = "txhistdiv" in body_lc
        has_known_login_marker: bool = "struts.token.name" in body_lc

        return has_known_dashboard_marker and not has_known_login_marker
