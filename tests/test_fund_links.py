"""A symbol links to its quote page, unless there is no page to link to.

Nine of the twelve holdings in a real workspace are public tickers. The other
three are "Q4R7", an employer 401k fund code; "70310", a Schwab 529 portfolio
number; and "L 2060", a TSP fund. All three are real positions and none of them
is findable on a quote site.

**A link that 404s is worse than no link**, because the reader has to click it to
learn it was worthless -- and does so once per morning until they stop trusting
any of them. So the rule refuses rather than guesses: a symbol is linked only
when it looks like a public ticker, and looks like one means one to five ASCII
letters and nothing else.

The ASCII part is load-bearing rather than pedantic. ``str.isalpha()`` is true of
Cyrillic and full-width characters, and a symbol arrives from a scraped page --
so the looser test would let arbitrary text into a URL. Constrained to five
ASCII letters there is nothing left to inject with, and the template is refused
by the config unless it is https, which is the second gate on the same value.
"""

import unittest

from config_isolation import UserConfigMixin
from stonksmith.etc.brief import fund_url
from stonksmith.etc.config import DEFAULT_FUND_LINK, get_brief_fund_link

TEMPLATE: str = "https://finance.yahoo.com/quote/{symbol}"


class APublicTickerGetsALink(unittest.TestCase):
    def test_the_symbols_this_workspace_actually_holds(self) -> None:
        for symbol in ("SWPPX", "FSKAX", "SWYNX", "SWTSX", "SWYOX", "SPYM"):
            with self.subTest(symbol=symbol):
                self.assertEqual(
                    fund_url(symbol=symbol, template=TEMPLATE),
                    f"https://finance.yahoo.com/quote/{symbol}",
                )

    def test_a_lowercase_symbol_is_upcased_in_the_url(self) -> None:
        # Quote sites route on the upper-cased ticker, and a source is free to
        # spell it either way.
        self.assertEqual(
            fund_url(symbol="swppx", template=TEMPLATE),
            "https://finance.yahoo.com/quote/SWPPX",
        )


class AHoldingWithNoPublicPageGetsNone(unittest.TestCase):
    def test_the_three_this_workspace_actually_holds(self) -> None:
        # A 401k fund code, a 529 portfolio number and a TSP fund. Real
        # positions, no quote page, and each one would 404.
        for symbol in ("Q4R7", "70310", "L 2060"):
            with self.subTest(symbol=symbol):
                self.assertEqual(fund_url(symbol=symbol, template=TEMPLATE), "")

    def test_a_symbol_too_long_to_be_a_ticker_gets_none(self) -> None:
        self.assertEqual(fund_url(symbol="BTCLPATH", template=TEMPLATE), "")

    def test_an_empty_symbol_gets_none(self) -> None:
        self.assertEqual(fund_url(symbol="", template=TEMPLATE), "")

    def test_a_non_ascii_symbol_gets_none(self) -> None:
        # str.isalpha() is true of both of these. The pattern is ASCII-only
        # precisely because a symbol comes off a scraped page, and that is the
        # difference between a constrained URL and an arbitrary one.
        #
        # Written as escapes rather than as the characters themselves. A
        # homoglyph pasted into source is invisible to a reviewer -- which is the
        # whole reason it is a hazard -- and ruff refuses one on sight (RUF001),
        # correctly. Naming the code points says what is being tested.
        confusable: str = "\u0405W\u0420\u0420\u0425"  # Cyrillic DZE, ER, ER, HA
        fullwidth: str = "\uff33\uff37\uff30\uff30\uff38"  # fullwidth S W P P X

        for symbol in (confusable, fullwidth):
            with self.subTest(symbol=symbol.encode("unicode_escape").decode()):
                self.assertTrue(symbol.isalpha(), "the loose test would pass this")
                self.assertEqual(fund_url(symbol=symbol, template=TEMPLATE), "")

    def test_a_symbol_carrying_url_punctuation_gets_none(self) -> None:
        for symbol in ("A/B", "A?x=1", "A#frag", "A B"):
            with self.subTest(symbol=symbol):
                self.assertEqual(fund_url(symbol=symbol, template=TEMPLATE), "")


class AnUnusableTemplateLinksNothing(unittest.TestCase):
    def test_no_template_means_no_links(self) -> None:
        self.assertEqual(fund_url(symbol="SWPPX", template=""), "")


class TheConfigRefusesWhatIsNotAnHttpsUrl(UserConfigMixin, unittest.TestCase):
    def test_the_default_is_used_when_nothing_is_configured(self) -> None:
        self.assertEqual(get_brief_fund_link(), DEFAULT_FUND_LINK)

    def test_a_javascript_url_is_refused(self) -> None:
        # The reason the check exists. This value is written into an href, and a
        # config file is not a place for a scheme that executes.
        self.config_body = "[BRIEF]\nfund_link = javascript:alert(1)//{symbol}\n"
        self.tearDown()
        self.setUp()

        self.assertEqual(get_brief_fund_link(), "")

    def test_plain_http_is_refused(self) -> None:
        self.config_body = "[BRIEF]\nfund_link = http://example.test/{symbol}\n"
        self.tearDown()
        self.setUp()

        self.assertEqual(get_brief_fund_link(), "")

    def test_a_template_with_no_symbol_placeholder_is_refused(self) -> None:
        # It would link every holding to the same page, which is a link that
        # lies rather than one that is missing.
        self.config_body = "[BRIEF]\nfund_link = https://example.test/quotes\n"
        self.tearDown()
        self.setUp()

        self.assertEqual(get_brief_fund_link(), "")

    def test_a_custom_https_template_is_accepted(self) -> None:
        self.config_body = "[BRIEF]\nfund_link = https://example.test/f/{symbol}\n"
        self.tearDown()
        self.setUp()

        self.assertEqual(
            fund_url(symbol="SWPPX", template=get_brief_fund_link()),
            "https://example.test/f/SWPPX",
        )


class ThePageLinksOnlyWhatItCan(UserConfigMixin, unittest.TestCase):
    def _page(self) -> str:
        import datetime as dt

        from stonksmith.etc.brief import build_brief
        from stonksmith.etc.brief_html import render
        from stonksmith.etc.portfolio import HoldingRow, Portfolio

        held = tuple(
            HoldingRow(
                broker="b",
                source="b",
                account="An Account",
                account_key="a1",
                symbol=symbol,
                value=1000.0,
            )
            for symbol in ("SWPPX", "Q4R7")
        )

        return render(
            brief=build_brief(
                portfolio=Portfolio(holdings=held),
                baseline=None,
                today=dt.date(2026, 8, 14),
            ),
            now=dt.datetime(2026, 8, 14, 6, 30, tzinfo=dt.UTC),
        )

    def test_the_ticker_is_an_anchor(self) -> None:
        self.assertIn(
            '<a class="sym who" href="https://finance.yahoo.com/quote/SWPPX"',
            self._page(),
        )

    def test_the_fund_code_is_plain_text(self) -> None:
        page: str = self._page()

        self.assertIn('<span class="who">Q4R7</span>', page)
        self.assertNotIn("quote/Q4R7", page)

    def test_the_link_does_not_hand_the_page_to_the_opener(self) -> None:
        # target=_blank without rel=noopener lets the opened page reach back
        # through window.opener. This one is a file:// page listing balances.
        self.assertIn('rel="noopener noreferrer"', self._page())


if __name__ == "__main__":
    unittest.main()
