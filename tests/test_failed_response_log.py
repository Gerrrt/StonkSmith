"""A saved page says what rendered; it cannot say why nothing did.

An Angular app that is signed out, blocked by a bot filter, or pointed at an
account it cannot see all render the same empty shell. The difference lives in
the XHRs behind it, which never reach the markup -- so a capture taken at the
moment a session check fails looks identical in all three cases, and picking
between them means guessing.

Recording the refused requests alongside the capture is what makes those three
outcomes say different things. What the recording owes its reader:

* no query strings, because these lines are meant to be pasted into an issue
  and Ally's carry tokens and account ids
* one line per endpoint, because a blocked page retries the same call dozens of
  times and the retries would push every other endpoint off the end
* an explicit line when *nothing* failed, since "the page asked for nothing"
  points at routing rather than refusal, and silence would read as the
  diagnostic never having been wired up
"""

import unittest
from unittest.mock import MagicMock

import etc.browser_connection as browser_mod


class FakeResponse:
    """The two fields the recorder reads off a Playwright response."""

    def __init__(self, status: int, url: str) -> None:
        self.status = status
        self.url = url


def _connection() -> browser_mod.BrowserConnection:
    """A BrowserConnection with a stub page, ready to record."""
    conn = browser_mod.BrowserConnection()
    conn.page = MagicMock()
    conn.logger = MagicMock()
    return conn


def _emit(conn: browser_mod.BrowserConnection, *responses: FakeResponse) -> None:
    """Feed responses to whatever watch_failed_responses() registered."""
    handler = conn.page.on.call_args[0][1]  # type: ignore[union-attr]
    for response in responses:
        handler(response)


class FailedResponseRecording(unittest.TestCase):
    """What gets recorded, and in what form."""

    def test_successes_are_not_recorded(self) -> None:
        """Only 4xx and 5xx. A 302 is how the session gets handed around."""
        conn = _connection()
        conn.watch_failed_responses()
        _emit(
            conn,
            FakeResponse(status=200, url="https://live.invest.ally.com/api/accounts"),
            FakeResponse(status=302, url="https://live.invest.ally.com/api/session"),
        )

        self.assertEqual(conn.failed_responses, [])

    def test_query_strings_are_dropped(self) -> None:
        """The path identifies the endpoint; the query carries the secrets."""
        conn = _connection()
        conn.watch_failed_responses()
        _emit(
            conn,
            FakeResponse(
                status=403,
                url="https://live.invest.ally.com/api/holdings?jwt=SECRET&acct=12345",
            ),
        )

        self.assertEqual(
            conn.failed_responses,
            ["403 https://live.invest.ally.com/api/holdings"],
        )
        self.assertNotIn("SECRET", conn.failed_responses[0])

    def test_one_endpoint_retried_is_one_line(self) -> None:
        """A blocked call retries; twenty retries are still one fact."""
        conn = _connection()
        conn.watch_failed_responses()
        _emit(
            conn,
            *[
                FakeResponse(
                    status=403, url=f"https://live.invest.ally.com/api/holdings?try={n}"
                )
                for n in range(20)
            ],
        )

        self.assertEqual(len(conn.failed_responses), 1)

    def test_differing_statuses_are_kept_apart(self) -> None:
        """401 and 403 on one endpoint are different diagnoses."""
        conn = _connection()
        conn.watch_failed_responses()
        _emit(
            conn,
            FakeResponse(status=401, url="https://live.invest.ally.com/api/holdings"),
            FakeResponse(status=403, url="https://live.invest.ally.com/api/holdings"),
        )

        self.assertEqual(len(conn.failed_responses), 2)

    def test_watching_is_installed_once(self) -> None:
        """Re-arming on a second check would double every recorded line."""
        conn = _connection()
        conn.watch_failed_responses()
        conn.watch_failed_responses()

        self.assertEqual(conn.page.on.call_count, 1)  # type: ignore[union-attr]

    def test_no_page_means_no_listener(self) -> None:
        """Recording before the browser starts must not raise."""
        conn = browser_mod.BrowserConnection()
        conn.page = None
        conn.watch_failed_responses()

        self.assertFalse(conn.watching_responses)


class FailedResponseReporting(unittest.TestCase):
    """What reaches the operator once a capture happens."""

    def _messages(self, conn: browser_mod.BrowserConnection) -> str:
        return "\n".join(
            str(call.kwargs.get("msg", ""))
            for call in conn.logger.fail.call_args_list  # type: ignore[union-attr]
        )

    def test_nothing_failed_is_stated_not_implied(self) -> None:
        """A page that asked for nothing is a different bug from one refused."""
        conn = _connection()
        conn.watch_failed_responses()
        conn.report_failed_responses()

        self.assertIn("No request failed", self._messages(conn))

    def test_silent_when_never_armed(self) -> None:
        """Captures from flows that do not record must not claim anything."""
        conn = _connection()
        conn.report_failed_responses()

        self.assertEqual(conn.logger.fail.call_count, 0)  # type: ignore[union-attr]

    def test_failures_are_listed(self) -> None:
        """The status and endpoint are the whole point."""
        conn = _connection()
        conn.watch_failed_responses()
        _emit(
            conn,
            FakeResponse(status=403, url="https://live.invest.ally.com/api/holdings"),
        )
        conn.report_failed_responses()
        messages = self._messages(conn)

        self.assertIn("403", messages)
        self.assertIn("/api/holdings", messages)

    def test_long_lists_are_capped_and_say_so(self) -> None:
        """Truncation that does not announce itself reads as the whole story."""
        conn = _connection()
        conn.watch_failed_responses()
        _emit(
            conn,
            *[
                FakeResponse(status=403, url=f"https://live.invest.ally.com/api/{n}")
                for n in range(browser_mod.FAILED_RESPONSE_LIMIT + 5)
            ],
        )
        conn.report_failed_responses()

        self.assertIn("and 5 more", self._messages(conn))


if __name__ == "__main__":
    unittest.main()
