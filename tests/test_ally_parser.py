"""Selectors and parsing for the Ally Invest holdings page.

Verified against a signed-in capture, which is committed redacted as
tests/ally_holdings.html. The fixture keeps the two things that make this page
awkward: the _ngcontent-gdx-NNN attributes Ally's build stamps on every element
and rewrites on every deploy, and gain/loss amounts written with no sign, where
the direction lives in an "up"/"down" class.

The sign is the one worth restating. A holding that is down $3.00 renders as
`<span class="down">$3.00</span>` -- identical characters to a $3.00 gain. A
parser that reads the text records every loss as a gain, and the magnitude is
right, so nothing about the number looks wrong afterwards.
"""

import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from stonksmith.helpers.ally import (
    INVESTMENT_KIND,
    account_balances,
    account_label,
    account_totals,
    collapse,
    column_index,
    holdings,
    masked_form,
    masked_matches,
    selected_account,
    sidebar_accounts,
    signed_amount,
)

FIXTURE = Path(__file__).resolve().parent / "ally_holdings.html"


def _page() -> BeautifulSoup:
    """The captured holdings page, parsed."""

    return BeautifulSoup(
        markup=FIXTURE.read_text(encoding="utf-8"), features="html.parser"
    )


def _fragment(markup: str) -> BeautifulSoup:
    """A literal snippet, parsed the same way as the page."""

    return BeautifulSoup(markup=markup, features="html.parser")


class SignedAmountTests(unittest.TestCase):
    """The direction of a gain or loss is in the class, not the text."""

    def test_a_loss_comes_back_negative(self) -> None:
        node = _fragment(
            '<day-gain-loss><span class="down">$3.00</span></day-gain-loss>'
        )
        self.assertEqual(signed_amount(node=node.select_one("day-gain-loss")), "-$3.00")

    def test_a_gain_comes_back_unsigned(self) -> None:
        node = _fragment(
            '<total-gain-loss><span class="up">$250.00</span></total-gain-loss>'
        )
        self.assertEqual(
            signed_amount(node=node.select_one("total-gain-loss")), "$250.00"
        )

    def test_the_identical_text_of_a_gain_and_a_loss_is_told_apart(self) -> None:
        # The regression this function exists for: same characters, opposite
        # meanings, and only the class distinguishes them.
        gain = _fragment('<p><span class="up">$3.00</span></p>')
        loss = _fragment('<p><span class="down">$3.00</span></p>')

        self.assertNotEqual(
            signed_amount(node=gain.select_one("p")),
            signed_amount(node=loss.select_one("p")),
        )

    def test_an_unclassed_amount_is_left_alone(self) -> None:
        node = _fragment(
            "<total-market-value><span>$1,500.00</span></total-market-value>"
        )
        self.assertEqual(
            signed_amount(node=node.select_one("total-market-value")), "$1,500.00"
        )

    def test_the_percentage_beside_the_amount_is_not_included(self) -> None:
        node = _fragment(
            '<holding-total-gain-loss><span class="total up">$250.00</span>'
            '<span class="percentage up">(20.00%)</span></holding-total-gain-loss>'
        )
        self.assertEqual(
            signed_amount(node=node.select_one("holding-total-gain-loss")), "$250.00"
        )

    def test_a_missing_element_is_not_an_amount(self) -> None:
        self.assertEqual(signed_amount(node=None), "")

    def test_an_already_signed_loss_does_not_gain_a_second_minus(self) -> None:
        node = _fragment('<p><span class="down">-$3.00</span></p>')
        self.assertEqual(signed_amount(node=node.select_one("p")), "-$3.00")

    def test_the_caret_glyph_does_not_reach_the_amount(self) -> None:
        # Ally puts an <i> arrow inside the same span as the number.
        node = _fragment(
            '<day-gain-loss><span class="down">'
            '<caret-display><i aria-label="Loss"></i></caret-display> $3.00'
            "</span></day-gain-loss>"
        )
        self.assertEqual(signed_amount(node=node.select_one("day-gain-loss")), "-$3.00")


