"""What the funds charge to hold them, and why it is stated rather than fetched.

The figure exists in Yahoo's ``quoteSummary``. It is gated behind a
cookie-and-crumb handshake that answered "Too Many Requests" on every attempt
from a cold address, which is a materially different class of dependency from
the chart endpoint the prices and dividends already use -- that one needs no
credential and has never refused. A morning brief that breaks when somebody
else's rate limiter is unhappy is not one worth scheduling.

An expense ratio also barely moves: funds restate them about once a year, in a
prospectus. A number that changes annually is a poor reason to make a network
call every night.

So it is declared, like the asset classes and the stated cost basis before it,
and the three rules that keep it honest are the subject of this file.

**Weighted by value, never averaged across symbols.** A costly fund held in
small size is a small cost. Averaging 0.02% and 0.60% to 0.31% describes a
portfolio nobody owns; weighting them by what is actually in each gives 0.078%,
which is what is actually being paid.

**A fund nobody looked up is not a free fund.** An absent ratio produces no fee
rather than a zero one, and the tile states how many positions it covers -- the
same coverage rule the indicated yield follows, and for the same reason.

**The figure is money, not a rate.** 0.08% reads as nothing. The same fact as an
annual sum in dollars is a number somebody can weigh against what it buys.
"""

import unittest

from config_isolation import UserConfigMixin
from stonksmith.etc.brief import performance, positions
from stonksmith.etc.brief_html import render
from stonksmith.etc.config import get_expense_ratios
from stonksmith.etc.portfolio import HoldingRow, Portfolio

#: Nine thousand at two basis points and one thousand at sixty, plus a fund
#: whose ratio nobody has declared. The spread is the point: the cheap holding
#: is nine times the size of the dear one.
HELD: tuple[HoldingRow, ...] = (
    HoldingRow(
        broker="b",
        source="s",
        account="An Account",
        account_key="a1",
        symbol="CHEAP",
        units=1.0,
        value=9000.0,
    ),
    HoldingRow(
        broker="b",
        source="s",
        account="An Account",
        account_key="a1",
        symbol="DEAR",
        units=1.0,
        value=1000.0,
    ),
    HoldingRow(
        broker="b",
        source="s",
        account="An Account",
        account_key="a1",
        symbol="UNKNOWN",
        units=1.0,
        value=5000.0,
    ),
)

RATIOS: dict[str, float] = {"CHEAP": 0.02, "DEAR": 0.60}


class TheRatioIsReadAsAFundPagePrintsIt(UserConfigMixin, unittest.TestCase):
    def _reload(self, body: str) -> tuple[dict[str, float], list[str]]:
        self.config_body = body
        self.tearDown()
        self.setUp()

        return get_expense_ratios()

    def test_nothing_configured_is_no_ratios_and_no_complaints(self) -> None:
        self.assertEqual(get_expense_ratios(), ({}, []))

    def test_a_percentage_is_read_with_or_without_the_sign(self) -> None:
        ratios, refused = self._reload(
            "[FEES]\nexpense_ratios =\n\tCHEAP = 0.02\n\tDEAR = 0.60%\n"
        )

        self.assertEqual(ratios, {"CHEAP": 0.02, "DEAR": 0.60})
        self.assertEqual(refused, [])

    def test_a_figure_that_looks_like_basis_points_is_refused(self) -> None:
        # "2" for two basis points is the mistake this catches: it would be read
        # as two percent, a hundred times the truth, and produce a fee figure
        # nobody would question because it is merely large rather than absurd.
        _ratios, refused = self._reload("[FEES]\nexpense_ratios =\n\tCHEAP = 20\n")

        self.assertEqual(len(refused), 1)
        self.assertIn("percentage like 0.02", refused[0])

    def test_something_that_is_not_a_number_is_named(self) -> None:
        _ratios, refused = self._reload("[FEES]\nexpense_ratios =\n\tCHEAP = cheap\n")

        self.assertIn("not a percentage", refused[0])


