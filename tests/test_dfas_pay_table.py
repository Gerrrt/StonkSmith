"""The published pay tables, and the service date that picks a column out of one.

Two things here are worth more than the rest. The tables are split in half at
twenty years, so a parser that reads one table caps everyone at eighteen years
of service and says nothing about it. And "over N years" is a strict
inequality -- DFAS spells it out on the prior-service page, "over 4 years (i.e.,
at least 4 years and 1 day)" -- so the anniversary itself is still the band
below, which is exactly the sort of boundary that gets a member paid at the
wrong rate for a month and never looks wrong.

The fixtures are reconstructions, not saved responses; each says so at the top
and says why. Nothing here touches the network or the real config file.
"""

import datetime as dt
import unittest
from pathlib import Path

from helpers.dfas import (
    BANDS,
    band_on,
    basic_pay_table,
    effective_date,
    monthly_basic_pay,
    normalize_grade,
    table_for,
)

FIXTURES = Path(__file__).resolve().parent
ENLISTED = FIXTURES / "dfas_basic_pay_em.html"
PRIOR_SERVICE = FIXTURES / "dfas_basic_pay_co_fe.html"


def _enlisted() -> dict[str, dict[str, float]]:
    return basic_pay_table(html=ENLISTED.read_text(encoding="utf-8"))


class GradeSpellingTests(unittest.TestCase):
    def test_accepts_the_spellings_a_config_file_carries(self) -> None:
        # A hyphen is not worth refusing a run over.
        for written in ("E-5", "E5", "e5", "  e-5  "):
            self.assertEqual(normalize_grade(rank=written), "E-5")

    def test_keeps_the_prior_service_suffix(self) -> None:
        self.assertEqual(normalize_grade(rank="o3e"), "O-3E")

    def test_refuses_a_rank_title(self) -> None:
        # "Sergeant" is a different pay grade in different services, so there
        # is no honest way to turn one into the other.
        self.assertIsNone(normalize_grade(rank="Sergeant"))
        self.assertIsNone(normalize_grade(rank=""))

    def test_refuses_a_grade_number_nobody_holds(self) -> None:
        # Caught by name here rather than missed in the table, where it would
        # read as DFAS not publishing the grade.
        self.assertIsNone(normalize_grade(rank="E-15"))
        self.assertIsNone(normalize_grade(rank="W-9"))
        self.assertIsNone(normalize_grade(rank="O-11"))

    def test_refuses_prior_service_where_it_does_not_exist(self) -> None:
        # The prior-service rates protect a *new* officer's pay, so they stop
        # at O-3E and never applied to enlisted or warrant grades at all.
        self.assertIsNone(normalize_grade(rank="E-5E"))
        self.assertIsNone(normalize_grade(rank="W-2E"))
        self.assertIsNone(normalize_grade(rank="O-4E"))

    def test_picks_the_page_a_grade_lives_on(self) -> None:
        self.assertEqual(table_for(rank="E-5"), "EM")
        self.assertEqual(table_for(rank="O-3"), "CO")
        self.assertEqual(table_for(rank="O-3E"), "CO_FE")
        self.assertEqual(table_for(rank="W-2"), "WO")
        self.assertIsNone(table_for(rank="Chief"))


class BandTests(unittest.TestCase):
    def test_the_anniversary_is_still_the_band_below(self) -> None:
        # The whole reason BASD is configured rather than a years figure. On
        # the tenth anniversary a member has ten years, not over ten.
        basd = dt.date(2016, 3, 14)
        self.assertEqual(band_on(basd=basd, day=dt.date(2026, 3, 14)), "Over 8")
        self.assertEqual(band_on(basd=basd, day=dt.date(2026, 3, 15)), "Over 10")

    def test_two_years_exactly_is_not_over_two(self) -> None:
        basd = dt.date(2024, 8, 8)
        self.assertEqual(band_on(basd=basd, day=dt.date(2026, 8, 8)), "2 or less")
        self.assertEqual(band_on(basd=basd, day=dt.date(2026, 8, 9)), "Over 2")

    def test_the_day_of_enlistment_is_the_first_band(self) -> None:
        basd = dt.date(2026, 8, 8)
        self.assertEqual(band_on(basd=basd, day=basd), "2 or less")

    def test_a_long_career_stops_at_the_last_column(self) -> None:
        # There is no "Over 42", so a 41-year member is paid at "Over 40".
        basd = dt.date(1985, 1, 1)
        self.assertEqual(band_on(basd=basd, day=dt.date(2026, 1, 2)), "Over 40")

    def test_a_leap_day_service_date_still_crosses(self) -> None:
        # 29 February exists one year in four, so the anniversary falls back to
        # the 28th rather than never arriving.
        basd = dt.date(2020, 2, 29)
        self.assertEqual(band_on(basd=basd, day=dt.date(2026, 2, 28)), "Over 4")
        self.assertEqual(band_on(basd=basd, day=dt.date(2026, 3, 1)), "Over 6")


class PayTableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = _enlisted()

    def test_merges_both_published_tables(self) -> None:
        # The page splits its columns at twenty years. Reading only the first
        # table would cap every grade at "Over 18" and look like it worked.
        self.assertEqual(len(self.table["E-7"]), len(BANDS))
        self.assertEqual(self.table["E-7"]["2 or less"], 3932.10)
        self.assertEqual(self.table["E-7"]["Over 40"], 7067.40)

    def test_a_blank_cell_is_absent_rather_than_zero(self) -> None:
        # E-9 publishes no rate below "Over 10", because nobody gets there that
        # fast. A zero would value a senior member's contribution at nothing
        # and read as an answer rather than as a grade that cannot be held.
        self.assertNotIn("2 or less", self.table["E-9"])
        self.assertNotIn("Over 8", self.table["E-9"])
        self.assertEqual(self.table["E-9"]["Over 10"], 6910.20)

    def test_reads_the_effective_date(self) -> None:
        self.assertEqual(
            effective_date(html=ENLISTED.read_text(encoding="utf-8")),
            dt.date(2026, 1, 1),
        )

    def test_ignores_a_page_that_is_not_a_pay_table(self) -> None:
        denied = "<html><body>Access Denied</body></html>"

        self.assertEqual(basic_pay_table(html=denied), {})
        self.assertIsNone(effective_date(html=denied))

    def test_a_stray_pair_of_band_words_does_not_pass_for_the_header(self) -> None:
        # The header is the row carrying the most band labels, not the first
        # row carrying a couple. Taking the first here would match every rate
        # against two columns instead of three -- which reads as a grade with
        # almost no published pay rather than as a table read wrongly.
        page = """
        <table>
          <tr><td>See Over 20 and Over 22 below</td></tr>
          <tr><th>Pay Grade</th><th>2 or less</th><th>Over 2</th><th>Over 3</th></tr>
          <tr><td>E-5</td><td>$1.00</td><td>$2.00</td><td>$3.00</td></tr>
        </table>
        """

        self.assertEqual(
            basic_pay_table(html=page),
            {"E-5": {"2 or less": 1.00, "Over 2": 2.00, "Over 3": 3.00}},
        )

    def test_a_lone_band_word_is_not_a_header_at_all(self) -> None:
        page = (
            "<table><tr><td>Over 20</td></tr>"
            "<tr><td>E-5</td><td>$1.00</td></tr></table>"
        )

        self.assertEqual(basic_pay_table(html=page), {})

    def test_does_not_depend_on_the_leading_header_cells(self) -> None:
        # The two fixtures head their tables differently on purpose: a spanning
        # row above the labels in one, a single row in the other, and a missing
        # "Pay Grade" cell in the second half of the other. Columns are matched
        # from the right so none of that reaches the rates.
        prior = basic_pay_table(html=PRIOR_SERVICE.read_text(encoding="utf-8"))
        self.assertEqual(prior["O-3E"]["Over 4"], 7100.00)
        self.assertEqual(prior["O-3E"]["Over 40"], 7900.00)
        self.assertNotIn("2 or less", prior["O-3E"])


class MonthlyPayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = _enlisted()

    def test_pairs_a_service_date_with_a_rate(self) -> None:
        basd = dt.date(2016, 3, 14)
        self.assertEqual(
            monthly_basic_pay(
                table=self.table, grade="E-7", basd=basd, day=dt.date(2026, 3, 15)
            ),
            5300.40,
        )

    def test_a_band_crossed_mid_window_changes_the_rate(self) -> None:
        # A member does not get one rate for a quarter. This is why time in
        # service is recomputed at every posting date rather than once.
        basd = dt.date(2016, 3, 14)
        before = monthly_basic_pay(
            table=self.table, grade="E-7", basd=basd, day=dt.date(2026, 2, 28)
        )
        after = monthly_basic_pay(
            table=self.table, grade="E-7", basd=basd, day=dt.date(2026, 4, 30)
        )
        self.assertEqual(before, 5135.70)
        self.assertEqual(after, 5300.40)

    def test_an_unpublished_rate_is_none_rather_than_zero(self) -> None:
        # An E-9 with two years of service does not exist, and the table says
        # so by leaving the cell empty.
        self.assertIsNone(
            monthly_basic_pay(
                table=self.table,
                grade="E-9",
                basd=dt.date(2025, 1, 1),
                day=dt.date(2026, 1, 1),
            )
        )

    def test_a_grade_the_page_does_not_carry_is_none(self) -> None:
        self.assertIsNone(
            monthly_basic_pay(
                table=self.table,
                grade="O-3",
                basd=dt.date(2016, 1, 1),
                day=dt.date(2026, 1, 1),
            )
        )


if __name__ == "__main__":
    unittest.main()
