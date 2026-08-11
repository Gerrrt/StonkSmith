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
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gspread.utils import ValueRenderOption

from etc.config import get_asset_classes
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
    remove_tab,
    require_worksheet,
    tab_exists,
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
BY_KIND_COL: str = "V"
BY_POSITION_COL: str = "Z"

#: The asset class block, which starts one column past the position block's right
#: edge plus the gutter the other blocks already keep between them. Last because
#: it is the one block that is not always drawn: with no mapping configured there
#: is nothing here, and a block that comes and goes must not sit between two that
#: do not.
BY_CLASS_COL: str = "AD"

#: Columns an allocation block occupies: what the slice is, what it is worth,
#: and what share of the portfolio that is.
ALLOCATION_WIDTH: int = 3

#: The one currency the dashboard totals in, and therefore the only one a share
#: can be a share of. Named rather than spelled out at each use so the summary
#: block and the allocation blocks cannot come to disagree about it.
USD: str = "USD"

#: How far below zero the cash gap may fall before the position block refuses to
#: draw. Money is carried to the cent, and a gap of -0.000001 is float noise
#: rather than a position counted twice -- refusing on that would replace a
#: correct breakdown with an accusation.
ALLOCATION_TOLERANCE: float = 0.005

#: The summary block's rows, in the order they are written.
#:
#: Module level rather than local to _summary, because the allocation blocks
#: point at two of these cells and have to derive the references the same way
#: the summary derives its own -- a typed B3 and B8 would keep producing numbers
#: after somebody reordered this list.
#:
#: Append rather than insert, on the same principle the column contracts follow.
#: summary_cell() derives every reference from this tuple, so an insertion would
#: not break a formula -- but a person reading last sync's dashboard beside this
#: one would find the rows they knew had moved, and that is worth more than
#: tidiness.
SUMMARY_LABELS: tuple[str, ...] = (
    "Total (USD)",
    "Total as read",
    "Accounts",
    "Holdings",
    "Holdings total (USD)",
    "In accounts, not in positions",
    "Other currencies present",
    "Newest scrape",
    "Oldest scrape",
    "Brokers read",
    "Movements",
    "Newest movement",
    # Appended for the reason the two above were. These two belong together:
    # the first says how long the series is, the second how much of it is
    # not a reading. A series whose carried count approaches its length is
    # a chart of one broker's runs with everything else held still, and the
    # only place that is visible is here.
    "Dates in the series",
    "Carried values",
)

#: What the label column says in place of a slice whose name the source left
#: blank. Stated rather than dropped: a position with no ticker is still money,
#: and a breakdown that silently omits it is one whose shares no longer add up.
UNNAMED_KIND: str = "(no kind)"
UNNAMED_SYMBOL: str = "(no symbol)"

#: Where a held symbol goes when the configured mapping has no line for it. Named
#: for the same reason those two are: the money is held whether or not anybody has
#: said what kind of thing it is, and a class breakdown that dropped it would be a
#: breakdown of part of the portfolio presented as a breakdown of all of it.
UNCLASSIFIED: str = "(unclassified)"

#: The row closing each allocation block. Its two values are what the slices
#: above it actually add to -- the sheet's own arithmetic over the cells it
#: wrote, not Python's over the databases. A share sum that is not 1 is a wrong
#: base, visible without anybody having to add the column up by hand.
ALLOCATION_CHECK: str = "Slices sum to"

#: What a holdings block's name column says in place of its slices when the cash
#: gap has gone negative. Named because two things now depend on the wording: the
#: block that writes it, and the read-back that has to tell a refusal apart from
#: a block that failed to write. Those agreeing by having the string typed twice
#: is how a check comes to pass on a tab it never looked at properly.
ALLOCATION_REFUSED: str = "Allocation not drawn"

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

    #: Symbols the configured asset class mapping names that nothing in the
    #: workspace holds. Appended for the reason net_worth was.
    unmatched_classes: tuple[str, ...] = ()


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


def summary_cell(label: str) -> str:
    """
    The cell one summary row's value sits in.

    Derived rather than typed, for the same reason the column letters are: the
    formulas that refer to the summary block's own rows would otherwise keep
    pointing at rows 3 and 8 after somebody reordered SUMMARY_LABELS, and they
    would keep producing numbers while doing it.
    :param label: The row's label, exactly as SUMMARY_LABELS spells it
    :return: A cell reference such as "B3"
    :rtype: str
    :raises KeyError: if the summary has no such row
    """

    try:
        offset: int = list(SUMMARY_LABELS).index(label)

    except ValueError as e:
        raise KeyError(f"no summary row named {label!r}") from e

    return f"B{FIRST_DATA_ROW + offset}"


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


