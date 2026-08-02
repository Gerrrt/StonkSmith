"""Fidelity refuses sign-ins with a page that looks like the 2FA step.

From a live run: the page under /signin, titled "Log in to Fidelity", carried
only "Sorry, we can't complete this action right now." No OTP field, no "Text me
the code", no username field. The old code saw "signin" in the URL, assumed 2FA,
and reported "the markup has probably changed" -- which sent debugging in
entirely the wrong direction.

The fixture below mirrors the structure of that real capture. It is written by
hand: the real one is 3MB of markup from a signed-in session.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from playwright.sync_api import Error as PlaywrightError

SRC = Path(__file__).resolve().parents[1] / "src"

REFUSED_PAGE = """
<html><head><title>Log in to Fidelity</title></head><body>
  <div id="dom-widget"><div>
    <div class="ccl-title-root">
      Sorry, we can't complete this action right now. Please try again.
    </div>
    <a class="pvd-link__link" id="dom-sys-err-go-to-login-button">Go back to login</a>
  </div></div>
</body></html>
"""

TWO_FACTOR_PAGE = """
<html><head><title>Log in to Fidelity</title></head><body>
  <div id="dom-widget"><div>
    <button>Text me the code</button>
    <input placeholder="XXXXXX" />
    <label>Don't ask me again on this device</label>
  </div></div>
</body></html>
"""


def _load_fidelity():
    spec = importlib.util.spec_from_file_location(
        "fidelity_broker_refused", SRC / "brokers/fidelity.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fidelity_mod = _load_fidelity()


class _IsolatedBrokerTest(unittest.TestCase):
    """Keep every filesystem path these tests touch inside a temp directory.

    save_session() and capture_page() write under ~/.stonksmith by default, so
    without this the suite mutates real user state and fails wherever $HOME is
    not writable.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # capture_page() reads this at call time from the module namespace.
        self._logs_patch = patch.object(fidelity_mod, "logs_path", self.tmp / "logs")
        self._logs_patch.start()

    def tearDown(self) -> None:
        self._logs_patch.stop()
        self._tmp.cleanup()

    def broker(self, content: str | None = None):
        broker = fidelity_mod.Fidelity()
        broker.logger = MagicMock()
        broker.page = MagicMock()
        broker.profile_path = self.tmp / "playwright" / "Fidelity.json"
        if content is not None:
            broker.active_page.content.return_value = content
        return broker


class RefusedPageDetectionTests(_IsolatedBrokerTest):
    def test_refused_page_is_recognised(self) -> None:
        self.assertTrue(self.broker(REFUSED_PAGE).page_was_refused())

    def test_genuine_2fa_page_is_not_misread(self) -> None:
        self.assertFalse(self.broker(TWO_FACTOR_PAGE).page_was_refused())

    def test_unreadable_page_is_not_treated_as_refused(self) -> None:
        broker = self.broker()
        broker.active_page.content.side_effect = PlaywrightError("gone")

        self.assertFalse(broker.page_was_refused())


class SaveSessionTests(_IsolatedBrokerTest):
    def test_storage_state_is_written(self) -> None:
        broker = self.broker()
        broker.context = MagicMock()

        broker.save_session()

        broker.context.storage_state.assert_called_once()
        written = broker.context.storage_state.call_args.kwargs["path"]
        self.assertIn("Fidelity.json", written)
        self.assertTrue(
            written.startswith(str(self.tmp)), "must not write to the real home"
        )

    def test_no_context_is_a_no_op(self) -> None:
        broker = self.broker()
        broker.context = None

        broker.save_session()  # must not raise

    def test_failure_to_save_is_reported_not_raised(self) -> None:
        broker = self.broker()
        broker.context = MagicMock()
        broker.context.storage_state.side_effect = PlaywrightError("nope")

        broker.save_session()

        self.assertTrue(broker.logger.fail.called)

    def test_teardown_saves_before_closing(self) -> None:
        # Cookies set during the run -- including any device-trust cookie -- are
        # lost if the context closes first.
        broker = self.broker()
        context = MagicMock()
        broker.context = context
        order: list[str] = []
        context.storage_state.side_effect = lambda **kw: order.append("save")
        context.close.side_effect = lambda: order.append("close")

        broker.teardown()

        self.assertEqual(order, ["save", "close"])

    def test_nothing_is_written_outside_the_temp_directory(self) -> None:
        broker = self.broker()
        broker.context = MagicMock()

        broker.save_session()

        # The only directory created belongs to the temp tree.
        self.assertTrue((self.tmp / "playwright").is_dir())


if __name__ == "__main__":
    unittest.main()
