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
    alignment_faults,
    band_on,
    basic_pay_table,
    effective_date,
    grade_in_cell,
    missing_upper_table,
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

    def test_reads_a_grade_the_page_hangs_a_footnote_on(self) -> None:
        # The live enlisted page prints "E-9 (Notes 2 & 3)" and "E-1 (Notes 4 &
        # 5)" in the pay grade column, and the cell collapses to this once the
        # markup between the two is dropped. Read strictly, both rows vanish --
        # the top and the bottom of the enlisted scale -- and a run then reports
        # that DFAS publishes no rate for the grade, which sends somebody to
        # dfas.mil to look for a row that is printed right there.
        self.assertEqual(grade_in_cell(text="E-9(Notes 2 & 3)"), "E-9")
        self.assertEqual(grade_in_cell(text="E-1 (Notes 4 & 5)"), "E-1")
        self.assertEqual(grade_in_cell(text="E-7"), "E-7")

    def test_a_footnote_does_not_make_a_grade_out_of_prose(self) -> None:
        # Stripping the reference must not turn a note or a header into a row.
        self.assertIsNone(grade_in_cell(text="Cumulative Years of Service (Note 1)"))
        self.assertIsNone(grade_in_cell(text="NOTE 4. Must have 4 months (or more)"))

    def test_the_config_reader_stays_strict(self) -> None:
        # Only the table cell tolerates a footnote. A config file saying
        # "E-9 (Notes 2 & 3)" is a member typing something odd, not a page.
        self.assertIsNone(normalize_grade(rank="E-9 (Notes 2 & 3)"))

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

    def test_reads_every_grade_the_page_publishes(self) -> None:
        # Nine, and the two that carry footnote references are the two that used
        # to go missing. Asserted on the whole set rather than on E-9 alone
        # because the symptom was a short table that still looked like a table.
        self.assertEqual(
            sorted(self.table),
            ["E-1", "E-2", "E-3", "E-4", "E-5", "E-6", "E-7", "E-8", "E-9"],
        )
        self.assertEqual(self.table["E-9"]["Over 40"], 10729.20)
        self.assertEqual(self.table["E-1"]["2 or less"], 2407.20)

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


class AlignmentTests(unittest.TestCase):
    """
    The failure the fixtures cannot show, because they are reconstructions.

    Columns are matched from the right, so one column the page grew after the
    last band moves every rate one place. What comes out is not out of range,
    not missing and not zero -- it is a real published figure for a seniority
    the member does not have, and it prices an accrual and gets stored looking
    exactly like an answer. These tests are the standing check on that, and they
    assert the harm as well as the detection: a test that only proved the fault
    was reported would not show why reporting it matters.
    """

    def _shifted(self) -> str:
        # One extra cell after the last band on every row, which is the shape of
        # the change nobody would notice DFAS making.
        return ENLISTED.read_text(encoding="utf-8").replace(
            "</tr>", "<td>&nbsp;</td></tr>"
        )

    def test_the_published_fixtures_line_up(self) -> None:
        # Including the prior-service page, whose second table heads its columns
        # with no "Pay Grade" cell at all. Right-anchoring is there for that, so
        # the check must not read it as a fault.
        for fixture in (ENLISTED, PRIOR_SERVICE):
            html = fixture.read_text(encoding="utf-8")
            self.assertEqual(alignment_faults(html=html), [], fixture.name)

    def test_a_trailing_column_shifts_every_rate_by_one_band(self) -> None:
        # The harm, stated. E-7 at "Over 10" comes back as the "Over 12" rate:
        # $291.30 a month too much, and a figure the page really does print.
        shifted = basic_pay_table(html=self._shifted())
        self.assertEqual(shifted["E-7"]["Over 10"], 5591.70)
        self.assertEqual(_enlisted()["E-7"]["Over 12"], 5591.70)

    def test_a_trailing_column_is_reported(self) -> None:
        faults = alignment_faults(html=self._shifted())

        self.assertTrue(faults)
        self.assertTrue(any(fault.startswith("E-7 carries a rate") for fault in faults))

    def test_an_extra_label_column_is_not_a_fault(self) -> None:
        # The guard against crying wolf, and the reason the check asks what is
        # in the cell rather than how many there are. A column between the grade
        # and the first band widens the row exactly as much as a trailing one
        # does, but moves nothing the match consumes -- and the page has already
        # varied its leading cells between its own two tables. What separates
        # the two is that this one leaves something that is not money there.
        page = """
        <table>
          <tr><th>Pay Grade</th><th>Note</th>
              <th>2 or less</th><th>Over 2</th><th>Over 3</th></tr>
          <tr><td>E-5</td><td>&nbsp;</td>
              <td>$1.00</td><td>$2.00</td><td>$3.00</td></tr>
        </table>
        """

        self.assertEqual(alignment_faults(html=page), [])
        self.assertEqual(
            basic_pay_table(html=page),
            {"E-5": {"2 or less": 1.00, "Over 2": 2.00, "Over 3": 3.00}},
        )

    def test_a_header_that_skips_a_band_is_reported(self) -> None:
        # Bands are printed in order and unbroken. A header holding "Over 2" and
        # then "Over 6" did not come off one header row, so the columns beneath
        # it are not the columns it names.
        page = """
        <table>
          <tr><th>Pay Grade</th><th>2 or less</th><th>Over 2</th><th>Over 6</th></tr>
          <tr><td>E-5</td><td>$1.00</td><td>$2.00</td><td>$3.00</td></tr>
        </table>
        """
        faults = alignment_faults(html=page)

        self.assertEqual(len(faults), 1)
        self.assertIn("skips or repeats", faults[0])

    def test_a_page_that_is_not_a_pay_table_reports_nothing(self) -> None:
        # There is no alignment to fault. An error page already has its own
        # message, and two complaints about one cause is one too many.
        self.assertEqual(
            alignment_faults(html="<html><body>Access Denied</body></html>"), []
        )


class SplitTableTests(unittest.TestCase):
    def test_both_fixtures_carry_the_half_past_twenty_years(self) -> None:
        for fixture in (ENLISTED, PRIOR_SERVICE):
            table = basic_pay_table(html=fixture.read_text(encoding="utf-8"))
            self.assertFalse(missing_upper_table(table=table), fixture.name)

    def test_a_page_read_as_one_table_is_reported(self) -> None:
        # The naive parse, which caps everyone at eighteen years of service and
        # says nothing about it. Nothing it read is wrong; it is short.
        html = ENLISTED.read_text(encoding="utf-8")
        first = html[: html.find("</table>") + len("</table>")]
        table = basic_pay_table(html=first)

        self.assertTrue(missing_upper_table(table=table))
        self.assertEqual(table["E-7"]["Over 18"], 6177.30)
        self.assertNotIn("Over 20", table["E-7"])

    def test_an_empty_page_is_not_reported_as_a_half_read_one(self) -> None:
        # A page that parsed to nothing at all is a different failure with its
        # own message, and it is not made clearer by adding this one to it.
        self.assertFalse(missing_upper_table(table={}))


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
