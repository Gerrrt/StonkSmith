"""A saved page says what rendered; it cannot say why nothing did.

An Angular app that is signed out, blocked by a bot filter, or pointed at an
account it cannot see all render the same empty shell. The difference lives in
the XHRs behind it, which never reach the markup -- so a capture taken at the
moment a session check fails looks identical in all three cases, and picking
between them means guessing.

Recording the failures was the first half, and on its own it was not an answer:
a live Ally run reported "No request failed while the page was loading" against
a page that had rendered nothing. Zero failures is consistent with two opposite
bugs -- data calls that come back 200-and-empty, which is a session the site
accepts but treats as nobody, and no data calls at all, which is a router or a
guard that never ran. So the calls themselves are recorded too.

What the recording owes its reader:

* no query strings and no long path segments, because these lines are meant to
  be pasted into an issue and Ally's URLs carry the jwt and the account id
* one line per endpoint, because a blocked page retries the same call dozens of
  times and the retries would push every other endpoint off the end
* an explicit line for each half when it is empty, since "nothing was refused"
  and "nothing was asked for" are both findings, and silence would read as the
  diagnostic never having been wired up
"""

import unittest
from unittest.mock import MagicMock

import etc.browser_connection as browser_mod


class FakeRequest:
    """The one field the recorder reads off a Playwright request."""

    def __init__(self, resource_type: str) -> None:
        self.resource_type = resource_type


class FakeResponse:
    """The fields the recorder reads off a Playwright response."""

    def __init__(
        self,
        status: int,
        url: str,
        resource_type: str = "script",
        content_length: str | None = None,
        content_type: str | None = None,
        body: bytes = b"",
    ) -> None:
        self.status = status
        self.url = url
        self.request = FakeRequest(resource_type=resource_type)
        self._content_length = content_length
        self._content_type = content_type
        self._body = body

    def header_value(self, name: str) -> str | None:
        if name == "content-length":
            return self._content_length
        if name == "content-type":
            return self._content_type
        return None

    def body(self) -> bytes:
        return self._body


def _refused(payload: bytes, content_type: str = "application/json") -> FakeResponse:
    """A 401 carrying a JSON error body."""
    return FakeResponse(
        status=401,
        url="https://secure.ally.com/acs/customers/authenticate/api/v2/auth/login",
        resource_type="xhr",
        content_length=str(object=len(payload)),
        content_type=content_type,
        body=payload,
    )


class DeadResponse(FakeResponse):
    """A response whose page went away before the header could be read."""

    def header_value(self, name: str) -> str | None:
        raise RuntimeError("Target page, context or browser has been closed")


def _xhr(status: int, url: str, content_length: str | None = None) -> FakeResponse:
    """A data call, as opposed to part of the shell arriving."""
    return FakeResponse(
        status=status, url=url, resource_type="xhr", content_length=content_length
    )


def _connection() -> browser_mod.BrowserConnection:
    """A BrowserConnection with a stub page, ready to record."""
    conn = browser_mod.BrowserConnection()
    conn.page = MagicMock()
    conn.logger = MagicMock()
    return conn


def _emit(conn: browser_mod.BrowserConnection, *responses: FakeResponse) -> None:
    """Feed responses to whatever watch_responses() registered."""
    handler = conn.page.on.call_args[0][1]  # type: ignore[union-attr]
    for response in responses:
        handler(response)


def _messages(conn: browser_mod.BrowserConnection) -> str:
    return "\n".join(
        str(call.kwargs.get("msg", ""))
        for call in conn.logger.fail.call_args_list  # type: ignore[union-attr]
    )


class EndpointRedaction(unittest.TestCase):
    """What is stripped before anything is written down."""

    def test_the_query_string_goes(self) -> None:
        """Ally's query string carries the jwt."""
        self.assertEqual(
            browser_mod.endpoint_of(
                url="https://live.invest.ally.com/api/holdings?jwt=SECRET"
            ),
            "https://live.invest.ally.com/api/holdings",
        )

    def test_long_path_segments_are_masked(self) -> None:
        """The per-account URL carries a 64-character id in the path."""
        account = "a" * 64

        self.assertEqual(
            browser_mod.endpoint_of(
                url=f"https://live.invest.ally.com/accounts/{account}/holdings"
            ),
            "https://live.invest.ally.com/accounts/<id>/holdings",
        )

    def test_route_names_survive(self) -> None:
        """Masking everything would leave nothing to diagnose from."""
        self.assertEqual(
            browser_mod.endpoint_of(
                url="https://live.invest.ally.com/accounts/holdings-balances"
            ),
            "https://live.invest.ally.com/accounts/holdings-balances",
        )


