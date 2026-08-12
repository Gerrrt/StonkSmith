"""
schwab529plan.py: Helpers for schwab529plan module
"""

import re
from typing import Any, cast

from bs4 import BeautifulSoup
from bs4.element import AttributeValueList, Tag

from etc.records import Holding, Transaction
from helpers.normalize import to_amount, to_currency

#: Canonical transaction column names, in the order the parser and the sheet
#: have always used, mapped to the header spellings a page might print. The
#: point of the lookup is that a page which grows a seventh column must not
#: shift the other six: positional reads are only correct until they are not.
TRANSACTION_COLUMNS: dict[str, tuple[str, ...]] = {
    "Processed": ("processed", "process date", "processed date", "settlement date"),
    "Traded": ("traded", "trade date", "traded date"),
    "Type": ("type", "transaction type", "activity"),
    "Units": ("units", "shares", "quantity", "qty"),
    "Price": ("price", "unit price", "share price", "nav"),
    "Value": ("value", "amount", "total"),
}

#: The header spellings that name the account a row belongs to. Not one of the
#: six above: this is the column issue #36 is about, and it may not exist.
ACCOUNT_COLUMNS: tuple[str, ...] = (
    "account",
    "account number",
    "account #",
    "beneficiary",
    "for",
    "owner",
)

#: Below this, a header row is more likely to be something else -- a spacer, a
#: date banner, a colspan title -- than a real header, and reading positions
#: off it would scramble every field. Fixed positions are the safer answer.
_MIN_MAPPED_COLUMNS = 4

#: A masked account number has to carry enough digits to identify an account.
#: Four is what Schwab shows and what a human would match on.
_MIN_DIGITS_FOR_SUFFIX_MATCH = 4


def clean_up(data: Any) -> Any:
    """
    Clean up HTML data
    :param data:
    :return:
    """
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, list):
        return [clean_up(data=item) for item in cast(list[Any], data)]
    if isinstance(data, dict):
        new_dict: dict[Any, Any] = {}
        for key, value in cast(dict[Any, Any], data).items():
            new_key: str = cast(str, key).strip()
            new_value = clean_up(data=value)
            new_dict[new_key] = new_value
        return new_dict
    return data


def strip_label(text: str) -> str:
    """
    Tidy a scraped heading into a label: collapse whitespace, drop a trailing
    colon.
    :param text: Raw scraped text
    :return: The cleaned label
    """

    return " ".join(text.split()).rstrip(":").strip()


def normalize_key(text: Any) -> str:
    """
    Reduce a scraped label to something two spellings of it can be compared on.

    Case, punctuation and runs of whitespace are all things a page is free to
    change between renders; none of them changes which account a heading names.
    :param text: Any scraped text
    :return: The comparable form, possibly empty
    :rtype: str
    """

    lowered: str = " ".join(str(object=text or "").split()).casefold()

    return " ".join(re.sub(pattern=r"[^0-9a-z]+", repl=" ", string=lowered).split())


def column_map(headers: list[str]) -> dict[str, int]:
    """
    Work out which column holds which field from a table's header row.

    ``transaction_data()`` read fixed positions -- ``td[1]`` through ``td[6]``
    -- which is correct exactly until the page prints a seventh column, at
    which point every field silently shifts by one and the database fills with
    plausible nonsense. Reading the header instead costs nothing when the
    header says what it has always said.

    Returns nothing rather than a partial guess when the row does not look like
    a header, so the caller falls back to the positions that have always
    worked.
    :param headers: The header cell texts, in page order
    :return: Canonical field name to zero-based column index
    :rtype: dict[str, int]
    """

    mapping: dict[str, int] = {}

    for index, header in enumerate(iterable=headers):
        key: str = normalize_key(text=header)

        if not key:
            continue

        if "Account" not in mapping and key in ACCOUNT_COLUMNS:
            mapping["Account"] = index
            continue

        for canonical, spellings in TRANSACTION_COLUMNS.items():
            # First column wins: a table carrying both "Value" and "Total"
            # should read the one it printed first, not the last one seen.
            if canonical not in mapping and key in spellings:
                mapping[canonical] = index
                break

    known: int = sum(1 for name in TRANSACTION_COLUMNS if name in mapping)

    if known < _MIN_MAPPED_COLUMNS:
        return {}

    return mapping


def account_hint(
    row: dict[str, Any], keys: tuple[str, ...] = ("Account", "Section", "Title")
) -> str | None:
    """
    Read whatever the page said about which account a transaction belongs to.

    Three places, in descending order of how directly they name the account: a
    column on the row itself, a section heading the row sits under, and the
    caption of the table it came from. The parser fills whichever of them the
    markup actually has, and issue #36 exists because the one known rendering
    has none of them.
    :param row: One row from Parser.transaction_data()
    :param keys: Which of the three to trust. The caller drops the caption when
        one table covers several accounts, where a caption naming one of them
        would misattribute the rest.
    :return: The identifying text, or None when the row carries none
    :rtype: str | None
    """

    for key in keys:
        value: Any = row.get(key)

        if value and str(object=value).strip():
            return strip_label(text=str(object=value))

    return None


def _digits(text: str) -> str:
    """
    Keep only the digits in a string, so a masked account number can be
    compared with a full one.
    :param text: Any text
    :return: Just the digits
    :rtype: str
    """

    return re.sub(pattern=r"\D", repl="", string=text)