def check_tabs(
    workspace: str | None = None,
    root: Path | None = None,
    spreadsheet: str = SPREADSHEET_NAME,
    book: Any | None = None,
    classes: dict[str, str] | None = None,
) -> tuple[GuardCase, ...]:
    """
    Read the tabs back and check what a successful write cannot show.

    write_rows() returning says the request was accepted, not that the values
    arrived as the kind of thing they were meant to be. Money can land as text, a
    column can drift, a date can reach a cell in the format its source used, and
    a RAW upload reports success through all of it. These are the checks that used
    to need somebody opening the spreadsheet.

    Most compare strings and are certain: the banner, the column contract on
    each tab that has one, the movement count against the databases, the date
    format, and the ordering. The rest read cell *values* -- money as a number,
    the dashboard's two totals agreeing, and each allocation block's slices
    coming to that total with its shares coming to 1 -- and those rested on what
    gspread hands back for a rendered cell, which no test here could settle. They
    carried a marker saying so, on the grounds that reporting an unconfirmed
    assumption as a confirmed defect is its own kind of wrong.

    The marker is gone because the run happened: 2026-08-10, against the real
    spreadsheet, every check then defined passing. A pass settles both directions
    at once -- had the unformatted read returned display text, every money cell
    would have been rejected as text, and a formula arriving as its own source
    would have failed float() into "could not read both". Restoring the marker
    would mean a new assumption, not a rediscovered one.

    The Net Worth contract check postdates that run and went through one of its
    own: 2026-08-11, same spreadsheet, all ten passing, the two value checks
    unmarked this time on a sheet written that morning.

    The allocation checks postdate both and have been through neither. Every
    block was already closing on a row stating what its slices came to, and
    nothing read it -- so a wrong base was visible on the tab and invisible to
    this function, which is the gap they close. Whether they hold against a real
    spreadsheet is an open row in docs/live-verification.md.

    A third value check was intended and cannot exist: an absent date arriving as
    an empty cell rather than as an empty string is invisible to a read, since
    Sheets returns "" or a short row for either. See the note where it would have
    gone.

    Opens with open_worksheet and not ensure_worksheet, deliberately: a missing
    tab means the sync was never run, and creating one here would manufacture the
    thing being checked.
    :param workspace: The workspace whose databases the tabs are compared against
    :param root: The directory workspaces live in, for tests
    :param spreadsheet: The spreadsheet to read
    :param book: An already-open spreadsheet, to save an authorization
    :param classes: Symbol to asset class, or None for the configured mapping
    :return: One GuardCase per check
    :rtype: tuple[GuardCase, ...]
    :raises SheetsUnavailable: if Sheets is unreachable or a tab is missing
    """

    portfolio: Portfolio = read_workspace(workspace=workspace, root=root)
    mapping: dict[str, str] = get_asset_classes() if classes is None else classes
    opened: Any = (
        book if book is not None else open_spreadsheet(spreadsheet=spreadsheet)
    )
    tabs: dict[str, Any] = {
        name: require_worksheet(
            book=opened, worksheet_name=name, spreadsheet=spreadsheet
        )
        for name in MACHINE_OWNED_TABS
    }

    cases: list[GuardCase] = [_banner_case(tabs=tabs)]

    for tab, columns in (
        (ACCOUNTS_TAB, ACCOUNT_COLUMNS),
        (HOLDINGS_TAB, HOLDING_COLUMNS),
        (TRANSACTIONS_TAB, TRANSACTION_COLUMNS),
        # Every tab that carries columns, which is every machine-owned tab but
        # the dashboard. The banner case above walks MACHINE_OWNED_TABS and so
        # picked this one up for free; this loop is written out, so a tab added
        # to the contract and not to here would be written every sync and never
        # checked -- covered enough to look covered.
        (NET_WORTH_TAB, NET_WORTH_COLUMNS),
    ):
        cases.append(_contract_case(worksheet=tabs[tab], tab=tab, columns=columns))

    cases.append(
        _count_case(
            worksheet=tabs[TRANSACTIONS_TAB], expected=len(portfolio.transactions)
        )
    )
    cases.extend(_date_cases(worksheet=tabs[TRANSACTIONS_TAB]))
    cases.append(_money_case(worksheet=tabs[ACCOUNTS_TAB]))
    cases.append(_totals_case(worksheet=tabs[DASHBOARD_TAB]))
    cases += _allocation_cases(worksheet=tabs[DASHBOARD_TAB], classes=mapping)

    # Check 4 -- an account with no date being surfaced rather than counted at
    # face value -- is deliberately absent and cannot be added here. It is a
    # question about a formula's behaviour, not a cell's contents, and read back an
    # empty cell and an empty string are the same value: "" or a short row for
    # both.
    #
    # Its absence costs less than it looks. The distinction only matters where a
    # formula counts one and not the other, and no dashboard formula does: As Of
    # reaches exactly one, the staleness QUERY in _bands, whose "is null or
    # < cutoff" catches an undated account either way -- the column holds text, not
    # dates, because the RAW write keeps it that way. Add a COUNTA or COUNTIF over
    # As Of and that stops holding, at which point this check has to come back.
    # docs/live-verification.md carries the reasoning.

    return tuple(cases)


def _values(worksheet: Any, cells: str, rendered: bool = False) -> list[list[Any]]:
    """
    A range, as text by default and as Sheets computed it when asked.

    Unformatted is what turns a currency cell into a float and a formula into the
    number it evaluated to -- which is the only way to ask whether money arrived
    as money, and the only way to compare a SUMIF against a literal.
    :param worksheet: The tab to read
    :param cells: An A1 range
    :param rendered: True to get values rather than their displayed text
    :return: Rows of cell values
    :rtype: list[list[Any]]
    """

    option: str = (
        ValueRenderOption.unformatted if rendered else ValueRenderOption.formatted
    )

    return worksheet.get_values(cells, value_render_option=option) or []


def _banner_case(tabs: dict[str, Any]) -> GuardCase:
    """
    The first cell of every tab, including the one with no columns.
    :param tabs: The machine-owned tabs, by name
    :return: What was found
    :rtype: GuardCase
    """

    missing: list[str] = [
        name
        for name, worksheet in tabs.items()
        if str(object=worksheet.acell(BANNER_CELL).value or "").strip() != BANNER
    ]

    return GuardCase(
        name=f"All {len(tabs)} tabs carry the banner in {BANNER_CELL}",
        expected="present",
        passed=not missing,
        detail="" if not missing else f"without it: {', '.join(missing)}",
    )


def _contract_case(worksheet: Any, tab: str, columns: Sequence[str]) -> GuardCase:
    """
    Row 2, against the contract as etc.portfolio spells it.

    Exact and in order, not a subset: the dashboard addresses columns by
    position, so a column that moved keeps every formula pointing somewhere
    plausible and wrong.
    :param worksheet: The tab to read
    :param tab: Its name
    :param columns: What row 2 must say
    :return: What was found
    :rtype: GuardCase
    """

    last: str = last_column(columns=columns)
    found: list[list[Any]] = _values(
        worksheet=worksheet, cells=f"A{HEADER_ROW}:{last}{HEADER_ROW}"
    )
    header: list[str] = [str(object=cell) for cell in (found[0] if found else [])]
    want: list[str] = list(columns)

    return GuardCase(
        name=f"{tab} row {HEADER_ROW} is the column contract, ending at {last}",
        expected="exact",
        passed=header == want,
        detail="" if header == want else f"found {header or 'nothing'}",
    )


def _count_case(worksheet: Any, expected: int) -> GuardCase:
    """
    Every movement the databases hold, against what the tab holds.

    Counted against read_workspace rather than against the shell's reader, whose
    limit of five hundred is the thing this check exists to see past.
    :param worksheet: The Transactions tab
    :param expected: How many movements the databases hold
    :return: What was found
    :rtype: GuardCase
    """

    key: str = column_of(columns=TRANSACTION_COLUMNS, name="Account Key")
    found: int = len(
        [value for value in _column_at(worksheet=worksheet, letter=key) if value]
    )

    return GuardCase(
        name=f"Transactions holds all {expected} movements the databases have",
        expected="all",
        passed=found == expected,
        detail="" if found == expected else f"the tab has {found}",
    )


def _column_at(worksheet: Any, letter: str, rendered: bool = False) -> list[Any]:
    """
    One column by letter, from the first data row down.
    :param worksheet: The tab to read
    :param letter: The column letter
    :param rendered: True to get values rather than their displayed text
    :return: The values
    :rtype: list[Any]
    """

    rows: list[list[Any]] = _values(
        worksheet=worksheet,
        cells=f"{letter}{FIRST_DATA_ROW}:{letter}",
        rendered=rendered,
    )

    return [row[0] if row else "" for row in rows]


