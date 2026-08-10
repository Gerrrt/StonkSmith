# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""The one thing that puts the databases on a sheet.

`etc.portfolio` settled what a row is. This settles where it goes, and there is
deliberately only one of these: five brokers each writing their own tab is the
arrangement the column contract exists to end. A per-broker tab cannot show a
total anyway, because no single broker's database has one.

So one read of the workspace feeds five tabs. `Accounts`, `Holdings`,
`Transactions` and `Net Worth` are the four row shapes, verbatim. `Dashboard` is
formulas over them, which is what makes append-only matter in the spreadsheet
and not only in the tests: a QUERY addresses a column by position, so a column
added at the end costs nothing and a column inserted in the middle would
silently repoint every one of them.

`Transactions` and `Net Worth` are the two that are not current state, and both
carry the whole of what they hold. The other tabs are bounded by the size of the
portfolio; these grow forever -- one with every movement, one with every run --
which is exactly why they are written in full. A tab whose purpose is history,
showing the newest few hundred rows with nothing saying so, would be worse than
not having one.

`Net Worth` is also the one tab whose rows no source ever stated. It is a series
across brokers that do not report on the same day, so most of its points carry
some account's older value forward -- see `etc.portfolio.net_worth_history` for
why the alternative draws a portfolio that collapses and recovers on nothing but
scrape timing. Every row says which of its numbers were read and which were
carried, and the dashboard's band totals the two separately rather than
flattening them, because a point that is mostly carried is a weaker claim than
one that was read.

**The tabs are machine-owned, and this is where that stops being a README
paragraph.** A tab is cleared only if its first cell carries BANNER, or if the
tab is empty. Anything else is refused by name, and nothing is written. The rule
was already documented, and documentation is not what stops a sync from eating a
note somebody left in a cell.

**Values go up RAW, never USER_ENTERED.** Two things go wrong otherwise and
neither announces itself. An account whose display name begins with "=" stops
being a name and becomes a formula -- scraped text turning into something the
spreadsheet executes. And an ISO date stops being the string the database stored
and becomes a date serial, at which point the dashboard's string comparisons
fail a type check into an empty result: a staleness panel that silently reports
that nothing is stale. USER_ENTERED is used for exactly one thing, the
dashboard's formula cells, and the dashboard's literal cells go up RAW beside
them for the same reason -- an unreadable broker's reason is exception text, and
exception text beginning with "=" is a formula.
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from etc.context import Context
from etc.portfolio import (
    ACCOUNT_COLUMNS,
    CARRIED,
    HOLDING_COLUMNS,
    ISO_DATE_PATTERN,
    NET_WORTH_COLUMNS,
    TRANSACTION_COLUMNS,
    Portfolio,
    read_workspace,
)
from helpers.sheets import (
    SPREADSHEET_NAME,
    SheetNotOwned,
    SheetsUnavailable,
    a1_range,
    ensure_worksheet,
    fit,
    open_spreadsheet,
)

#: Written into the first cell of every tab this module owns, and the only thing
#: that makes a tab writable. Changing it orphans every tab already in the field:
#: the next sync finds a first cell it does not recognise and refuses them all.
BANNER: str = (
    "StonkSmith machine-owned tab. Cleared and rewritten on every sync -- "
    "anything you put here is lost. Keep your own work on a tab of your own."
)

ACCOUNTS_TAB: str = "Accounts"
HOLDINGS_TAB: str = "Holdings"
TRANSACTIONS_TAB: str = "Transactions"
NET_WORTH_TAB: str = "Net Worth"
DASHBOARD_TAB: str = "Dashboard"

#: Every tab StonkSmith opens. Nothing outside this tuple is ever touched, which
#: is what makes any other tab in the book safe to keep things on.
MACHINE_OWNED_TABS: tuple[str, ...] = (
    ACCOUNTS_TAB,
    HOLDINGS_TAB,
    TRANSACTIONS_TAB,
    #: Appended ahead of the dashboard rather than after it, so the four data
    #: tabs stay together and the one made of formulas over them stays last.
    #: Nothing depends on the order -- claim() walks the whole tuple -- but the
    #: tuple is also what a person reads to learn what this touches.
    NET_WORTH_TAB,
    DASHBOARD_TAB,
)

BANNER_CELL: str = "A1"

#: Where claim() remembers that it has already vetted a worksheet handle. Set on
#: the gspread object rather than kept in a module-level set, so that it cannot
#: outlive the handle and quietly vouch for a later one.
CLAIMED_ATTR: str = "_stonksmith_claimed"

