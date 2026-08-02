"""
schwab529plan.py: Helpers for schwab529plan module
"""

from typing import Any, cast

from bs4 import BeautifulSoup
from bs4.element import AttributeValueList, Tag


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


def get_value(html: BeautifulSoup, name: str) -> str | AttributeValueList | None:
    """
    Get value from HTML
    :param html:
    :param name:
    :return:
    """

    tag: Tag | None = html.find(name="input", attrs={"name": name})
    return tag.attrs["value"] if tag else None