def _date_cases(worksheet: Any) -> tuple[GuardCase, GuardCase]:
    """
    Processed On, in one format and in one order.

    The sources disagree -- the 529 scraper stores "12/30/2025" and SnapTrade
    stores ISO -- so the tab is where they must agree, and a "12/30/2025" in a
    cell means the normalization was skipped. The order follows from that: it
    sorts above every January, so a tab whose dates were not normalized is also
    a tab whose ordering is wrong.
    :param worksheet: The Transactions tab
    :return: The format case and the ordering case
    :rtype: tuple[GuardCase, GuardCase]
    """

    keys: list[Any] = _column_at(
        worksheet=worksheet,
        letter=column_of(columns=TRANSACTION_COLUMNS, name="Account Key"),
    )
    dates: list[Any] = _column_at(
        worksheet=worksheet,
        letter=column_of(columns=TRANSACTION_COLUMNS, name="Processed On"),
    )
    pattern: re.Pattern[str] = re.compile(pattern=ISO_DATE_PATTERN)
    odd: list[str] = [
        str(object=value)
        for value in dates
        if str(object=value) and not pattern.match(string=str(object=value))
    ]

    unsorted: list[str] = []
    seen: dict[str, str] = {}

    # Not strict: Sheets trims trailing empties per column, so two columns off the
    # same rows can come back different lengths. Pairing what overlaps is right --
    # the count is checked separately, by _count_case.
    for key, value in zip(keys, dates, strict=False):
        account, date = str(object=key), str(object=value)

        if not account or not date:
            continue

        if account in seen and date > seen[account]:
            unsorted.append(account)

        seen[account] = date

    return (
        GuardCase(
            name="Every Processed On is YYYY-MM-DD",
            expected="normalized",
            passed=not odd,
            detail="" if not odd else f"found {sorted(set(odd))[:5]}",
        ),
        GuardCase(
            name="Processed On runs newest-first within each account",
            expected="sorted",
            passed=not unsorted,
            detail=""
            if not unsorted
            else f"out of order under {sorted(set(unsorted))[:5]}",
        ),
    )


def _money_case(worksheet: Any) -> GuardCase:
    """
    Value on Accounts, as a number rather than as text.

    The failure this catches is a regression to writing strings: a currency cell
    holding "1234.00" totals as zero in every formula that touches it, and looks
    identical to one holding 1234.0 unless you notice which way it aligns.
    :param worksheet: The Accounts tab
    :return: What was found
    :rtype: GuardCase
    """

    # Rendered, and the check does not work any other way: the formatted read
    # returns display text for every cell, so a perfectly good 1234.5 comes back
    # as "1,234.50" and this would report every sheet as broken. Unformatted is
    # what distinguishes a number Sheets stored from a string it was handed.
    values: list[Any] = [
        value
        for value in _column_at(
            worksheet=worksheet,
            letter=column_of(columns=ACCOUNT_COLUMNS, name="Value"),
            rendered=True,
        )
        if value != ""
    ]
    text: list[Any] = [value for value in values if not isinstance(value, (int, float))]

    return GuardCase(
        name="Accounts Value is a number, not text",
        expected="numeric",
        passed=not text,
        detail="" if not text else f"{len(text)} of {len(values)} came back as text",
    )


def _totals_case(worksheet: Any) -> GuardCase:
    """
    The dashboard's two totals, which are one number computed twice.

    Sheets over the cells beside Python over the databases. They disagree only if
    the write was truncated or a row failed to land, which is otherwise
    invisible. Located by reading the labels back rather than by row number, so
    a reordered summary is caught here instead of comparing the wrong two cells.
    :param worksheet: The Dashboard tab
    :return: What was found
    :rtype: GuardCase
    """

    labels: list[Any] = _column_at(worksheet=worksheet, letter=SUMMARY_COL)
    name: str = "The dashboard's two totals agree"

    try:
        computed = _summary_value(
            worksheet=worksheet, labels=labels, label="Total (USD)"
        )
        as_read = _summary_value(
            worksheet=worksheet, labels=labels, label="Total as read"
        )

    except (LookupError, TypeError, ValueError) as e:
        return GuardCase(
            name=name,
            expected="equal",
            passed=False,
            detail=f"could not read both ({e})",
        )

    # Two floats that came from the same numbers by different routes, so this is
    # a rounding tolerance and not a fuzzy match.
    agree: bool = abs(computed - as_read) < 0.01

    return GuardCase(
        name=name,
        expected="equal",
        passed=agree,
        detail="" if agree else f"Sheets says {computed}, Python says {as_read}",
    )


def _summary_value(worksheet: Any, labels: list[Any], label: str) -> float:
    """
    One summary row's value, found by its label.
    :param worksheet: The Dashboard tab
    :param labels: The label column, from the first data row down
    :param label: The row to find
    :return: The value beside it
    :rtype: float
    :raises LookupError: if the label is not there
    :raises ValueError: if the cell beside it is empty or not a number
    """

    row: int = FIRST_DATA_ROW + [str(object=cell) for cell in labels].index(label)
    found: list[list[Any]] = _values(
        worksheet=worksheet, cells=f"B{row}:B{row}", rendered=True
    )

    # Checked rather than indexed into. An empty cell comes back as an empty row
    # or as no rows at all, and while the IndexError that would cause is a
    # LookupError and so already caught by the caller, arriving there by accident
    # of the exception hierarchy is not the same as saying what went wrong.
    if not found or not found[0]:
        raise ValueError(f"the cell beside '{label}' is empty")

    return float(found[0][0])