#: What that attribute has to hold. A private sentinel rather than True, because
#: the check is the one thing standing between a sync and somebody's data, and
#: "any truthy attribute of that name" is a bypass anything could trip into --
#: a test double that invents attributes on demand does exactly that. Only this
#: module can produce this object, so only this module can vouch for a handle.
_CLAIMED: object = object()

HEADER_ROW: int = 2
FIRST_DATA_ROW: int = 3

#: Data rows per update call. A single request carrying every position in a large
#: workspace is one rejection away from losing the whole write; chunking bounds
#: what one rejected request costs.
CHUNK_ROWS: int = 2000

#: An account whose As Of is older than this, or missing, is listed on the
#: dashboard rather than quietly counted at full value.
STALE_DAYS: int = 7

#: How short the dashboard's grid may be. A floor, not the answer -- the bands
#: below the summary block spill as far as the portfolio is long, so the height
#: is computed per sync and this only covers the case where there is nothing to
#: spill and the summary block is the tallest thing on the tab.
DASHBOARD_MIN_ROWS: int = 40

#: Where the dashboard's bands start. Separate columns rather than separate row
#: bands because a QUERY that would spill into an occupied cell returns #REF!
#: and shows nothing at all -- the same reason the old Ally tab put its holdings
#: beside its accounts rather than below them.
SUMMARY_COL: str = "A"
BY_BROKER_COL: str = "D"
BY_SOURCE_COL: str = "G"
STALENESS_COL: str = "J"
UNREADABLE_COL: str = "O"

#: The net worth band: one row per date, its USD total split into the part that
#: was read that day and the part that was carried onto it.
NET_WORTH_COL: str = "R"


@dataclass(frozen=True, slots=True)
class SheetSync:
    """
    What one refresh put on the sheet, and what it could not read.

    Returned rather than logged so that the caller chooses the wording, and so a
    test can assert the numbers that landed instead of parsing log lines.
    """

    accounts: int = 0
    holdings: int = 0
    transactions: int = 0
    brokers_read: tuple[str, ...] = ()
    unreadable: tuple[tuple[str, str], ...] = ()
    total: float = 0.0

    #: Rows on the Net Worth tab: accounts times the dates they can be placed
    #: on, not dates. Appended rather than slotted in beside the other three
    #: counts, so a caller reading positionally keeps its meaning.
    net_worth: int = 0


def column_letter(index: int) -> str:
    """
    The A1 column letter for a 1-indexed column.

    Loops past Z rather than stopping there. The contract is append-only, so the
    twenty-seventh column is a question of when and not whether, and a letter
    that quietly went wrong at that point would take every formula with it.
    :param index: The column number, 1 for A
    :return: The column letter, e.g. "G" or "AA"
    :rtype: str
    """

    if index < 1:
        raise ValueError(f"column numbers start at 1, not {index}")

    letters: str = ""
    remaining: int = index

    while remaining:
        remaining, offset = divmod(remaining - 1, 26)
        letters = chr(ord("A") + offset) + letters

    return letters


def column_index(letter: str) -> int:
    """
    The 1-indexed column a letter names. The inverse of column_letter.
    :param letter: A column letter, e.g. "O"
    :return: Its column number
    :rtype: int
    """

    index: int = 0

    for character in letter.upper():
        index = index * 26 + (ord(character) - ord("A") + 1)

    return index


def tab_ref(tab: str) -> str:
    """
    How a formula names a tab.

    Quoted, always. ``Accounts!$A$3:$J`` is valid and ``Net Worth!$A$3:$K`` is
    not -- a tab name with a space in it has to be wrapped in single quotes or
    the reference is a parse error, and the failure is a whole panel showing
    nothing. Quoting unconditionally rather than only when the name needs it,
    because a branch taken by one tab out of five is a branch nothing exercises
    until the day a tab is renamed.
    :param tab: The tab's name
    :return: The reference prefix, e.g. "'Accounts'!"
    :rtype: str
    """

    return f"'{tab}'!"


def _is_formula(cell: Any) -> bool:
    """
    Whether a cell has to go up as USER_ENTERED to mean what it says.

    Asked of every dashboard cell rather than assumed per block, because the
    summary column interleaves the two: a run of formulas with one plain float
    in the middle of it.
    :param cell: The cell's value
    :return: True when it is a formula
    :rtype: bool
    """

    return isinstance(cell, str) and cell.startswith("=")


