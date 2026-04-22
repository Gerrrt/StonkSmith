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


def get_value(html: BeautifulSoup, name: str) -> str | AttributeValueList | None:
    """
    Get value from HTML
    :param html:
    :param name:
    :return:
    """

    tag: Tag | None = html.find(name="input", attrs={"name": name})
    return tag.attrs["value"] if tag else None
