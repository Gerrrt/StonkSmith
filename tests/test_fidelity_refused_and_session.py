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
import unittest
from pathlib import Path
from unittest.mock import MagicMock

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


def _broker(content: str | None = None):
    broker = fidelity_mod.Fidelity()
    broker.logger = MagicMock()
    broker.page = MagicMock()
    if content is not None:
        broker.active_page.content.return_value = content
    return broker


class RefusedPageDetectionTests(unittest.TestCase):
    def test_refused_page_is_recognised(self) -> None:
        self.assertTrue(_broker(REFUSED_PAGE).page_was_refused())

    def test_genuine_2fa_page_is_not_misread(self) -> None:
        self.assertFalse(_broker(TWO_FACTOR_PAGE).page_was_refused())

    def test_unreadable_page_is_not_treated_as_refused(self) -> None:
        broker = _broker()
        broker.active_page.content.side_effect = PlaywrightError("gone")

        self.assertFalse(broker.page_was_refused())


class SaveSessionTests(unittest.TestCase):
    def test_storage_state_is_written(self) -> None:
        broker = _broker()
        broker.context = MagicMock()

        broker.save_session()

        broker.context.storage_state.assert_called_once()
        self.assertIn(
            "Fidelity.json", broker.context.storage_state.call_args.kwargs["path"]
        )

    def test_no_context_is_a_no_op(self) -> None:
        broker = _broker()
        broker.context = None

        broker.save_session()  # must not raise

    def test_failure_to_save_is_reported_not_raised(self) -> None:
        broker = _broker()
        broker.context = MagicMock()
        broker.context.storage_state.side_effect = PlaywrightError("nope")

        broker.save_session()

        self.assertTrue(broker.logger.fail.called)

    def test_teardown_saves_before_closing(self) -> None:
        # Cookies set during the run -- including any device-trust cookie -- are
        # lost if the context closes first.
        broker = _broker()
        context = MagicMock()
        broker.context = context
        order: list[str] = []
        context.storage_state.side_effect = lambda **kw: order.append("save")
        context.close.side_effect = lambda: order.append("close")

        broker.teardown()

        self.assertEqual(order, ["save", "close"])


if __name__ == "__main__":
    unittest.main()