def match_account(hint: str, candidates: list[list[str]]) -> int | None:
    """
    Decide which account a scraped hint names, or decline to.

    ``candidates[i]`` is every string that identifies account *i* -- its
    display name, its beneficiary, its account number. Three rules, tried in
    order and each stricter than a human eyeballing the page would need:
    an exact match on the normalised text, a shared trailing run of digits
    (Schwab masks account numbers, so ``...4321`` has to match ``XXXX4321``),
    and finally a candidate name appearing inside the hint (``Contributions
    for Beneficiary A``).

    A hint that matches two accounts is not an attribution, it is a collision,
    and it returns None for the same reason the multi-account case stores
    nothing today: a wrong answer here is indistinguishable from a right one
    afterwards.
    :param hint: The text the page attached to the row
    :param candidates: Identifying strings per account, in balance order
    :return: The account's index, or None when there is no single answer
    :rtype: int | None
    """

    key: str = normalize_key(text=hint)

    if not key:
        return None

    normalized: list[set[str]] = [
        {value for value in (normalize_key(text=item) for item in group) if value}
        for group in candidates
    ]

    exact: list[int] = [i for i, group in enumerate(normalized) if key in group]

    if len(exact) == 1:
        return exact[0]
    if exact:
        return None

    hint_digits: str = _digits(text=key)

    if len(hint_digits) >= _MIN_DIGITS_FOR_SUFFIX_MATCH:
        by_digits: list[int] = [
            i
            for i, group in enumerate(normalized)
            if any(
                len(digits := _digits(text=value)) >= _MIN_DIGITS_FOR_SUFFIX_MATCH
                and (digits.endswith(hint_digits) or hint_digits.endswith(digits))
                for value in group
            )
        ]

        if len(by_digits) == 1:
            return by_digits[0]
        if by_digits:
            return None

    # Word-boundary containment: "Naomi" must not match "Naomiah", and a
    # one-character candidate must not match every hint on the page.
    contained: list[int] = [
        i
        for i, group in enumerate(normalized)
        if any(
            len(value) > 2
            and re.search(pattern=rf"\b{re.escape(pattern=value)}\b", string=key)
            for value in group
        )
    ]

    if len(contained) == 1:
        return contained[0]

    return None


def account_label(
    beneficiaries: list[dict[str, Any]], balance: dict[str, Any], index: int
) -> str:
    """
    Pick a readable account name for a scraped balance row.

    The balance heading's first text node is a label ("Balance:"), not an
    account name, so using it directly filled the accounts table with rows
    literally named "Balance:". Prefer the matching beneficiary's name, then
    anything else identifying on the beneficiary, and only fall back to the
    cleaned balance label.
    :param beneficiaries: Parsed beneficiary rows, in page order
    :param balance: The balance row being saved
    :param index: Position of that balance row, used to pair it with a
        beneficiary when the counts line up
    :return: A non-empty display name
    """

    if index < len(beneficiaries):
        beneficiary: dict[str, Any] = beneficiaries[index] or {}
        for key in ("Name", "Account", "Title"):
            value: Any = beneficiary.get(key)
            if value and str(object=value).strip():
                return strip_label(text=str(object=value))

    fallback: Any = balance.get("Title")
    if fallback and str(object=fallback).strip():
        return strip_label(text=str(object=fallback))

    return "Unknown account"


def beneficiary_field(
    beneficiaries: list[dict[str, Any]], index: int, key: str
) -> str | None:
    """
    Read one field off the beneficiary paired with a balance, if there is one.

    The page renders one beneficiary heading, one balance heading and one fund
    table per account, in the same order, so position is the pairing. When the
    counts do not line up there is no honest pairing to make, and None is the
    answer rather than the wrong beneficiary's name.
    :param beneficiaries: Parsed beneficiary rows, in page order
    :param index: Position of the balance row being saved
    :param key: Which field to read
    :return: The value, or None
    :rtype: str | None
    """

    if index >= len(beneficiaries):
        return None

    value: Any = (beneficiaries[index] or {}).get(key)

    if not value or not str(object=value).strip():
        return None

    return strip_label(text=str(object=value))


def holding_from_row(row: dict[str, Any]) -> Holding:
    """
    Turn one parsed fund row into a holding record.

    Principal and earnings are table-level totals that the parser repeats onto
    every row, so a multi-fund account stores the same pair against each of its
    holdings rather than splitting a number the page never split.
    :param row: One row from Parser.investment_data()
    :return: The holding
    :rtype: Holding
    """

    value: Any = row.get("Value")

    return Holding(
        fund_code=strip_label(text=str(object=row.get("Fund Code") or "")) or None,
        name=strip_label(text=str(object=row.get("Fund") or "")) or None,
        units=to_amount(row.get("Units")),
        price=to_amount(row.get("Price")),
        value=to_amount(value),
        principal=to_amount(row.get("Principal")),
        earnings=to_amount(row.get("Earnings")),
        currency=to_currency(value),
        raw_value=str(object=value) if value is not None else None,
    )


def transaction_from_row(row: dict[str, Any]) -> Transaction:
    """
    Turn one parsed transaction row into a transaction record.

    The raw value text is carried through because it is what the deduplication
    key is built from: keying on the parsed number would make every stored row
    look new the day the parser learned to read a format it previously could
    not.
    :param row: One row from Parser.transaction_data()
    :return: The transaction
    :rtype: Transaction
    """

    value: Any = row.get("Value")

    return Transaction(
        processed_on=strip_label(text=str(object=row.get("Processed") or "")),
        traded_on=strip_label(text=str(object=row.get("Traded") or "")),
        tx_type=strip_label(text=str(object=row.get("Type") or "")),
        units=to_amount(row.get("Units")),
        price=to_amount(row.get("Price")),
        value=to_amount(value),
        currency=to_currency(value),
        raw=str(object=value) if value is not None else None,
    )


def get_value(html: BeautifulSoup, name: str) -> str | AttributeValueList | None:
    """
    Get value from HTML
    :param html:
    :param name:
    :return:
    """

    tag: Tag | None = html.find(name="input", attrs={"name": name})
    return tag.attrs["value"] if tag else None