def _slices_case(worksheet: Any, start: str, heading: str, total: float) -> GuardCase:
    """
    One allocation block's closing row, read back off the tab.

    Every block ends with ALLOCATION_CHECK, whose two cells are what the slices
    above it actually came to -- the sheet's own arithmetic over the cells it
    wrote. The module says of that row that a wrong base "shows up as a share
    column that does not come to 1, visible without anybody having to add the
    column up by hand". It was visible and nothing looked: the row was written
    and never read, so a block whose shares summed to 0.8 would have been written,
    reported as a success, and agreed with by every other check here.

    That is the failure this project keeps finding -- the run reporting success
    because from its side nothing went wrong -- sitting inside the row built to
    prevent it. This is the thing that looks.
    :param worksheet: The Dashboard tab
    :param start: The block's first column letter
    :param heading: What the block is called, for the case name
    :param total: Total (USD), which the values must come to
    :return: What was found
    :rtype: GuardCase
    """

    name: str = f"The {heading.lower()} allocation adds up"
    labels: list[str] = [
        str(object=cell) for cell in _column_at(worksheet=worksheet, letter=start)
    ]

    if ALLOCATION_REFUSED in labels:
        # A refusal is the block working, not failing. It draws nothing precisely
        # because the arithmetic it would render is wrong, and a check that read
        # that as a defect would report the safety mechanism as the fault.
        return GuardCase(
            name=name,
            expected="equal",
            passed=True,
            detail="not drawn: positions exceed account balances, which the "
            "block says in place of rendering a negative wedge",
        )

    if ALLOCATION_CHECK not in labels:
        return GuardCase(
            name=name,
            expected="equal",
            passed=False,
            detail=f"no '{ALLOCATION_CHECK}' row in column {start}",
        )

    row: int = FIRST_DATA_ROW + labels.index(ALLOCATION_CHECK)
    values: str = column_letter(index=column_index(letter=start) + 1)
    shares: str = column_letter(index=column_index(letter=start) + 2)
    found: list[list[Any]] = _values(
        worksheet=worksheet, cells=f"{values}{row}:{shares}{row}", rendered=True
    )

    try:
        summed = float(found[0][0])
        share = float(found[0][1])

    except (IndexError, TypeError, ValueError) as e:
        return GuardCase(
            name=name,
            expected="equal",
            passed=False,
            detail=f"could not read the '{ALLOCATION_CHECK}' row ({e})",
        )

    # Money to the cent, as _totals_case compares its two totals: both sides came
    # from the same numbers by different routes, so this is rounding and not a
    # fuzzy match.
    adds_up: bool = abs(summed - total) < 0.01

    if not adds_up:
        return GuardCase(
            name=name,
            expected="equal",
            passed=False,
            detail=f"the slices come to {summed}, the total is {total}",
        )

    if abs(total) < 0.01:
        # An empty workspace divides by zero, so every share is IFERROR'd to ""
        # and the column sums to nothing. There is no base for a share to be
        # wrong about, so the question is not asked rather than answered no.
        return GuardCase(
            name=name,
            expected="equal",
            passed=True,
            detail="no money in the workspace, so the shares have no base",
        )

    whole: bool = abs(share - 1.0) < ALLOCATION_TOLERANCE

    return GuardCase(
        name=name,
        expected="equal",
        passed=whole,
        detail="" if whole else f"the shares come to {share} rather than 1",
    )


def _allocation_cases(worksheet: Any, classes: dict[str, str]) -> list[GuardCase]:
    """
    Every allocation block that should be on the tab, checked against the total.

    The two that are always drawn, plus the asset class block when a mapping is
    configured -- which is why the mapping has to reach this function rather than
    being inferred from the tab. Inferring it would make an absent block
    indistinguishable from a block that failed to write, and the absent one is
    correct only when nobody asked for it.
    :param worksheet: The Dashboard tab
    :param classes: Symbol to asset class, as configured
    :return: One case per block expected to be drawn
    :rtype: list[GuardCase]
    """

    blocks: list[tuple[str, str]] = [
        (BY_KIND_COL, "Account kind"),
        (BY_POSITION_COL, "Position"),
    ]

    if classes:
        blocks.append((BY_CLASS_COL, "Asset class"))

    labels: list[Any] = _column_at(worksheet=worksheet, letter=SUMMARY_COL)

    try:
        total: float = _summary_value(
            worksheet=worksheet, labels=labels, label="Total (USD)"
        )

    except (LookupError, TypeError, ValueError) as e:
        # One failure rather than one per block: they would all be the same
        # failure, and a reader counting three red lines would go looking for
        # three problems.
        return [
            GuardCase(
                name="The allocation blocks add up",
                expected="equal",
                passed=False,
                detail=f"could not read the total they are shares of ({e})",
            )
        ]

    return [
        _slices_case(worksheet=worksheet, start=start, heading=heading, total=total)
        for start, heading in blocks
    ]


#: The tab check_ownership_guard() makes and removes. Named to read as disposable
#: and to be nothing a person would reach for, because the one thing this must
#: never do is delete a tab somebody wanted.
GUARD_CHECK_TAB: str = "StonkSmith ownership check"


@dataclass(frozen=True)
class GuardCase:
    """
    One outcome claim() was asked for, and what it did.

    ``passed`` is whether claim() behaved, not whether it refused: two of the
    three cases expect a refusal and the third expects an adoption, so the
    refusal itself is not the signal. ``detail`` carries the refusal message, or
    what came back instead when it did not.
    """

    name: str
    expected: str
    passed: bool
    detail: str = ""


def check_ownership_guard(
    spreadsheet: str = SPREADSHEET_NAME,
    book: Any | None = None,
    tab: str = GUARD_CHECK_TAB,
) -> tuple[GuardCase, ...]:
    """
    Put claim() in front of real Sheets, on a tab of its own.

    The refusal is the one claim in this module whose failure cannot be undone by
    running again -- a sync that ate a hand-written tab has already eaten it --
    and until now the only way to observe it was to deface a live tab and hand it
    back. That is a thing done once, nervously, if at all, which is a poor way to
    hold up a safety property.

    It does not need to be that. claim() decides on what a tab *holds*, not on
    what it is called; MACHINE_OWNED_TABS only picks which tabs refresh() claims.
    So the same function, over the same network, can be asked all three of its
    questions on a tab created for the purpose and removed afterwards, with the
    real tabs never opened.

    What this does not cover: that a refusal stops the *whole* sync, leaving no
    tab freshly written beside a stale one. That is refresh() claiming every tab
    before clearing any, this tab is not one of them, and observing it still
    means defacing a real one.

    Deleting a tab is not something anything else here does, so the guards
    matter more than the checks. A tab of this name that already exists is
    somebody else's and stops the run; the only tab ever removed is the one this
    call made; and a name that has found its way into MACHINE_OWNED_TABS is
    refused before Sheets is touched at all.
    :param spreadsheet: The spreadsheet to work in
    :param book: An already-open spreadsheet, to save an authorization
    :param tab: The throwaway tab's name
    :return: One GuardCase per outcome, in the order they were tried
    :rtype: tuple[GuardCase, ...]
    :raises SheetsUnavailable: if Sheets is unreachable, or the tab is taken
    """

    if tab in MACHINE_OWNED_TABS:
        raise SheetsUnavailable(
            f"'{tab}' is one of the tabs StonkSmith writes, so it cannot be used "
            "as the throwaway tab for this check. Pass a different name."
        )

    opened: Any = (
        book if book is not None else open_spreadsheet(spreadsheet=spreadsheet)
    )

    if tab_exists(book=opened, worksheet_name=tab, spreadsheet=spreadsheet):
        # Not ours, so not ours to clear and not ours to delete. The same answer
        # claim() gives, for the same reason.
        raise SheetsUnavailable(
            f"Spreadsheet '{spreadsheet}' already has a tab named '{tab}'. This "
            "check makes that tab and deletes it again, so it will not touch one "
            "that is already there. Rename or remove it, or pass another name."
        )

    made: Any = opened.add_worksheet(title=tab, rows=100, cols=8)
    cases: list[GuardCase] = []

    try:
        cases.append(
            _guard_case(
                book=opened,
                tab=tab,
                name="A defaced first cell is refused",
                text_at=(BANNER_CELL, "Mine, not StonkSmith's"),
                refusal_expected=True,
            )
        )
        cases.append(
            _guard_case(
                book=opened,
                tab=tab,
                # The subtle one, and the shape both a leftover layout and a tab
                # somebody started on row 3 have. A1 empty is not enough to adopt.
                name="Text below a blank first cell is refused",
                text_at=("A3", "Mine, further down"),
                refusal_expected=True,
            )
        )
        cases.append(
            _guard_case(
                book=opened,
                tab=tab,
                name="A wholly empty tab is adopted",
                # Neither 2026-08-10 run reached this: both had the banner in A1,
                # so claim() answered on the first read and never took the branch
                # that decides whether an empty tab can be handed over.
                text_at=None,
                refusal_expected=False,
            )
        )

    finally:
        # Whatever happened above, including something unexpected. remove_tab
        # reports rather than raises, so a scratch tab that would not go cannot
        # replace the findings with the news that it is still there.
        failure: str = remove_tab(book=opened, worksheet=made, worksheet_name=tab)
        cases.append(
            GuardCase(
                name="The throwaway tab was removed",
                expected="removed",
                passed=not failure,
                detail=failure,
            )
        )

    return tuple(cases)


