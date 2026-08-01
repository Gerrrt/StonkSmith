"""Regression tests for the Fidelity browser lifecycle and login flow.

Two bugs lived here: __init__ launched Firefox that nothing ever closed, and a
total credential failure still walked into the 2FA path with an empty code.
"""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock

SRC = Path(__file__).resolve().parents[1] / "src"


def _load_fidelity():
    spec = importlib.util.spec_from_file_location(
        "fidelity_broker", SRC / "brokers/fidelity.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fidelity_mod = _load_fidelity()


class FidelityLifecycleTests(unittest.TestCase):
    def test_construction_does_not_start_a_browser(self) -> None:
        broker = fidelity_mod.Fidelity()

        self.assertIsNone(broker.playwright)
        self.assertIsNone(broker.browser)
        self.assertIsNone(broker.page)

    def test_active_page_refuses_before_the_browser_starts(self) -> None:
        broker = fidelity_mod.Fidelity()

        with self.assertRaises(RuntimeError):
            _ = broker.active_page

    def test_teardown_releases_every_handle(self) -> None:
        broker = fidelity_mod.Fidelity()
        playwright, browser, context = MagicMock(), MagicMock(), MagicMock()
        broker.playwright, broker.browser = playwright, browser
        broker.context, broker.page = context, MagicMock()

        broker.teardown()

        self.assertTrue(context.tracing.stop.called)
        self.assertTrue(context.close.called)
        self.assertTrue(browser.close.called)
        self.assertTrue(playwright.stop.called)
        self.assertIsNone(broker.browser)
        self.assertIsNone(broker.playwright)
        self.assertIsNone(broker.page)

    def test_teardown_is_idempotent(self) -> None:
        broker = fidelity_mod.Fidelity()
        broker.teardown()
        broker.teardown()

    def test_teardown_runs_even_when_broker_flow_raises(self) -> None:
        broker = fidelity_mod.Fidelity()
        broker.teardown = MagicMock()
        broker.broker_flow = MagicMock(side_effect=RuntimeError("boom"))
        broker.logger = MagicMock()

        broker(args=MagicMock(), db=MagicMock(), host=None)

        broker.teardown.assert_called_once()


class FidelityLoginFlowTests(unittest.TestCase):
    def test_total_credential_failure_skips_the_2fa_attempt(self) -> None:
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.login_credentials = MagicMock(return_value=(False, False))
        broker.login_2FA = MagicMock(return_value=True)

        result = broker.plaintext_login(username="u", password="p")

        self.assertFalse(result)
        broker.login_2FA.assert_not_called()

    def test_full_success_skips_the_2fa_attempt(self) -> None:
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.login_credentials = MagicMock(return_value=(True, True))
        broker.login_2FA = MagicMock(return_value=True)

        self.assertTrue(broker.plaintext_login(username="u", password="p"))
        broker.login_2FA.assert_not_called()


if __name__ == "__main__":
    unittest.main()
