"""Attached mode must not drive the page before the operator signs in.

Observed in the field: each time StonkSmith navigated an attached, signed-out
browser -- `session_is_live()` going to the summary, or `manual_login()` going
to the sign-in page -- Akamai flagged `_abck` for that Chrome profile. Every
later attempt in the same profile was then refused, *including the operator's
own manual sign-in*, which made the failure look like a site-wide block rather
than something StonkSmith had caused.

Navigation after sign-in is fine; the scrape's own goto works. Only
unauthenticated navigation is poison.
"""

import importlib.util
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock

SRC = Path(__file__).resolve().parents[1] / "src"

LOGIN_URL = "https://digital.fidelity.com/prgw/digital/signin/retail"
SUMMARY_URL = "https://digital.fidelity.com/ftgw/digital/portfolio/summary"


def _load_fidelity():
    spec = importlib.util.spec_from_file_location(
        "fidelity_no_nav", SRC / "brokers/fidelity.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fidelity_mod = _load_fidelity()


def _broker(*, attached: bool, url: str, body: str = "<html>ok</html>"):
    broker = fidelity_mod.Fidelity()
    broker.logger = MagicMock()
    broker.page = MagicMock()
    broker.context = MagicMock()
    broker.attached = attached
    broker.args = Namespace(manual_login=True, cred_id=[], username=[], password=[])
    broker.active_page.url = url
    broker.active_page.content.return_value = body
    return broker


class SessionCheckTests(unittest.TestCase):
    def test_attached_and_signed_out_never_navigates(self) -> None:
        broker = _broker(attached=True, url=LOGIN_URL)

        self.assertFalse(broker.session_is_live())
        broker.active_page.goto.assert_not_called()

    def test_attached_and_on_the_summary_needs_no_navigation(self) -> None:
        broker = _broker(attached=True, url=SUMMARY_URL)

        self.assertTrue(broker.session_is_live())
        broker.active_page.goto.assert_not_called()

    def test_launched_mode_still_navigates(self) -> None:
        # We own that browser, so probing it costs nothing.
        broker = _broker(attached=False, url=SUMMARY_URL)

        broker.session_is_live()
        broker.active_page.goto.assert_called_once()


class ManualLoginTests(unittest.TestCase):
    def test_attached_waits_without_opening_the_login_page(self) -> None:
        broker = _broker(attached=True, url=LOGIN_URL)

        broker.manual_login()

        broker.active_page.goto.assert_not_called()
        broker.active_page.wait_for_url.assert_called_once()

    def test_launched_mode_still_opens_the_login_page(self) -> None:
        broker = _broker(attached=False, url=LOGIN_URL)
        # Not live, so it proceeds to the sign-in wait.
        broker.session_is_live = MagicMock(return_value=False)

        broker.manual_login()

        broker.active_page.goto.assert_called_once_with(url=broker.login_url)

    def test_attached_instructions_say_it_will_not_touch_the_page(self) -> None:
        broker = _broker(attached=True, url=LOGIN_URL)

        broker.manual_login()

        said = " ".join(str(c) for c in broker.logger.highlight.call_args_list)
        self.assertIn("will not touch", said)


class LaunchCommandTests(unittest.TestCase):
    def test_chrome_opens_the_sign_in_page_itself(self) -> None:
        # Chrome navigating from its own command line is not automation-driven
        # navigation, so it does not trip the sensor.
        broker = fidelity_mod.Fidelity()
        broker.args = Namespace(cdp_url=None)

        command = broker.cdp_launch_command()

        self.assertIn("--remote-debugging-port=9222", command)
        self.assertIn("--user-data-dir=", command)
        self.assertIn(broker.login_url, command)


if __name__ == "__main__":
    unittest.main()