def _guard_case(
    book: Any,
    tab: str,
    name: str,
    text_at: tuple[str, str] | None,
    refusal_expected: bool,
) -> GuardCase:
    """
    Set one tab state up and ask claim() about it.

    A fresh handle for the question, deliberately. claim() remembers its answer
    on the worksheet object, and while it only remembers an adoption, re-fetching
    keeps every case a real round trip rather than a cached one.
    :param book: The open spreadsheet
    :param tab: The throwaway tab's name
    :param name: What this case is called, for the report
    :param text_at: A cell and the text to put in it, or None to leave it empty
    :param refusal_expected: Whether claim() ought to refuse
    :return: What happened
    :rtype: GuardCase
    """

    staged: Any = book.worksheet(tab)
    staged.clear()

    if text_at is not None:
        cell, text = text_at
        staged.update_acell(cell, text)

    expected: str = "refused" if refusal_expected else "adopted"
    fresh: Any = book.worksheet(tab)

    try:
        claim(worksheet=fresh, tab=tab)

    except SheetNotOwned as e:
        return GuardCase(
            name=name,
            expected=expected,
            passed=refusal_expected,
            detail=str(object=e),
        )

    return GuardCase(
        name=name,
        expected=expected,
        passed=not refusal_expected,
        detail="" if not refusal_expected else "the tab was adopted instead",
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


def down(tab: str, columns: Sequence[str], name: str) -> str:
    """
    One whole data column, absolutely addressed and open-ended.

    Shared by the summary and the allocation blocks so that both address a
    column the one way this module allows -- through column_of, never typed.
    :param tab: The tab the column is on
    :param columns: The column contract that tab carries
    :param name: The column's name in that contract
    :return: A range such as "'Accounts'!$G$3:$G"
    :rtype: str
    :raises KeyError: if the contract has no such column
    """

    letter: str = column_of(columns=columns, name=name)
    return f"{tab_ref(tab=tab)}${letter}${FIRST_DATA_ROW}:${letter}"


def _summary(portfolio: Portfolio) -> tuple[list[list[Any]], list[list[Any]]]:
    """
    The dashboard's summary block, split into labels and values.

    :param portfolio: What the workspace holds
    :return: (label column, value column) as single-column grids
    :rtype: tuple[list[list[Any]], list[list[Any]]]
    """

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

    labels: list[list[Any]] = [[label] for label in SUMMARY_LABELS]
    at = summary_cell

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


def _quoted(text: str) -> str:
    """
    A string safe to drop inside a formula's double quotes.

    A slice's name comes from a broker, not from this module: an account kind or
    a fund code carrying a double quote would otherwise close the criterion
    early and leave the rest of it as syntax, which is a broken formula at best
    and a silently different criterion at worst.
    :param text: The name to embed
    :return: The name with its quotes doubled, as Sheets escapes them
    :rtype: str
    """

    return text.replace('"', '""')


def _slices(rows: Sequence[Any], name: str, currency: str) -> list[tuple[str, float]]:
    """
    One (name, value) pair per distinct slice, largest first.

    Only rows in the asked-for currency, because that is the only total the
    shares can be a share of -- Portfolio.total refuses to add a dollar to a
    euro, and a breakdown must not do quietly what the code declines to do
    loudly. Whatever is therefore left out is named by the summary block's
    "Other currencies present" rather than folded in at a rate nothing here
    knows.
    :param rows: AccountRow or HoldingRow values to group
    :param name: The attribute to group on, "kind" or "symbol"
    :param currency: The currency to keep
    :return: (slice name, value) sorted by value descending then name
    :rtype: list[tuple[str, float]]
    """

    totals: dict[str, float] = {}

    for row in rows:
        if row.value is None or row.currency != currency:
            continue

        # Grouped on exactly what _cell wrote to the sheet -- not stripped, not
        # case-folded, not tidied. This key becomes a SUMIFS criterion, and a
        # criterion that has been cleaned up no longer matches the cell it is
        # meant to find: a broker reporting "VTI " would be grouped under "VTI",
        # searched for as "VTI", and add up to nothing. Two spellings of one
        # ticker therefore get two rows, which looks worse and is right -- they
        # are two different strings on the tab, and between a breakdown that
        # shows both and one that silently drops half a position, the honest
        # answer is both. Tidying belongs on the way in, where the tab would see
        # it too, and not here.
        #
        # None becomes "" for the same reason: that is the cell _cell wrote, and
        # "" is the criterion that matches an empty one. The label the reader
        # sees is chosen at the call site; the criterion stays raw.
        key: str = str(object=getattr(row, name) or "")
        totals[key] = totals.get(key, 0.0) + row.value

    return sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))


