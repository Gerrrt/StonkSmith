# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""
dfas.py: Helpers for the published military basic pay tables.

TSP values an account as units x share price, and units only move when a
transaction posts. For a uniformed member the transactions that move them
between statements are almost entirely one thing: the monthly contribution. So
the gap between "the mark is exact" and "the mark is short by every
contribution since the last statement" can be closed from public data, the same
way the share price already is.

DFAS publishes basic pay as four HTML tables -- enlisted, commissioned
officers, commissioned officers with over four years of enlisted or warrant
service, and warrant officers. A pay grade and a time in service pick exactly
one monthly figure out of them, and a member who knows what fraction of basic
pay they and their agency contribute knows the dollars that buy units each
month.

Everything here is pure -- HTML in, numbers out. Nothing fetches, nothing
caches, nothing writes. The one impure part, getting the page, lives in
brokers/tsp/broker.py beside the share price download it is modelled on.

Two things about the published tables that a naive reader gets wrong:

* There are *two* tables per page, not one. The first carries "2 or less"
  through "Over 18", the second "Over 20" through "Over 40". A grade's rates
  are split across both, so reading only the first silently caps everyone at
  eighteen years of service.
* A cell with no rate is empty, not zero. E-9 has no rate below "Over 10",
  because nobody reaches E-9 that fast. Reading the blank as $0.00 would report
  a senior enlisted member as contributing nothing, which looks like an answer.

