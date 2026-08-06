"""Fidelity can be driven by Firefox or a persistent Chromium profile.

Fidelity's bot protection refuses to render the login form to Playwright's
bundled Firefox -- the block happens on a plain page load, before any
credentials, so a human at the keyboard cannot get past it either. A persistent
profile in a Chromium-family browser presents as one that has been used before,
and `channel="chrome"` uses the real Google Chrome binary.
"""

import importlib.util
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

from playwright.sync_api import Error as PlaywrightError

import etc.browser_connection as browser_mod

SRC = Path(__file__).resolve().parents[1] / "src"


def _load_fidelity():
    spec = importlib.util.spec_from_file_location(
        "fidelity_broker_browser", SRC / "brokers/fidelity/broker.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fidelity_mod = _load_fidelity()


class BrowserSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _broker(self, **args):
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.stealth = MagicMock()
        broker.profile_path = self.tmp / "Fidelity.json"
        defaults = {
            "browser": "firefox",
            "headed": False,
            "manual_login": False,
            "profile_dir": str(self.tmp / "profile"),
        }
        broker.args = Namespace(**{**defaults, **args})
        return broker

    def _launch(self, broker, playwright):
        with patch.object(
            browser_mod,
            "sync_playwright",
            return_value=MagicMock(start=lambda: playwright),
        ):
            broker.getDriver()

    def test_firefox_is_the_default(self) -> None:
        broker = self._broker()
        playwright = MagicMock()

        self._launch(broker, playwright)

        playwright.firefox.launch.assert_called_once()
        playwright.chromium.launch_persistent_context.assert_not_called()

    def test_chromium_uses_a_persistent_profile_and_no_channel(self) -> None:
        broker = self._broker(browser="chromium")
        playwright = MagicMock()

        self._launch(broker, playwright)

        kwargs = playwright.chromium.launch_persistent_context.call_args.kwargs
        self.assertIsNone(kwargs["channel"])
        self.assertTrue(kwargs["user_data_dir"].endswith("profile"))
        # The single most-checked automation tell.
        self.assertIn("--disable-blink-features=AutomationControlled", kwargs["args"])

    def test_chrome_requests_the_real_binary(self) -> None:
        broker = self._broker(browser="chrome")
        playwright = MagicMock()

        self._launch(broker, playwright)

        kwargs = playwright.chromium.launch_persistent_context.call_args.kwargs
        self.assertEqual(kwargs["channel"], "chrome")

    def test_persistent_context_owns_its_browser(self) -> None:
        # There is no separate browser handle to close in this mode.
        broker = self._broker(browser="chromium")
        playwright = MagicMock()

        self._launch(broker, playwright)

        self.assertIsNone(broker.browser)
        self.assertIsNotNone(broker.context)

    def test_manual_login_still_forces_a_visible_window(self) -> None:
        broker = self._broker(browser="chromium", manual_login=True)
        playwright = MagicMock()

        self._launch(broker, playwright)

        kwargs = playwright.chromium.launch_persistent_context.call_args.kwargs
        self.assertFalse(kwargs["headless"])

    def test_profile_dir_defaults_under_stonksmith(self) -> None:
        broker = self._broker(browser="chromium")
        broker.args.profile_dir = None

        self.assertTrue(str(broker.chrome_profile_dir()).endswith("chrome-profile"))


class SessionPersistenceModeTests(unittest.TestCase):
    """A persistent profile is the cookie store; do not also write a jar."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _broker(self, persistent: bool):
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.context = MagicMock()
        broker.profile_path = self.tmp / "Fidelity.json"
        broker.persistent_profile = persistent
        return broker

    def test_firefox_mode_writes_the_storage_state(self) -> None:
        broker = self._broker(persistent=False)

        self.assertTrue(broker.save_session())
        broker.context.storage_state.assert_called_once()

    def test_persistent_mode_writes_no_storage_state(self) -> None:
        # Otherwise the next Firefox run loads a Chromium cookie jar.
        broker = self._broker(persistent=True)

        self.assertTrue(broker.save_session())
        broker.context.storage_state.assert_not_called()
        self.assertFalse(broker.profile_path.exists())


class UnknownBrowserTests(unittest.TestCase):
    def test_unknown_browser_reports_the_valid_choices(self) -> None:
        # argparse guards the CLI; a stale config must not KeyError.
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.stealth = MagicMock()
        broker.args = Namespace(
            browser="netscape", headed=False, manual_login=False, profile_dir=None
        )

        with (
            patch.object(browser_mod, "sync_playwright", return_value=MagicMock()),
            self.assertRaises(RuntimeError) as caught,
        ):
            broker.getDriver()

        message = str(caught.exception)
        self.assertIn("netscape", message)
        self.assertIn("firefox", message)
        self.assertIn("chrome", message)


class MissingBrowserGuidanceTests(unittest.TestCase):
    """Playwright downloads browsers separately; say which command to run."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _broker_that_fails_with(self, message: str, browser: str):
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.stealth = MagicMock()
        # profile_dir must never be None here: start_chromium() creates the
        # directory before launching, and the default lives under ~/.stonksmith.
        broker.args = Namespace(
            browser=browser,
            headed=False,
            manual_login=False,
            profile_dir=str(self.tmp / "profile"),
        )
        playwright = MagicMock()
        playwright.chromium.launch_persistent_context.side_effect = PlaywrightError(
            message
        )
        return broker, playwright

    def _run(self, broker, playwright):
        with patch.object(
            browser_mod,
            "sync_playwright",
            return_value=MagicMock(start=lambda: playwright),
        ):
            broker.getDriver()

    def test_missing_bundled_chromium_names_the_command(self) -> None:
        broker, playwright = self._broker_that_fails_with(
            "Executable doesn't exist at /path/headless_shell", "chromium"
        )

        with self.assertRaises(RuntimeError) as caught:
            self._run(broker, playwright)

        self.assertIn("playwright install chromium", str(caught.exception))

    def test_missing_chrome_channel_names_the_command(self) -> None:
        # Playwright words this case differently.
        broker, playwright = self._broker_that_fails_with(
            "Chromium distribution 'chrome' is not found at /Applications/...",
            "chrome",
        )

        with self.assertRaises(RuntimeError) as caught:
            self._run(broker, playwright)

        message = str(caught.exception)
        self.assertIn("playwright install chrome", message)
        self.assertIn("--browser chromium", message, "offer the fallback")

    def test_unrelated_launch_errors_are_not_swallowed(self) -> None:
        broker, playwright = self._broker_that_fails_with(
            "Target page, context or browser has been closed", "chromium"
        )

        with self.assertRaises(PlaywrightError):
            self._run(broker, playwright)


if __name__ == "__main__":
    unittest.main()