class SelectedAccountTests(unittest.TestCase):
    def test_reads_the_nickname_and_number_from_the_heading(self) -> None:
        self.assertEqual(selected_account(soup=_page()), ("Brokerage", "1AB20111"))

    def test_a_nickname_containing_the_separator_keeps_all_of_it(self) -> None:
        # rsplit, not split: only the last " - " separates name from number.
        page = _fragment(
            '<change-account><span role="heading">Joint - Taxable - 1AB20111</span>'
            "</change-account>"
        )
        self.assertEqual(selected_account(soup=page), ("Joint - Taxable", "1AB20111"))

    def test_a_heading_with_no_number_still_yields_a_name(self) -> None:
        page = _fragment(
            '<change-account><span role="heading">Brokerage</span></change-account>'
        )
        self.assertEqual(selected_account(soup=page), ("Brokerage", ""))

    def test_a_missing_heading_is_not_an_account(self) -> None:
        self.assertEqual(selected_account(soup=_fragment("<div></div>")), ("", ""))


class SidebarAccountTests(unittest.TestCase):
    def test_lists_every_account_including_the_bank_ones(self) -> None:
        rows = sidebar_accounts(soup=_page())

        self.assertEqual(
            [(row["Kind"], row["Label"], row["Balance"]) for row in rows],
            [
                ("investments", "Brokerage (...0111)", "$1,500.00"),
                ("savings", "Savings Account (...0222)", "$4,000.00"),
            ],
        )

    def test_each_account_is_listed_once(self) -> None:
        # The selector names both the component and the id it wraps, and those
        # nest -- a non-deduplicating match would report every account twice
        # and double the net worth.
        rows = sidebar_accounts(soup=_page())
        self.assertEqual(len(rows), len({row["Label"] for row in rows}))

    def test_the_investment_kind_matches_the_module_constant(self) -> None:
        rows = sidebar_accounts(soup=_page())
        self.assertIn(INVESTMENT_KIND, {row["Kind"] for row in rows})

    def test_the_group_heading_is_kept(self) -> None:
        rows = sidebar_accounts(soup=_page())
        self.assertEqual(rows[0]["Group"], "Investments")


class AccountLabelTests(unittest.TestCase):
    def test_name_and_number_are_combined(self) -> None:
        self.assertEqual(
            account_label(name="Brokerage", number="...0111"), "Brokerage (...0111)"
        )

    def test_a_missing_number_leaves_the_name(self) -> None:
        self.assertEqual(account_label(name="Brokerage", number=""), "Brokerage")

    def test_a_missing_name_leaves_the_number(self) -> None:
        self.assertEqual(account_label(name="", number="...0111"), "...0111")


class MaskedNumberTests(unittest.TestCase):
    def test_a_masked_number_matches_the_full_one(self) -> None:
        self.assertTrue(masked_matches(masked="...0111", number="1AB20111"))

    def test_a_different_account_does_not_match(self) -> None:
        self.assertFalse(masked_matches(masked="...0222", number="1AB20111"))

    def test_an_empty_side_never_matches(self) -> None:
        self.assertFalse(masked_matches(masked="", number="1AB20111"))
        self.assertFalse(masked_matches(masked="...0111", number=""))

    def test_masking_a_full_number_reproduces_the_sidebar_form(self) -> None:
        # The two identities have to agree: deriving one key from the sidebar
        # and another from the heading would give one account two rows the
        # first time the sidebar failed to render.
        rows = sidebar_accounts(soup=_page())
        _name, number = selected_account(soup=_page())

        self.assertEqual(masked_form(number=number), rows[0]["Number"])

    def test_masking_an_empty_number_yields_nothing(self) -> None:
        self.assertEqual(masked_form(number=""), "")


class AccountTotalTests(unittest.TestCase):
    def test_reads_all_four_headline_figures(self) -> None:
        self.assertEqual(
            account_totals(soup=_page()),
            {
                "Account Value": "$1,500.00",
                "Market Value": "$1,500.00",
                "Total G/L": "$250.00",
                # The one the class encodes: down $3.00, not up.
                "Today's G/L": "-$3.00",
            },
        )

    def test_a_page_without_the_block_reports_nothing_rather_than_raising(self) -> None:
        self.assertEqual(account_totals(soup=_fragment("<div></div>")), {})


