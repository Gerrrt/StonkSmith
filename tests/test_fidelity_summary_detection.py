"""Being on the summary page must be judged by the URL path, not a substring.

From a live run: an unauthenticated request to the portfolio summary bounces to

    /prgw/digital/signin/retail?AuthRedUrl=...%2Fportfolio%2Fsummary

which contains the literal "summary". The old check tested that substring
against the whole URL, so a signed-out session looked authenticated,
`manual_login()` skipped the sign-in entirely, and the module scraped the login
page. The captured "summary" markup turned out to be the login form.
"""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock

SRC = Path(__file__).resolve().parents[1] / "src"

# The real redirect observed in the wild.
LOGIN_URL = (
    "https://digital.fidelity.com/prgw/digital/signin/retail"
    "?AuthRedUrl=https%3A%2F%2Fdigital.fidelity.com%2Fftgw%2Fdigital"
    "%2Fportfolio%2Fsummary"
)
SUMMARY_URL = "https://digital.fidelity.com/ftgw/digital/portfolio/summary"

LOGIN_BODY = (
    "<html><signin-pi-login-template><pvdccl-form/></signin-pi-login-template></html>"
)
SUMMARY_BODY = "<html><div>holdings</div></html>"


def _load_fidelity():
    spec = importlib.util.spec_from_file_location(
        "fidelity_broker_summary", SRC / "brokers/fidelity.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fidelity_mod = _load_fidelity()


def _broker(url: str, body: str):
    broker = fidelity_mod.Fidelity()
    broker.logger = MagicMock()
    broker.page = MagicMock()
    broker.active_page.url = url
    broker.active_page.content.return_value = body
    return broker


class SummaryPageDetectionTests(unittest.TestCase):
    def test_login_redirect_is_not_the_summary_page(self) -> None:
        # The literal substring is present; the path is not.
        self.assertIn("summary", LOGIN_URL)
        self.assertFalse(_broker(LOGIN_URL, LOGIN_BODY).on_summary_page())

    def test_real_summary_url_is_the_summary_page(self) -> None:
        self.assertTrue(_broker(SUMMARY_URL, SUMMARY_BODY).on_summary_page())


class SessionIsLiveTests(unittest.TestCase):
    def test_signed_out_session_is_not_live(self) -> None:
        broker = _broker(LOGIN_URL, LOGIN_BODY)

        self.assertFalse(broker.session_is_live())

    def test_signed_in_session_is_live(self) -> None:
        broker = _broker(SUMMARY_URL, SUMMARY_BODY)

        self.assertTrue(broker.session_is_live())

    def test_sign_in_form_on_the_summary_path_is_not_live(self) -> None:
        # Belt and braces: if a redirect ever preserved the path, the form
        # being on screen still means we are signed out.
        broker = _broker(SUMMARY_URL, LOGIN_BODY)

        self.assertFalse(broker.session_is_live())

    def test_refusal_page_is_not_live(self) -> None:
        broker = _broker(
            SUMMARY_URL, "<html>can't complete this action right now</html>"
        )

        self.assertFalse(broker.session_is_live())


class ManualLoginWaitTests(unittest.TestCase):
    def test_wait_predicate_rejects_the_login_url(self) -> None:
        # wait_for_url gets a path predicate; a "**summary**" glob would have
        # matched the login URL and returned before any sign-in happened.
        broker = _broker(LOGIN_URL, LOGIN_BODY)
        broker.context = MagicMock()

        broker.manual_login()

        predicate = broker.active_page.wait_for_url.call_args.kwargs["url"]
        self.assertFalse(predicate(LOGIN_URL), "must keep waiting on the login page")
        self.assertTrue(predicate(SUMMARY_URL), "must finish on the summary page")


if __name__ == "__main__":
    unittest.main()
