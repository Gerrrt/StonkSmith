# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Scraped text becomes numbers, and the awkward cases stay awkward.

Every broker hands StonkSmith money as display text, and the schema stores a
number. The cases pinned here are the ones that silently corrupt history when
they go wrong:

* "0" is a real balance. Anything that treats it as falsy loses it.
* "1.5%" is not dollars. Dropping the sign and storing 1.5 is a unit error that
  reads as a plausible number forever after.
* "(1,234.56)" is negative. Accounting parentheses are the one negative form
  that has no minus sign in it.
* A non-USD amount must not come back wearing a dollar sign; it would sum
  cleanly into a USD total and be wrong.
"""

import datetime
import unittest
from decimal import Decimal

from stonksmith.helpers.normalize import (
    format_amount,
    format_units,
    to_amount,
    to_currency,
    to_iso_date,
)


class ToAmountTests(unittest.TestCase):
    """Reading a scraped amount as a number."""

    def test_nothing_reads_as_nothing(self) -> None:
        for blank in (None, "", "   ", "--", "-", "—", "N/A", "n/a", "unavailable"):
            with self.subTest(blank=blank):
                self.assertIsNone(to_amount(blank))

    def test_zero_is_a_value_not_a_blank(self) -> None:
        # The falsy-vs-None bug: a zero balance is a fact about the account.
        for zero in ("0", "$0.00", "0.00", 0, 0.0):
            with self.subTest(zero=zero):
                self.assertEqual(to_amount(zero), 0.0)

    def test_plain_us_money(self) -> None:
        self.assertEqual(to_amount("$1,234.56"), 1234.56)
        self.assertEqual(to_amount("1,234.56"), 1234.56)
        self.assertEqual(to_amount("1,234"), 1234.0)

    def test_negatives_in_every_form_the_brokers_emit(self) -> None:
        for text in ("-$1,234.56", "$-1,234.56", "(1,234.56)", "($1,234.56)"):
            with self.subTest(text=text):
                self.assertEqual(to_amount(text), -1234.56)

    def test_trailing_currency_code_is_not_part_of_the_number(self) -> None:
        self.assertEqual(to_amount("1,234.56 CAD"), 1234.56)

    def test_european_separators(self) -> None:
        self.assertEqual(to_amount("1.234,56"), 1234.56)
        self.assertEqual(to_amount("1.234.567,89"), 1234567.89)

    def test_a_lone_comma_that_cannot_be_a_thousands_group_is_a_decimal_point(
        self,
    ) -> None:
        self.assertEqual(to_amount("1,5"), 1.5)
        self.assertEqual(to_amount("1,234"), 1234.0)

    def test_fractional_units_keep_their_precision(self) -> None:
        self.assertEqual(to_amount("12.3456"), 12.3456)

    def test_a_unit_suffix_is_refused_rather_than_dropped(self) -> None:
        # Storing 1.5 for "1.5%" would be a plausible-looking number that is
        # wrong by two orders of magnitude.
        for text in ("1.5%", "150 bps", "3 percent"):
            with self.subTest(text=text):
                self.assertIsNone(to_amount(text))

    def test_numbers_the_sdk_already_parsed(self) -> None:
        self.assertEqual(to_amount(Decimal("1234.56")), 1234.56)
        self.assertEqual(to_amount(1234), 1234.0)
        self.assertEqual(to_amount(1234.56), 1234.56)

    def test_a_bool_is_not_a_balance(self) -> None:
        # bool subclasses int, so an unguarded float() would store True as 1.0.
        self.assertIsNone(to_amount(True))
        self.assertIsNone(to_amount(False))

    def test_junk_never_raises(self) -> None:
        for junk in ("abc", "$", "..", "1.2.3", object()):
            # repr(), not the value: pytest-xdist ships subTest parameters back
            # to the controller and cannot serialise a bare object(), which
            # failed the test under -n auto for a reason having nothing to do
            # with to_amount(). The object itself still goes to the function.
            with self.subTest(junk=repr(junk)):
                self.assertIsNone(to_amount(junk))


class ToCurrencyTests(unittest.TestCase):
    """Reading what a scraped amount is denominated in."""

    def test_a_dollar_sign_means_usd(self) -> None:
        self.assertEqual(to_currency("$1,234.56"), "USD")

    def test_a_trailing_code_wins(self) -> None:
        self.assertEqual(to_currency("1,234.56 CAD"), "CAD")
        self.assertEqual(to_currency("EUR"), "EUR")

    def test_a_bare_number_is_not_evidence_of_a_currency(self) -> None:
        self.assertEqual(to_currency("1234.56"), "USD")
        self.assertEqual(to_currency("1234.56", default="GBP"), "GBP")

    def test_nothing_gets_the_default(self) -> None:
        self.assertEqual(to_currency(None), "USD")
        self.assertEqual(to_currency(""), "USD")


class ToIsoDateTests(unittest.TestCase):
    """Reading the source's own as-of date."""

    def test_the_formats_the_brokers_emit(self) -> None:
        for text in ("2025-12-31", "12/31/2025", "Dec 31, 2025", "December 31, 2025"):
            with self.subTest(text=text):
                self.assertEqual(to_iso_date(text), "2025-12-31")

    def test_a_snaptrade_timestamp_keeps_only_its_date(self) -> None:
        self.assertEqual(to_iso_date("2025-12-31T09:30:00Z"), "2025-12-31")
        self.assertEqual(to_iso_date("2025-12-31T09:30:00+00:00"), "2025-12-31")

    def test_a_date_embedded_in_prose(self) -> None:
        self.assertEqual(to_iso_date("Balance as of 12/31/2025"), "2025-12-31")

    def test_date_objects_pass_through(self) -> None:
        self.assertEqual(to_iso_date(datetime.date(2025, 12, 31)), "2025-12-31")
        self.assertEqual(
            to_iso_date(datetime.datetime(2025, 12, 31, 9, 30)), "2025-12-31"
        )

    def test_no_date_is_none_not_a_guess(self) -> None:
        for text in (None, "", "--", "sometime last week"):
            with self.subTest(text=text):
                self.assertIsNone(to_iso_date(text))


class FormatTests(unittest.TestCase):
    """Rendering stored values back into display text."""

    def test_usd_gets_a_dollar_sign(self) -> None:
        self.assertEqual(format_amount(1234.56, "USD"), "$1,234.56")
        self.assertEqual(format_amount(-1234.56, "USD"), "-$1,234.56")

    def test_other_currencies_do_not(self) -> None:
        # A "$" on a CAD number sums cleanly into a USD total and is wrong.
        self.assertEqual(format_amount(1234.56, "CAD"), "1,234.56 CAD")

    def test_no_value_renders_as_nothing(self) -> None:
        self.assertEqual(format_amount(None, "USD"), "")

    def test_a_round_trip_survives(self) -> None:
        self.assertEqual(to_amount(format_amount(1234.56, "USD")), 1234.56)
        self.assertEqual(to_amount(format_amount(-1234.56, "USD")), -1234.56)
        self.assertEqual(to_amount(format_amount(1234.56, "CAD")), 1234.56)

    def test_units_are_trimmed_not_padded(self) -> None:
        self.assertEqual(format_units(12.345), "12.345")
        self.assertEqual(format_units(100), "100")
        self.assertEqual(format_units(0), "0")
        self.assertEqual(format_units(None), "")


if __name__ == "__main__":
    unittest.main()
