"""The published pay tables, and the service date that picks a column out of one.

Two things here are worth more than the rest. The tables are split in half at
twenty years, so a parser that reads one table caps everyone at eighteen years
of service and says nothing about it. And "over N years" is a strict
inequality -- DFAS spells it out on the prior-service page, "over 4 years (i.e.,
at least 4 years and 1 day)" -- so the anniversary itself is still the band
below, which is exactly the sort of boundary that gets a member paid at the
wrong rate for a month and never looks wrong.

All four fixtures are now the pages as DFAS serves them, trimmed to their two
tables. None is a reconstruction any more, and the two swaps are why several of
the tests below exist. The enlisted reconstruction was right about every rate
and wrong about the markup in two ways, and the parser passed against it while
reading nothing whatever off the real page. The prior-service one was weaker
still: its dollar figures were invented outright, so nothing that quoted them
was testing anything.

Having all four also shows something one page cannot. DFAS does not mark up its
own four pages alike -- the officer pages write "<b>Over 10</b>" and the
enlisted and warrant pages stack it over a line break -- and only the officer
page footnotes every grade rather than two of them. A parser checked against a
single page is checked against one of two spellings and one of two habits.

Nothing here touches the network or the real config file.
"""

import datetime as dt
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from helpers.dfas import (
    BANDS,
    alignment_faults,
    band_on,
    basic_pay_table,
    effective_date,
    grade_order,
    missing_upper_table,
    monthly_basic_pay,
    normalize_grade,
    table_for,
)
from helpers.tsp import to_number

FIXTURES = Path(__file__).resolve().parent
ENLISTED = FIXTURES / "dfas_basic_pay_em.html"
PRIOR_SERVICE = FIXTURES / "dfas_basic_pay_co_fe.html"
OFFICERS = FIXTURES / "dfas_basic_pay_co.html"
WARRANTS = FIXTURES / "dfas_basic_pay_wo.html"


def _enlisted() -> dict[str, dict[str, float]]:
    return basic_pay_table(html=ENLISTED.read_text(encoding="utf-8"))


def _cell_texts(html: str) -> set[str]:
    """Every table cell's text, as the parser reads it."""

    soup = BeautifulSoup(markup=html, features="html.parser")

    return {
        cell.get_text(strip=True)
        for table in soup.find_all(name="table")
        for cell in table.find_all(name=["th", "td"])
    }


