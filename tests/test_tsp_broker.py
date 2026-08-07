"""Getting the share price file is the one part of this broker that can fail.

Everything after it -- the parser, the arithmetic, the statement reader -- is
covered elsewhere against real data. The download was not, and it turned out to
have two holes: no URL shipped, so a fresh install could only run with --prices,
and no User-Agent, which the CDN in front of tsp.gov answers with a 403 and an
HTML "Access Denied" page. Both are the difference between a broker that runs
unattended and one that needs a human to fetch a CSV first, which is the entire
reason this broker exists.

So the header is asserted here rather than assumed: it is not decoration, it is
the request working at all.

Nothing here touches the network or the real config file.
"""

import importlib.util
import logging
import unittest
from argparse import Namespace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from requests.exceptions import RequestException

BROKER_FILE = (
    Path(__file__).resolve().parents[1] / "src" / "brokers" / "tsp" / "broker.py"
)

PRICES = Path(__file__).resolve().parent / "tsp_prices.csv"

#: What the CDN actually serves a rejected caller: HTTP 200 is never the
#: problem, but a 403 body is HTML, not a CSV.
ACCESS_DENIED_HTML = (
    "<!DOCTYPE html><html><head>"
    "<title>Access Denied | The Thrift Savings Plan (TSP)</title>"
    "</head><body>Access Denied</body></html>"
)


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _load_broker_module() -> Any:
    """Load broker.py by path, the way BrokerLoader does."""

    spec = importlib.util.spec_from_file_location("tsp_broker", BROKER_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _response(*, status: int = 200, text: str = "") -> MagicMock:
    response = MagicMock()
    response.ok = 200 <= status < 400
    response.status_code = status
    response.text = text
    return response


class TspFetchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_broker_module()

        self.capture = _CaptureHandler()
        self.logger = logging.getLogger("stonksmith")
        self.logger.addHandler(self.capture)
        self.previous_level = self.logger.level
        # Everything asserted here has to survive the default level.
        self.logger.setLevel(logging.ERROR)

        self.broker = self.module.Tsp()
        self.broker.args = Namespace(prices="")
        self.broker.session = MagicMock()

        # The broker binds the config getters at import, so patching etc.config
        # would not reach the path-loaded module -- and calling the real one
        # would read (and rewrite) the developer's own stonksmith.conf.
        self.module.get_tsp_price_url = lambda: "https://example.invalid/prices.csv"
        self.module.get_tsp_fund = lambda: "C Fund"

    def tearDown(self) -> None:
        self.logger.removeHandler(self.capture)
        self.logger.setLevel(self.previous_level)

    def _logged(self) -> str:
        return " ".join(self.capture.messages)

    def test_sends_a_user_agent_the_cdn_accepts(self) -> None:
        # Without this header the real request is refused outright, so it is
        # not a nicety -- it is the request.
        self.broker.session.get.return_value = _response(text="Date\n")

        self.broker.fetch_published()

        headers = self.broker.session.get.call_args.kwargs["headers"]
        self.assertEqual(headers["User-Agent"], self.module.PRICE_USER_AGENT)

    def test_the_user_agent_satisfies_the_cdn_rule(self) -> None:
        # tsp.gov wants a UA that opens with Mozilla/5.0 and carries a second
        # product/version token; "Mozilla/5.0 (compatible; stonksmith)" is
        # refused. Editing the constant without knowing that would look
        # harmless and break every unattended run.
        agent = self.module.PRICE_USER_AGENT

        self.assertTrue(agent.startswith("Mozilla/5.0"))
        self.assertRegex(agent[len("Mozilla/5.0") :], r"[A-Za-z][\w.-]*/\d")

    def test_the_header_does_not_leak_onto_the_shared_session(self) -> None:
        # self.session is created once on the base class and shared with every
        # other broker, so this header must ride on the request.
        self.broker.session.get.return_value = _response(text="Date\n")

        self.broker.fetch_published()

        self.broker.session.headers.__setitem__.assert_not_called()

    def test_returns_the_body_unchanged(self) -> None:
        body = PRICES.read_text(encoding="utf-8")
        self.broker.session.get.return_value = _response(text=body)

        self.assertEqual(self.broker.fetch_published(), body)
        self.assertEqual(self.capture.messages, [], "success should be quiet")

    def test_a_refusal_says_it_was_a_refusal(self) -> None:
        self.broker.session.get.return_value = _response(
            status=403, text=ACCESS_DENIED_HTML
        )

        self.assertIsNone(self.broker.fetch_published())

        logged = self._logged()
        self.assertIn("403", logged)
        self.assertIn("refused", logged)
        self.assertIn("--prices", logged, "should say how to get a value anyway")

    def test_other_statuses_are_reported_plainly(self) -> None:
        self.broker.session.get.return_value = _response(status=404)

        self.assertIsNone(self.broker.fetch_published())

        logged = self._logged()
        self.assertIn("404", logged)
        self.assertNotIn("refused", logged, "404 is not the WAF turning us away")

    def test_a_transport_error_is_caught(self) -> None:
        self.broker.session.get.side_effect = RequestException("name resolution")

        self.assertIsNone(self.broker.fetch_published())

        self.assertIn("name resolution", self._logged())


class TspLoadTests(unittest.TestCase):
    """create_conn_obj(), the caller that decides download vs --prices."""

    def setUp(self) -> None:
        self.module = _load_broker_module()

        self.capture = _CaptureHandler()
        self.logger = logging.getLogger("stonksmith")
        self.logger.addHandler(self.capture)
        self.previous_level = self.logger.level
        self.logger.setLevel(logging.ERROR)

        self.broker = self.module.Tsp()
        self.broker.args = Namespace(prices="")
        self.broker.session = MagicMock()
        self.module.get_tsp_fund = lambda: "C Fund"

    def tearDown(self) -> None:
        self.logger.removeHandler(self.capture)
        self.logger.setLevel(self.previous_level)

    def _logged(self) -> str:
        return " ".join(self.capture.messages)

    def test_downloads_with_nothing_configured_but_the_fund(self) -> None:
        # The point of the default URL: fund and units are the whole setup, and
        # a run with neither price_url nor --prices has to work.
        from etc.config import DEFAULT_TSP_PRICE_URL

        self.module.get_tsp_price_url = lambda: DEFAULT_TSP_PRICE_URL
        self.broker.session.get.return_value = _response(
            text=PRICES.read_text(encoding="utf-8")
        )

        self.assertTrue(self.broker.create_conn_obj())

        self.assertEqual(
            self.broker.session.get.call_args.kwargs["url"], DEFAULT_TSP_PRICE_URL
        )
        self.assertTrue(self.broker.client)

    def test_prices_flag_skips_the_download(self) -> None:
        self.broker.args = Namespace(prices=str(PRICES))
        self.module.get_tsp_price_url = lambda: "https://example.invalid/prices.csv"

        self.assertTrue(self.broker.create_conn_obj())

        self.broker.session.get.assert_not_called()

    def test_an_html_page_served_as_200_is_not_valued_at_nothing(self) -> None:
        # The backstop for a block page that comes back with a success status:
        # it parses to no rows, and no rows must fail loudly rather than mark
        # the account at zero.
        self.module.get_tsp_price_url = lambda: "https://example.invalid/prices.csv"
        self.broker.session.get.return_value = _response(text=ACCESS_DENIED_HTML)

        self.assertFalse(self.broker.create_conn_obj())

        self.assertIn("no rows", self._logged())


class TspPriceUrlTests(unittest.TestCase):
    """get_tsp_price_url(): blank means unset, not "download nothing"."""

    def setUp(self) -> None:
        import etc.config as config

        self.config = config

    def _with_price_url(self, value: str | None) -> None:
        """Stand in for a config where price_url is set, blank, or absent."""

        parser = MagicMock()
        parser.get.return_value = "" if value is None else value
        self.config.get_config = lambda: parser

    def tearDown(self) -> None:
        importlib.reload(self.config)

    def test_a_configured_url_wins(self) -> None:
        self._with_price_url("https://example.invalid/moved.csv")

        self.assertEqual(
            self.config.get_tsp_price_url(), "https://example.invalid/moved.csv"
        )

    def test_a_blank_value_falls_back_to_the_default(self) -> None:
        # Every install predating the default carries a literal "price_url ="
        # line, and get_config() backfills only absent options -- so blank has
        # to be what triggers the fallback.
        self._with_price_url("")

        self.assertEqual(
            self.config.get_tsp_price_url(), self.config.DEFAULT_TSP_PRICE_URL
        )

    def test_a_missing_option_falls_back_to_the_default(self) -> None:
        self._with_price_url(None)

        self.assertEqual(
            self.config.get_tsp_price_url(), self.config.DEFAULT_TSP_PRICE_URL
        )

    def test_the_default_is_the_published_file(self) -> None:
        self.assertEqual(
            self.config.DEFAULT_TSP_PRICE_URL,
            "https://www.tsp.gov/data/fund-price-history.csv",
        )


if __name__ == "__main__":
    unittest.main()
