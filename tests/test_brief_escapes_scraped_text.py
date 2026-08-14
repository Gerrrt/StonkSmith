"""Nothing a broker's page said becomes markup in the brief.

Account names, symbols and transaction descriptions are the least trusted strings
this project handles. They are read out of signed-in brokerage pages, and a
nickname is a field the account holder types -- so "attacker-influenced" here is
not a hypothetical, it is the ordinary way an account gets named.

Everywhere else those values land somewhere inert. The sheet writes them as RAW
cell values, which is a deliberate choice made for a different reason -- a name
beginning with "=" would otherwise become a formula -- and it has the side effect
that markup in a name is just text. The shell prints them into a terminal. This
is the first surface in the project that renders them as HTML and opens the
result in a browser, so it is the first place the question has teeth.

The brief is written to ~/.stonksmith/reports and opened as a file:// URL, which
is the worst context to get this wrong in: a file:// page is same-origin with the
rest of the user's filesystem in some browsers, and the file sits beside the
databases it was rendered from.

Every field, not a representative one. A test that checks the account name and
not the symbol pins the half somebody already thought about.
"""

import datetime as dt
import unittest
from html import escape

from config_isolation import UserConfigMixin
from stonksmith.etc.brief import Baseline, Mark, build_brief
from stonksmith.etc.brief_html import render
from stonksmith.etc.portfolio import (
    OBSERVED,
    HoldingRow,
    NetWorthRow,
    Portfolio,
    TransactionRow,
)

#: Closes an attribute, opens a tag, and fires without needing to be clicked.
#: A payload that only works inside a <script> would pass a page that strips
#: those and still renders this one.
PAYLOAD: str = '"><img src=x onerror=alert(1)>'

NOW: dt.datetime = dt.datetime(2026, 8, 14, 6, 30, tzinfo=dt.UTC)


class ScrapedTextIsInert(UserConfigMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()

        self.portfolio = Portfolio(
            net_worth=(
                NetWorthRow(
                    broker=PAYLOAD,
                    source=PAYLOAD,
                    account=PAYLOAD,
                    account_key="a1",
                    date="2026-08-13",
                    value=1000.0,
                    basis=OBSERVED,
                    observed_on="2026-08-13",
                ),
            ),
            holdings=(
                HoldingRow(
                    broker=PAYLOAD,
                    source=PAYLOAD,
                    account=PAYLOAD,
                    account_key="a1",
                    symbol=PAYLOAD,
                    units=1.0,
                    value=1000.0,
                ),
            ),
            transactions=(
                TransactionRow(
                    broker=PAYLOAD,
                    source=PAYLOAD,
                    account=PAYLOAD,
                    account_key="a1",
                    tx_type=PAYLOAD,
                    description=PAYLOAD,
                    value=10.0,
                    processed_on="2026-08-13",
                    first_seen="2026-08-13T18:30:00",
                ),
            ),
            unreadable=((PAYLOAD, PAYLOAD),),
        )

        # A baseline, so the mover and transaction sections render rather than
        # being skipped as "nothing to compare" -- which would pass this test
        # without ever putting the payload on the page.
        self.baseline = Baseline(
            taken_on="2026-08-12",
            seen_through="2026-08-01T00:00:00",
            totals={"USD": 500.0},
            holdings={(PAYLOAD, "a1", PAYLOAD): Mark(value=500.0, units=1.0)},
        )

        self.page: str = render(
            brief=build_brief(
                portfolio=self.portfolio,
                baseline=self.baseline,
                today=dt.date(2026, 8, 14),
            ),
            now=NOW,
        )

    def test_the_payload_never_appears_as_markup(self) -> None:
        self.assertNotIn(
            PAYLOAD,
            self.page,
            "a scraped value reached the page unescaped, so a broker nickname "
            "is executable markup in a file:// page beside the databases",
        )

    def test_no_tag_was_created(self) -> None:
        # The assertion above is about the exact payload; this one is about the
        # shape, so a partial escape that neutralised the quote and left the tag
        # cannot pass.
        #
        # Deliberately not asserting that the word "onerror" is absent. It is
        # present, escaped, in the account's rendered name -- and it should be:
        # that is what the account is called. What makes a name inert is that the
        # angle brackets around it became entities, not that the letters were
        # censored, and a test demanding the letters be gone would be satisfied
        # by a renderer that silently dropped the account instead.
        #
        # Nor that the sequence `"><` is absent, which was the first thing tried
        # here and is wrong for a subtler reason: the page's own markup is full
        # of it, because that is what one tag ending and the next beginning looks
        # like. An assertion about a payload has to name something only the
        # payload could produce.
        self.assertNotIn("<img", self.page)
        self.assertNotIn("<script", self.page)

        # The whole payload, rendered as text. Together with the tag checks above
        # this says the value survived and none of it became markup, which the
        # exact-payload assertion alone cannot distinguish from it being dropped.
        self.assertIn(escape(s=PAYLOAD), self.page)

    def test_the_value_is_still_shown(self) -> None:
        # Escaped, not dropped. A renderer that stripped unknown text would pass
        # every assertion above while silently hiding the account it could not
        # spell -- and an account missing from the page is the failure mode this
        # project cares about most.
        self.assertIn("&lt;img", self.page)

    def test_the_unreadable_banner_is_escaped_too(self) -> None:
        # The degraded banner interpolates a broker name and the reason its
        # database would not open, and the reason is an exception message --
        # which routinely quotes the input that caused it.
        self.assertIn("could not be read", self.page)
        self.assertNotIn(PAYLOAD, self.page)


if __name__ == "__main__":
    unittest.main()