class ResponseSize(unittest.TestCase):
    """A 200 is not evidence the call returned anything."""

    def test_the_size_is_appended(self) -> None:
        """Four hundred bytes against forty is the whole diagnosis."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            _xhr(
                status=200,
                url="https://live.invest.ally.com/api/account/get",
                content_length="412",
            ),
        )

        self.assertEqual(
            conn.data_responses,
            ["200 https://live.invest.ally.com/api/account/get (412 bytes)"],
        )

    def test_a_missing_header_is_left_off(self) -> None:
        """Chunked responses carry no length; the line is still worth having."""
        conn = _connection()
        conn.watch_responses()
        _emit(conn, _xhr(status=200, url="https://live.invest.ally.com/api/settings"))

        self.assertEqual(
            conn.data_responses, ["200 https://live.invest.ally.com/api/settings"]
        )

    def test_surrounding_whitespace_is_tolerated(self) -> None:
        """A header is allowed to carry it; isdigit() would reject the value."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            _xhr(
                status=200,
                url="https://live.invest.ally.com/api/account/get",
                content_length="  412  ",
            ),
        )

        self.assertEqual(
            conn.data_responses,
            ["200 https://live.invest.ally.com/api/account/get (412 bytes)"],
        )

    def test_a_nonsense_header_is_left_off(self) -> None:
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            _xhr(
                status=200,
                url="https://live.invest.ally.com/api/settings",
                content_length="not-a-number",
            ),
        )

        self.assertEqual(
            conn.data_responses, ["200 https://live.invest.ally.com/api/settings"]
        )

    def test_a_dead_page_does_not_take_the_log_down(self) -> None:
        """Reading a header off a closed page must not raise out of a handler."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            DeadResponse(
                status=200,
                url="https://live.invest.ally.com/api/settings",
                resource_type="xhr",
            ),
        )

        self.assertEqual(
            conn.data_responses, ["200 https://live.invest.ally.com/api/settings"]
        )

    def test_the_same_endpoint_at_two_sizes_is_two_lines(self) -> None:
        """An empty answer and a full one are the comparison being made."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            _xhr(
                status=200,
                url="https://live.invest.ally.com/api/account/get",
                content_length="40",
            ),
            _xhr(
                status=200,
                url="https://live.invest.ally.com/api/account/get",
                content_length="4000",
            ),
        )

        self.assertEqual(len(conn.data_responses), 2)


