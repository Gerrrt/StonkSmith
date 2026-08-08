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

import datetime as dt
import importlib.util
import logging
import tempfile
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
PAY_TABLE = Path(__file__).resolve().parent / "dfas_basic_pay_em.html"

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
        self.broker.args = Namespace(prices="", pay_table="", no_accrual=False)
        self.broker.session = MagicMock()

        # The broker binds the config getters at import, so patching etc.config
        # would not reach the path-loaded module -- and calling the real one
        # would read (and rewrite) the developer's own stonksmith.conf.
        self.module.get_tsp_price_url = lambda: "https://example.invalid/prices.csv"
        self.module.get_tsp_fund = lambda: "C Fund"
        # Every getter the broker reaches, not only the ones under test: one
        # left real is one that reads the developer's own config, and
        # create_conn_obj() reaches all of them.
        self.module.get_tsp_rank = lambda: ""
        self.module.get_tsp_basd = lambda: ""
        self.module.get_tsp_contributions = lambda: (None, None)
        self.module.get_tsp_pay_table_url = lambda: "https://example.invalid/pay/"

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
        self.broker.args = Namespace(prices="", pay_table="", no_accrual=False)
        self.broker.session = MagicMock()
        self.module.get_tsp_fund = lambda: "C Fund"
        # create_conn_obj() also reaches the contribution getters, and one left
        # real reads -- and rewrites -- the developer's own stonksmith.conf.
        self.module.get_tsp_rank = lambda: ""
        self.module.get_tsp_basd = lambda: ""
        self.module.get_tsp_contributions = lambda: (None, None)
        self.module.get_tsp_pay_table_url = lambda: "https://example.invalid/pay/"

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
        self.broker.args = Namespace(prices=str(PRICES), pay_table="", no_accrual=False)
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