def last_column(columns: Sequence[str]) -> str:
    """
    The letter of a column tuple's rightmost column.
    :param columns: A column contract, e.g. ACCOUNT_COLUMNS
    :return: The column letter the tuple ends at
    :rtype: str
    """

    return column_letter(index=len(columns))


def column_of(columns: Sequence[str], name: str) -> str:
    """
    The A1 letter a named column sits at.

    Every formula in this module is built through here rather than typed. That
    is the whole of what makes them append-only-safe: a column added to the end
    moves no letter, and a column moved into the middle moves the formulas with
    it -- while also failing the tuple that tests/test_portfolio_contract.py
    pins, which is where that change is supposed to be argued about.
    :param columns: The column contract to look in
    :param name: The column name, exactly as the contract spells it
    :return: The column letter
    :rtype: str
    :raises KeyError: if the contract has no such column
    """

    try:
        return column_letter(index=list(columns).index(name) + 1)

    except ValueError as e:
        raise KeyError(f"no column named {name!r} in {list(columns)}") from e


def claim(worksheet: Any, tab: str) -> None:
    """
    Refuse to clear a tab StonkSmith did not write.

    Two reads, and only when it has to be. The first cell answers the ordinary
    case in one small call: it either carries the banner, in which case this tab
    is ours and has been before, or it does not. What the first cell cannot
    answer is a blank one -- every tab StonkSmith used to write left A1 blank and
    started its headers at B2, so "A1 is empty" is exactly the shape a leftover
    layout has, and exactly the shape a person's own tab has if they started
    below the top row. Only then is the whole tab read, which is the first sync
    of a tab and no other.

    Asked once per worksheet object. refresh() claims every tab up front so
    that a tab which is not ours costs nothing, and each write then claims the
    tab it is about to clear so that no write path can exist without the guard
    on it. Those two are both worth having and would otherwise mean two rounds
    of reads -- and on a first adoption, two whole-tab downloads. So the answer
    is remembered on the handle it was asked about: same object, same tab, same
    answer, and a handle lives exactly as long as the sync that opened it.
    :param worksheet: The tab about to be cleared
    :param tab: Its name, for the message
    :return: None
    :raises SheetNotOwned: when the tab holds anything StonkSmith did not write
    """

    if getattr(worksheet, CLAIMED_ATTR, None) is _CLAIMED:
        return

    first: Any = worksheet.acell(BANNER_CELL).value

    if str(object=first or "").strip() == BANNER:
        setattr(worksheet, CLAIMED_ATTR, _CLAIMED)
        return

    if str(object=first or "").strip():
        raise SheetNotOwned(_refusal(tab=tab))

    for row in worksheet.get_all_values() or ():
        if any(str(object=cell or "").strip() for cell in row):
            raise SheetNotOwned(_refusal(tab=tab))

    setattr(worksheet, CLAIMED_ATTR, _CLAIMED)


def _refusal(tab: str) -> str:
    """
    What to say when a tab is not ours.

    Names the tab and gives the three ways out, because "sync skipped" with no
    tab name is a message that sends someone looking through a whole spreadsheet.
    :param tab: The tab that was left alone
    :return: The message
    :rtype: str
    """

    return (
        f"Tab '{tab}' holds something StonkSmith did not write, so it was left "
        "untouched and nothing was synced. StonkSmith rewrites this tab from "
        "scratch every run and would have lost whatever is on it. Move your "
        "work to a tab of your own, empty this one to hand it over, or delete "
        "it and let the next sync recreate it."
    )


def _chunks(rows: Sequence[Sequence[Any]], size: int) -> list[list[Sequence[Any]]]:
    """
    Split rows into writes of at most ``size``.
    :param rows: The data rows
    :param size: Rows per write
    :return: One list of rows per request
    :rtype: list[list[Sequence[Any]]]
    """

    return [list(rows[start : start + size]) for start in range(0, len(rows), size)]


