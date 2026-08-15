# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""
tsp.py: Helpers for the Thrift Savings Plan module.

TSP is the one account StonkSmith tracks that needs no login to value. TSP does
not report a balance so much as compute one, and it computes it the way this
module does:

    balance = units held x share price

Share prices are published daily as a public CSV. Units only move when a
transaction happens -- a contribution, an interfund transfer, a loan, a
withdrawal. So between transactions a daily mark is not an estimate, it is
arithmetic, and it stays correct for as long as nobody logs in.

That is not a modelling choice, it is checked. Run against a real quarterly
statement, the units and unit price it prints multiply out to the closing
balance printed on the same page, to the cent -- and the unit price is
identical to the public file's entry for that date. The public feed is not an
approximation of what TSP marks an account with; it is the same number.

Everything here is pure -- text in, records out. The price fixture is a genuine
slice of the published file, which is public data; the statement fixtures
mirror a real statement's layout with every figure invented, because a
statement carries a member's name, address and balances.
"""

import csv
import datetime as dt
import io
import re

#: Every fund the price file publishes, in the order its header lists them.
#: Doubles as the vocabulary the statement parser needs: fund names contain
#: spaces ("L 2060", "C Fund"), so a multi-fund statement line cannot be split
#: on whitespace without knowing what a fund is called.
TSP_FUNDS: tuple[str, ...] = (
    "L Income",
    "L 2030",
    "L 2035",
    "L 2040",
    "L 2045",
    "L 2050",
    "L 2055",
    "L 2060",
    "L 2065",
    "L 2070",
    "L 2075",
    "G Fund",
    "F Fund",
    "C Fund",
    "S Fund",
    "I Fund",
)

#: Column holding the price date.
DATE_COLUMN = "Date"

#: Numbers as the statement writes them: "$1,234.56", "100.000", "20.000000",
#: "$-25.00". The sign sits inside the currency symbol here, unlike Ally.
AMOUNT = re.compile(pattern=r"-?\$?\s*-?[\d,]+(?:\.\d+)?")

#: Statement labels this reads. Each is a line prefix; whatever follows is one
#: value per fund, left to right in the same order as the "Fund Name" line.
FUND_NAME_LABEL = "Fund Name"
CLOSING_UNITS_LABEL = "Closing Units"
UNIT_PRICE_LABEL = "Unit Price (NAV)"
CONTRIBUTIONS_LABEL = "Contributions"
CLOSING_BALANCE_LABEL = "Closing Balance"

#: The reporting period, e.g. "Account Summary 04-01-2026 to 06-30-2026".
PERIOD = re.compile(pattern=r"(\d{2}-\d{2}-\d{4})\s+to\s+(\d{2}-\d{2}-\d{4})")

#: Heading of the per-fund activity table. Everything read per fund is read
#: from below it, because the account summary earlier in the statement carries
#: the *same labels* -- "Opening Balance", "Contributions", "Closing Balance" --
#: against account-wide totals. On a one-fund statement the two agree and the
#: distinction is invisible; on a two-fund one the summary line holds a single
#: aggregate where the table holds one figure per fund, so reading the first
#: match yields one number where two were wanted and drops a fund's worth of
#: money.
ACTIVITY_HEADING = "Activity Detail by Fund"

#: Agency money. Read rather than assumed: whether any arrives depends on which
#: retirement system the member is under, which is not StonkSmith's to guess.
#: A statement showing $0.00 here means $0.00 was paid, and that is a fact worth
#: storing rather than a default worth hardcoding.
EMPLOYER_LABEL = "Employer"

#: The activity table's first column on a real multi-fund statement: an
#: account-wide total that is not a fund and carries no fund name.
#:
#:     Fund Name       All Funds Total  L 2050  L 2060
#:     Closing Balance $8,409.71        $0.00   $8,409.71
#:
#: Three numbers, two fund names. Read positionally that puts the account total
#: against the first fund and drops the last fund entirely -- which on the
#: statement above reports the emptied fund as holding everything and the fund
#: actually held as holding nothing, an exact inversion that looks like an
#: ordinary row. Neither test fixture had this column, which is why it shipped.
AGGREGATE_LABEL = "All Funds Total"


def to_number(text: str) -> float | None:
    """
    Read one money or unit figure off the statement.
    :param text: The raw token, e.g. "$1,234.56" or "100.000"
    :return: The value, or None when the text holds no number
    :rtype: float | None
    """

    found = AMOUNT.search(string=text)

    if found is None:
        return None

    cleaned: str = found.group(0).replace("$", "").replace(",", "").replace(" ", "")

    # "$-25.00" puts the sign after the dollar sign; "-$25.00" puts it before.
    # Both survive stripping, but "--" would not, so collapse it.
    cleaned = cleaned.replace("--", "-")

    try:
        return float(cleaned)

    except ValueError:
        return None


def fund_prices(text: str) -> dict[dt.date, dict[str, float]]:
    """
    Parse the public daily share price file.

    Two shapes in the real file that a naive reader gets wrong. The last line is
    ``,,,,,,,,,,,,,,,,`` -- all separators, no date -- which becomes a row of
    empty strings and, unguarded, a date-less entry that later lookups trip
    over. And the columns are sparse on purpose: the L funds are blank back to
    2003 and L 2060 only begins in 2020, because those funds did not exist yet.
    A blank is "no price", not zero, and treating it as zero would value an
    account at nothing on every date before its fund launched.
    :param text: The CSV as published
    :return: Date mapped to fund name mapped to share price; funds with no
        price on a date are absent rather than zero
    :rtype: dict[dt.date, dict[str, float]]
    """

    prices: dict[dt.date, dict[str, float]] = {}

    for row in csv.DictReader(f=io.StringIO(initial_value=text)):
        stamp: str = (row.get(DATE_COLUMN) or "").strip()

        if not stamp:
            continue

        try:
            day: dt.date = dt.date.fromisoformat(stamp)

        except ValueError:
            continue

        day_prices: dict[str, float] = {}

        for fund in TSP_FUNDS:
            value: float | None = to_number(text=(row.get(fund) or "").strip())

            if value is not None:
                day_prices[fund] = value

        if day_prices:
            prices[day] = day_prices

    return prices


def price_on(
    prices: dict[dt.date, dict[str, float]], fund: str, day: dt.date
) -> tuple[dt.date, float] | None:
    """
    The fund's price on a day, or the most recent one before it.

    Falls back rather than failing because the calendar and the market disagree:
    a Sunday, a holiday, or a run before the day's price is published all ask
    for a date the file does not carry. Returning the price *and* the date it
    came from is what lets a caller say how stale a mark is instead of quietly
    presenting Friday's number as today's.
    :param prices: Parsed price file
    :param fund: Fund name, e.g. "L 2060"
    :param day: The date wanted
    :return: (price date, price), or None when the fund has no price on or
        before that day
    :rtype: tuple[dt.date, float] | None
    """

    for candidate in sorted(prices, reverse=True):
        if candidate <= day and fund in prices[candidate]:
            return candidate, prices[candidate][fund]

    return None


def statement_period(text: str) -> tuple[dt.date, dt.date] | None:
    """
    The reporting period a statement covers.
    :param text: Extracted statement text
    :return: (period start, period end), or None when no period is stated
    :rtype: tuple[dt.date, dt.date] | None
    """

    found = PERIOD.search(string=text)

    if found is None:
        return None

    start, end = (
        dt.datetime.strptime(part, "%m-%d-%Y").date() for part in found.groups()
    )
    return start, end


def activity_detail(text: str) -> str:
    """
    The part of a statement that reports per fund.

    Everything below the "Activity Detail by Fund" heading. Scoping to it is
    not tidiness: the account summary above reuses the same row labels for
    account-wide totals, so an unscoped search finds the aggregate first. That
    reads correctly on a single-fund statement -- where the two are the same
    number -- and silently loses funds on any other.
    :param text: Extracted statement text
    :return: The activity section, or the whole text when the heading is absent
    :rtype: str
    """

    index: int = text.find(ACTIVITY_HEADING)
    return text if index < 0 else text[index:]


def fund_name_row(text: str) -> str:
    """
    The activity table's column header, with its label stripped off.

    Everything read per fund is read positionally against this row, so it is
    the one place that knows how many columns there are and what each is. The
    first row naming a fund wins: a statement carries other "Fund Name" rows --
    the allocation summary has one -- and activity_detail() already excludes
    the ones above the table.
    :param text: Extracted statement text
    :return: The header after "Fund Name", e.g. " All Funds Total L 2050
        L 2060", or "" when the table has no such row
    :rtype: str
    """

    for line in activity_detail(text=text).splitlines():
        stripped: str = line.strip()

        if not stripped.startswith(FUND_NAME_LABEL):
            continue

        rest: str = stripped[len(FUND_NAME_LABEL) :]

        if any(fund in rest for fund in TSP_FUNDS):
            return rest

    return ""


def statement_funds(text: str) -> list[str]:
    """
    Which funds the statement's per-fund activity table covers.

    Matched against the known fund vocabulary rather than split on whitespace,
    because every fund name contains a space: splitting "Fund Name L 2060
    C Fund" naively yields "L", "2060", "C", "Fund".
    :param text: Extracted statement text
    :return: Fund names in the order the statement lists them
    :rtype: list[str]
    """

    rest: str = fund_name_row(text=text)
    found: list[tuple[int, str]] = [
        (rest.index(fund), fund) for fund in TSP_FUNDS if fund in rest
    ]

    return [fund for _position, fund in sorted(found)]


def leading_columns(text: str) -> int:
    """
    How many columns of the activity table come before the first fund.

    One on a real multi-fund statement, which leads with an account-wide "All
    Funds Total"; none on a single-fund one. It matters because every value row
    carries a figure for that column too, so a row is one longer than the fund
    list and reading it from the left assigns the account total to the first
    fund -- see AGGREGATE_LABEL for what that does.

    Counted from the header rather than inferred from a row's length, so a row
    that is long for some other reason is not silently re-aligned.
    :param text: Extracted statement text
    :return: 0 or 1
    :rtype: int
    """

    rest: str = fund_name_row(text=text)
    positions: list[int] = [rest.index(fund) for fund in TSP_FUNDS if fund in rest]

    if not positions:
        return 0

    return 1 if AGGREGATE_LABEL in rest[: min(positions)] else 0


def fund_values(text: str, label: str, count: int) -> list[float]:
    """
    Read one labelled row of the per-fund activity table.

    A single-fund statement puts one number after the label; a multi-fund one
    puts several on the same line, in the same order as the "Fund Name" row.
    Reading only the first would silently drop every fund but one, so the count
    is passed in and a short row is reported by being short rather than padded.

    Scoped to the activity table, never the account summary above it -- see
    activity_detail(), which exists because both use these same labels.

    A row carrying the account-wide total as well as the funds is trimmed from
    the left, not the right. Taking the first `count` values off such a row
    reads the total as the first fund's figure and drops the last fund; see
    AGGREGATE_LABEL, where doing so inverts a two-fund statement exactly.

    A row matching neither length is returned exactly as printed, long or
    short, and the caller is handed the ambiguity rather than a guess at it. It
    cannot be aligned: a lone figure on a two-fund table belongs to whichever
    fund the statement had something to say about, and position does not say
    which.

    Trimming an over-long row to the first `count` values would be the same
    unjustified assumption this function exists to avoid, pointed the other
    way. The transfer statement's extra column was on the *left*; taking the
    leftmost values is exactly what read it backwards.
    :param text: Extracted statement text
    :param label: The row label, e.g. "Closing Units"
    :param count: How many funds the table covers
    :return: One value per fund, in fund order, when the row aligns; otherwise
        the row as printed
    :rtype: list[float]
    """

    offset: int = leading_columns(text=text)

    for line in activity_detail(text=text).splitlines():
        stripped: str = line.strip()

        if not stripped.startswith(label):
            continue

        rest: str = stripped[len(label) :]
        values: list[float] = [
            value
            for token in AMOUNT.findall(string=rest)
            if (value := to_number(text=token)) is not None
        ]

        if not values:
            continue

        if len(values) == count + offset:
            return values[offset:]

        return values

    return []


def sole_position(text: str) -> tuple[str, float] | None:
    """
    The one fund still holding money at the close, when there is exactly one.

    A statement spanning an interfund transfer covers both funds: the one moved
    out of, closing at $0.00, and the one moved into, closing at everything.
    The per-fund rows below the balances then have nothing to say about the
    emptied fund and print a single figure -- one number under a two-fund
    header, belonging to a fund that position alone cannot name.

    Closing balances can name it. They are printed per fund and one of them is
    zero, so "which fund does the lone unit count belong to" has an answer on
    the page rather than needing a guess.

    Refuses whenever the answer is not unique -- no funds with a balance, or
    more than one -- because then the lone figure genuinely is ambiguous and a
    unit count attached to the wrong fund is priced with the wrong fund's
    price, which is the whole failure this exists to stop.
    :param text: Extracted statement text
    :return: (fund, its closing balance), or None when it is not unique
    :rtype: tuple[str, float] | None
    """

    funds: list[str] = statement_funds(text=text)
    balances: list[float] = fund_values(
        text=text, label=CLOSING_BALANCE_LABEL, count=len(funds)
    )

    # Only a fully aligned balance row can name anything. A short one is the
    # same ambiguity one level down.
    if not funds or len(balances) != len(funds):
        return None

    held: list[tuple[str, float]] = [
        (fund, balance)
        for fund, balance in zip(funds, balances, strict=True)
        if balance
    ]

    return held[0] if len(held) == 1 else None


def employer_total(text: str) -> float | None:
    """
    Agency money in the account, as the statement reports it.

    Deliberately read rather than modelled. Whether a member receives agency
    contributions at all depends on their retirement system, and a tool that
    assumed one would either invent money that never arrives or hide money that
    does. A statement saying $0.00 is recording a fact.
    :param text: Extracted statement text
    :return: The employer figure, or None when the statement does not carry one
    :rtype: float | None
    """

    lines: list[str] = [line.strip() for line in text.splitlines()]

    for index, line in enumerate(iterable=lines):
        if line != EMPLOYER_LABEL:
            continue

        # The label sits on its own line with the amount on the next.
        for following in lines[index + 1 : index + 3]:
            value: float | None = to_number(text=following)

            if value is not None:
                return value

    return None


def same_fund(one: str, other: str) -> bool:
    """
    Whether two spellings name the same TSP fund.

    Compared loosely on purpose. A statement writes "L 2050 Fund" where the
    price file heads its column "L 2050" and a config line might carry either,
    with any amount of whitespace and any case -- and none of those differences
    means a different fund.

    An unnamed side matches anything. A statement whose fund would not parse
    has already lost that information, and refusing the whole run over a
    detail the file never carried would reject a perfectly good unit count.
    What must not pass is two names that are both present and genuinely
    different, because units are per fund and so are prices.
    :param one: A fund name, possibly empty
    :param other: The other, possibly empty
    :return: True when they name the same fund, or either is unnamed
    :rtype: bool
    """

    if not one.strip() or not other.strip():
        return True

    def bare(name: str) -> str:
        words = name.upper().replace("-", " ").split()
        return " ".join(word for word in words if word != "FUND")

    return bare(one) == bare(other)
