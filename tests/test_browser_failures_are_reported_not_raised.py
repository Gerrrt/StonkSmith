"""A browser that goes away, or a selector that breaks, must not end in a traceback.

Two failures from real runs, and they arrive the same way: something that worked
last week stops working, deep inside Playwright, and what reaches the operator is
a stack trace naming a locator rather than a sentence naming the problem.

**The closed window.** Closing a headed browser mid-run raised a raw
`TargetClosedError`. That is not a fault -- the operator shut the window, which
is a thing people do -- so it has to be recognised and reported as what it was.
`browser_was_closed()` reads the message, which means it can also *mis*read one:
an ordinary strict-mode violation reported as "you closed the browser" would send
somebody looking at the wrong thing entirely. Both directions are checked here.

**The broken selector.** When markup moves, the only thing that makes the next
fix cheap is the page as it actually rendered, so `capture_page()` writes it out.
That markup is a signed-in brokerage session -- account numbers, balances, 2FA
context -- so it is written 0600 and never inherits a permissive umask. And
because it runs on a path that is already failing, it must swallow its own
errors: a capture that raises replaces the real failure with a second one.

`capture_page()`'s mode is checked here and nowhere else.
tests/test_written_files_are_owner_only.py covers the trace, the profile
directory, the databases and the logs, but not this file.

Both are `BrowserConnection`, exercised through Ally.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from playwright.sync_api import Error as PlaywrightError

import stonksmith.etc.browser_connection as browser_mod
from package_tree import PACKAGE


def _load_ally():
    spec = importlib.util.spec_from_file_location(
        "ally_broker_failures", PACKAGE / "brokers/ally/broker.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ally_mod = _load_ally()


class BrowserClosedDetectionTests(unittest.TestCase):
    def test_recognises_the_closed_target_message(self) -> None:
        # The exact message Playwright raised in the field.
        error = PlaywrightError(
            "Locator.click: Target page, context or browser has been closed"
        )

        self.assertTrue(browser_mod.browser_was_closed(error=error))

    def test_does_not_misread_an_ordinary_error(self) -> None:
        error = PlaywrightError("Locator.click: strict mode violation")

        self.assertFalse(browser_mod.browser_was_closed(error=error))


class CapturePageTests(unittest.TestCase):
    """capture_page() writes under ~/.stonksmith/logs by default, so these
    redirect it into a temp directory rather than touching real user state."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._logs_patch = patch.object(browser_mod, "logs_path", self.tmp / "logs")
        self._logs_patch.start()

    def tearDown(self) -> None:
        self._logs_patch.stop()
        self._tmp.cleanup()

    def _broker(self):
        broker = ally_mod.Ally()
        broker.logger = MagicMock()
        broker.page = MagicMock()
        return broker

    def test_writes_the_markup_for_selector_debugging(self) -> None:
        broker = self._broker()
        broker.active_page.content.return_value = "<html>holdings</html>"

        saved = broker.capture_page(reason="unit-test")

        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertIn("holdings", saved.read_text())
        self.assertIn("unit-test", saved.name)
        self.assertTrue(
            str(saved).startswith(str(self.tmp)), "must not write to the real home"
        )

    def test_captures_are_owner_readable_only(self) -> None:
        # Raw markup from a signed-in brokerage session: account numbers,
        # balances, sign-in context. It must not inherit a permissive umask.
        broker = self._broker()
        broker.active_page.content.return_value = "<html>account 1234</html>"

        saved = broker.capture_page(reason="perm-test")

        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)

    def test_no_browser_returns_none_instead_of_raising(self) -> None:
        broker = ally_mod.Ally()
        broker.logger = MagicMock()

        self.assertIsNone(broker.capture_page(reason="unit-test"))

    def test_capture_failure_is_swallowed(self) -> None:
        broker = self._broker()
        broker.active_page.content.side_effect = PlaywrightError("gone")

        self.assertIsNone(broker.capture_page(reason="unit-test"))
        self.assertTrue(broker.logger.fail.called)


if __name__ == "__main__":
    unittest.main()