def _class_slices(
    holdings: Sequence[Any], mapping: dict[str, str], currency: str
) -> list[tuple[str, list[str], float]]:
    """
    One (class, its symbols, value) triple per asset class held, largest first.

    Unlike the other two breakdowns, a class is not a column on any tab -- it is
    a name the operator gave to a set of symbols. So a slice carries the symbols
    rather than a single criterion, and its formula adds up one SUMIFS per symbol
    over the column that *is* on the tab. Nothing new is written to Holdings for
    this: a class is a fact about the operator's opinion, not about the position,
    and the rule that a column belongs to a fact the database holds is the reason
    Units As Of got one and Ally's G/L did not.

    The keys are raw, for the reason _slices spells out at length: they become
    SUMIFS criteria, and a criterion that has been tidied no longer matches the
    cell it is meant to find. A configured "vti" therefore does not classify a
    held "VTI" -- it classifies nothing, and _unmatched_classes reports it.

    :param holdings: HoldingRow values to group
    :param mapping: Symbol to class name, as configured
    :param currency: The currency to keep
    :return: (class, symbols ascending, value), declared classes by value
        descending then name, with the unclassified residual last
    :rtype: list[tuple[str, list[str], float]]
    """

    totals: dict[str, float] = {}
    symbols: dict[str, set[str]] = {}

    for row in holdings:
        if row.value is None or row.currency != currency:
            continue

        key: str = str(object=row.symbol or "")
        label: str = mapping.get(key, UNCLASSIFIED)

        totals[label] = totals.get(label, 0.0) + row.value
        symbols.setdefault(label, set()).add(key)

    # The residual sits below the declared classes rather than being sorted in
    # among them. It is a different kind of row -- what nobody has said anything
    # about -- and it belongs beside the cash slice for the same reason: both are
    # what is left after the breakdown, not slices of it.
    ordered: list[str] = sorted(
        (label for label in totals if label != UNCLASSIFIED),
        key=lambda label: (-totals[label], label),
    )

    if UNCLASSIFIED in totals:
        ordered.append(UNCLASSIFIED)

    return [(label, sorted(symbols[label]), totals[label]) for label in ordered]


def _unmatched_classes(
    portfolio: Portfolio, mapping: dict[str, str]
) -> tuple[str, ...]:
    """
    Configured symbols that nothing in the workspace holds.

    A mapping line is typed by hand and matched exactly, so the way it fails is
    silence: the symbol classifies nothing, its holdings fall into the
    unclassified slice, and the tab looks the same as it would with no line at
    all. Reported by the run so a typo says so, which is the only feedback there
    is that the config took effect.
    :param portfolio: What the workspace holds
    :param mapping: Symbol to class name, as configured
    :return: The unmatched symbols, in the order they were configured
    :rtype: tuple[str, ...]
    """

    held: set[str] = {str(object=row.symbol or "") for row in portfolio.holdings}

    return tuple(symbol for symbol in mapping if symbol not in held)


def _block(
    start: str,
    heading: str,
    slices: Sequence[tuple[str, float]],
    criterion_range: str,
    value_range: str,
    currency_range: str,
    unnamed: str,
    currency: str,
    extra: Sequence[tuple[str, str]] = (),
) -> list[list[Any]]:
    """
    One allocation block: a header row, a row per slice, and a check row.

    The slice names come from Python and the numbers come from formulas over the
    data tabs, which is the split the summary block already uses. Nothing here
    is a QUERY: QUERY cannot divide a group's sum by a scalar, so the share
    column would need an open-ended ARRAYFORMULA that spills down the whole grid
    and cannot be pinned by a test. A SUMIFS per row is longer and exact.
    :param start: The block's first column letter
    :param heading: What the name column is called
    :param slices: (name, value) pairs, already ordered
    :param criterion_range: The column SUMIFS matches names against
    :param value_range: The column SUMIFS adds up
    :param currency_range: The column SUMIFS filters on currency
    :param unnamed: The label for a slice whose name the source left blank
    :param currency: The currency being totalled
    :param extra: (label, value formula) rows appended after the slices
    :return: The grid, header row first
    :rtype: list[list[Any]]
    """

    # The names go in `start` itself; these two are the columns beside it.
    values: str = column_letter(index=column_index(letter=start) + 1)
    shares: str = column_letter(index=column_index(letter=start) + 2)
    total: str = summary_cell(label="Total (USD)")

    # Stated in the header rather than left to be inferred. A share whose base
    # is unnamed is the failure this block exists to avoid: percentages over the
    # holdings subtotal leave the cash out and still add to 100%.
    grid: list[list[Any]] = [
        [heading, f"Value ({currency})", f"Share of total ({currency})"]
    ]

    for offset, (name, _) in enumerate(slices):
        row: int = FIRST_DATA_ROW + offset
        grid.append(
            [
                # Stripped for the label and only for the label. A name that is
                # blank or nothing but spaces reads as an empty row, which is
                # indistinguishable from one that failed to write -- so it is
                # named. The criterion beside it keeps the raw string, because
                # that is what is on the tab.
                name.strip() or unnamed,
                f"=SUMIFS({value_range},{criterion_range},"
                f'"{_quoted(text=name)}",{currency_range},"{currency}")',
                f'=IFERROR({values}{row}/{total},"")',
            ]
        )

    for label, formula in extra:
        row = FIRST_DATA_ROW + len(grid) - 1
        grid.append([label, formula, f'=IFERROR({values}{row}/{total},"")'])

    last: int = FIRST_DATA_ROW + len(grid) - 2
    grid.append(
        [
            ALLOCATION_CHECK,
            f"=SUM({values}{FIRST_DATA_ROW}:{values}{last})",
            f"=SUM({shares}{FIRST_DATA_ROW}:{shares}{last})",
        ]
    )

    return grid


def _sum_of(
    symbols: Sequence[str],
    criterion_range: str,
    value_range: str,
    currency_range: str,
    currency: str,
) -> str:
    """
    One class slice's value: a SUMIFS per symbol in it, added together.

    Longer than an array criterion and deliberately so. The alternative that
    reads better -- one SUMIFS over a {"VTI";"VOO"} literal wrapped in
    SUMPRODUCT -- puts the set of symbols inside a piece of spreadsheet syntax,
    where a fund code containing a semicolon or a brace stops being a string and
    starts being punctuation. A term per symbol quotes each one the same way
    every other criterion on this tab is quoted, and _quoted is then the only
    thing standing between scraped text and the formula.
    :param symbols: The raw symbols in the class, as the tab spells them
    :param criterion_range: The column SUMIFS matches symbols against
    :param value_range: The column SUMIFS adds up
    :param currency_range: The column SUMIFS filters on currency
    :param currency: The currency being totalled
    :return: The value formula
    :rtype: str
    """

    return "=" + "+".join(
        f'SUMIFS({value_range},{criterion_range},"{_quoted(text=symbol)}",'
        f'{currency_range},"{currency}")'
        for symbol in symbols
    )


def _refused(heading: str, cash: float) -> list[list[Any]]:
    """
    What a holdings-based block says instead of drawing itself.

    Stated in place of the block, not left blank -- an empty region is
    indistinguishable from a write that failed, which is the same reason the
    unreadable panel says "everything read". Shared by the two blocks built over
    holdings, because the arithmetic that defeats them is the same arithmetic and
    two wordings of it could come to disagree.
    :param heading: What the block's name column is called
    :param cash: The gap, which is negative here
    :return: The grid, header row first
    :rtype: list[list[Any]]
    """

    return [
        [heading, f"Value ({USD})", f"Share of total ({USD})"],
        [
            ALLOCATION_REFUSED,
            f"positions exceed account balances by {-cash:,.2f} {USD}, "
            "so something is counted twice",
            "",
        ],
    ]


