"""Regression tests for the Fidelity browser lifecycle and login flow.

Two bugs lived here: __init__ launched Firefox that nothing ever closed, and a
total credential failure still walked into the 2FA path with an empty code.
"""

import importlib.util
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        # Tracing only stops if it started; getDriver() records that.
        broker.tracing_started = True

        broker.teardown()

        self.assertTrue(context.tracing.stop.called)
        self.assertTrue(context.close.called)
        self.assertTrue(browser.close.called)
        self.assertTrue(playwright.stop.called)
        self.assertIsNone(broker.browser)
        self.assertIsNone(broker.playwright)
        self.assertIsNone(broker.page)

    def test_teardown_skips_tracing_it_never_started(self) -> None:
        # Tracing can be unavailable on a context we attached to rather than
        # created; stopping it then would raise.
        broker = fidelity_mod.Fidelity()
        context = MagicMock()
        broker.context = context
        broker.tracing_started = False

        broker.teardown()

        context.tracing.stop.assert_not_called()

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


class FidelityHeadedFlagTests(unittest.TestCase):
    """--headed is defined in broker_args; it must reach the browser launch."""

    def _launch_kwargs(self, args: object) -> dict:
        broker = fidelity_mod.Fidelity()
        broker.args = args
        broker.profile_path = MagicMock()
        broker.profile_path.exists.return_value = True

        # Stub the stealth application: this test is about the launch kwargs,
        # and running the real implementation against a MagicMock page couples
        # it to playwright-stealth internals (it warned about a duplicate
        # application) for no benefit.
        broker.stealth = MagicMock()

        playwright = MagicMock()
        with patch.object(
            fidelity_mod,
            "sync_playwright",
            return_value=MagicMock(start=lambda: playwright),
        ):
            broker.getDriver()

        return playwright.firefox.launch.call_args.kwargs

    def test_default_is_headless(self) -> None:
        self.assertTrue(self._launch_kwargs(args=Namespace())["headless"])

    def test_headed_flag_launches_headed(self) -> None:
        kwargs = self._launch_kwargs(args=Namespace(headed=True))
        self.assertFalse(kwargs["headless"], "--headed must launch a visible browser")


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