class TspPayTableTests(unittest.TestCase):
    """The DFAS download, which is the share price download's twin.

    dfas.mil sits behind the same kind of CDN as tsp.gov and refuses a plain
    client the same way, so the same header and the same offline flag are what
    make this runnable at all. What differs is the consequence of failing:
    prices are the mark, and the pay table is an addition to it -- so every
    failure here has to leave the run working rather than end it.
    """

    def setUp(self) -> None:
        self.module = _load_broker_module()

        self.capture = _CaptureHandler()
        self.logger = logging.getLogger("stonksmith")
        self.logger.addHandler(self.capture)
        self.previous_level = self.logger.level
        # Lower than the other classes here on purpose: half a setup is
        # reported as a highlight rather than a failure, and a level that hid it
        # would make this class pass on the very silence it exists to forbid.
        self.logger.setLevel(logging.DEBUG)

        self.broker = self.module.Tsp()
        self.broker.args = Namespace(prices=str(PRICES), pay_table="", no_accrual=False)
        self.broker.session = MagicMock()

        self.module.get_tsp_fund = lambda: "C Fund"
        self.module.get_tsp_price_url = lambda: "https://example.invalid/prices.csv"
        self.module.get_tsp_pay_table_url = lambda: "https://example.invalid/pay/"
        self._configure(rank="E-7", basd="2016-03-14", member=5.0, agency=5.0)

        # A cache under the real ~/.stonksmith would be read instead of the
        # request under test, and written to a directory the suite does not own.
        self.cache = tempfile.TemporaryDirectory()
        self.module.stonksmith_path = Path(self.cache.name)

    def tearDown(self) -> None:
        self.logger.removeHandler(self.capture)
        self.logger.setLevel(self.previous_level)
        self.cache.cleanup()

    def _configure(
        self,
        rank: str = "E-7",
        basd: str = "2016-03-14",
        member: float | None = 5.0,
        agency: float | None = 5.0,
    ) -> None:
        self.module.get_tsp_rank = lambda: rank
        self.module.get_tsp_basd = lambda: basd
        self.module.get_tsp_contributions = lambda: (member, agency)

    def _logged(self) -> str:
        return " ".join(self.capture.messages)

    def _serve(self, status: int = 200) -> None:
        self.broker.session.get.return_value = _response(
            status=status, text=PAY_TABLE.read_text(encoding="utf-8")
        )

    def test_nothing_configured_makes_no_request_at_all(self) -> None:
        # The backward compatibility guarantee. An install that has never heard
        # of a pay table must behave exactly as it did before there was one.
        self._configure(rank="", basd="", member=None, agency=None)

        self.assertTrue(self.broker.create_conn_obj())

        self.broker.session.get.assert_not_called()
        self.assertIsNone(self.broker.pay_table)
        self.assertEqual(self.capture.messages, [])

    def test_half_a_setup_is_named_rather_than_ignored(self) -> None:
        # Silence here is the failure worth avoiding: the member filled
        # something in and expected it to do something.
        self._configure(rank="E-7", basd="", member=None, agency=None)

        self.assertTrue(self.broker.create_conn_obj())

        self.assertIn("member_contribution", self._logged())
        self.assertIsNone(self.broker.pay_table)

    def test_the_pay_request_carries_the_user_agent(self) -> None:
        self._serve()

        self.broker.create_conn_obj()

        headers = self.broker.session.get.call_args.kwargs["headers"]
        self.assertEqual(headers["User-Agent"], self.module.PRICE_USER_AGENT)
        self.broker.session.headers.__setitem__.assert_not_called()

    def test_the_grade_picks_the_page(self) -> None:
        self._serve()

        self.broker.create_conn_obj()

        url = self.broker.session.get.call_args.kwargs["url"]
        self.assertEqual(url, "https://example.invalid/pay/EM/")

    def test_a_successful_load_carries_the_grade_and_the_service_date(self) -> None:
        self._serve()

        self.assertTrue(self.broker.create_conn_obj())

        self.assertEqual(self.broker.grade, "E-7")
        self.assertEqual(self.broker.basd, dt.date(2016, 3, 14))
        self.assertEqual(self.broker.pay_effective, dt.date(2026, 1, 1))
        self.assertEqual(self.broker.pay_table["E-7"]["Over 10"], 5300.40)

    def test_a_refusal_costs_the_estimate_and_not_the_run(self) -> None:
        self.broker.session.get.return_value = _response(status=403, text="Denied")

        self.assertTrue(self.broker.create_conn_obj())

        logged = self._logged()
        self.assertIn("403", logged)
        self.assertIn("refused", logged)
        self.assertIn("--pay-table", logged)
        self.assertIsNone(self.broker.pay_table)

    def test_a_block_page_served_as_200_is_not_read_as_a_pay_table(self) -> None:
        self.broker.session.get.return_value = _response(text=ACCESS_DENIED_HTML)

        self.assertTrue(self.broker.create_conn_obj())

        self.assertIn("no rates", self._logged())
        self.assertIsNone(self.broker.pay_table)

    def test_a_rank_title_is_refused_by_name(self) -> None:
        self._configure(rank="Sergeant First Class")

        self.assertTrue(self.broker.create_conn_obj())

        self.assertIn("not a pay grade", self._logged())
        self.broker.session.get.assert_not_called()

    def test_an_unreadable_service_date_says_what_was_expected(self) -> None:
        self._configure(basd="March 2016")

        self.assertTrue(self.broker.create_conn_obj())

        self.assertIn("YYYY-MM-DD", self._logged())
        self.broker.session.get.assert_not_called()

    def test_the_pay_table_flag_skips_the_download(self) -> None:
        self.broker.args = Namespace(
            prices=str(PRICES), pay_table=str(PAY_TABLE), no_accrual=False
        )

        self.assertTrue(self.broker.create_conn_obj())

        self.broker.session.get.assert_not_called()
        self.assertEqual(self.broker.pay_table["E-7"]["Over 10"], 5300.40)

    def test_no_accrual_skips_the_whole_thing(self) -> None:
        self.broker.args = Namespace(prices=str(PRICES), pay_table="", no_accrual=True)

        self.assertTrue(self.broker.create_conn_obj())

        self.broker.session.get.assert_not_called()
        self.assertIsNone(self.broker.pay_table)

    def test_a_downloaded_page_is_cached_and_the_next_run_reuses_it(self) -> None:
        # The tables change once a year. A daily run has no business asking for
        # the same page three hundred times to be told the same thing.
        self._serve()
        self.broker.create_conn_obj()

        cached = Path(self.cache.name) / (
            f"dfas-basic-pay-EM-{dt.datetime.now(tz=dt.UTC).year}.html"
        )
        self.assertTrue(cached.is_file())

        again = self.module.Tsp()
        again.args = self.broker.args
        again.session = MagicMock()

        self.assertTrue(again.create_conn_obj())

        again.session.get.assert_not_called()
        self.assertEqual(again.pay_table["E-7"]["Over 10"], 5300.40)

    def test_a_missing_state_directory_is_not_created_to_cache_into(self) -> None:
        # setup_tool() owns making ~/.stonksmith, and a run must not be the
        # thing that creates it. A cache that cannot be written costs a request.
        self.module.stonksmith_path = Path(self.cache.name) / "absent"
        self._serve()

        self.assertTrue(self.broker.create_conn_obj())

        self.assertFalse((Path(self.cache.name) / "absent").exists())
        self.assertEqual(self.broker.pay_table["E-7"]["Over 10"], 5300.40)

    def test_a_grade_with_no_rate_today_drops_the_estimate_and_says_so(self) -> None:
        # verify_access() is where a bad grade turns into one actionable line,
        # rather than into an accrual that silently never happens.
        self._configure(rank="E-9", basd="2025-01-01")
        self._serve()
        self.broker.create_conn_obj()

        self.assertTrue(self.broker.verify_access())

        self.assertIn("no E-9 rate", self._logged())
        self.assertIsNone(self.broker.pay_table)


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