class GradeSpellingTests(unittest.TestCase):
    def test_accepts_the_spellings_a_config_file_carries(self) -> None:
        # A hyphen is not worth refusing a run over.
        for written in ("E-5", "E5", "e5", "  e-5  "):
            self.assertEqual(normalize_grade(rank=written), "E-5")

    def test_keeps_the_prior_service_suffix(self) -> None:
        self.assertEqual(normalize_grade(rank="o3e"), "O-3E")

    def test_reads_a_grade_the_page_footnotes(self) -> None:
        # Exactly the two grades whose rates come with conditions carry a note
        # marker, and reading the cell literally dropped both of them -- E-9
        # silently, which is the worst way for a senior member's accrual to be
        # wrong, because "no rate published" looks like an answer.
        self.assertEqual(normalize_grade(rank="E-9(Notes 2 & 3)"), "E-9")
        self.assertEqual(normalize_grade(rank="E-1 (Notes 4 & 5)"), "E-1")

    def test_a_note_does_not_make_a_grade_out_of_prose(self) -> None:
        # Only a trailing parenthesis goes. The refusal to guess at rank names
        # is the rule the trimming must not quietly widen.
        self.assertIsNone(normalize_grade(rank="Sergeant (Note 1)"))
        self.assertIsNone(normalize_grade(rank="Cumulative Years of Service(Note 1)"))

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

    def test_every_enlisted_grade_is_carried(self) -> None:
        # Nine grades, and the two the served page footnotes are the two that
        # went missing. Asserting the whole set rather than a sample is the
        # point: a grade dropped from the parse is indistinguishable from a
        # grade the page publishes no rate for, so nothing else would say.
        self.assertEqual(
            sorted(self.table),
            ["E-1", "E-2", "E-3", "E-4", "E-5", "E-6", "E-7", "E-8", "E-9"],
        )

    def test_a_band_heading_split_over_a_line_break_is_still_that_band(self) -> None:
        # How the served page writes its headings: the word and the number are
        # stacked, so reading the cell as text returns them run together. This
        # matched no label, so no header row was found, so basic_pay_table
        # skipped the table -- and a page of perfectly good rates parsed to {}.
        stacked = """
        <table>
          <tr><td>Pay Grade</td><td><b>Over</b><br/>10</td>
              <td><b>Over</b><br/>12</td></tr>
          <tr><td>E-7</td><td>5,300.40</td><td>5,591.70</td></tr>
        </table>
        """

        table = basic_pay_table(html=stacked)

        # Canonically spelled on the way out, whatever the markup did, because
        # band_on names the column it wants and has to find it.
        self.assertEqual(table["E-7"]["Over 10"], 5300.40)
        self.assertEqual(table["E-7"]["Over 12"], 5591.70)

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
        # The four fixtures head their tables differently, because DFAS does:
        # a spanning caption row above the labels on some, a "Pay Grade" cell
        # that is present in one half and not the other. Columns are matched
        # from the right so none of that reaches the rates.
        prior = basic_pay_table(html=PRIOR_SERVICE.read_text(encoding="utf-8"))
        self.assertEqual(prior["O-3E"]["Over 4"], 7382.70)
        self.assertEqual(prior["O-3E"]["Over 40"], 9609.60)

    def test_the_prior_service_rates_start_at_over_four(self) -> None:
        # The columns are all there -- "2 or less" through "Over 18", as on
        # every other page -- but no prior-service rate exists below "Over 4",
        # because these rates protect a new officer who already has four years'
        # enlisted or warrant service. So the bands are absent from the parse
        # while the headings are present in the markup, and those are different
        # facts. The fixture this replaced was invented and had neither.
        prior = basic_pay_table(html=PRIOR_SERVICE.read_text(encoding="utf-8"))

        self.assertNotIn("2 or less", prior["O-3E"])
        self.assertNotIn("Over 3", prior["O-3E"])
        self.assertEqual(prior["O-3E"]["Over 4"], 7382.70)
        self.assertEqual(sorted(prior, key=grade_order), ["O-1E", "O-2E", "O-3E"])

    def test_the_word_blank_is_not_a_rate(self) -> None:
        # This page writes the literal word "blank" into every cell with no
        # rate; the other three leave the cell empty. It costs nothing today
        # because to_number() returns None for it exactly as for "", so the
        # band is absent either way -- but that is luck, not design, and it is
        # the sort of thing only the served page could have taught. Pinned so
        # that anything later treating a non-empty cell as a published figure
        # fails here rather than storing the string where a rate belongs.
        page = PRIOR_SERVICE.read_text(encoding="utf-8")

        self.assertIn("blank", _cell_texts(html=page))
        self.assertIsNone(to_number(text="blank"))

        for band in ("2 or less", "Over 2", "Over 3"):
            with self.subTest(band=band):
                self.assertNotIn(band, basic_pay_table(html=page)["O-3E"])

        # And only this page does it, so the others are not silently relying
        # on the same accident. Asked of the cells rather than of the file,
        # which also says the word in its header comment.
        for other in (ENLISTED, OFFICERS, WARRANTS):
            with self.subTest(page=other.name):
                texts = _cell_texts(html=other.read_text(encoding="utf-8"))
                self.assertNotIn("blank", texts)
                self.assertIn("", texts)


