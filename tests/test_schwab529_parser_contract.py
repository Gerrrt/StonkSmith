"""What the 529 parser emits has to be what its consumer reads.

This used to pin the parser against the saver, because the saver was what read
those keys. The saver is gone and the keys still matter -- they are what
`helpers.schwab529plan` turns into the Holding and Transaction records that reach
the database, and from there the sheet. So the pin moved to the real consumer
rather than being deleted with the tab it used to protect.

One key did go: "Total Assets" was read by nothing but the saver's own layout,
and no record carries it.
"""

import importlib.util
import unittest
from typing import Any

from package_tree import PACKAGE
from stonksmith.helpers.schwab529plan import holding_from_row, transaction_from_row


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, PACKAGE / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parser_mod = _load("schwab529_parser", "brokers/schwab529plan/parser.py")


def parse(html: str, method: str) -> list[dict[str, Any]]:
    """
    Run one parser method over a fixture page.
    :param html: The page
    :param method: The Parser method to call
    :return: Its rows
    :rtype: list[dict[str, Any]]
    """

    response = type("R", (), {"text": html})()
    return getattr(parser_mod.Parser(response=response), method)()


INVESTMENTS = """
<html><body><div><div><div><div><div><table>
  <caption>Investments</caption>
  <tbody><tr>
    <td>FC</td><td>Fund</td><td>10</td><td>5</td><td>50</td>
  </tr></tbody>
  <tfoot><tr><td>50</td></tr><tr><td>40</td></tr><tr><td>10</td></tr></tfoot>
</table></div></div></div></div></div></body></html>
"""

TRANSACTIONS = """
<html><body><div id="txHistDiv"><table><tbody><tr>
  <td>12/30/2025</td><td>12/29/2025</td><td>Contribution</td>
  <td>1</td><td>$50.00</td><td>$50.00</td>
</tr></tbody></table></div></body></html>
"""


class ParserRecordContractTests(unittest.TestCase):
    def test_investment_keys_cover_every_key_the_holding_reads(self) -> None:
        parsed = parse(html=INVESTMENTS, method="investment_data")

        self.assertTrue(parsed, "fixture should yield one investment row")

        needed = {
            "Fund Code",
            "Fund",
            "Units",
            "Price",
            "Value",
            "Principal",
            "Earnings",
        }
        self.assertTrue(
            needed.issubset(parsed[0].keys()),
            f"parser is missing {needed - parsed[0].keys()}",
        )

    def test_a_parsed_investment_becomes_a_holding_with_its_numbers(self) -> None:
        # The pin that a key rename cannot survive: not that the keys are there,
        # but that the record built from them still carries the values.
        holding = holding_from_row(
            row=parse(html=INVESTMENTS, method="investment_data")[0]
        )

        self.assertEqual(holding.fund_code, "FC")
        self.assertEqual(holding.name, "Fund")
        self.assertEqual(holding.units, 10.0)
        self.assertEqual(holding.price, 5.0)
        self.assertEqual(holding.value, 50.0)
        self.assertEqual(holding.principal, 40.0)
        self.assertEqual(holding.earnings, 10.0)

    def test_transaction_keys_cover_every_key_the_transaction_reads(self) -> None:
        parsed = parse(html=TRANSACTIONS, method="transaction_data")

        self.assertTrue(parsed, "fixture should yield one transaction row")

        needed = {"Processed", "Traded", "Type", "Units", "Price", "Value"}
        self.assertTrue(
            needed.issubset(parsed[0].keys()),
            f"parser is missing {needed - parsed[0].keys()}",
        )

    def test_a_parsed_transaction_becomes_a_transaction_with_its_numbers(self) -> None:
        record = transaction_from_row(
            row=parse(html=TRANSACTIONS, method="transaction_data")[0]
        )

        self.assertEqual(record.processed_on, "12/30/2025")
        self.assertEqual(record.traded_on, "12/29/2025")
        self.assertEqual(record.tx_type, "Contribution")
        self.assertEqual(record.units, 1.0)
        self.assertEqual(record.price, 50.0)
        self.assertEqual(record.value, 50.0)


if __name__ == "__main__":
    unittest.main()