def write_rows(
    worksheet: Any,
    tab: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> int:
    """
    Claim a tab, empty it, and write one contract's worth of rows into it.

    The banner goes in first and the data last, so a write that dies partway
    leaves a tab that still identifies itself as ours rather than one the next
    run would refuse to touch.
    :param worksheet: The tab to write
    :param tab: Its name, for the refusal message
    :param columns: The column contract for this tab, which is also its header
    :param rows: One list of cells per record, already in column order
    :return: How many data rows were written
    :rtype: int
    :raises SheetNotOwned: when the tab is not StonkSmith's
    """

    claim(worksheet=worksheet, tab=tab)

    right: str = last_column(columns=columns)
    # The last row actually addressed: the header sits on HEADER_ROW and the
    # data runs from the row after it, so N rows end on HEADER_ROW + N. Asking
    # for FIRST_DATA_ROW + N asked for one row past that -- harmless, since the
    # grid then satisfied the request forever after, but it made this call say
    # something slightly untrue about what the write needs.
    fit(worksheet=worksheet, rows=HEADER_ROW + len(rows), cols=len(columns))
    worksheet.clear()

    worksheet.update([[BANNER]], BANNER_CELL, value_input_option="RAW")
    worksheet.update(
        [list(columns)],
        f"A{HEADER_ROW}:{right}{HEADER_ROW}",
        value_input_option="RAW",
    )

    first_row: int = FIRST_DATA_ROW

    for chunk in _chunks(rows=rows, size=CHUNK_ROWS):
        worksheet.update(
            [list(row) for row in chunk],
            a1_range(
                first_col="A",
                last_col=right,
                first_row=first_row,
                row_count=len(chunk),
            ),
            value_input_option="RAW",
        )
        first_row += len(chunk)

    return len(rows)


def _summary(portfolio: Portfolio) -> tuple[list[list[Any]], list[list[Any]]]:
    """
    The dashboard's summary block, split into labels and values.

    :param portfolio: What the workspace holds
    :return: (label column, value column) as single-column grids
    :rtype: tuple[list[list[Any]], list[list[Any]]]
    """

    def down(tab: str, columns: Sequence[str], name: str) -> str:
        """
        One whole data column, absolutely addressed and open-ended.
        :param tab: The tab the column is on
        :param columns: The column contract that tab carries
        :param name: The column's name in that contract
        :return: A range such as "'Accounts'!$G$3:$G"
        :rtype: str
        """

        letter: str = column_of(columns=columns, name=name)
        return f"{tab_ref(tab=tab)}${letter}${FIRST_DATA_ROW}:${letter}"

    value: str = down(tab=ACCOUNTS_TAB, columns=ACCOUNT_COLUMNS, name="Value")
    currency: str = down(tab=ACCOUNTS_TAB, columns=ACCOUNT_COLUMNS, name="Currency")
    key: str = down(tab=ACCOUNTS_TAB, columns=ACCOUNT_COLUMNS, name="Account Key")
    scraped: str = down(tab=ACCOUNTS_TAB, columns=ACCOUNT_COLUMNS, name="Scraped At")
    held: str = down(tab=HOLDINGS_TAB, columns=HOLDING_COLUMNS, name="Value")
    held_currency: str = down(
        tab=HOLDINGS_TAB, columns=HOLDING_COLUMNS, name="Currency"
    )
    held_key: str = down(tab=HOLDINGS_TAB, columns=HOLDING_COLUMNS, name="Account Key")
    moved_key: str = down(
        tab=TRANSACTIONS_TAB, columns=TRANSACTION_COLUMNS, name="Account Key"
    )
    processed: str = down(
        tab=TRANSACTIONS_TAB, columns=TRANSACTION_COLUMNS, name="Processed On"
    )
    dated: str = down(tab=NET_WORTH_TAB, columns=NET_WORTH_COLUMNS, name="Date")
    basis: str = down(tab=NET_WORTH_TAB, columns=NET_WORTH_COLUMNS, name="Basis")

    labels: list[list[Any]] = [
        ["Total (USD)"],
        ["Total as read"],
        ["Accounts"],
        ["Holdings"],
        ["Holdings total (USD)"],
        ["In accounts, not in positions"],
        ["Other currencies present"],
        ["Newest scrape"],
        ["Oldest scrape"],
        ["Brokers read"],
        # Appended rather than slotted in beside the account and holding counts,
        # on the same principle the columns follow. at() derives every row
        # reference from this list, so an insertion would not break a formula --
        # but a person reading last sync's dashboard beside this one would find
        # the rows they knew had moved, and that is worth more than tidiness.
        ["Movements"],
        ["Newest movement"],
        # Appended for the reason the two above were. These two belong together:
        # the first says how long the series is, the second how much of it is
        # not a reading. A series whose carried count approaches its length is
        # a chart of one broker's runs with everything else held still, and the
        # only place that is visible is here.
        ["Dates in the series"],
        ["Carried values"],
    ]

    def at(label: str) -> str:
        """
        The cell one summary row's value sits in.

        Derived rather than typed, for the same reason the column letters are:
        the one formula here that refers to its own neighbours would otherwise
        keep pointing at rows 3 and 7 after somebody reordered the list above,
        and it would keep producing a number while doing it.
        :param label: The row's label, exactly as spelled above
        :return: A cell reference such as "B3"
        :rtype: str
        """

        return f"B{FIRST_DATA_ROW + [row[0] for row in labels].index(label)}"

    values: list[list[Any]] = [
        # SUMIF on Currency rather than SUM on Value, because Portfolio.total
        # refuses to add a dollar to a euro and the sheet must not do quietly
        # what the code declines to do loudly.
        [f'=SUMIF({currency},"USD",{value})'],
        # The same number the other way round: Python over the databases beside
        # Sheets over the cells. They disagree only if the write was truncated
        # or a row failed to land, which is otherwise invisible.
        [portfolio.total()],
        # Counted on Account Key, not Account: the key is written unwrapped and
        # can never be blank, while a display name goes through _cell and can.
        [f"=COUNTA({key})"],
        [f"=COUNTA({held_key})"],
        [f'=SUMIF({held_currency},"USD",{held})'],
        # The reason there are two row shapes at all: uninvested cash sits in a
        # balance and in no position. Negative means positions are being counted
        # twice.
        [f"={at(label='Total (USD)')}-{at(label='Holdings total (USD)')}"],
        # Names what the USD total left out. A USD-only total with a euro
        # account in the workspace is a wrong number that looks right.
        [
            f'=IFERROR(TEXTJOIN(", ",TRUE,UNIQUE(FILTER({currency},'
            f'{currency}<>"USD",{currency}<>""))),"")'
        ],
        # SORT rather than MAX: Scraped At is text under RAW, and MAX over text
        # returns 0. The stored format is YYYY-MM-DD HH:MM:SS, which sorts
        # lexicographically exactly as it sorts chronologically.
        [
            f'=IFERROR(INDEX(SORT(UNIQUE(FILTER({scraped},{scraped}<>"")),1,FALSE),1,1),"")'
        ],
        [
            f'=IFERROR(INDEX(SORT(UNIQUE(FILTER({scraped},{scraped}<>"")),1,TRUE),1,1),"")'
        ],
        [", ".join(portfolio.brokers_read) or "none"],
        # Counted on Account Key for the same reason the two counts above are:
        # it is written unwrapped and can never be blank, while Type and
        # Description are both routinely empty depending on the source.
        [f"=COUNTA({moved_key})"],
        # SORT rather than MAX, as the two scrape dates above -- and safe for
        # the same reason only because etc.portfolio normalizes Processed On to
        # ISO on the way out of the database. It is stored as the source wrote
        # it, and "12/30/2025" sorts above "01/15/2026".
        #
        # Filtered on the shape of a date rather than on <>"", which the two
        # cells above can afford and this one cannot. Scraped At is written by
        # StonkSmith and is always a timestamp; Processed On comes from a source
        # and is kept verbatim when it will not parse, deliberately. Sorted as
        # text, one such row wins -- every letter compares above every digit --
        # so the cell would answer "whenever" and look authoritative. The row
        # keeps its place on the tab; it just cannot be the answer here.
        [
            f"=IFERROR(INDEX(SORT(UNIQUE(FILTER({processed},"
            f'REGEXMATCH({processed}&"","{ISO_DATE_PATTERN}"))),1,FALSE),1,1),"")'
        ],
        # COUNTUNIQUE over a column with trailing blanks counts the blank as a
        # value, so the empty tail is filtered out rather than subtracted.
        [f'=IFERROR(COUNTUNIQUE(FILTER({dated},{dated}<>"")),0)'],
        # Counted rather than inferred from the band below it. The band is USD
        # only, because a total has to be; this is a count, which does not, so
        # it says how many carried values are on the tab rather than how many
        # are in the total.
        [f'=COUNTIF({basis},"{CARRIED}")'],
    ]

    return labels, values


def _bands(today: dt.date) -> dict[str, str]:
    """
    The dashboard's four QUERY bands, keyed by the column they start in.

    Every reference is positional -- Col1..Col10 are exactly ACCOUNT_COLUMNS
    indices, because the range starts below the header and the query is told it
    has none. Appending an eleventh column changes none of them. The range's own
    last letter is computed, so appending widens it on the next sync.
    :param today: The date staleness is measured from
    :return: Start column to formula
    :rtype: dict[str, str]
    """

    right: str = last_column(columns=ACCOUNT_COLUMNS)
    span: str = f"{tab_ref(tab=ACCOUNTS_TAB)}$A${FIRST_DATA_ROW}:${right}"

    broker: int = list(ACCOUNT_COLUMNS).index("Broker") + 1
    source: int = list(ACCOUNT_COLUMNS).index("Source") + 1
    account: int = list(ACCOUNT_COLUMNS).index("Account") + 1
    key: int = list(ACCOUNT_COLUMNS).index("Account Key") + 1
    value: int = list(ACCOUNT_COLUMNS).index("Value") + 1
    currency: int = list(ACCOUNT_COLUMNS).index("Currency") + 1
    as_of: int = list(ACCOUNT_COLUMNS).index("As Of") + 1
    scraped: int = list(ACCOUNT_COLUMNS).index("Scraped At") + 1

    # Baked rather than TEXT(TODAY()-7,...) inside a concatenated query string:
    # deterministic, so a test can pin the exact formula, and free of TEXT's
    # locale-dependent format string. It freezes between syncs, which costs
    # nothing -- the data it filters only changes at a sync anyway.
    cutoff: str = (today - dt.timedelta(days=STALE_DAYS)).isoformat()

    series: str = (
        f"{tab_ref(tab=NET_WORTH_TAB)}$A${FIRST_DATA_ROW}:"
        f"${last_column(columns=NET_WORTH_COLUMNS)}"
    )
    on: int = list(NET_WORTH_COLUMNS).index("Date") + 1
    worth: int = list(NET_WORTH_COLUMNS).index("Value") + 1
    held_in: int = list(NET_WORTH_COLUMNS).index("Currency") + 1
    basis: int = list(NET_WORTH_COLUMNS).index("Basis") + 1

    return {
        BY_BROKER_COL: (
            f"=IFERROR(QUERY({span},"
            f'"select Col{broker}, sum(Col{value}) '
            f"where Col{currency} = 'USD' and Col{key} is not null "
            f"group by Col{broker} order by sum(Col{value}) desc "
            f"label Col{broker} 'Broker', sum(Col{value}) 'Value (USD)'\","
            '0),"")'
        ),
        BY_SOURCE_COL: (
            f"=IFERROR(QUERY({span},"
            f'"select Col{source}, sum(Col{value}) '
            f"where Col{currency} = 'USD' and Col{key} is not null "
            f"group by Col{source} order by sum(Col{value}) desc "
            f"label Col{source} 'Source', sum(Col{value}) 'Value (USD)'\","
            '0),"")'
        ),
        STALENESS_COL: (
            f"=IFERROR(QUERY({span},"
            f'"select Col{broker}, Col{account}, Col{as_of}, Col{scraped} '
            f"where Col{key} is not null and "
            f"(Col{as_of} is null or Col{as_of} < '{cutoff}') "
            f"order by Col{scraped} "
            f"label Col{broker} 'Broker', Col{account} 'Account', "
            f"Col{as_of} 'As Of', Col{scraped} 'Scraped At'\","
            '0),"")'
        ),
        # Net worth over time, which is the only thing on this dashboard that is
        # a series rather than a state. Pivoted on Basis rather than totalled
        # flat, so each date arrives as its carried part beside its observed
        # part: a point that is mostly carried is a weaker claim than one that
        # was read, and a single summed column would render the two identically.
        # Charting the two as a stacked series is then the obvious thing to do
        # rather than something the reader has to think to ask for.
        #
        # USD only, on the SUMIF-on-currency precedent above: adding a dollar to
        # a euro produces a number that is not wrong so much as meaningless.
        NET_WORTH_COL: (
            f"=IFERROR(QUERY({series},"
            f'"select Col{on}, sum(Col{worth}) '
            f"where Col{held_in} = 'USD' "
            f"group by Col{on} order by Col{on} pivot Col{basis} "
            f"label Col{on} 'Date'\","
            '0),"")'
        ),
    }


def dashboard_cells(
    portfolio: Portfolio, today: dt.date | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    The dashboard, split into what must be entered as formulas and what must not.

    Two batches because value_input_option is a property of the request and the
    two halves need different ones. The formulas need USER_ENTERED or they land
    as the literal text "=QUERY(...)". The literals must not have it: an
    unreadable broker's reason is exception text, and exception text beginning
    with "=" would become a formula.
    :param portfolio: What the workspace holds
    :param today: The date staleness is measured from, for tests
    :return: (formula updates, literal updates)
    :rtype: tuple[list[dict[str, Any]], list[dict[str, Any]]]
    """

    labels, values = _summary(portfolio=portfolio)
    bands: dict[str, str] = _bands(today=today or dt.datetime.now(tz=dt.UTC).date())

    # Written cell by cell rather than as one column range, because "Total as
    # read" is a float sitting in the middle of a column of formulas: it belongs
    # in the literal batch, and every cell around it has to keep its own row.
    formulas: list[dict[str, Any]] = [
        {"range": f"B{FIRST_DATA_ROW + offset}", "values": [[cell[0]]]}
        for offset, cell in enumerate(values)
        if _is_formula(cell[0])
    ]
    formulas += [
        {"range": f"{start}2", "values": [[formula]]}
        for start, formula in bands.items()
    ]

    literals: list[dict[str, Any]] = [
        {"range": BANNER_CELL, "values": [[BANNER]]},
        {
            "range": f"{SUMMARY_COL}{FIRST_DATA_ROW}:"
            f"{SUMMARY_COL}{FIRST_DATA_ROW + len(labels) - 1}",
            "values": labels,
        },
    ]
    literals += [
        {"range": f"B{FIRST_DATA_ROW + offset}", "values": [[cell[0]]]}
        for offset, cell in enumerate(values)
        if not _is_formula(cell[0])
    ]

    unreadable: list[list[Any]] = [["Not read", "Why"]]
    unreadable += [[name, reason] for name, reason in portfolio.unreadable]

    if not portfolio.unreadable:
        # Stated rather than left blank. An empty region is indistinguishable
        # from a write that failed, and "nothing was missing" is the whole point
        # of the field.
        unreadable.append(["everything read", ""])

    right: str = column_letter(index=column_index(letter=UNREADABLE_COL) + 1)
    literals.append(
        {
            "range": f"{UNREADABLE_COL}2:{right}{len(unreadable) + 1}",
            "values": unreadable,
        }
    )

    return formulas, literals


def write_dashboard(
    worksheet: Any, portfolio: Portfolio, today: dt.date | None = None
) -> None:
    """
    Claim the dashboard, empty it, and write both halves of it.
    :param worksheet: The Dashboard tab
    :param portfolio: What the workspace holds
    :param today: The date staleness is measured from, for tests
    :return: None
    :raises SheetNotOwned: when the tab is not StonkSmith's
    """

    claim(worksheet=worksheet, tab=DASHBOARD_TAB)

    formulas, literals = dashboard_cells(portfolio=portfolio, today=today)

    # Every band starts on HEADER_ROW and spills downward -- the staleness query
    # by a row per account, the unreadable block by a row per broker that would
    # not open. A grid too short for that does not truncate the band: Sheets
    # refuses the whole array with #REF!, so the panel whose job is to say what
    # is stale would be the first thing to vanish from a portfolio big enough to
    # need it. The floor is only for the empty case, where the summary block is
    # the tallest thing on the tab.
    #
    # The net worth band spills by a row per date in the series, which is the
    # one of the three that grows with the number of runs rather than with the
    # size of the portfolio -- so on any workspace with a history it is the
    # tallest thing on the tab, and the first to hit this.
    spill: int = max(
        len(portfolio.accounts),
        len(portfolio.unreadable),
        len({row.date for row in portfolio.net_worth}),
    )

    fit(
        worksheet=worksheet,
        rows=max(DASHBOARD_MIN_ROWS, HEADER_ROW + spill),
        # The net worth band is three columns wide at most -- the date, and one
        # each for the carried and observed halves of its total.
        cols=column_index(letter=NET_WORTH_COL) + 2,
    )
    worksheet.clear()

    worksheet.batch_update(literals, value_input_option="RAW")
    worksheet.batch_update(formulas, value_input_option="USER_ENTERED")


def refresh(
    workspace: str | None = None,
    root: Path | None = None,
    spreadsheet: str = SPREADSHEET_NAME,
    book: Any | None = None,
    today: dt.date | None = None,
) -> SheetSync:
    """
    Put everything every broker in the workspace holds onto the sheet.

    One read of the databases and one authorization, feeding four tabs. All of
    them are claimed before any is cleared: a tab that is not ours then costs
    nothing rather than leaving Accounts rewritten beside a stale Holdings.
    :param workspace: The workspace name, or None for the configured one
    :param root: The directory workspaces live in, for tests
    :param spreadsheet: The spreadsheet to write into
    :param book: An already-open spreadsheet, for tests and for reuse
    :param today: The date staleness is measured from, for tests
    :return: What was written, and what would not read
    :rtype: SheetSync
    :raises SheetsUnavailable: if Sheets is unreachable or a tab is not ours
    """

    portfolio: Portfolio = read_workspace(workspace=workspace, root=root)

    if portfolio.unreadable and not portfolio.brokers_read:
        # Every database failed to open. Clearing the tabs here would replace a
        # correct sheet with a blank one and report success for doing it.
        raise SheetsUnavailable(
            "Not one broker database in the workspace could be read ("
            + "; ".join(f"{name}: {reason}" for name, reason in portfolio.unreadable)
            + "), so the sheet was left as it was rather than emptied."
        )

    opened: Any = (
        book if book is not None else open_spreadsheet(spreadsheet=spreadsheet)
    )

    tabs: dict[str, Any] = {
        name: ensure_worksheet(
            worksheet_name=name, spreadsheet=spreadsheet, book=opened
        )
        for name in MACHINE_OWNED_TABS
    }

    for name, worksheet in tabs.items():
        claim(worksheet=worksheet, tab=name)

    accounts: int = write_rows(
        worksheet=tabs[ACCOUNTS_TAB],
        tab=ACCOUNTS_TAB,
        columns=ACCOUNT_COLUMNS,
        rows=[row.cells() for row in portfolio.accounts],
    )
    holdings: int = write_rows(
        worksheet=tabs[HOLDINGS_TAB],
        tab=HOLDINGS_TAB,
        columns=HOLDING_COLUMNS,
        rows=[row.cells() for row in portfolio.holdings],
    )
    transactions: int = write_rows(
        worksheet=tabs[TRANSACTIONS_TAB],
        tab=TRANSACTIONS_TAB,
        columns=TRANSACTION_COLUMNS,
        rows=[row.cells() for row in portfolio.transactions],
    )
    net_worth: int = write_rows(
        worksheet=tabs[NET_WORTH_TAB],
        tab=NET_WORTH_TAB,
        columns=NET_WORTH_COLUMNS,
        rows=[row.cells() for row in portfolio.net_worth],
    )
    write_dashboard(worksheet=tabs[DASHBOARD_TAB], portfolio=portfolio, today=today)

    return SheetSync(
        accounts=accounts,
        holdings=holdings,
        transactions=transactions,
        brokers_read=portfolio.brokers_read,
        unreadable=portfolio.unreadable,
        total=portfolio.total(),
        net_worth=net_worth,
    )


def sync(context: Context, workspace: str | None = None) -> bool:
    """
    Refresh the sheet, say what happened, and never fail the run.

    The five modules each carried a copy of this: the same try, the same two
    excepts, the same two lines of logging. The behaviour it protects is worth
    keeping exactly -- the scrape is committed by the time this runs, so a Sheets
    problem is a report and not a failure -- and one copy of it is easier to keep
    exactly than five.
    :param context: The module context, for logging
    :param workspace: The workspace name, or None for the configured one
    :return: False when the dashboard was not updated
    :rtype: bool
    """

    try:
        context.log.highlight(msg="Syncing data to Google Sheets...")
        result: SheetSync = refresh(workspace=workspace)

        for name, reason in result.unreadable:
            # Reported here as well as on the tab. A total that is short by a
            # whole broker is the failure this project keeps finding, and the
            # operator watching the run should not have to open the sheet to
            # learn that it happened.
            context.log.fail(
                msg=f"Not on the sheet: {name} could not be read ({reason})."
            )

        context.log.success(msg="Google Sheets updated successfully!")
        context.log.success(
            msg=(
                f"Sheet shows {result.accounts} accounts, {result.holdings} "
                f"holdings, {result.transactions} movements and "
                f"{result.net_worth} net worth rows from "
                f"{', '.join(result.brokers_read) or 'no brokers'}."
            )
        )
        return True

    except SheetsUnavailable as e:
        context.log.fail(msg=f"Google Sheets sync skipped: {e}")
        return False

    except Exception as e:
        # Broad on purpose: the scrape is already in the broker database.
        context.log.fail(msg=f"Google Sheets sync failed: {e}")
        return False