class TheCostIsWeightedByWhatIsHeld(UserConfigMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.rows = positions(
            portfolio=Portfolio(holdings=HELD),
            classes={},
            income={},
            history={},
            fees=RATIOS,
        )
        self.by = {row.symbol: row for row in self.rows}
        self.money = performance(
            held=self.rows, income={}, covered=0, currency="USD", total=15000.0
        )

    def test_a_position_pays_its_own_rate_on_its_own_value(self) -> None:
        self.assertAlmostEqual(self.by["CHEAP"].annual_fee or 0.0, 1.80, places=2)
        self.assertAlmostEqual(self.by["DEAR"].annual_fee or 0.0, 6.00, places=2)

    def test_a_fund_nobody_looked_up_pays_nothing_rather_than_zero(self) -> None:
        # None, not 0.0. A ratio nobody has declared is not a fund that is free,
        # and a zero would let it dilute the weighted rate downward -- making the
        # portfolio look cheaper the less of it anybody has checked.
        self.assertIsNone(self.by["UNKNOWN"].expense_ratio)
        self.assertIsNone(self.by["UNKNOWN"].annual_fee)

    def test_the_rate_is_weighted_and_not_a_mean_of_the_symbols(self) -> None:
        # 7.80 over the 10,000 that has a ratio is 0.078%. The mean of 0.02 and
        # 0.60 is 0.31%, four times higher, describing a portfolio in which the
        # dear fund is as large as the cheap one. It is not.
        self.assertAlmostEqual(self.money.fee_cost, 7.80, places=2)
        self.assertAlmostEqual(self.money.fee_ratio or 0.0, 0.078, places=4)

    def test_the_rate_divides_by_what_it_covers_not_the_portfolio(self) -> None:
        # Over 10,000, not the 15,000 the portfolio holds. Dividing by the whole
        # would report 0.052% -- a real number about nothing anybody asked.
        self.assertEqual(self.money.fee_value, 10000.0)
        self.assertEqual(self.money.fee_over, 2)
        self.assertEqual(self.money.holdings, 3)


class ThePageLeadsWithTheMoney(UserConfigMixin, unittest.TestCase):
    def _page(self, fees: dict[str, float]) -> str:
        self.config_body = "[FEES]\nexpense_ratios =\n" + "".join(
            f"\t{symbol} = {ratio}\n" for symbol, ratio in fees.items()
        )
        self.tearDown()
        self.setUp()

        import datetime as dt

        from stonksmith.etc.brief import build_brief

        return render(
            brief=build_brief(
                portfolio=Portfolio(holdings=HELD),
                baseline=None,
                today=dt.date(2026, 8, 14),
            ),
            now=dt.datetime(2026, 8, 14, 6, 30, tzinfo=dt.UTC),
        )

    def test_the_figure_is_the_annual_sum(self) -> None:
        # 0.078% reads as nothing. $7.80 a year is a number somebody can weigh
        # against what it buys.
        page: str = self._page(fees=RATIOS)

        self.assertIn("Fund Fees", page)
        self.assertIn("$7.80", page)

    def test_the_coverage_travels_with_it(self) -> None:
        self.assertIn("across 2 of 3 positions", self._page(fees=RATIOS))

    def test_declared_but_worthless_does_not_deny_the_count(self) -> None:
        # The count and the sentence must agree. A holding with a declared ratio
        # and no value leaves nothing to charge a rate against -- which is not
        # the same as nothing being declared, and saying so would contradict the
        # "across N positions" the tile is already carrying.
        held = (
            HoldingRow(
                broker="b",
                source="s",
                account="An Account",
                account_key="a1",
                symbol="CHEAP",
                units=0.0,
                value=0.0,
            ),
        )

        import datetime as dt

        from stonksmith.etc.brief import build_brief

        self.config_body = "[FEES]\nexpense_ratios =\n\tCHEAP = 0.02\n"
        self.tearDown()
        self.setUp()

        page: str = render(
            brief=build_brief(
                portfolio=Portfolio(holdings=held),
                baseline=None,
                today=dt.date(2026, 8, 14),
            ),
            now=dt.datetime(2026, 8, 14, 6, 30, tzinfo=dt.UTC),
        )

        self.assertIn("worth nothing to charge a rate against", page)
        self.assertNotIn("no holding has a declared expense ratio", page)

    def test_nothing_declared_says_so_rather_than_showing_nought(self) -> None:
        # A fee of zero is a claim about the funds. Nothing declared is a claim
        # about the config, and the page says which.
        page: str = self._page(fees={})

        self.assertIn("no holding has a declared expense ratio", page)
        self.assertNotIn("$0.00 a year", page)


class ARefusedLineReachesTheOperator(UserConfigMixin, unittest.TestCase):
    """
    The refusal has to be said out loud, or it is not a refusal.

    A rejected ratio shows up only as a fee figure covering one position fewer,
    which is a number that looks entirely right. "SWPPX = O.02" with a letter O
    is indistinguishable, on the page, from a fund nobody has looked up yet --
    and the second is an ordinary state this brief reports every morning.

    This is the third time in this codebase that a parser built a list of
    refused lines and the caller dropped it: the account colours did it, the
    stated cost basis did it, and so did this.
    """

    def test_the_brief_command_names_what_it_could_not_read(self) -> None:
        import tempfile
        from pathlib import Path as P
        from unittest.mock import patch

        from stonksmith.etc.stonksmithdb import StonkSmithDBMenu

        self.config_body = "[FEES]\nexpense_ratios =\n\tSWPPX = O.02\n"
        self.tearDown()
        self.setUp()

        printed: list[str] = []
        shell = StonkSmithDBMenu.__new__(StonkSmithDBMenu)
        shell.workspace = "default"
        shell.failed = False

        with tempfile.TemporaryDirectory() as root:
            (P(root) / "default").mkdir()

            with (
                patch("stonksmith.etc.portfolio.workspace_dir", str(object=root)),
                patch("stonksmith.etc.paths.reports_path", P(root) / "reports"),
                patch("stonksmith.etc.paths.baseline_path", P(root) / "b.json"),
                patch("webbrowser.open"),
                patch(
                    "builtins.print",
                    side_effect=lambda *a: printed.append(" ".join(map(str, a))),
                ),
            ):
                shell.do_brief("--no-open")

        said: str = "\n".join(printed)

        self.assertIn("[FEES] expense_ratios", said)
        self.assertIn("O.02", said)


if __name__ == "__main__":
    unittest.main()
