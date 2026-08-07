# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Units are per fund, and so are prices. Pairing them across funds is junk.

Found on the first live statement run. The module read a real statement, said
so, and priced it with the wrong fund:

    [+] Statement: 315.789 units of L 2050 as of 2026-08-05
    [+] L 2060: 315.789 units x $24.6710 (2026-08-06) = $7,790.83

The statement was L 2050; the configured fund was L 2060. `read_statement()`
returns the statement's own fund and the caller unpacked it over the `fund`
parameter -- so it was printed, then thrown away when the function returned
only the units. The units were then valued at the configured fund's price.

On the published prices for that day, L 2050 was $46.8496 and L 2060 was
$24.6710. The run reported $7,790.83 where the statement's own fund gives
$14,794.59: ninety percent wrong, with both fund names printed on adjacent
lines and nothing said about the difference. No exception, no warning, and a
total that looks entirely reasonable.

Which one is right is not knowable from here -- the config may be stale or the
parse may be off -- so the run refuses rather than picking.
"""

import unittest
from unittest.mock import MagicMock, patch

from helpers.tsp import same_fund
from modules.tsp_module import TspModule


class FundNames(unittest.TestCase):
    """Compared loosely: spelling differences are not different funds."""

    def test_different_funds_do_not_match(self) -> None:
        self.assertFalse(same_fund("L 2050", "L 2060"))

    def test_the_word_fund_is_not_a_difference(self) -> None:
        """A statement writes "L 2050 Fund"; the price file heads it "L 2050"."""
        self.assertTrue(same_fund("L 2050 Fund", "L 2050"))

    def test_case_and_padding_are_not_differences(self) -> None:
        self.assertTrue(same_fund("  l 2050  ", "L 2050"))

    def test_the_lettered_funds_are_told_apart(self) -> None:
        self.assertFalse(same_fund("C Fund", "S Fund"))

    def test_an_unnamed_side_matches(self) -> None:
        """A statement whose fund would not parse still has a real unit count.

        Refusing over a detail the file never carried would throw away good
        data; what must not pass is two names both present and different.
        """
        self.assertTrue(same_fund("", "L 2060"))
        self.assertTrue(same_fund("L 2050", ""))


class MismatchedStatement(unittest.TestCase):
    """The live failure, end to end through the module."""

    def _units(self, statement_fund: str, configured: str):
        module = TspModule()
        module.statement = "/tmp/statement.pdf"
        context = MagicMock()

        with patch(
            target="modules.tsp_module.read_statement",
            return_value=(315.789, statement_fund, None),
        ):
            return module.units_for(
                context=context, prices=None, fund=configured
            ), context

    def test_a_mismatch_yields_no_units(self) -> None:
        """Better no mark than one that is ninety percent wrong."""
        (units, _as_of, _source), _context = self._units("L 2050", "L 2060")

        self.assertIsNone(units)

    def test_it_names_both_funds(self) -> None:
        """The reader has to know which two disagreed to fix either."""
        _result, context = self._units("L 2050", "L 2060")
        said = " ".join(str(object=c) for c in context.log.fail.call_args_list)

        self.assertIn("L 2050", said)
        self.assertIn("L 2060", said)

    def test_it_says_how_to_fix_it(self) -> None:
        _result, context = self._units("L 2050", "L 2060")
        said = " ".join(str(object=c) for c in context.log.fail.call_args_list)

        self.assertIn("stonksmith.conf", said)
        self.assertIn("STATEMENT", said)

    def test_a_matching_statement_still_works(self) -> None:
        """The guard must not reject the ordinary case."""
        (units, _as_of, _source), _context = self._units("L 2060", "L 2060")

        self.assertEqual(units, 315.789)

    def test_a_statement_naming_no_fund_still_works(self) -> None:
        (units, _as_of, _source), _context = self._units("", "L 2060")

        self.assertEqual(units, 315.789)


if __name__ == "__main__":
    unittest.main()
