import sys
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_BROKER_FILE = (
    Path(__file__).resolve().parents[1] / "src" / "brokers" / "schwab529plan.py"
)
_SPEC = spec_from_file_location("brokers_schwab529plan_file", _BROKER_FILE)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Unable to load Schwab529plan broker module for tests")
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
Schwab529plan = _MODULE.Schwab529plan


class _StubLogger:
    def __init__(self) -> None:
        self.debug_messages: list[str] = []
        self.success_messages: list[str] = []
        self.fail_messages: list[str] = []

    def debug(self, msg: str) -> None:
        self.debug_messages.append(msg)

    def success(self, msg: str) -> None:
        self.success_messages.append(msg)

    def fail(self, msg: str) -> None:
        self.fail_messages.append(msg)

    def highlight(self, msg: str) -> None:
        pass


class _StubResponse:
    def __init__(self, *, text: str, url: str, ok: bool = True) -> None:
        self.text = text
        self.url = url
        self.ok = ok


class _StubSession:
    def __init__(
        self,
        *,
        get_responses: list[_StubResponse],
        post_response: _StubResponse,
    ) -> None:
        self._get_responses = get_responses
        self._get_index = 0
        self._post_response = post_response
        self.post_payload: dict[str, Any] | None = None

    def get(self, url: str, timeout: int = 10) -> _StubResponse:
        response = self._get_responses[self._get_index]
        self._get_index += 1
        return response

    def post(
        self,
        url: str,
        data: dict[str, Any],
        timeout: int = 10,
    ) -> _StubResponse:
        self.post_payload = data
        return self._post_response


class Schwab529LoginDetectionTests(unittest.TestCase):
    def _landing_page_html(self) -> str:
        return (
            "<html><body><form>"
            '<input name="struts.token.name" value="tok_name" />'
            '<input name="token" value="tok_value" />'
            '<input name="tplcb" value="tplcb_value" />'
            "</form></body></html>"
        )

    def test_plaintext_login_success_after_follow_up_get(self) -> None:
        broker = Schwab529plan()
        broker.logger = _StubLogger()  # type: ignore[assignment]

        post_response = _StubResponse(
            text="redirected",
            url="https://www.schwab529plan.com/swatpl/aggregator/overview/viewAggrOverview.cs",
            ok=True,
        )
        login_response = _StubResponse(
            text='<div id="txHistDiv"></div>',
            url="https://www.schwab529plan.com/swatpl/aggregator/overview/viewAggrOverview.cs",
            ok=True,
        )
        broker.session = _StubSession(  # type: ignore[assignment]
            get_responses=[
                _StubResponse(
                    text=self._landing_page_html(),
                    url=broker.login_url,
                    ok=True,
                ),
                login_response,
            ],
            post_response=post_response,
        )

        result = broker.plaintext_login("alice", "s3cr3t")

        self.assertTrue(result)
        assert isinstance(broker.session, _StubSession)
        assert broker.session.post_payload is not None
        self.assertEqual(broker.session.post_payload["struts.token.name"], "tok_name")
        self.assertEqual(broker.session.post_payload["token"], "tok_value")
        self.assertEqual(broker.session.post_payload["tplcb"], "tplcb_value")
        self.assertEqual(broker.session.post_payload["username"], "alice")
        self.assertEqual(broker.session.post_payload["passcode"], "s3cr3t")

    def test_plaintext_login_fails_when_follow_up_is_login_page(self) -> None:
        broker = Schwab529plan()
        broker.logger = _StubLogger()  # type: ignore[assignment]

        post_response = _StubResponse(
            text="still login",
            url=broker.login_url,
            ok=True,
        )
        login_response = _StubResponse(
            text="""<input name="struts.token.name" value="tok_name" />""",
            url=broker.login_url,
            ok=True,
        )
        broker.session = _StubSession(  # type: ignore[assignment]
            get_responses=[
                _StubResponse(
                    text=self._landing_page_html(),
                    url=broker.login_url,
                    ok=True,
                ),
                login_response,
            ],
            post_response=post_response,
        )

        result = broker.plaintext_login("alice", "bad-password")

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
