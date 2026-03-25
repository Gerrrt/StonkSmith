"""
Module to login and scrape data from https://www.schwab529plan.com
"""

import requests
from bs4 import BeautifulSoup


class Scraper:
    def __init__(self, login_url):
        self.login_url = login_url

    def start_session(self, username, password):
        """
        Create a session, grab Apache Struts token value, and construct
        payload with all appropriate fields.
        :param username:
        :param password:
        :return:
        """
        with requests.session() as session:
            request = session.get(self.login_url).text
            html = BeautifulSoup(request, "html.parser")
            name = html.find("input", {"name": "struts.token.name"}).attrs["value"]
            token = html.find("input", {"name": "token"}).attrs["value"]
            tplcb = html.find("input", {"name": "tplcb"}).attrs["value"]

            payload = {
                "struts.token.name": name,
                "token": token,
                "tplcb": tplcb,
                "username": username,
                "passcode": password,
            }

            return self.login_and_scrape(session, payload)

    def login_and_scrape(self, session, payload):
        """
        Send the log in request, and scrape the account page.
        :param session:
        :param payload:
        :return:
        """
        login_response = session.post(self.login_url, data=payload)

        if login_response.ok:
            page_response = session.get(login_response.url)
            return page_response
        else:
            return "Login failed."