class AccountBalanceTests(unittest.TestCase):
    def test_reads_the_collapsed_balance_breakdown(self) -> None:
        balances = account_balances(soup=_page())

        self.assertEqual(balances["Total Cash and Money Fund"], "$0.00")
        self.assertEqual(balances["Total Securities"], "$1,500.00")

    def test_the_trailing_colon_is_not_part_of_the_label(self) -> None:
        self.assertNotIn("Cash:", account_balances(soup=_page()))

    def test_a_negative_cash_balance_keeps_its_sign(self) -> None:
        # Written "$-25.00", with the sign inside the amount rather than in a
        # class -- the opposite convention to the gain/loss cells.
        self.assertEqual(account_balances(soup=_page())["Cash"], "$-25.00")


class ColumnIndexTests(unittest.TestCase):
    def test_the_two_positional_columns_are_found_by_heading(self) -> None:
        table = _page().select_one("table.dash-hldg-table")
        assert table is not None
        columns = column_index(table=table)

        self.assertEqual(columns["Qty"], 2)
        self.assertEqual(columns["Cost Basis"], 6)


class HoldingTests(unittest.TestCase):
    def test_reads_the_position_off_the_captured_page(self) -> None:
        position = holdings(soup=_page())[0]

        self.assertEqual(position.symbol, "EXMPL")
        self.assertEqual(position.name, "Example Index Fund")
        self.assertEqual(position.units, 100.0)
        self.assertEqual(position.price, 15.0)
        self.assertEqual(position.value, 1500.0)
        self.assertEqual(position.currency, "USD")
        self.assertEqual(position.raw_value, "$1,500.00")

    def test_cost_basis_is_the_total_not_the_per_unit_price(self) -> None:
        # Ally's Cost Basis column is what the position cost altogether, which
        # is the convention Holding.cost_basis already carries. SnapTrade
        # reports a per-unit figure that its module multiplies out, so reading
        # this one as per-unit would make the same field mean two things and
        # understate Ally by a factor of the share count.
        position = holdings(soup=_page())[0]

        assert position.units is not None
        assert position.cost_basis is not None
        self.assertEqual(position.cost_basis, 1250.0)
        self.assertAlmostEqual(position.cost_basis / position.units, 12.50, places=2)

    def test_the_build_scoped_attributes_are_not_load_bearing(self) -> None:
        # _ngcontent-gdx-NNN changes on every Ally deploy. Stripping it must
        # not change what is read.
        stripped = FIXTURE.read_text(encoding="utf-8").replace(
            '_ngcontent-gdx-91=""', ""
        )

        self.assertEqual(
            holdings(soup=BeautifulSoup(markup=stripped, features="html.parser")),
            holdings(soup=_page()),
        )

    def test_a_table_with_no_rows_yields_no_positions(self) -> None:
        page = _fragment(
            '<holdings-table><table class="dash-hldg-table"><thead><tr><th>Qty</th>'
            "</tr></thead><tbody></tbody></table></holdings-table>"
        )
        self.assertEqual(holdings(soup=page), [])

    def test_a_missing_table_yields_no_positions(self) -> None:
        self.assertEqual(holdings(soup=_fragment("<div></div>")), [])

    def test_a_row_missing_its_market_value_reports_nothing(self) -> None:
        # The tempting shorthand falls back to the row itself, whose text is
        # every cell run together and parses to a wrong number rather than to
        # none at all.
        page = _fragment(
            '<holdings-table><table class="dash-hldg-table">'
            "<thead><tr><th>Sym/Desc</th><th>Qty</th></tr></thead>"
            '<tbody><tr holding-row=""><td class="static">'
            '<div class="symbol"><span title="EXMPL">'
            "<strong>EXMPL</strong></span></div>"
            "</td><td><div><span>100.000</span></div></td></tr></tbody>"
            "</table></holdings-table>"
        )
        position = holdings(soup=page)[0]

        self.assertEqual(position.units, 100.0)
        self.assertIsNone(position.value)
        self.assertIsNone(position.price)


class CollapseTests(unittest.TestCase):
    def test_pretty_printed_markup_becomes_one_line(self) -> None:
        self.assertEqual(collapse(text="\n  $1,500.00\n"), "$1,500.00")

    def test_empty_text_stays_empty(self) -> None:
        self.assertEqual(collapse(text="   \n "), "")


if __name__ == "__main__":
    unittest.main()
