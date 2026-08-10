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

from bs4 import BeautifulSoup
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
    """The DFAS download, which is the share price download's near twin.

    dfas.mil sits behind the same kind of CDN as tsp.gov and refuses a plain
    client the same way, so a browser-shaped request and an offline flag are
    what make this runnable at all. What differs is the consequence of failing:
    prices are the mark, and the pay table is an addition to it -- so every
    failure here has to leave the run working rather than end it.

    Where the twins stop being identical is the request itself. tsp.gov accepts
    a User-Agent that names StonkSmith; dfas.mil wants a real browser's UA and a
    real browser's navigation headers together, and 403s anything less. That
    asymmetry is deliberate and tested for here, because collapsing the two back
    into one header is the obvious tidy-up and it silently stops the accrual.
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
        # The pay table does not go through self.session: dfas.mil refuses
        # urllib3's handshake, so it has a client of its own. Mocked at that
        # seam rather than at the client, so a test that expects no request
        # still fails if one is made.
        self.broker.pay_table_get = MagicMock()

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
        self.broker.pay_table_get.return_value = _response(
            status=status, text=PAY_TABLE.read_text(encoding="utf-8")
        )

    def test_nothing_configured_makes_no_request_at_all(self) -> None:
        # The backward compatibility guarantee. An install that has never heard
        # of a pay table must behave exactly as it did before there was one.
        self._configure(rank="", basd="", member=None, agency=None)

        self.assertTrue(self.broker.create_conn_obj())

        self.broker.pay_table_get.assert_not_called()
        self.assertIsNone(self.broker.pay_table)
        self.assertEqual(self.capture.messages, [])

    def test_half_a_setup_is_named_rather_than_ignored(self) -> None:
        # Silence here is the failure worth avoiding: the member filled
        # something in and expected it to do something.
        self._configure(rank="E-7", basd="", member=None, agency=None)

        self.assertTrue(self.broker.create_conn_obj())

        self.assertIn("member_contribution", self._logged())
        self.assertIsNone(self.broker.pay_table)

    def test_the_pay_request_carries_the_browser_headers(self) -> None:
        # Down at the real method, since everything above mocks it away. All
        # three of these were measured against the live host and all three are
        # needed: drop any one and DFAS answers 403.
        captured: dict[str, Any] = {}

        class _Client:
            def __init__(self, **kwargs: Any) -> None:
                captured["client"] = kwargs

            def __enter__(self) -> _Client:
                return self

            def __exit__(self, *_: Any) -> None:
                return None

            def get(self, url: str, headers: dict[str, str]) -> MagicMock:
                captured["url"] = url
                captured["headers"] = headers
                return _response(text="")

        self.module.Client = _Client

        # setUp replaced the bound method with a mock, so reach past it to the
        # real one -- it is the thing under test here.
        self.module.Tsp.pay_table_get(
            self.broker, url="https://example.invalid/pay/EM/"
        )

        headers = captured["headers"]
        self.assertEqual(headers["User-Agent"], self.module.PAY_TABLE_USER_AGENT)
        self.assertTrue(
            any(name.startswith("Sec-Fetch-") for name in headers),
            f"no navigation headers on the pay table request: {sorted(headers)}",
        )
        # DFAS moved this path once already, from Military-Members to
        # MilitaryMembers, and answered the old one with a 301.
        self.assertTrue(captured["client"]["follow_redirects"])

    def test_the_pay_table_does_not_touch_the_shared_session(self) -> None:
        # A whole separate client, not merely a separate header, so the way it
        # could leak is by being asked for at all.
        self._serve()

        self.broker.create_conn_obj()

        self.broker.session.get.assert_not_called()
        self.broker.session.headers.__setitem__.assert_not_called()

    def test_dfas_is_not_asked_by_the_user_agent_tsp_gov_is(self) -> None:
        # Two hosts, two answers, and the honest one must not drift onto DFAS
        # or the accrual stops -- nor the browser one onto tsp.gov, which has
        # no need of it and is told truthfully who is calling.
        self.assertNotEqual(
            self.module.PAY_TABLE_USER_AGENT, self.module.PRICE_USER_AGENT
        )
        self.assertIn("stonksmith", self.module.PRICE_USER_AGENT)
        self.assertNotIn("stonksmith", self.module.PAY_TABLE_USER_AGENT)

    def test_the_grade_picks_the_page(self) -> None:
        self._serve()

        self.broker.create_conn_obj()

        url = self.broker.pay_table_get.call_args.kwargs["url"]
        self.assertEqual(url, "https://example.invalid/pay/EM/")

    def test_a_successful_load_carries_the_grade_and_the_service_date(self) -> None:
        self._serve()

        self.assertTrue(self.broker.create_conn_obj())

        self.assertEqual(self.broker.grade, "E-7")
        self.assertEqual(self.broker.basd, dt.date(2016, 3, 14))
        self.assertEqual(self.broker.pay_effective, dt.date(2026, 1, 1))
        self.assertEqual(self.broker.pay_table["E-7"]["Over 10"], 5300.40)

    def test_a_refusal_costs_the_estimate_and_not_the_run(self) -> None:
        self.broker.pay_table_get.return_value = _response(status=403, text="Denied")

        self.assertTrue(self.broker.create_conn_obj())

        logged = self._logged()
        self.assertIn("403", logged)
        self.assertIn("refused", logged)
        self.assertIn("--pay-table", logged)
        self.assertIsNone(self.broker.pay_table)

    def test_a_block_page_served_as_200_is_not_read_as_a_pay_table(self) -> None:
        self.broker.pay_table_get.return_value = _response(text=ACCESS_DENIED_HTML)

        self.assertTrue(self.broker.create_conn_obj())

        self.assertIn("no rates", self._logged())
        self.assertIsNone(self.broker.pay_table)

    def test_a_rank_title_is_refused_by_name(self) -> None:
        self._configure(rank="Sergeant First Class")

        self.assertTrue(self.broker.create_conn_obj())

        self.assertIn("not a pay grade", self._logged())
        self.broker.pay_table_get.assert_not_called()

    def test_an_unreadable_service_date_says_what_was_expected(self) -> None:
        self._configure(basd="March 2016")

        self.assertTrue(self.broker.create_conn_obj())

        self.assertIn("YYYY-MM-DD", self._logged())
        self.broker.pay_table_get.assert_not_called()

    def test_the_pay_table_flag_skips_the_download(self) -> None:
        self.broker.args = Namespace(
            prices=str(PRICES), pay_table=str(PAY_TABLE), no_accrual=False
        )

        self.assertTrue(self.broker.create_conn_obj())

        self.broker.pay_table_get.assert_not_called()
        self.assertEqual(self.broker.pay_table["E-7"]["Over 10"], 5300.40)

    def test_no_accrual_skips_the_whole_thing(self) -> None:
        self.broker.args = Namespace(prices=str(PRICES), pay_table="", no_accrual=True)

        self.assertTrue(self.broker.create_conn_obj())

        self.broker.pay_table_get.assert_not_called()
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
        again.pay_table_get = MagicMock()

        self.assertTrue(again.create_conn_obj())

        again.pay_table_get.assert_not_called()
        self.assertEqual(again.pay_table["E-7"]["Over 10"], 5300.40)

    def test_a_missing_state_directory_is_not_created_to_cache_into(self) -> None:
        # setup_tool() owns making ~/.stonksmith, and a run must not be the
        # thing that creates it. A cache that cannot be written costs a request.
        self.module.stonksmith_path = Path(self.cache.name) / "absent"
        self._serve()

        self.assertTrue(self.broker.create_conn_obj())

        self.assertFalse((Path(self.cache.name) / "absent").exists())
        self.assertEqual(self.broker.pay_table["E-7"]["Over 10"], 5300.40)

    def _served_with_a_trailing_column(self) -> None:
        """The served page, grown one column after the last band."""

        soup = BeautifulSoup(
            markup=PAY_TABLE.read_text(encoding="utf-8"), features="html.parser"
        )

        for element in soup.find_all(name="table"):
            for row in element.find_all(name="tr"):
                cell = soup.new_tag(name="td")
                cell.string = "Note 6"
                row.append(cell)

        self.broker.pay_table_get.return_value = _response(text=str(object=soup))

    def test_a_page_read_one_column_out_drops_the_accrual(self) -> None:
        # The one failure here that is refused rather than reported, and the
        # reason is that it does not look like a failure. Every other way this
        # can go wrong leaves a rate unavailable and says so; this one leaves
        # $5,591.70 available for a member who is paid $5,300.40, which prices
        # an accrual and is stored as a mark with nothing to show for it.
        self._served_with_a_trailing_column()

        self.assertTrue(self.broker.create_conn_obj())

        logged = self._logged()
        self.assertIn("does not line up", logged)
        self.assertIn("wrong years of service", logged)
        self.assertIsNone(self.broker.pay_table)

    def test_half_a_page_is_reported_and_still_priced(self) -> None:
        # Short, not wrong: the difference between this and a misalignment, and
        # why one warns and the other refuses.
        soup = BeautifulSoup(
            markup=PAY_TABLE.read_text(encoding="utf-8"), features="html.parser"
        )
        soup.find_all(name="table")[-1].decompose()
        self.broker.pay_table_get.return_value = _response(text=str(object=soup))

        self.assertTrue(self.broker.create_conn_obj())

        self.assertIn("Over 18", self._logged())
        self.assertEqual(self.broker.pay_table["E-7"]["Over 10"], 5300.40)

    def test_show_pay_table_prints_the_whole_grid(self) -> None:
        # What a single printed rate cannot show. E-7 was correct throughout
        # while E-9 and E-1 were missing entirely, so the run that would have
        # caught that is the one that prints every grade and every blank.
        self.broker.args = Namespace(
            prices=str(PRICES), pay_table="", no_accrual=False, show_pay_table=True
        )
        self._serve()

        self.assertTrue(self.broker.create_conn_obj())

        logged = self._logged()
        self.assertIn("9 grade(s)", logged)
        self.assertIn("E-9", logged)
        self.assertIn("6,910.20", logged)
        # Both halves of the page, so the columns past twenty years are visibly
        # there rather than assumed.
        self.assertIn("Over 40", logged)

    def test_the_grid_is_not_printed_unless_it_is_asked_for(self) -> None:
        self._serve()

        self.assertTrue(self.broker.create_conn_obj())

        self.assertNotIn("as parsed", self._logged())

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
