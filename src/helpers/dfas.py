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

#: Any run of whitespace, including the non-breaking spaces an HTML table is apt
#: to head its columns with.
SPACING = re.compile(pattern=r"\s+")

#: Band labels keyed by their spacing removed entirely, because how much space
#: falls inside one is not a fact about the column. The served page stacks the
#: heading over two lines --
#:
#:     <td><b>Over</b><br/><span><b>10</b></span></td>
#:
#: -- which a reader sees as "Over 10" and which reading the cell as text
#: returns as "Over10", the line break being markup rather than a character. A
#: copy saved from a browser and reflowed says "Over 10" instead. Matching the
#: label exactly therefore found no header row in the page DFAS actually
#: serves, and since basic_pay_table skips a table whose header it cannot find,
#: the whole page parsed to nothing rather than to something visibly wrong.
#:
#: Keying on the spaceless form rather than adding a second spelling to BANDS
#: keeps one name per column: the canonical label is what comes back, so
#: everything downstream -- band_on's lookups above all -- still sees "Over 10".
BAND_BY_SHAPE: dict[str, str] = {
    SPACING.sub(repl="", string=label).casefold(): label for label, _years in BANDS
}

#: A trailing footnote marker on a pay grade, as the published first column
#: writes it: "E-9(Notes 2 & 3)", "E-1(Notes 4 & 5)". Only the two grades whose
#: rates carry conditions have one, which is what made this expensive to notice
#: -- E-8 through E-2 read cleanly, so the table parsed and simply had no E-9 in
#: it. A senior enlisted member then accrues nothing, and the run still looks
#: like it worked.
FOOTNOTE = re.compile(pattern=r"\s*\([^)]*\)\s*$")

#: A pay grade as the tables write it: "E-7", "O-3", "W-5", and the "E" suffix
#: that marks an officer with prior enlisted or warrant service, "O-3E". The
#: hyphen is optional here but not in the output, so a config line reading "e5"
#: still finds the row spelled "E-5".
GRADE = re.compile(pattern=r"^([EOW])-?(\d{1,2})(E?)$", flags=re.IGNORECASE)

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

    A trailing parenthesised note is dropped first. That is how the published
    tables write the two grades whose rates come with conditions, and reading
    the cell literally dropped both of them from the parse -- silently, because
    a grade that is absent from the table is indistinguishable from a grade the
    table publishes no rate for. Only a *trailing* group goes, and only the
    outermost one: nothing that could be part of a grade lives inside it.
    :param rank: The grade as configured, or as the first column writes it
    :return: The canonical spelling, e.g. "E-5" or "O-3E", or None when the text
        is not a pay grade at all
    :rtype: str | None
    """

    found = GRADE.match(string=FOOTNOTE.sub(repl="", string=rank.strip()))

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

    Called what they are called, but not spaced how they are spaced: the served
    page writes "Over10" and a saved copy "Over 10". So the comparison is made
    on the label with its spacing removed, and what is returned is the canonical
    spelling rather than whatever the cell said -- the rest of this module, and
    band_on in particular, has one name per column and must keep it.

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
            label
            for cell in row.find_all(name=["th", "td"])
            if (
                label := BAND_BY_SHAPE.get(
                    SPACING.sub(repl="", string=cell.get_text(strip=True)).casefold()
                )
            )
            is not None
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

            grade: str | None = normalize_grade(rank=cells[0])

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