class OfficerAndWarrantPageTests(unittest.TestCase):
    """
    The three pages that are not the enlisted one, all served rather than made up.

    Worth having separately from the enlisted tests because the four pages are
    not marked up alike, and a parser checked against one of them is checked
    against one of two spellings and one of two footnote habits.
    """

    def setUp(self) -> None:
        self.officers = OFFICERS.read_text(encoding="utf-8")
        self.warrants = WARRANTS.read_text(encoding="utf-8")

    def test_every_officer_grade_is_carried(self) -> None:
        # Ten of ten, and every one of them footnoted on the page -- "O-10
        # (Note 4)", "O-3 (Notes 5 & 6)", "O-1 (Notes 5, 6 & 7)". Read
        # literally this page yields no grades whatever, so unlike the
        # enlisted page, where the same bug cost the top and bottom rows,
        # here it would have cost all of them.
        table = basic_pay_table(html=self.officers)

        self.assertEqual(
            sorted(table, key=grade_order),
            ["O-1", "O-2", "O-3", "O-4", "O-5", "O-6", "O-7", "O-8", "O-9", "O-10"],
        )

    def test_every_warrant_grade_is_carried(self) -> None:
        table = basic_pay_table(html=self.warrants)

        self.assertEqual(
            sorted(table, key=grade_order), ["W-1", "W-2", "W-3", "W-4", "W-5"]
        )

    def test_the_two_heading_spellings_are_both_the_same_column(self) -> None:
        # DFAS does not mark up its own four pages the same way. The officer
        # page writes "<b>Over 10</b>" on one line; the warrant page stacks it
        # as "<b>Over</b><br/><b>10</b>", which reads as "Over10". Matching the
        # label with its spacing removed is what makes both of them "Over 10",
        # and testing only one page would leave the other spelling unguarded.
        self.assertIn("<b>Over 10</b>", self.officers)
        self.assertNotIn("<b>Over 10</b>", self.warrants)

        self.assertEqual(basic_pay_table(html=self.officers)["O-4"]["Over 10"], 9420.00)
        self.assertEqual(basic_pay_table(html=self.warrants)["W-3"]["Over 10"], 6910.50)

    def test_a_grade_nobody_holds_early_is_blank_rather_than_zero(self) -> None:
        # O-9, O-10 and W-5 are empty across the whole first table. That is the
        # page being right rather than short: those grades do not exist under
        # twenty years, and a zero would price a general's contribution at
        # nothing and look like an answer.
        officers = basic_pay_table(html=self.officers)
        warrants = basic_pay_table(html=self.warrants)

        for grade, table in (("O-9", officers), ("O-10", officers), ("W-5", warrants)):
            with self.subTest(grade=grade):
                self.assertNotIn("2 or less", table[grade])
                self.assertNotIn("Over 18", table[grade])
                self.assertIn("Over 20", table[grade])

    def test_both_halves_arrived_on_every_page(self) -> None:
        for name, html in (
            ("officers", self.officers),
            ("warrants", self.warrants),
            ("prior service", PRIOR_SERVICE.read_text(encoding="utf-8")),
        ):
            with self.subTest(page=name):
                table = basic_pay_table(html=html)
                self.assertFalse(missing_upper_table(table=table))
                self.assertEqual(alignment_faults(html=html), [])
                self.assertEqual(effective_date(html=html), dt.date(2026, 1, 1))

    def test_the_published_cap_is_taken_as_printed(self) -> None:
        # O-8 upward tops out at the Level II limit, and the page has already
        # applied it. Re-capping here would either double it or hardcode a
        # dollar figure that goes stale every January.
        table = basic_pay_table(html=self.officers)

        self.assertEqual(table["O-8"]["Over 40"], 18999.90)
        self.assertEqual(table["O-10"]["Over 40"], 18999.90)

    def test_each_page_carries_only_its_own_family(self) -> None:
        # table_for() sends a grade to one of four pages, so a page that also
        # carried a neighbouring family would make that routing untestable.
        self.assertEqual(
            {grade[0] for grade in basic_pay_table(html=self.officers)}, {"O"}
        )
        self.assertEqual(
            {grade[0] for grade in basic_pay_table(html=self.warrants)}, {"W"}
        )


class GradeOrderTests(unittest.TestCase):
    def test_double_digit_grades_sort_after_single_digit_ones(self) -> None:
        # "O-10" between "O-1" and "O-2" is what sorting the strings gives, and
        # the officer tables go that high. A grid printed to be read against the
        # published page has to be in the published page's order.
        grades = ["O-10", "O-1", "O-2", "O-9", "E-9", "W-5", "O-3E"]

        self.assertEqual(
            sorted(grades, key=grade_order),
            ["E-9", "O-1", "O-2", "O-3E", "O-9", "O-10", "W-5"],
        )

    def test_the_prior_service_rates_follow_the_plain_ones(self) -> None:
        self.assertEqual(sorted(["O-3E", "O-3"], key=grade_order), ["O-3", "O-3E"])