def _allocation(
    portfolio: Portfolio, classes: dict[str, str] | None = None
) -> dict[str, list[list[Any]]]:
    """
    The dashboard's allocation blocks, keyed by the column they start in.

    Two always, and a third when it has been configured, because no one of them
    alone is honest. Account kind is free -- it is already on AccountRow, needs
    no data this project does not have, and its slices are account balances, so
    they add up to the portfolio exactly with no cash left over. Position is the
    breakdown somebody actually wants, and it is the one with the problem:
    holdings do not sum to the portfolio, because uninvested cash sits in a
    balance and in no position. So cash is a named slice here, taken from the
    very cell the summary block already publishes it in, and every share divides
    by the portfolio total rather than by the holdings subtotal.

    Asset class is the third, and it exists only because somebody typed it. No
    source here supplies one: SnapTrade gives a ticker, a scraped 529 gives a
    fund code, TSP gives a fund. So the mapping is config -- see
    etc.config.get_asset_classes -- and this block groups by what it says and
    names what it does not cover, rather than deriving a class from a ticker. A
    guess buried in a formula would still be a guess, and it would be one nobody
    could see. Sector and region stay absent for the reason class used to be:
    nothing states them and no lookup has been added to ask.

    With no mapping the block is not drawn at all. One 100% "(unclassified)"
    wedge is not a breakdown, and unlike the refusal above there is nothing to
    report -- a block nobody asked for is absent rather than empty.

    The mapping is passed in rather than read here. Rendering a tab is not the
    layer that should be deciding what the user's config file says: refresh()
    reads it once at the edge, the way it resolves the workspace once at the
    edge, and everything below this point works off values it was handed.
    :param portfolio: What the workspace holds
    :param classes: Symbol to asset class, or None for no mapping
    :return: Start column to grid, header row first
    :rtype: dict[str, list[list[Any]]]
    """

    kinds: list[tuple[str, float]] = _slices(
        rows=portfolio.accounts, name="kind", currency=USD
    )
    positions: list[tuple[str, float]] = _slices(
        rows=portfolio.holdings, name="symbol", currency=USD
    )
    mapping: dict[str, str] = classes or {}

    # Derived once and shared: the position block and the class block address the
    # same three columns of the same tab, and two derivations of one range is one
    # more place for them to come apart.
    symbol_range: str = down(tab=HOLDINGS_TAB, columns=HOLDING_COLUMNS, name="Symbol")
    held_range: str = down(tab=HOLDINGS_TAB, columns=HOLDING_COLUMNS, name="Value")
    held_currency: str = down(
        tab=HOLDINGS_TAB, columns=HOLDING_COLUMNS, name="Currency"
    )

    # The cash row both holdings blocks close on. Pointed at rather than
    # recomputed per block, for the reason it is pointed at rather than
    # subtracted: one number, one cell, no way for two of them to disagree.
    uninvested: tuple[str, str] = (
        "Cash and uninvested",
        f"={summary_cell(label='In accounts, not in positions')}",
    )

    blocks: dict[str, list[list[Any]]] = {
        BY_KIND_COL: _block(
            start=BY_KIND_COL,
            heading="Account kind",
            slices=kinds,
            criterion_range=down(
                tab=ACCOUNTS_TAB, columns=ACCOUNT_COLUMNS, name="Kind"
            ),
            value_range=down(tab=ACCOUNTS_TAB, columns=ACCOUNT_COLUMNS, name="Value"),
            currency_range=down(
                tab=ACCOUNTS_TAB, columns=ACCOUNT_COLUMNS, name="Currency"
            ),
            unnamed=UNNAMED_KIND,
            currency=USD,
        )
    }

    # The same subtraction the summary block already does, pointed at rather
    # than repeated. A second copy of it could drift from the first, and two
    # cells on one tab disagreeing about how much cash there is would be worse
    # than not drawing the slice at all.
    cash: float = portfolio.total(currency=USD) - portfolio.invested(currency=USD)

    if cash < -ALLOCATION_TOLERANCE:
        # Refused rather than drawn. A negative gap means some position is
        # counted twice, and the slice it implies cannot exist: it would be a
        # negative wedge in a pie, with every other share overstated to make
        # room for it. Both holdings blocks refuse together -- the class block is
        # the same money grouped a second way, so a version of it that drew while
        # the position block refused would be the same lie with better manners.
        blocks[BY_POSITION_COL] = _refused(heading="Position", cash=cash)

        if mapping:
            blocks[BY_CLASS_COL] = _refused(heading="Asset class", cash=cash)

        return blocks

    blocks[BY_POSITION_COL] = _block(
        start=BY_POSITION_COL,
        heading="Position",
        slices=positions,
        criterion_range=symbol_range,
        value_range=held_range,
        currency_range=held_currency,
        unnamed=UNNAMED_SYMBOL,
        currency=USD,
        extra=(uninvested,),
    )

    if mapping:
        blocks[BY_CLASS_COL] = _block(
            start=BY_CLASS_COL,
            heading="Asset class",
            # Every row of this block is an extra rather than a slice: a slice is
            # one name matched against one column, and a class is a set of
            # symbols with no column of its own. _block's extra rows already get
            # the share column and the check row, so the block closes on the same
            # arithmetic as the other two without _block knowing about classes.
            slices=(),
            criterion_range=symbol_range,
            value_range=held_range,
            currency_range=held_currency,
            # Unreachable while slices is empty, and passed as what it would have
            # to be rather than as a placeholder that would be wrong the day it
            # is not.
            unnamed=UNCLASSIFIED,
            currency=USD,
            extra=(
                *(
                    (
                        label,
                        _sum_of(
                            symbols=symbols,
                            criterion_range=symbol_range,
                            value_range=held_range,
                            currency_range=held_currency,
                            currency=USD,
                        ),
                    )
                    for label, symbols, _ in _class_slices(
                        holdings=portfolio.holdings, mapping=mapping, currency=USD
                    )
                ),
                uninvested,
            ),
        )

    return blocks


