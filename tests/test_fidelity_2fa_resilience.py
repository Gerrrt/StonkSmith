"""The 2FA flow must survive changed markup and a closed browser.

Both from real runs. A missing "don't ask me again" checkbox killed the whole
login after Playwright's 30s default timeout, and closing the headed browser
produced a raw TargetClosedError traceback.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

SRC = Path(__file__).resolve().parents[1] / "src"


def _load_fidelity():
    spec = importlib.util.spec_from_file_location(
        "fidelity_broker_2fa", SRC / "brokers/fidelity/broker.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fidelity_mod = _load_fidelity()


class RememberDeviceTests(unittest.TestCase):
    def _broker(self):
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.page = MagicMock()
        return broker

    def test_missing_checkbox_does_not_fail_the_login(self) -> None:
        broker = self._broker()
        checkbox = broker.active_page.locator.return_value.filter.return_value
        checkbox.count.return_value = 0

        # The point: it returns rather than raising, so login continues.
        self.assertFalse(broker.remember_this_device())
        self.assertTrue(broker.logger.highlight.called)

    def test_uncheckable_checkbox_does_not_fail_the_login(self) -> None:
        broker = self._broker()
        checkbox = broker.active_page.locator.return_value.filter.return_value
        checkbox.count.return_value = 1
        checkbox.check.side_effect = PlaywrightTimeout("Timeout 5000ms exceeded")

        self.assertFalse(broker.remember_this_device())

    def test_checkbox_uses_the_short_timeout_not_playwrights_default(self) -> None:
        broker = self._broker()
        checkbox = broker.active_page.locator.return_value.filter.return_value
        checkbox.count.return_value = 1
        checkbox.is_checked.return_value = True

        self.assertTrue(broker.remember_this_device())
        self.assertEqual(
            checkbox.check.call_args.kwargs["timeout"],
            fidelity_mod.SHORT_TIMEOUT_MS,
        )


class BrowserClosedDetectionTests(unittest.TestCase):
    def test_recognises_the_closed_target_message(self) -> None:
        # The exact message Playwright raised in the field.
        error = PlaywrightError(
            "Locator.click: Target page, context or browser has been closed"
        )

        self.assertTrue(fidelity_mod._browser_was_closed(error=error))

    def test_does_not_misread_an_ordinary_error(self) -> None:
        error = PlaywrightError("Locator.click: strict mode violation")

        self.assertFalse(fidelity_mod._browser_was_closed(error=error))


class CapturePageTests(unittest.TestCase):
    """capture_page() writes under ~/.stonksmith/logs by default, so these
    redirect it into a temp directory rather than touching real user state."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._logs_patch = patch.object(fidelity_mod, "logs_path", self.tmp / "logs")
        self._logs_patch.start()

    def tearDown(self) -> None:
        self._logs_patch.stop()
        self._tmp.cleanup()

    def _broker(self):
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.page = MagicMock()
        return broker

    def test_writes_the_markup_for_selector_debugging(self) -> None:
        broker = self._broker()
        broker.active_page.content.return_value = "<html>2fa</html>"

        saved = broker.capture_page(reason="unit-test")

        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertIn("2fa", saved.read_text())
        self.assertIn("unit-test", saved.name)
        self.assertTrue(
            str(saved).startswith(str(self.tmp)), "must not write to the real home"
        )

    def test_captures_are_owner_readable_only(self) -> None:
        # Raw markup from a signed-in brokerage session: account numbers,
        # balances, 2FA context. It must not inherit a permissive umask.
        broker = self._broker()
        broker.active_page.content.return_value = "<html>account 1234</html>"

        saved = broker.capture_page(reason="perm-test")

        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)

    def test_no_browser_returns_none_instead_of_raising(self) -> None:
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()

        self.assertIsNone(broker.capture_page(reason="unit-test"))

    def test_capture_failure_is_swallowed(self) -> None:
        broker = self._broker()
        broker.active_page.content.side_effect = PlaywrightError("gone")

        self.assertIsNone(broker.capture_page(reason="unit-test"))
        self.assertTrue(broker.logger.fail.called)


if __name__ == "__main__":
    unittest.main()