class FailureRecording(unittest.TestCase):
    """What lands in the refused list."""

    def test_successes_are_not_recorded(self) -> None:
        """Only 4xx and 5xx. A 302 is how the session gets handed around."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            _xhr(status=200, url="https://live.invest.ally.com/api/accounts"),
            _xhr(status=302, url="https://live.invest.ally.com/api/session"),
        )

        self.assertEqual(conn.failed_responses, [])

    def test_the_secret_does_not_survive(self) -> None:
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            _xhr(
                status=403,
                url="https://live.invest.ally.com/api/holdings?jwt=SECRET&acct=12345",
            ),
        )

        self.assertEqual(
            conn.failed_responses, ["403 https://live.invest.ally.com/api/holdings"]
        )

    def test_one_endpoint_retried_is_one_line(self) -> None:
        """A blocked call retries; twenty retries are still one fact."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            *[
                _xhr(status=403, url=f"https://live.invest.ally.com/api/hold?try={n}")
                for n in range(20)
            ],
        )

        self.assertEqual(len(conn.failed_responses), 1)

    def test_differing_statuses_are_kept_apart(self) -> None:
        """401 and 403 on one endpoint are different diagnoses."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            _xhr(status=401, url="https://live.invest.ally.com/api/holdings"),
            _xhr(status=403, url="https://live.invest.ally.com/api/holdings"),
        )

        self.assertEqual(len(conn.failed_responses), 2)


class DataCallRecording(unittest.TestCase):
    """What lands in the data-call list, which zero failures made necessary."""

    def test_the_shell_is_not_a_data_call(self) -> None:
        """Scripts and images arriving say nothing about the app asking."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            FakeResponse(
                status=200,
                url="https://live.invest.ally.com/main.js",
                resource_type="script",
            ),
        )

        self.assertEqual(conn.data_responses, [])

    def test_a_successful_data_call_is_recorded(self) -> None:
        """The 200s are the point here: a refused call was never the issue."""
        conn = _connection()
        conn.watch_responses()
        _emit(conn, _xhr(status=200, url="https://live.invest.ally.com/api/accounts"))

        self.assertEqual(
            conn.data_responses, ["200 https://live.invest.ally.com/api/accounts"]
        )

    def test_fetch_counts_as_well_as_xhr(self) -> None:
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            FakeResponse(
                status=200,
                url="https://live.invest.ally.com/api/v2/accounts",
                resource_type="fetch",
            ),
        )

        self.assertEqual(len(conn.data_responses), 1)

    def test_a_refused_data_call_appears_in_both(self) -> None:
        """It is both a failure and evidence the app went looking."""
        conn = _connection()
        conn.watch_responses()
        _emit(conn, _xhr(status=403, url="https://live.invest.ally.com/api/accounts"))

        self.assertEqual(len(conn.failed_responses), 1)
        self.assertEqual(len(conn.data_responses), 1)


class Arming(unittest.TestCase):
    """When the listener is installed."""

    def test_watching_is_installed_once(self) -> None:
        """Re-arming on a second check would double every recorded line."""
        conn = _connection()
        conn.watch_responses()
        conn.watch_responses()

        self.assertEqual(conn.page.on.call_count, 1)  # type: ignore[union-attr]

    def test_no_page_means_no_listener(self) -> None:
        """Recording before the browser starts must not raise."""
        conn = browser_mod.BrowserConnection()
        conn.page = None
        conn.watch_responses()

        self.assertFalse(conn.watching_responses)