def _block_updates(
    start: str, grid: Sequence[Sequence[Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    One allocation block's cells, split the way the two batches need them.

    Written a column at a time rather than a cell at a time: a workspace with
    three hundred positions would otherwise put nine hundred ranges into one
    request. Every column of a block is all formula or all literal -- the names
    are Python's, the numbers are the sheet's -- so the split is asked per
    column and never has to cut one in half.
    :param start: The block's first column letter
    :param grid: The block, header row first
    :return: (formula updates, literal updates)
    :rtype: tuple[list[dict[str, Any]], list[dict[str, Any]]]
    """

    formulas: list[dict[str, Any]] = []
    literals: list[dict[str, Any]] = [
        {
            "range": f"{start}{HEADER_ROW}:"
            f"{column_letter(index=column_index(letter=start) + len(grid[0]) - 1)}"
            f"{HEADER_ROW}",
            "values": [list(grid[0])],
        }
    ]

    body: list[Sequence[Any]] = list(grid[1:])

    if not body:
        return formulas, literals

    for offset in range(len(grid[0])):
        letter: str = column_letter(index=column_index(letter=start) + offset)
        column: list[list[Any]] = [[row[offset]] for row in body]
        update: dict[str, Any] = {
            "range": f"{letter}{FIRST_DATA_ROW}:"
            f"{letter}{FIRST_DATA_ROW + len(body) - 1}",
            "values": column,
        }

        # The name column is literal because of what it holds, not because of
        # what it looks like. It is the one column here carrying text a broker
        # chose, and a fund named "=IMPORTXML(...)" is precisely the string that
        # must not be asked whether it looks like a formula -- the answer is
        # yes, and the whole module goes up RAW to stop that answer mattering.
        #
        # Today the question never reaches it: every block ends with a "Slices
        # sum to" row, so the column is never all-formula and the check below
        # would land it in the literal batch anyway. That is a coincidence of
        # the current layout, not a property of it. A block that ever loses its
        # check row, or renders a single slice and nothing else, would start
        # executing scraped text and say nothing about it.
        if offset and all(_is_formula(cell=cell[0]) for cell in column):
            formulas.append(update)

        else:
            literals.append(update)

    return formulas, literals


def dashboard_cells(
    portfolio: Portfolio,
    today: dt.date | None = None,
    classes: dict[str, str] | None = None,
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
    :param classes: Symbol to asset class, or None for no mapping
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

    for start, grid in _allocation(portfolio=portfolio, classes=classes).items():
        block_formulas, block_literals = _block_updates(start=start, grid=grid)
        formulas += block_formulas
        literals += block_literals

    return formulas, literals


def write_dashboard(
    worksheet: Any,
    portfolio: Portfolio,
    today: dt.date | None = None,
    classes: dict[str, str] | None = None,
) -> None:
    """
    Claim the dashboard, empty it, and write both halves of it.
    :param worksheet: The Dashboard tab
    :param portfolio: What the workspace holds
    :param today: The date staleness is measured from, for tests
    :param classes: Symbol to asset class, or None for no mapping
    :return: None
    :raises SheetNotOwned: when the tab is not StonkSmith's
    """

    claim(worksheet=worksheet, tab=DASHBOARD_TAB)

    formulas, literals = dashboard_cells(
        portfolio=portfolio, today=today, classes=classes
    )

    # Every band starts on HEADER_ROW and spills downward -- the staleness query
    # by a row per account, the unreadable block by a row per broker that would
    # not open, the position allocation by a row per distinct symbol plus cash.
    # A grid too short for that does not truncate the band: Sheets refuses the
    # whole array with #REF!, so the panel whose job is to say what is stale
    # would be the first thing to vanish from a portfolio big enough to need it.
    # The allocation blocks are written cell ranges rather than spilled arrays
    # and so would truncate instead, which is worse -- a breakdown missing its
    # smallest slices still looks like a breakdown. The floor is only for the
    # empty case, where the summary block is the tallest thing on the tab.
    #
    # The net worth band spills by a row per date in the series, which is the
    # one of these that grows with the number of runs rather than with the size
    # of the portfolio -- so on any workspace with a history it is the tallest
    # thing on the tab, and the first to hit this.
    #
    # Measured off the same grids that get written, not recounted from the
    # portfolio: a height derived a second way is a height that can be wrong.
    blocks: dict[str, list[list[Any]]] = _allocation(
        portfolio=portfolio, classes=classes
    )

    spill: int = max(
        len(portfolio.accounts),
        len(portfolio.unreadable),
        len({row.date for row in portfolio.net_worth}),
        *(len(grid) - 1 for grid in blocks.values()),
    )

    fit(
        worksheet=worksheet,
        rows=max(DASHBOARD_MIN_ROWS, HEADER_ROW + spill),
        # The rightmost edge of the bands that sit furthest right, rather than
        # whichever one happens to be further today: the net worth band is three
        # columns wide at most -- the date, and one each for the carried and
        # observed halves of its total -- and every allocation block is
        # ALLOCATION_WIDTH. A max means moving any band's start column cannot
        # silently cut another one off at the edge of the grid.
        #
        # Taken off the blocks that were actually built, for the same reason the
        # height is: the asset class block is drawn only when a mapping is
        # configured, and reserving columns for a block nobody asked for would
        # widen every dashboard in the field to hold nothing.
        cols=max(
            column_index(letter=NET_WORTH_COL) + 2,
            *(column_index(letter=start) + ALLOCATION_WIDTH - 1 for start in blocks),
        ),
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
    classes: dict[str, str] | None = None,
) -> SheetSync:
    """
    Put everything every broker in the workspace holds onto the sheet.

    One read of the databases and one authorization, feeding five tabs. All of
    them are claimed before any is cleared: a tab that is not ours then costs
    nothing rather than leaving Accounts rewritten beside a stale Holdings.
    :param workspace: The workspace name, or None for the configured one
    :param root: The directory workspaces live in, for tests
    :param spreadsheet: The spreadsheet to write into
    :param book: An already-open spreadsheet, for tests and for reuse
    :param today: The date staleness is measured from, for tests
    :param classes: Symbol to asset class, or None for the configured mapping
    :return: What was written, and what would not read
    :rtype: SheetSync
    :raises SheetsUnavailable: if Sheets is unreachable or a tab is not ours
    """

    portfolio: Portfolio = read_workspace(workspace=workspace, root=root)

    # Read once, here, and handed down. This is the only place in the sheet path
    # that asks the config anything, which is what keeps rendering a function of
    # its arguments -- a dashboard that changed shape with the developer's own
    # config file would be untestable in the way that matters.
    mapping: dict[str, str] = get_asset_classes() if classes is None else classes

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
    write_dashboard(
        worksheet=tabs[DASHBOARD_TAB],
        portfolio=portfolio,
        today=today,
        classes=mapping,
    )

    return SheetSync(
        accounts=accounts,
        holdings=holdings,
        transactions=transactions,
        brokers_read=portfolio.brokers_read,
        unreadable=portfolio.unreadable,
        total=portfolio.total(),
        net_worth=net_worth,
        unmatched_classes=_unmatched_classes(portfolio=portfolio, mapping=mapping),
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

        if result.unmatched_classes:
            # A warning rather than a failure: the sheet is correct either way,
            # and the money is on it. What is wrong is the operator's belief that
            # they classified something -- a mapping line is matched exactly, so
            # the way a typo fails is by classifying nothing and looking no
            # different from having written no line at all.
            context.log.highlight(
                msg=(
                    "Asset class lines matching nothing held: "
                    f"{', '.join(result.unmatched_classes)}. Those holdings, if "
                    "any, are counted as unclassified."
                )
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
