# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""
ally.py: Helpers for the Ally Invest module.

Everything here is pure -- markup in, records out -- so the selectors can be
tested against a captured signed-in page without starting a browser. Two
properties of Ally's markup shaped all of it.

**The sign of a gain or a loss is not in the text.** A position that is down
$4.94 today renders as ``<span class="down">$4.94</span>``: the same characters
a $4.94 gain produces, with only the CSS class telling them apart. Read the
text alone and every loss on the page silently becomes a gain -- and the
resulting number looks perfectly reasonable, which is what makes it dangerous.
``signed_amount()`` exists for exactly that, and nothing here should read a
gain/loss element's text directly.

**Angular build attributes are not selectors.** Ally's build stamps
``_ngcontent-gdx-NNN`` onto every element and the ``gdx-NNN`` part changes with
each deploy, so a selector keyed on one works until the next release and then
matches nothing. What is stable is the component tag names Ally wrote
(``holdings-table``, ``total-market-value``, ``holding-row``), the handful of
classes its stylesheet depends on (``.dash-hldg-table``, ``.symbol``,
``.acc-totals``, ``.balance-column``), and ``title`` attributes.
"""

from typing import Any, cast

from bs4 import BeautifulSoup
from bs4.element import Tag

from stonksmith.etc.records import Holding
from stonksmith.helpers.normalize import to_amount, to_currency

#: Class Ally puts on a losing amount. A gain gets "up". Neither is written
#: with a sign, so this class *is* the minus sign.
LOSS_CLASS = "down"

#: The holdings grid. Both anchors are Ally's own: ``holdings-table`` is the
#: Angular component, ``dash-hldg-table`` the class its stylesheet targets.
HOLDINGS_TABLE_SELECTOR = "holdings-table table.dash-hldg-table"

#: One position. The attribute is the component's selector, so it is as stable
#: as the component itself.
HOLDING_ROW_SELECTOR = "tr[holding-row]"

#: Column headings read positionally, because these two cells are plain
#: ``<td><div><span>number</span></div></td>`` with no component to anchor on.
#: Everything else in a row has its own element and is looked up by name.
QUANTITY_HEADER = "Qty"
COST_BASIS_HEADER = "Cost Basis"

#: The left-hand account rail. Two anchors because the component and the id
#: fail differently. Named here rather than written inline so the module can
#: wait for the same thing this file parses -- the rail renders after the
#: holdings do, and reading it early is indistinguishable from it being gone.
SIDEBAR_SELECTOR = "ally-accounts-list li, #allyAccountsList li"

#: Sidebar entries carry a ``<kind>-account`` class: "investments-account",
#: "savings-account". The suffix is stripped to get the kind.
ACCOUNT_CLASS_SUFFIX = "-account"

#: The kind that belongs to this broker. The same sidebar also lists Ally Bank
#: deposit accounts, which are not Ally Invest's to report.
INVESTMENT_KIND = "investments"

#: Separates the nickname from the account number in the page heading:
#: "Individual - 3LD21234".
SELECTED_ACCOUNT_SEPARATOR = " - "

#: How many trailing characters Ally leaves visible when it masks an account
#: number: "...1234".
MASKED_DIGITS = 4


def collapse(text: str) -> str:
    """
    Squeeze a scraped string onto one line.

    Ally's templates are pretty-printed, so almost every value arrives wrapped
    in newlines and indentation.
    :param text: Raw element text
    :return: The text with runs of whitespace reduced to single spaces
    :rtype: str
    """

    return " ".join(text.split())


def signed_amount(node: Tag | None) -> str:
    """
    Read a money element, putting back the minus sign Ally left in the CSS.

    Ally renders a $4.94 loss and a $4.94 gain with identical characters and
    distinguishes them only by a ``down``/``up`` class on the span holding the
    number. Taking the text at face value therefore records every loss as a
    gain, with nothing to notice: the sign is the only thing wrong and the
    magnitude is right.

    Prefers the classed span when there is one, which also picks the amount out
    of an element that carries the percentage beside it -- a total gain/loss
    cell holds ``$221.52`` and ``(9.90%)`` as two spans, and only the first is
    the amount.
    :param node: The element wrapping the amount, or None if it was not found
    :return: The amount as text, prefixed with "-" for a loss; "" when there is
        nothing to read
    :rtype: str
    """

    if node is None:
        return ""

    holder: Tag = node.select_one(selector=f".up, .{LOSS_CLASS}") or node
    text: str = collapse(text=holder.get_text())

    if not text:
        return ""

    classes: list[str] = [str(object=c) for c in cast(Any, holder.get("class")) or []]

    # Already-negative text would end up "--$4.94"; Ally does not currently
    # write one, but a sign appearing later must not double up.
    if LOSS_CLASS in classes and not text.startswith("-"):
        return f"-{text}"

    return text


def selected_account(soup: BeautifulSoup) -> tuple[str, str]:
    """
    The account the holdings table is currently showing.

    Ally puts it in the page heading as "Individual - 3LD21234". The number is
    the unmasked one, which the sidebar only shows masked, so it is what pairs
    the two together.
    :param soup: The parsed holdings page
    :return: (nickname, account number); either may be "" if the heading is
        absent or shaped differently
    :rtype: tuple[str, str]
    """

    heading: Tag | None = soup.select_one(selector="change-account [role='heading']")

    if heading is None:
        return "", ""

    text: str = collapse(text=heading.get_text())

    if SELECTED_ACCOUNT_SEPARATOR not in text:
        return text, ""

    # rsplit, not split: a nickname is free text and may well contain " - ".
    name, number = text.rsplit(sep=SELECTED_ACCOUNT_SEPARATOR, maxsplit=1)
    return name.strip(), number.strip()


def sidebar_accounts(soup: BeautifulSoup) -> list[dict[str, str]]:
    """
    Every account Ally lists in the left-hand rail, investing and banking both.

    Read even though only one account's holdings are on screen, because it is
    the only place the page says how many accounts exist. Without it a second
    investment account would simply never be mentioned by a run that appeared
    to succeed.
    :param soup: The parsed holdings page
    :return: One dict per account with "Kind" ("investments", "savings", ...),
        "Group", "Name", "Number" (masked, e.g. "...1234"), "Label" and
        "Balance"
    :rtype: list[dict[str, str]]
    """

    accounts: list[dict[str, str]] = []

    for item in soup.select(selector=SIDEBAR_SELECTOR):
        classes: list[str] = [str(object=c) for c in cast(Any, item.get("class")) or []]
        kind: str = next(
            (
                c.removesuffix(ACCOUNT_CLASS_SUFFIX)
                for c in classes
                if c.endswith(ACCOUNT_CLASS_SUFFIX)
            ),
            "",
        )

        left: Tag | None = item.select_one(selector=".left")
        right: Tag | None = item.select_one(selector=".right")

        if left is None:
            continue

        group_node: Tag | None = left.select_one(selector="div")
        link: Tag | None = left.select_one(selector="a")
        number_node: Tag | None = left.select_one(selector="span")
        balance_node: Tag | None = (
            right.select_one(selector="span") if right is not None else None
        )

        name: str = collapse(text=link.get_text()) if link is not None else ""
        number: str = (
            collapse(text=number_node.get_text()) if number_node is not None else ""
        )

        accounts.append(
            {
                "Kind": kind,
                "Group": collapse(text=group_node.get_text())
                if group_node is not None
                else "",
                "Name": name,
                "Number": number,
                "Label": account_label(name=name, number=number),
                "Balance": collapse(text=balance_node.get_text())
                if balance_node is not None
                else "",
            }
        )

    return accounts


def account_label(name: str, number: str) -> str:
    """
    Build the display and identity string for an account.

    "Individual (...1234)". The masked number is deliberately part of it: two
    Ally accounts can share a nickname, and the masked digits are the only
    thing on the page that tells them apart. It is also stable -- Ally masks
    the same trailing digits every run -- which matters because this string is
    the database's identity key.
    :param name: The account nickname
    :param number: The masked account number, e.g. "...1234"
    :return: The label, falling back to whichever half is present
    :rtype: str
    """

    if name and number:
        return f"{name} ({number})"

    return name or number


def masked_form(number: str) -> str:
    """
    Write a full account number the way the sidebar masks it.

    Used when the holdings heading names an account the sidebar did not, so
    that both routes produce the same label. Deriving one identity from
    "...1234" and another from "3LD21234" would give one account two rows in
    the database the first time the sidebar failed to render -- the same
    double-count that excluding overlapping SnapTrade accounts exists to
    prevent, arriving from the opposite direction.
    :param number: The full account number
    :return: The masked form, e.g. "...1234"; "" for an empty number
    :rtype: str
    """

    tail: str = number.strip()

    if not tail:
        return ""

    return f"...{tail[-MASKED_DIGITS:]}"


def masked_matches(masked: str, number: str) -> bool:
    """
    Whether a masked sidebar number refers to the same account as a full one.

    The sidebar says "...1234" and the heading says "3LD21234"; pairing them is
    what lets the holdings on screen be attributed to a sidebar account rather
    than becoming a second row for an account already listed.
    :param masked: The masked number from the sidebar
    :param number: The full number from the page heading
    :return: True when the masked digits end the full number
    :rtype: bool
    """

    tail: str = masked.strip().lstrip(".").strip()

    if not tail or not number:
        return False

    return number.strip().upper().endswith(tail.upper())


def account_totals(soup: BeautifulSoup) -> dict[str, str]:
    """
    The four headline figures above the holdings table.

    "Account Value", "Market Value", "Total G/L", "Today's G/L". The two
    gain/loss figures go through signed_amount(), so a loss arrives negative.
    :param soup: The parsed holdings page
    :return: Heading text mapped to the amount as text
    :rtype: dict[str, str]
    """

    totals: dict[str, str] = {}

    for block in soup.select(selector="holdings-account-totals .acc-totals"):
        heading: Tag | None = block.select_one(selector="h3")

        if heading is None:
            continue

        # The value is whatever element follows the heading: a plain <p> for
        # Account Value, a component for the rest.
        value: Tag | None = heading.find_next_sibling()
        totals[collapse(text=heading.get_text())] = signed_amount(node=value)

    return totals


def account_balances(soup: BeautifulSoup) -> dict[str, str]:
    """
    The cash and securities breakdown Ally hides behind "Account Balances".

    Collapsed on the page, but present in the DOM, so it needs no clicking.
    Read for the cash line: an account can hold uninvested cash that no
    position accounts for, and a holdings-only reading would lose it.
    :param soup: The parsed holdings page
    :return: Label (without its trailing colon) mapped to the amount as text
    :rtype: dict[str, str]
    """

    balances: dict[str, str] = {}

    for row in soup.select(selector="account-balances-info .balance-column p"):
        spans: list[Tag] = row.find_all(name="span", recursive=False)

        if len(spans) < 2:
            continue

        label: str = collapse(text=spans[0].get_text()).rstrip(":")

        if label:
            balances[label] = collapse(text=spans[1].get_text())

    return balances


def column_index(table: Tag) -> dict[str, int]:
    """
    Map each column heading to its position.

    Positional reads are a last resort here -- used only for Qty and Cost
    Basis, which are bare ``<span>``s with no component wrapping them -- but
    hardcoding "column three" would break the first time Ally inserts a column.
    Going through the header row means a reordering is followed rather than
    silently misread.
    :param table: The holdings table
    :return: Heading text mapped to its column index
    :rtype: dict[str, int]
    """

    return {
        collapse(text=cell.get_text()): index
        for index, cell in enumerate(iterable=table.select(selector="thead th"))
    }


def symbol_and_name(row: Tag) -> tuple[str, str]:
    """
    The ticker and the security name out of a holdings row's first cell.

    Both are in ``title`` attributes as well as in the text, and the attributes
    are already trimmed, so they are preferred. The ticker additionally sits in
    a ``<strong>``, which is what separates it from the description when both
    spans look alike.
    :param row: One holdings row
    :return: (symbol, name); either may be ""
    :rtype: tuple[str, str]
    """

    cell: Tag | None = row.select_one(selector=".symbol")

    if cell is None:
        return "", ""

    titled: list[Tag] = cell.select(selector="span[title]")
    strong: Tag | None = cell.select_one(selector="strong")

    symbol: str = ""

    if strong is not None:
        symbol = collapse(text=strong.get_text())
    elif titled:
        symbol = collapse(text=str(object=titled[0].get("title") or ""))

    name: str = ""

    for span in titled:
        candidate: str = collapse(text=str(object=span.get("title") or ""))

        if candidate and candidate != symbol:
            name = candidate
            break

    return symbol, name


def element_text(parent: Tag, selector: str) -> str:
    """
    Read a nested element's text, or "" when it is not there.

    The "" matters: the tempting shorthand is ``(parent.select_one(s) or
    parent).get_text()``, which on a miss returns the whole row's text -- every
    cell run together -- and that parses to a plausible-looking wrong number
    instead of to nothing.
    :param parent: The element to search within
    :param selector: CSS selector for the value
    :return: The collapsed text, or ""
    :rtype: str
    """

    found: Tag | None = parent.select_one(selector=selector)
    return collapse(text=found.get_text()) if found is not None else ""


def cell_text(cells: list[Tag], index: int | None) -> str:
    """
    Read one cell by position, tolerating a column that is not there.
    :param cells: The row's cells, in page order
    :param index: The column index, or None when the heading was not found
    :return: The cell text, or "" when the column is missing
    :rtype: str
    """

    if index is None or index >= len(cells):
        return ""

    return collapse(text=cells[index].get_text())


def holdings(soup: BeautifulSoup) -> list[Holding]:
    """
    Every position in the holdings table.

    ``cost_basis`` is stored as the position's *total* cost, which is what Ally
    puts in that column: the sample row reads 2265.00 against 125.000 units at
    an 18.12 average price, and 125.000 x 18.12 is 2265.00. That is the same
    convention ``Holding.cost_basis`` already carries for SnapTrade positions,
    where the API reports a per-unit figure that the module multiplies out --
    so the two sources agree on what the column means, and a test pins it.
    :param soup: The parsed holdings page
    :return: One holding per row, in page order
    :rtype: list[Holding]
    """

    table: Tag | None = soup.select_one(
        selector=HOLDINGS_TABLE_SELECTOR
    ) or soup.select_one(selector="table.dash-hldg-table")

    if table is None:
        return []

    columns: dict[str, int] = column_index(table=table)
    positions: list[Holding] = []

    for row in table.select(selector=HOLDING_ROW_SELECTOR):
        cells: list[Tag] = cast(list[Tag], row.find_all(name="td", recursive=False))
        symbol, name = symbol_and_name(row=row)

        # Never fall back to the row itself when a component is missing: the
        # row's own text is every cell run together, which parses to a number
        # that is wrong rather than to nothing.
        value: str = element_text(parent=row, selector="total-market-value")
        price: str = element_text(parent=row, selector="invest-last")

        positions.append(
            Holding(
                symbol=symbol or None,
                name=name or None,
                units=to_amount(
                    cell_text(cells=cells, index=columns.get(QUANTITY_HEADER))
                ),
                price=to_amount(price),
                value=to_amount(value),
                cost_basis=to_amount(
                    cell_text(cells=cells, index=columns.get(COST_BASIS_HEADER))
                ),
                currency=to_currency(value),
                raw_value=value or None,
            )
        )

    return positions
