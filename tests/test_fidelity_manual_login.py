"""Manual-assist sign-in for Fidelity.

Fidelity fronts its login with Akamai Bot Manager and ThreatMetrix -- the saved
cookie jar from a real run contains _abck, bm_sz, ak_bmsc, __cf_bm, thx_guid and
tmx_guid -- and refuses a scripted sign-in before the form renders. The operator
signs in themselves; StonkSmith reuses the resulting session.
"""

import importlib.util
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

SRC = Path(__file__).resolve().parents[1] / "src"


def _load_fidelity():
    spec = importlib.util.spec_from_file_location(
        "fidelity_broker_manual", SRC / "brokers/fidelity/broker.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fidelity_mod = _load_fidelity()


class ManualLoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._logs_patch = patch.object(fidelity_mod, "logs_path", self.tmp / "logs")
        self._logs_patch.start()

    def tearDown(self) -> None:
        self._logs_patch.stop()
        self._tmp.cleanup()

    def _broker(self, **args):
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.page = MagicMock()
        broker.context = MagicMock()
        broker.profile_path = self.tmp / "Fidelity.json"
        broker.args = Namespace(manual_login=True, headed=False, **args)
        return broker

    def test_live_session_skips_the_sign_in_entirely(self) -> None:
        broker = self._broker()
        broker.active_page.url = "https://digital.fidelity.com/.../portfolio/summary"
        broker.active_page.content.return_value = "<html>holdings</html>"

        self.assertTrue(broker.manual_login())
        # No navigation to the login page was needed.
        broker.active_page.wait_for_url.assert_not_called()

    def test_stale_session_waits_for_the_operator(self) -> None:
        broker = self._broker()
        # First goto lands back on sign-in, so a human sign-in is required.
        broker.active_page.url = "https://digital.fidelity.com/prgw/digital/signin"
        broker.active_page.content.return_value = "<html>login</html>"

        self.assertTrue(broker.manual_login())

        broker.active_page.wait_for_url.assert_called_once()
        self.assertEqual(
            broker.active_page.wait_for_url.call_args.kwargs["timeout"],
            fidelity_mod.MANUAL_LOGIN_TIMEOUT_MS,
        )
        # The session is saved so later runs reuse it.
        broker.context.storage_state.assert_called()

    def test_failed_save_does_not_promise_session_reuse(self) -> None:
        # save_session() reports its own failure and carries on, so the caller
        # must not follow it with "later runs reuse it".
        broker = self._broker()
        broker.active_page.url = "https://digital.fidelity.com/prgw/digital/signin"
        broker.active_page.content.return_value = "<html>login</html>"
        broker.context.storage_state.side_effect = PlaywrightError("disk full")

        self.assertTrue(broker.manual_login())

        promised = " ".join(str(c) for c in broker.logger.success.call_args_list)
        self.assertNotIn("reuse", promised)
        warned = " ".join(str(c) for c in broker.logger.highlight.call_args_list)
        self.assertIn("could not be saved", warned)

    def test_goto_timeout_is_not_a_live_session_and_does_not_raise(self) -> None:
        # Playwright's TimeoutError subclasses its Error, so the existing
        # handler covers it; this pins that behaviour.
        broker = self._broker()
        broker.active_page.goto.side_effect = PlaywrightTimeout("Timeout 30000ms")

        self.assertFalse(broker.session_is_live())

    def test_operator_never_finishing_is_reported(self) -> None:
        broker = self._broker()
        broker.active_page.url = "https://digital.fidelity.com/prgw/digital/signin"
        broker.active_page.content.return_value = "<html>login</html>"
        broker.active_page.wait_for_url.side_effect = PlaywrightTimeout("timeout")

        self.assertFalse(broker.manual_login())
        self.assertTrue(broker.logger.fail.called)

    def test_closing_the_browser_is_reported_plainly(self) -> None:
        broker = self._broker()
        broker.active_page.url = "https://digital.fidelity.com/prgw/digital/signin"
        broker.active_page.content.return_value = "<html>login</html>"
        broker.active_page.wait_for_url.side_effect = PlaywrightError(
            "Target page, context or browser has been closed"
        )

        self.assertFalse(broker.manual_login())
        reported = " ".join(str(c) for c in broker.logger.fail.call_args_list)
        self.assertIn("closed", reported.lower())

    def test_refused_page_does_not_count_as_a_live_session(self) -> None:
        broker = self._broker()
        broker.active_page.url = "https://digital.fidelity.com/.../summary"
        broker.active_page.content.return_value = (
            "<html>can't complete this action right now</html>"
        )

        self.assertFalse(broker.session_is_live())


class ManualLoginRoutingTests(unittest.TestCase):
    def _broker(self, manual: bool):
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.args = Namespace(manual_login=manual, headed=False)
        return broker

    def test_manual_flag_routes_to_manual_login(self) -> None:
        broker = self._broker(manual=True)
        broker.manual_login = MagicMock(return_value=True)

        self.assertTrue(broker.login())
        broker.manual_login.assert_called_once()

    def test_without_the_flag_the_normal_credential_flow_runs(self) -> None:
        broker = self._broker(manual=False)
        broker.manual_login = MagicMock(return_value=True)
        broker.args.cred_id = []
        broker.args.username = []
        broker.args.password = []

        # No credentials, so the base implementation reports and returns False.
        self.assertFalse(broker.login())
        broker.manual_login.assert_not_called()


class HeadedImplicationTests(unittest.TestCase):
    def test_manual_login_forces_a_visible_browser(self) -> None:
        # Nobody can sign in to a window they cannot see.
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.args = Namespace(manual_login=True, headed=False)
        broker.profile_path = MagicMock()
        broker.profile_path.exists.return_value = True
        broker.stealth = MagicMock()

        playwright = MagicMock()
        with patch.object(
            fidelity_mod,
            "sync_playwright",
            return_value=MagicMock(start=lambda: playwright),
        ):
            broker.getDriver()

        self.assertFalse(playwright.firefox.launch.call_args.kwargs["headless"])


if __name__ == "__main__":
    unittest.main()
