"""Regression tests for the Google Sheets writer.

Two bugs lived here: the investment writer read a key the parser never emitted,
and every A1 range spanned one row more than the data it was given.
"""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock

SRC = Path(__file__).resolve().parents[1] / "src"


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, SRC / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


saver_mod = _load("schwab529_saver", "brokers/schwab529plan/saver.py")
parser_mod = _load("schwab529_parser", "brokers/schwab529plan/parser.py")


class A1RangeTests(unittest.TestCase):
    def test_range_spans_exactly_the_row_count(self) -> None:
        self.assertEqual(
            saver_mod._a1_range(first_col="B", last_col="D", first_row=3, row_count=1),
            "B3:D3",
        )
        self.assertEqual(
            saver_mod._a1_range(first_col="B", last_col="D", first_row=3, row_count=3),
            "B3:D5",
        )
        self.assertEqual(
            saver_mod._a1_range(first_col="B", last_col="I", first_row=10, row_count=2),
            "B10:I11",
        )


class SaverWritesTests(unittest.TestCase):
    def _saver(self) -> tuple[object, MagicMock]:
        saver = saver_mod.Saver()
        worksheet = MagicMock()
        # Pretend authentication already happened.
        saver.gc = MagicMock()
        saver.worksheet = worksheet
        return saver, worksheet

    def test_save_balance_range_matches_row_count(self) -> None:
        saver, worksheet = self._saver()

        saver.save_balance(
            data=[
                {"Title": "a", "Amount": "1", "Date": "d"},
                {"Title": "b", "Amount": "2", "Date": "d"},
            ]
        )

        rows_call = worksheet.update.call_args_list[-1]
        self.assertEqual(rows_call.args[1], "G3:I4")

    def test_save_investment_reads_the_key_the_parser_emits(self) -> None:
        saver, worksheet = self._saver()

        # Exactly the dict shape Parser.investment_data() produces.
        saver.save_investment(
            data=[
                {
                    "Fund Code": "FC",
                    "Fund": "Fund Name",
                    "Units": "10",
                    "Price": "5",
                    "Value": "50",
                    "Total Assets": "50",
                    "Principal": "40",
                    "Earnings": "10",
                }
            ]
        )

        rows_call = worksheet.update.call_args_list[-1]
        written_row = rows_call.args[0][0]
        self.assertIn("50", written_row, "the Value column must not be blank")
        self.assertEqual(rows_call.args[1], "B10:I10")


class ParserSaverContractTests(unittest.TestCase):
    def test_investment_keys_cover_every_key_the_saver_reads(self) -> None:
        html = """
        <html><body><div><div><div><div><div><table>
          <caption>Investments</caption>
          <tbody><tr>
            <td>FC</td><td>Fund</td><td>10</td><td>5</td><td>50</td>
          </tr></tbody>
          <tfoot><tr><td>50</td></tr><tr><td>40</td></tr><tr><td>10</td></tr></tfoot>
        </table></div></div></div></div></div></body></html>
        """
        response = type("R", (), {"text": html})()
        parsed = parser_mod.Parser(response=response).investment_data()

        self.assertTrue(parsed, "fixture should yield one investment row")

        saver_reads = {
            "Fund Code",
            "Fund",
            "Units",
            "Price",
            "Value",
            "Total Assets",
            "Principal",
            "Earnings",
        }
        self.assertTrue(
            saver_reads.issubset(parsed[0].keys()),
            f"parser is missing {saver_reads - parsed[0].keys()}",
        )


if __name__ == "__main__":
    unittest.main()