Both of those fail loudly once you know to look. The one that does not is the
match itself: columns are taken from the right, so a column the page grew after
the last band moves every rate one place, and a rate one place out is a genuine
published figure for the wrong time in service. Nothing downstream can tell it
from the right one. alignment_faults() exists to ask that question of the page
directly, because the fixtures here are reconstructions of the real markup and a
test against them cannot ask it -- see docs/live-verification.md.
"""

import datetime as dt
import re

from bs4 import BeautifulSoup, Tag

from helpers.tsp import to_number

#: Path segment per grade family, hung off the configured base URL, and keyed by
#: the name used throughout this module and in the cache file name. The base
#: itself lives in etc.config beside the share price URL, because where to
#: download from is configuration; what the columns mean is not.
TABLE_PATHS: dict[str, str] = {
    "EM": "EM/",
    "CO": "CO/",
    "CO_FE": "CO_FE/",
    "WO": "WO/",
}

#: What each family covers, for error messages that say which page to look at.
TABLE_NAMES: dict[str, str] = {
    "EM": "enlisted members",
    "CO": "commissioned officers",
    "CO_FE": "commissioned officers with over 4 years enlisted or warrant service",
    "WO": "warrant officers",
}

#: The years-of-service columns, in the order the tables print them, paired with
#: the number of years each one is "over". The first is the only one that is not
#: an "over" band: it is everyone who has not yet passed two years.
BANDS: tuple[tuple[str, int], ...] = (
    ("2 or less", 0),
    ("Over 2", 2),
    ("Over 3", 3),
    ("Over 4", 4),
    ("Over 6", 6),
    ("Over 8", 8),
    ("Over 10", 10),
    ("Over 12", 12),
    ("Over 14", 14),
    ("Over 16", 16),
    ("Over 18", 18),
    ("Over 20", 20),
    ("Over 22", 22),
    ("Over 24", 24),
    ("Over 26", 26),
    ("Over 28", 28),
    ("Over 30", 30),
    ("Over 32", 32),
    ("Over 34", 34),
    ("Over 36", 36),
    ("Over 38", 38),
    ("Over 40", 40),
)

#: The first band, which every grade has and which nothing is "over".
BASE_BAND: str = BANDS[0][0]

#: Band labels, for recognising a header row without caring what the page calls
#: the columns around it.
BAND_LABELS: frozenset[str] = frozenset(label for label, _years in BANDS)

#: Where each band sits in the published order. A header row's labels should be a
#: contiguous run of these: the page splits its columns in two and prints each
#: half in order, so a set of labels that skips or repeats one did not come off a
#: single header row and the columns under it are not what they are taken for.
BAND_ORDER: dict[str, int] = {
    label: index for index, (label, _years) in enumerate(iterable=BANDS)
}

#: The last column of the first published table. A parse that produced nothing
#: above this read one of the two tables and not both.
SPLIT_BAND: str = "Over 18"

#: A published rate, as the tables print it: dollars and cents, with or without
#: the sign and the thousands separator.
#:
#: Deliberately not to_number(), which is the statement reader's and finds the
#: "-7" inside "E-7". That is right where every token it sees is already known to
#: be money and wrong for asking whether a cell *is* money -- and this pattern is
#: only ever used for that question, on the one cell that decides whether the
#: columns were matched where the page put them.
RATE = re.compile(pattern=r"^\$?\s*\d[\d,]*\.\d{2}\b")

#: A pay grade as the tables write it: "E-7", "O-3", "W-5", and the "E" suffix
#: that marks an officer with prior enlisted or warrant service, "O-3E". The
#: hyphen is optional here but not in the output, so a config line reading "e5"
#: still finds the row spelled "E-5".
GRADE = re.compile(pattern=r"^([EOW])-?(\d{1,2})(E?)$", flags=re.IGNORECASE)

#: A footnote reference hung off a pay grade in a table's leftmost cell. The
#: enlisted page prints "E-9 (Notes 2 & 3)" and "E-1 (Notes 4 & 5)", and once the
#: markup between the grade and the reference is dropped the cell reads
#: "E-9(Notes 2 & 3)". Nothing else can trail a grade in that column, so a
#: parenthesis there is a footnote and not part of the grade.
FOOTNOTE = re.compile(pattern=r"(?:\s*\([^)]*\))+$")

#: Highest grade number each family publishes. Bounds exist so a typo like
#: "E-15" is refused by name rather than looked up, missed, and reported as a
#: table that does not carry the grade -- which points at DFAS for a problem in
#: the config file.
GRADE_LIMITS: dict[str, int] = {"E": 9, "O": 10, "W": 5}

#: Prior-service officer rates stop at O-3E; above that the ordinary officer
#: table applies, because the special rates exist to protect a new officer's pay
#: against what they earned as a senior enlisted member.
PRIOR_SERVICE_LIMIT = 3

#: "Effective January 1, 2026", as each page heads its table. Read rather than
#: assumed: the tables change every January, and an accrual reaching back before
#: the effective date is being priced at the wrong year's rates -- which is
#: worth saying rather than hiding.
EFFECTIVE = re.compile(pattern=r"[Ee]ffective\s+([A-Z][a-z]+)\s+(\d{1,2}),?\s+(\d{4})")


def normalize_grade(rank: str) -> str | None:
    """
    Rewrite a pay grade the way the published tables spell it.

    Accepts the spellings a config file plausibly carries -- "e5", "E5", "E-5",
    with any surrounding space -- because the alternative is refusing a run over
    a hyphen. What it will not do is guess: a rank name like "Sergeant" maps to
    different grades in different services, and there is no honest way to turn
    one into a pay grade without knowing which service.
    :param rank: The grade as configured
    :return: The canonical spelling, e.g. "E-5" or "O-3E", or None when the text
        is not a pay grade at all
    :rtype: str | None
    """

    found = GRADE.match(string=rank.strip())

    if found is None:
        return None

    family: str = found.group(1).upper()
    number = int(found.group(2))
    prior: str = found.group(3).upper()

    if not 1 <= number <= GRADE_LIMITS[family]:
        return None

    # "E-5E" and "W-2E" are not grades. Only commissioned officers can hold the
    # prior-service rates, and only the first three of them.
    if prior and (family != "O" or number > PRIOR_SERVICE_LIMIT):
        return None

    return f"{family}-{number}{prior}"


def grade_in_cell(text: str) -> str | None:
    """
    Read the pay grade out of a table's leftmost cell.

    Kept apart from normalize_grade() because the two are asked different
    questions. A config line is asked whether the member typed a pay grade, and
    "Sergeant" has to come back as no. A table cell is asked which row this is,
    and the page hangs its footnote references there: the enlisted page reads
    "E-9 (Notes 2 & 3)" and "E-1 (Notes 4 & 5)" -- the top and the bottom of the
    enlisted scale, and nothing in between.

    Reading those the strict way drops both rows, and drops them quietly. What a
    run says next is that DFAS publishes no rate for the grade, followed by the
    grades it does carry -- which reads as a gap in the pay table and sends
    somebody to dfas.mil to look for a row that is sitting right there. Confirmed
    against the live page on 2026-08-10; see docs/live-verification.md.
    :param text: The cell's text, as get_text(strip=True) returns it
    :return: The canonical grade, or None when the cell does not name one
    :rtype: str | None
    """

    return normalize_grade(rank=FOOTNOTE.sub(repl="", string=text))


def table_for(rank: str) -> str | None:
    """
    Which of the four published tables carries a grade.
    :param rank: The grade as configured, in any accepted spelling
    :return: A key of TABLE_PATHS, or None when the text is not a pay grade
    :rtype: str | None
    """

    grade: str | None = normalize_grade(rank=rank)

    if grade is None:
        return None

    if grade.startswith("E"):
        return "EM"

    if grade.startswith("W"):
        return "WO"

    return "CO_FE" if grade.endswith("E") else "CO"


def anniversary(basd: dt.date, years: int) -> dt.date:
    """
    The date a service date comes round again.

    29 February falls back to the 28th, which is the only day of the year that
    does not exist in most years. Doing so makes a leap-day BASD reach each
    band on the 28th rather than on 1 March -- a day early at worst, once every
    four years, against a table whose own bands are years wide.
    :param basd: Basic Active Service Date
    :param years: How many years on
    :return: The anniversary
    :rtype: dt.date
    """

    try:
        return basd.replace(year=basd.year + years)

    except ValueError:
        return basd.replace(year=basd.year + years, day=28)


def band_on(basd: dt.date, day: dt.date) -> str:
    """
    Which years-of-service column a member sits in on a given day.

    Exact to the day, which is the whole reason BASD is configured rather than a
    years figure: the bands are crossed on an anniversary, and a member who
    crosses one mid-quarter is paid at two different rates over an accrual
    window that a single "years of service" number would flatten into one.

    Strictly greater, because "over" means over. DFAS says so itself, in the
    note on the prior-service officer table: "over 4 years (i.e., at least 4
    years and 1 day)". So the anniversary itself is still the band below, and
    the day after it is the band above.
    :param basd: Basic Active Service Date
    :param day: The date to place
    :return: A band label, e.g. "Over 12"
    :rtype: str
    """

    band: str = BASE_BAND

    for label, years in BANDS:
        if years and day > anniversary(basd=basd, years=years):
            band = label

    return band


def header_bands(rows: list[Tag]) -> tuple[int, list[str]]:
    """
    Find the row that names the columns, and read the bands off it.

    Recognised by the band labels themselves rather than by anything around
    them. The tables lead with "Cumulative Years of Service (Note 1)" and a "Pay
    Grade" column, and whether those arrive as one row or two is a detail of the
    markup -- the one thing that is stable is that the columns are called what
    the pay tables have always called them.

    The row carrying the *most* labels wins, not the first row carrying a
    couple. Taking the first would let any row that happens to hold two band
    strings -- a footnote, a nested caption, a "see Over 20" cross-reference --
    stand in for the header, and the consequence is not a parse failure: every
    rate is then matched against two columns instead of eleven, which reads as a
    grade with almost no published pay rather than as a table read wrongly.
    Preferring the maximum cannot be fooled while a real header is present, and
    it needs no threshold tuned to how many columns DFAS currently splits
    across -- which they have changed before and may change again.

    Two labels remain the floor, so a table with one incidental "Over 20" in it
    and no header at all is reported as headerless rather than parsed.
    :param rows: Every row in one table, in order
    :return: (index of the header row, the band labels it carries in order); the
        index is -1 and the list empty when no row names at least two bands
    :rtype: tuple[int, list[str]]
    """

    best: tuple[int, list[str]] = (-1, [])

    for index, row in enumerate(iterable=rows):
        labels: list[str] = [
            text
            for cell in row.find_all(name=["th", "td"])
            if (text := cell.get_text(strip=True)) in BAND_LABELS
        ]

        if len(labels) > len(best[1]):
            best = (index, labels)

    return best if len(best[1]) >= 2 else (-1, [])


def basic_pay_table(html: str) -> dict[str, dict[str, float]]:
    """
    Parse one published basic pay page into rates per grade.

    Merges every table on the page. There are two, splitting the columns at
    twenty years, and a grade's row appears in both -- so the result is built by
    updating rather than replacing, and a grade found twice ends up with all of
    its bands rather than only the later half.

    Values are matched to bands from the right. The header row carries one or
    two label cells before the first band and the data rows carry one, and which
    it is depends on how the page nests its spanning header -- but nothing
    follows the last band in either. Counting back from the end therefore aligns
    without needing to know what the leading cells are called, which is the part
    of the markup most likely to change.

    A cell with no number contributes nothing rather than a zero. That is not
    tidiness: E-9 publishes no rate below "Over 10", and a zero there would
    value a senior enlisted member's contribution at nothing and look like an
    answer rather than like the "this grade cannot hold this service" the blank
    actually means.
    :param html: The page as served
    :return: Grade mapped to band label mapped to monthly basic pay; bands with
        no published rate are absent rather than zero
    :rtype: dict[str, dict[str, float]]
    """

    soup = BeautifulSoup(markup=html, features="html.parser")
    table: dict[str, dict[str, float]] = {}

    for element in soup.find_all(name="table"):
        rows: list[Tag] = element.find_all(name="tr")
        start, bands = header_bands(rows=rows)

        if not bands:
            continue

        for row in rows[start + 1 :]:
            cells: list[str] = [
                cell.get_text(strip=True) for cell in row.find_all(name=["th", "td"])
            ]

            if not cells:
                continue

            grade: str | None = grade_in_cell(text=cells[0])

            # A footnote row, a repeated header, or anything else that is not a
            # pay grade. Skipped rather than refused: the pages carry several.
            if grade is None or len(cells) <= len(bands):
                continue

            rates: dict[str, float] = table.setdefault(grade, {})

            for offset, band in enumerate(iterable=reversed(bands)):
                value: float | None = to_number(text=cells[len(cells) - 1 - offset])

                if value is not None:
                    rates[band] = value

    return table


def alignment_faults(html: str) -> list[str]:
    """
    Report a page whose columns are not where basic_pay_table() matched them.

    Matching from the right is what lets the parser ignore how many label cells
    the page puts in front of the first band, and it is also the whole exposure:
    one unexpected column *after* the last band shifts every rate one place, and
    a rate read one place out is a real figure for the wrong seniority. It is not
    out of range, not missing, and not zero -- it looks exactly like an answer,
    and it goes on to price a contribution accrual and be stored as a mark.

    Two things are checked, and both ask whether the page still has the shape the
    match assumes rather than whether the numbers look sensible -- there is no
    sensible-looking test that a wrong band's rate would fail.

    A header's labels must be a contiguous run of the published bands. The page
    prints "2 or less" through "Over 18" and then "Over 20" through "Over 40", so
    a header that skips or repeats one was assembled out of something other than
    a single header row and the columns beneath it are not the columns named.

    And no data row may carry a rate in the cell immediately before the matched
    ones. That cell is the pay grade on a well-formed row, so finding money there
    means a published rate fell outside the columns the match consumed -- which
    is the trailing-column shift, seen directly. An *extra* cell in front of the
    grade leaves the same slot holding something that is not money, so the check
    distinguishes the shift that matters from the widening that does not.
    :param html: The page as served
    :return: One line per fault, empty when the page lines up with its headings
    :rtype: list[str]
    """

    soup = BeautifulSoup(markup=html, features="html.parser")
    faults: list[str] = []

    for element in soup.find_all(name="table"):
        rows: list[Tag] = element.find_all(name="tr")
        start, bands = header_bands(rows=rows)

        if not bands:
            continue

        first: int = BAND_ORDER[bands[0]]
        run: list[int] = list(range(first, first + len(bands)))

        if [BAND_ORDER[label] for label in bands] != run:
            faults.append(
                f"a header running {bands[0]!r} to {bands[-1]!r} skips or "
                "repeats a published band"
            )
            # Every row under it would report the same one fault differently.
            continue

        for row in rows[start + 1 :]:
            cells: list[str] = [
                cell.get_text(strip=True) for cell in row.find_all(name=["th", "td"])
            ]

            if not cells:
                continue

            grade: str | None = grade_in_cell(text=cells[0])

            # The rows basic_pay_table() reads, and only those: a footnote or a
            # repeated header is not a misaligned row, it is not a row.
            if grade is None or len(cells) <= len(bands):
                continue

            spare: str = cells[len(cells) - len(bands) - 1]

            if RATE.match(string=spare):
                faults.append(
                    f"{grade} carries a rate at {spare!r}, outside the "
                    f"{len(bands)} columns matched"
                )

    return faults


def missing_upper_table(table: dict[str, dict[str, float]]) -> bool:
    """
    Whether a parsed page yielded only the first of its two tables.

    The columns are split at twenty years across two tables, so a page that
    produced no band above "Over 18" was read as one table. Nothing already read
    is wrong -- it is short, which is the difference between this and an
    alignment fault, and why it is worth saying rather than refusing over.

    Asked of the whole page rather than of each grade. A grade DFAS drops from
    the second table would otherwise be reported every run as a page half read.
    :param table: A parsed page, as basic_pay_table() returns
    :return: True when no grade carries a band past the split, False for an empty
        page -- which is a different failure and already has its own message
    :rtype: bool
    """

    if not table:
        return False

    split: int = BAND_ORDER[SPLIT_BAND]

    return not any(
        BAND_ORDER[band] > split for rates in table.values() for band in rates
    )


def effective_date(html: str) -> dt.date | None:
    """
    The date the rates on a page took effect.

    Basic pay changes every 1 January and DFAS publishes only the current year,
    so an accrual window reaching into last year is being priced at rates that
    were not in force. Reading the date is what lets a run say so instead of
    quietly applying this year's raise to last year's contributions.
    :param html: The page as served
    :return: The effective date, or None when the page does not state one
    :rtype: dt.date | None
    """

    found = EFFECTIVE.search(string=html)

    if found is None:
        return None

    month, day, year = found.groups()

    try:
        return dt.datetime.strptime(f"{month} {day} {year}", "%B %d %Y").date()

    except ValueError:
        return None


def monthly_basic_pay(
    table: dict[str, dict[str, float]], grade: str, basd: dt.date, day: dt.date
) -> float | None:
    """
    A member's monthly basic pay on a given day.

    The figure is taken as printed. The published tables already have the
    statutory cap applied -- O-8's top rate is exactly the Level II limit -- so
    re-applying one here would either duplicate the cap or, worse, hardcode a
    dollar figure that goes stale every January.
    :param table: A parsed page, as basic_pay_table() returns
    :param grade: The canonical grade, as normalize_grade() returns
    :param basd: Basic Active Service Date
    :param day: The date to value
    :return: Monthly basic pay, or None when the table publishes no rate for
        that grade at that time in service
    :rtype: float | None
    """

    return table.get(grade, {}).get(band_on(basd=basd, day=day))
