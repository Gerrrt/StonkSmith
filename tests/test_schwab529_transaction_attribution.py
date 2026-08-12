# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Which account a scraped 529 transaction belongs to.

Issue #36: on a page showing more than one beneficiary the movements were
dropped entirely, because the transaction table named no account and guessing
one would have written history that looks completely plausible and is wrong.

Two halves are pinned here. The pure matching rules -- how a header row becomes
a column map, and how a scraped marker resolves to one of the accounts on the
page -- and the whole path from HTML through the parser and the module into a
database, which is where a mistake would actually cost something.
"""

import unittest
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

from stonksmith.etc.records import AccountIdentity
from stonksmith.helpers.schwab529plan import account_hint, column_map, match_account
from stonksmith.modules.schwab529plan_module import Schwab529Module

_TX_COLUMNS: tuple[str, ...] = (
    "Processed",
    "Traded",
    "Type",
    "Units",
    "Price",
    "Value",
)


class ColumnMapTests(unittest.TestCase):
    """A table's header decides which column holds what.

    Reading fixed positions is correct right up until the page prints a column
    it did not print before, at which point every field shifts and the database
    fills with plausible nonsense that nothing downstream can detect.
    """

    def test_the_familiar_header_maps_to_the_familiar_positions(self) -> None:
        self.assertEqual(
            column_map(headers=list(_TX_COLUMNS)),
            {
                "Processed": 0,
                "Traded": 1,
                "Type": 2,
                "Units": 3,
                "Price": 4,
                "Value": 5,
            },
        )

    def test_an_account_column_shifts_the_rest(self) -> None:
        mapping = column_map(headers=["Account", *_TX_COLUMNS])

        self.assertEqual(mapping["Account"], 0)
        self.assertEqual(mapping["Processed"], 1)
        self.assertEqual(mapping["Value"], 6)

    def test_synonyms_and_punctuation_are_tolerated(self) -> None:
        mapping = column_map(
            headers=[
                "Beneficiary",
                "Process Date",
                "Trade Date",
                "Transaction Type",
                "Shares",
                "Unit Price",
                "Amount",
            ]
        )

        self.assertEqual(mapping["Account"], 0)
        self.assertEqual(mapping["Units"], 4)
        self.assertEqual(mapping["Value"], 6)

    def test_a_row_that_is_not_a_header_maps_nothing(self) -> None:
        # Below the floor the caller falls back to the positions that have
        # always worked, which beats a partial guess that scrambles them.
        self.assertEqual(column_map(headers=["Processed", "", "Notes"]), {})

    def test_no_header_at_all_maps_nothing(self) -> None:
        self.assertEqual(column_map(headers=[]), {})

    def test_the_first_spelling_of_a_column_wins(self) -> None:
        mapping = column_map(headers=[*_TX_COLUMNS, "Total"])

        self.assertEqual(mapping["Value"], 5)


class MatchAccountTests(unittest.TestCase):
    """A marker on a row resolves to one account, or to none."""

    CANDIDATES: ClassVar[list[list[str]]] = [
        ["Beneficiary A", "Beneficiary A", "1000-1234"],
        ["Naomi", "Naomi", "1000-5678"],
    ]

    def test_an_exact_name_matches(self) -> None:
        self.assertEqual(match_account(hint="Naomi", candidates=self.CANDIDATES), 1)

    def test_case_and_punctuation_do_not_matter(self) -> None:
        self.assertEqual(
            match_account(hint="  BENEFICIARY A:  ", candidates=self.CANDIDATES), 0
        )

    def test_a_masked_number_matches_on_its_tail(self) -> None:
        self.assertEqual(match_account(hint="XXXX-5678", candidates=self.CANDIDATES), 1)

    def test_a_short_number_is_not_enough_to_match_on(self) -> None:
        # Three digits identify nothing; matching on them would attach history
        # to whichever account happened to sort first.
        self.assertIsNone(
            match_account(hint="678", candidates=[["1000-5678"], ["2000-9678"]])
        )

    def test_a_name_inside_a_sentence_matches(self) -> None:
        self.assertEqual(
            match_account(hint="Contributions for Naomi", candidates=self.CANDIDATES),
            1,
        )

    def test_a_name_is_matched_whole_not_as_a_fragment(self) -> None:
        self.assertIsNone(
            match_account(hint="Naomiah", candidates=[["Naomi"], ["Beneficiary A"]])
        )

    def test_a_marker_matching_two_accounts_matches_neither(self) -> None:
        # A collision is not an attribution. Picking one of them produces a
        # database that is indistinguishable from a correct one.
        self.assertIsNone(
            match_account(hint="Smith", candidates=[["Smith"], ["Smith"]])
        )

    def test_a_marker_matching_nothing_matches_nothing(self) -> None:
        self.assertIsNone(
            match_account(hint="Someone Else", candidates=self.CANDIDATES)
        )

    def test_an_empty_marker_matches_nothing(self) -> None:
        self.assertIsNone(match_account(hint="   ", candidates=self.CANDIDATES))


class AccountHintTests(unittest.TestCase):
    """Where the marker is read from, and in which order."""

    def test_the_row_beats_the_section_which_beats_the_caption(self) -> None:
        row: dict[str, Any] = {
            "Account": "ACC-1",
            "Section": "Beneficiary A",
            "Title": "History",
        }

        self.assertEqual(account_hint(row=row), "ACC-1")
        self.assertEqual(account_hint(row={**row, "Account": None}), "Beneficiary A")
        self.assertEqual(
            account_hint(row={**row, "Account": None, "Section": None}), "History"
        )

    def test_the_caller_can_refuse_to_trust_the_caption(self) -> None:
        row: dict[str, Any] = {
            "Account": None,
            "Section": None,
            "Title": "Beneficiary A",
        }

        self.assertIsNone(account_hint(row=row, keys=("Account", "Section")))

    def test_a_row_naming_nothing_gives_nothing(self) -> None:
        self.assertIsNone(account_hint(row={"Processed": "12/30/2025"}))


class _SnapshotDb:
    """A database that keeps history, recording what it was handed."""

    def __init__(self) -> None:
        self.snapshots: list[dict[str, Any]] = []

    def save_snapshot(
        self,
        account: AccountIdentity,
        scraped_at: str,
        value: float | None,
        currency: str = "USD",
        as_of: str | None = None,
        raw_value: str | None = None,
        holdings: Any = (),
        transactions: Any = (),
    ) -> int:
        self.snapshots.append(
            {
                "account": account,
                "value": value,
                "transactions": list(transactions),
            }
        )
        return len(self.snapshots)

    def save_transactions(
        self, account: AccountIdentity, timestamp: str, rows: Any
    ) -> int:
        del account, timestamp
        return len(list(rows))

    def save_account_data(
        self, account_name: str, balance: Any, timestamp: str
    ) -> None:
        del account_name, balance, timestamp

    def get_credentials(self, filter_term: object = None) -> list[tuple[str, ...]]:
        del filter_term
        return []

    def shutdown_db(self) -> None:
        return None


def _account_panel(name: str, number: str, amount: str) -> str:
    """One beneficiary's block, in the shape the dashboard renders it.

    A beneficiary heading, a balance heading and a fund table per account, in
    that order -- which is why position pairs them.
    """

    return (
        "<div>"
        f"<div><h2>Beneficiary: <span>{name}</span><span>{number}</span></h2></div>"
        f"<div><h2>Balance: <span>{amount}</span>"
        "<span>as of 12/31/2025</span></h2></div>"
        "</div>"
    )


def _dashboard(panels: str, tx_div: str) -> str:
    """Assemble a dashboard the real Parser can read end to end.

    Four wrapper divs, then one div per account: that is the nesting the
    parser's absolute xpaths walk.
    """

    return (
        "<html><body><div><div><div><div>"
        f"{panels}"
        "</div></div></div></div>"
        f"{tx_div}"
        "</body></html>"
    )


def _tx_row(account: str | None, value: str) -> str:
    cells: list[str] = [] if account is None else [account]
    cells += ["12/30/2025", "12/29/2025", "Contribution", "1", value, value]

    return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


class OnLoginTransactionRoutingTests(unittest.TestCase):
    """The whole path: HTML in, per-account transactions in the database."""

    def _run(self, tx_div: str) -> tuple[_SnapshotDb, MagicMock]:
        panels: str = _account_panel(
            "Beneficiary A", "1000-1234", "$1,234.56"
        ) + _account_panel("Naomi", "1000-5678", "$2,000.00")

        response = MagicMock()
        response.ok = True
        response.url = (
            "https://www.schwab529plan.com/swatpl/aggregator/overview/"
            "viewAggrOverview.cs"
        )
        response.text = _dashboard(panels=panels, tx_div=tx_div)

        connection = MagicMock()
        connection.username = "testuser"
        connection.session.get.return_value = response

        db = _SnapshotDb()
        context = MagicMock()
        context.db = db
        context.log = MagicMock()

        with patch("stonksmith.modules.schwab529plan_module.sync"):
            Schwab529Module().on_login(context, connection)

        return db, context

    def test_each_account_receives_only_the_rows_that_name_it(self) -> None:
        tx_div: str = (
            '<div id="txHistDiv"><table><thead><tr>'
            "<th>Account</th><th>Processed</th><th>Traded</th><th>Type</th>"
            "<th>Units</th><th>Price</th><th>Value</th>"
            "</tr></thead><tbody>"
            + _tx_row("1000-5678", "$20.00")
            + _tx_row("1000-1234", "$10.00")
            + _tx_row("1000-1234", "$11.00")
            + "</tbody></table></div>"
        )

        db, _context = self._run(tx_div=tx_div)

        self.assertEqual(len(db.snapshots), 2)

        beneficiary_a, naomi = db.snapshots
        self.assertEqual(beneficiary_a["account"].display_name, "Beneficiary A")
        self.assertEqual(naomi["account"].display_name, "Naomi")

        self.assertEqual(
            [tx.raw for tx in beneficiary_a["transactions"]], ["$10.00", "$11.00"]
        )
        self.assertEqual([tx.raw for tx in naomi["transactions"]], ["$20.00"])

    def test_the_account_column_does_not_shift_the_other_fields(self) -> None:
        tx_div: str = (
            '<div id="txHistDiv"><table><thead><tr>'
            "<th>Account</th><th>Processed</th><th>Traded</th><th>Type</th>"
            "<th>Units</th><th>Price</th><th>Value</th>"
            "</tr></thead><tbody>"
            + _tx_row("Beneficiary A", "$10.00")
            + "</tbody></table>"
            "</div>"
        )

        db, _context = self._run(tx_div=tx_div)

        stored = db.snapshots[0]["transactions"][0]
        self.assertEqual(stored.processed_on, "12/30/2025")
        self.assertEqual(stored.traded_on, "12/29/2025")
        self.assertEqual(stored.tx_type, "Contribution")
        self.assertEqual(stored.units, 1.0)
        self.assertEqual(stored.value, 10.0)

    def test_one_table_per_beneficiary_pairs_by_position(self) -> None:
        tx_div: str = (
            '<div id="txHistDiv">'
            "<table><tbody>" + _tx_row(None, "$10.00") + "</tbody></table>"
            "<table><tbody>"
            + _tx_row(None, "$20.00")
            + _tx_row(None, "$21.00")
            + "</tbody></table>"
            "</div>"
        )

        db, _context = self._run(tx_div=tx_div)

        self.assertEqual([tx.raw for tx in db.snapshots[0]["transactions"]], ["$10.00"])
        self.assertEqual(
            [tx.raw for tx in db.snapshots[1]["transactions"]], ["$20.00", "$21.00"]
        )

    def test_a_page_naming_no_account_still_stores_the_balances(self) -> None:
        # The regression issue #36 describes, unchanged where it was right: the
        # movements are dropped, and the balances and holdings are not.
        tx_div: str = (
            '<div id="txHistDiv"><table><tbody>'
            + _tx_row(None, "$10.00")
            + "</tbody></table></div>"
        )

        db, context = self._run(tx_div=tx_div)

        self.assertEqual(
            [snapshot["value"] for snapshot in db.snapshots], [1234.56, 2000.0]
        )
        self.assertEqual(
            [snapshot["transactions"] for snapshot in db.snapshots], [[], []]
        )

        reported = " ".join(
            str(call.kwargs.get("msg", "")) for call in context.log.fail.call_args_list
        )
        self.assertIn("None were stored", reported)

    def test_the_markup_shape_is_printed_when_nothing_can_be_attributed(self) -> None:
        # Issue #36's blocking unknown is what a live multi-beneficiary page
        # renders. One run answers it without anybody reading HTML by hand.
        tx_div: str = (
            '<div id="txHistDiv"><table><tbody>'
            '<tr class="row"><td>12/30/2025</td><td>12/29/2025</td>'
            "<td>Contribution</td><td>1</td><td>$10.00</td><td>$10.00</td></tr>"
            "</tbody></table></div>"
        )

        _db, context = self._run(tx_div=tx_div)

        printed = " ".join(
            str(call.kwargs.get("msg", ""))
            for call in context.log.highlight.call_args_list
        )

        self.assertIn("cells-per-row=[6]", printed)
        self.assertIn("attributes=['class']", printed)
        self.assertNotIn("12/30/2025", printed, "no cell values in a diagnostic")
        self.assertNotIn("$10.00", printed, "no cell values in a diagnostic")


class SingleAccountRegressionTests(unittest.TestCase):
    """A single-beneficiary 529 stored its transactions before and still does."""

    def test_the_one_account_takes_them_all(self) -> None:
        panels: str = _account_panel("Beneficiary A", "1000-1234", "$1,234.56")
        tx_div: str = (
            '<div id="txHistDiv"><table><tbody>'
            + _tx_row(None, "$10.00")
            + _tx_row(None, "$11.00")
            + "</tbody></table></div>"
        )

        response = MagicMock()
        response.ok = True
        response.url = (
            "https://www.schwab529plan.com/swatpl/aggregator/overview/"
            "viewAggrOverview.cs"
        )
        response.text = _dashboard(panels=panels, tx_div=tx_div)

        connection = MagicMock()
        connection.username = "testuser"
        connection.session.get.return_value = response

        db = _SnapshotDb()
        context = MagicMock()
        context.db = db
        context.log = MagicMock()

        with patch("stonksmith.modules.schwab529plan_module.sync"):
            Schwab529Module().on_login(context, connection)

        self.assertEqual(len(db.snapshots), 1)
        self.assertEqual(
            [tx.raw for tx in db.snapshots[0]["transactions"]], ["$10.00", "$11.00"]
        )
        context.log.fail.assert_not_called()


if __name__ == "__main__":
    unittest.main()