class Reporting(unittest.TestCase):
    """What reaches the operator once a capture happens."""

    def test_silent_when_never_armed(self) -> None:
        """Captures from flows that do not record must not claim anything."""
        conn = _connection()
        conn.report_responses()

        self.assertEqual(conn.logger.fail.call_count, 0)  # type: ignore[union-attr]

    def test_both_empty_halves_are_stated(self) -> None:
        """The live run's actual outcome: nothing refused, nothing asked."""
        conn = _connection()
        conn.watch_responses()
        conn.report_responses()
        messages = _messages(conn)

        self.assertIn("No request failed", messages)
        self.assertIn("no data calls", messages)

    def test_data_calls_are_reported_when_nothing_failed(self) -> None:
        """The case the failure log alone could not distinguish."""
        conn = _connection()
        conn.watch_responses()
        _emit(conn, _xhr(status=200, url="https://live.invest.ally.com/api/accounts"))
        conn.report_responses()
        messages = _messages(conn)

        self.assertIn("No request failed", messages)
        self.assertIn("200 https://live.invest.ally.com/api/accounts", messages)

    def test_failures_are_listed(self) -> None:
        conn = _connection()
        conn.watch_responses()
        _emit(conn, _xhr(status=403, url="https://live.invest.ally.com/api/holdings"))
        conn.report_responses()
        messages = _messages(conn)

        self.assertIn("403", messages)
        self.assertIn("/api/holdings", messages)

    def test_long_failure_lists_are_capped_and_say_so(self) -> None:
        """Truncation that does not announce itself reads as the whole story."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            *[
                _xhr(status=403, url=f"https://live.invest.ally.com/api/{n}")
                for n in range(browser_mod.FAILED_RESPONSE_LIMIT + 5)
            ],
        )
        conn.report_responses()

        self.assertIn("and 5 more", _messages(conn))

    def test_long_data_lists_are_capped_too(self) -> None:
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            *[
                _xhr(status=200, url=f"https://live.invest.ally.com/api/{n}")
                for n in range(browser_mod.DATA_RESPONSE_LIMIT + 3)
            ],
        )
        conn.report_responses()

        self.assertIn("and 3 more", _messages(conn))


class AnswerChanges(unittest.TestCase):
    """One run holds two sessions; only the recorder saw both.

    The page captures cannot separate them -- a session Ally renders for and
    one it does not produced HTML identical to within one byte across four
    runs. What differs is what the endpoints handed back.
    """

    def test_an_endpoint_that_answered_once_is_not_reported(self) -> None:
        """Sameness is not evidence, and listing it buries what is."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            _xhr(
                status=200,
                url="https://live.invest.ally.com/api/settings",
                content_length="6576",
            ),
        )
        conn.report_answer_changes()

        self.assertEqual(conn.logger.fail.call_count, 0)  # type: ignore[union-attr]

    def test_two_sizes_from_one_endpoint_are_reported(self) -> None:
        """759 bytes to one session and 4000 to another is the finding."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            _xhr(
                status=200,
                url="https://live.invest.ally.com/api/account/get",
                content_length="759",
            ),
            _xhr(
                status=200,
                url="https://live.invest.ally.com/api/account/get",
                content_length="4096",
            ),
        )
        conn.report_answer_changes()
        messages = _messages(conn)

        self.assertIn("/api/account/get", messages)
        self.assertIn("759 bytes", messages)
        self.assertIn("4096 bytes", messages)

    def test_the_order_is_kept(self) -> None:
        """Which answer came first is which session it belonged to."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            _xhr(
                status=200,
                url="https://live.invest.ally.com/api/account/get",
                content_length="759",
            ),
            _xhr(
                status=200,
                url="https://live.invest.ally.com/api/account/get",
                content_length="4096",
            ),
        )
        conn.report_answer_changes()

        self.assertIn("200 (759 bytes) then 200 (4096 bytes)", _messages(conn))

    def test_a_status_change_counts_too(self) -> None:
        """403-then-200 is the same kind of finding as a size change."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            _xhr(status=403, url="https://live.invest.ally.com/api/account/get"),
            _xhr(status=200, url="https://live.invest.ally.com/api/account/get"),
        )
        conn.report_answer_changes()

        self.assertIn("403 then 200", _messages(conn))

    def test_truncation_announces_itself(self) -> None:
        """Silent truncation is what hid this finding the first time round."""
        conn = _connection()
        conn.watch_responses()
        for n in range(browser_mod.DATA_RESPONSE_LIMIT + 4):
            _emit(
                conn,
                _xhr(
                    status=200,
                    url=f"https://live.invest.ally.com/api/{n}",
                    content_length="10",
                ),
                _xhr(
                    status=200,
                    url=f"https://live.invest.ally.com/api/{n}",
                    content_length="20",
                ),
            )
        conn.report_answer_changes()

        self.assertIn("and 4 more", _messages(conn))

    def test_nothing_recorded_says_nothing(self) -> None:
        conn = _connection()
        conn.watch_responses()
        conn.report_answer_changes()

        self.assertEqual(conn.logger.fail.call_count, 0)  # type: ignore[union-attr]


class ErrorShape(unittest.TestCase):
    """A 401 is a fact; the reason inside it is the diagnosis.

    Ally answers a restored session with 401 on the bank's auth endpoint and
    then falls back to an anonymous session. Whether that 401 says the session
    expired or the device is unrecognised decides whether there is anything to
    fix -- but the body it says it in can also carry a name, an email or a
    masked account number, none of which belongs in a pasteable log.
    """

    def test_the_reason_code_is_quoted(self) -> None:
        conn = _connection()
        conn.watch_responses()
        _emit(conn, _refused(payload=b'{"error": "SESSION_EXPIRED"}'))

        self.assertIn("SESSION_EXPIRED", conn.failed_responses[0])

    def test_the_keys_are_named(self) -> None:
        """Which fields came back is itself the shape of the refusal."""
        conn = _connection()
        conn.watch_responses()
        _emit(conn, _refused(payload=b'{"error": "X_Y_Z", "traceId": "abc"}'))

        self.assertIn("error", conn.failed_responses[0])
        self.assertIn("traceId", conn.failed_responses[0])

    def test_free_text_is_never_printed(self) -> None:
        """A refusal can name the customer beside its reason."""
        conn = _connection()
        conn.watch_responses()
        _emit(conn, _refused(payload=b'{"customer": "Jane Qui Public"}'))
        line = conn.failed_responses[0]

        self.assertIn("customer", line)
        self.assertNotIn("Jane", line)

    def test_a_masked_account_is_not_a_reason_code(self) -> None:
        """Uppercase-looking values must not smuggle account data through."""
        conn = _connection()
        conn.watch_responses()
        _emit(conn, _refused(payload=b'{"acct": "3LD20847"}'))

        self.assertNotIn("3LD20847", conn.failed_responses[0])

    def test_a_successful_response_is_never_opened(self) -> None:
        """Only refusals. A 200 body is the payload, not an explanation."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            FakeResponse(
                status=200,
                url="https://live.invest.ally.com/api/account/get",
                resource_type="xhr",
                content_length="27",
                content_type="application/json",
                body=b'{"error": "SESSION_EXPIRED"}',
            ),
        )

        self.assertEqual(conn.failed_responses, [])

    def test_a_large_body_is_left_shut(self) -> None:
        """Past a point it is a page or a payload, not an error."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            _refused(payload=b'{"error": "TOO_BIG"}').__class__(
                status=401,
                url="https://secure.ally.com/acs/x",
                resource_type="xhr",
                content_length=str(object=browser_mod.ERROR_BODY_LIMIT + 1),
                content_type="application/json",
                body=b'{"error": "TOO_BIG"}',
            ),
        )

        self.assertNotIn("TOO_BIG", conn.failed_responses[0])

    def test_html_is_not_parsed_as_json(self) -> None:
        conn = _connection()
        conn.watch_responses()
        _emit(conn, _refused(payload=b"<html>nope</html>", content_type="text/html"))

        self.assertEqual(
            conn.failed_responses,
            [
                "401 https://secure.ally.com/acs/customers/authenticate/api/v2"
                "/auth/login (17 bytes)"
            ],
        )

    def test_a_redirect_target_is_reported(self) -> None:
        """A refusal that answers with somewhere to go describes the fix."""
        conn = _connection()
        conn.watch_responses()
        _emit(
            conn,
            _refused(
                payload=b'{"redirectUrl": "https://secure.ally.com/acs/sso/start"}'
            ),
        )

        self.assertIn(
            "points to: https://secure.ally.com/acs/sso/start",
            conn.failed_responses[0],
        )

    def test_the_target_goes_through_the_same_redaction(self) -> None:
        """A handoff URL carries its token in the query and its id in the path."""
        conn = _connection()
        conn.watch_responses()
        token = "t" * 40
        _emit(
            conn,
            _refused(
                payload=(
                    b'{"redirectUrl": "https://secure.ally.com/sso/'
                    + token.encode()
                    + b'/go?jwt=SECRET"}'
                )
            ),
        )
        line = conn.failed_responses[0]

        self.assertIn("https://secure.ally.com/sso/<id>/go", line)
        self.assertNotIn("SECRET", line)
        self.assertNotIn(token, line)

    def test_a_relative_target_is_not_mistaken_for_free_text(self) -> None:
        """Only absolute http(s) values are URLs; the rest stay withheld."""
        conn = _connection()
        conn.watch_responses()
        _emit(conn, _refused(payload=b'{"redirectUrl": "/accounts/summary"}'))
        line = conn.failed_responses[0]

        self.assertIn("redirectUrl", line)
        self.assertNotIn("/accounts/summary", line)

    def test_an_unreadable_body_still_leaves_the_status(self) -> None:
        conn = _connection()
        conn.watch_responses()
        _emit(conn, _refused(payload=b"not json at all"))

        self.assertIn("401", conn.failed_responses[0])


if __name__ == "__main__":
    unittest.main()