class AlignmentTests(unittest.TestCase):
    """
    The one way this parser can be wrong and still look right.

    Rates are matched from the right, so a column the page grows after the last
    band moves every figure one place. What comes back is a real published rate
    for the wrong time in service -- not missing, not zero, not out of range --
    and it goes on to price an accrual and be stored as a mark.

    Every page here is the served page with one thing changed, because that is
    the only honest way to ask the question: the fault is in the shape of the
    markup, so a hand-written table would be testing the shape the test author
    imagined rather than the one DFAS publishes.
    """

    def setUp(self) -> None:
        self.html = ENLISTED.read_text(encoding="utf-8")

    def grown(self, text: str, trailing: bool) -> str:
        """The served page with one cell added to every row of every table."""

        soup = BeautifulSoup(markup=self.html, features="html.parser")

        for element in soup.find_all(name="table"):
            for row in element.find_all(name="tr"):
                cell = soup.new_tag(name="td")
                cell.string = text

                if trailing:
                    row.append(cell)

                else:
                    row.insert(0, cell)

        return str(object=soup)

    def test_the_page_as_served_lines_up_with_its_headings(self) -> None:
        self.assertEqual(alignment_faults(html=self.html), [])

    def test_a_trailing_column_is_caught(self) -> None:
        # Silent without this. E-7 at "Over 10" comes back as $5,591.70, which
        # is E-7 at "Over 12" -- a rate a real member is really paid, six years
        # further into a career than the one asking.
        shifted: str = self.grown(text="Note 6", trailing=True)

        self.assertEqual(basic_pay_table(html=shifted)["E-7"]["Over 10"], 5591.70)

        faults: list[str] = alignment_faults(html=shifted)

        self.assertTrue(faults)
        self.assertIn("outside the 11 columns matched", faults[0])

    def test_a_leading_column_is_left_to_the_caller(self) -> None:
        # Not a fault, and not a shift: the rates still end where they ended.
        # The row simply stops naming a grade in its first cell, so the parse
        # produces nothing at all -- which the caller already reports as a page
        # that is not the pay table. Firing here as well would file a loud
        # failure under the name of the silent one.
        widened: str = self.grown(text="", trailing=False)

        self.assertEqual(basic_pay_table(html=widened), {})
        self.assertEqual(alignment_faults(html=widened), [])

    def test_a_header_that_skips_a_band_is_refused_once(self) -> None:
        # The published columns run in order and unbroken. A header missing one
        # was assembled out of something other than a single header row, so the
        # columns beneath it are not the ones it names -- said once for the
        # table rather than once for each row under it.
        page = """
        <table>
          <tr><th>Pay Grade</th><th>Over 2</th><th>Over 4</th></tr>
          <tr><td>E-5</td><td>$1.00</td><td>$2.00</td></tr>
          <tr><td>E-6</td><td>$3.00</td><td>$4.00</td></tr>
        </table>
        """

        faults: list[str] = alignment_faults(html=page)

        self.assertEqual(len(faults), 1)
        self.assertIn("skips or repeats", faults[0])

    def test_a_page_with_no_pay_table_in_it_has_no_faults(self) -> None:
        # Nothing was matched, so nothing was matched wrongly.
        self.assertEqual(alignment_faults(html="<p>Access Denied</p>"), [])


class SplitTableTests(unittest.TestCase):
    """Whether both halves of the page arrived, which is short rather than wrong."""

    def setUp(self) -> None:
        self.html = ENLISTED.read_text(encoding="utf-8")

    def test_the_page_as_served_carries_both_halves(self) -> None:
        self.assertFalse(missing_upper_table(table=basic_pay_table(html=self.html)))

    def test_one_table_of_the_two_is_reported(self) -> None:
        soup = BeautifulSoup(markup=self.html, features="html.parser")
        soup.find_all(name="table")[-1].decompose()
        half: dict[str, dict[str, float]] = basic_pay_table(html=str(object=soup))

        # Right as far as it goes, and eighteen years is where it stops.
        self.assertEqual(half["E-7"]["Over 10"], 5300.40)
        self.assertNotIn("Over 20", half["E-7"])
        self.assertTrue(missing_upper_table(table=half))

    def test_an_empty_page_is_not_reported_as_a_half_read_one(self) -> None:
        # A different failure, and one that already has its own message. Saying
        # both would point at the split when the page is not a pay table at all.
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
