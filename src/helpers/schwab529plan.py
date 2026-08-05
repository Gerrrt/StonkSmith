"""
schwab529plan.py: Helpers for schwab529plan module
"""

from typing import Any, cast

from bs4 import BeautifulSoup
from bs4.element import AttributeValueList, Tag

from etc.records import Holding, Transaction
from helpers.normalize import to_amount, to_currency


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
