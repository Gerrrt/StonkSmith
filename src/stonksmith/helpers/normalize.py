# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Turn scraped text into values a database can do arithmetic on.

Every broker hands StonkSmith money as display text: ``"$1,234.56"`` from a
scraped page, a ``Decimal`` from the SnapTrade SDK, ``"--"`` from a fund table
with nothing in it. The database stores a number, a currency and the original
string side by side, and these are the functions that produce the first two.

Nothing here raises. A source can change its formatting without warning, and a
balance that cannot be read is a NULL value next to the raw text it came from --
not a traceback that costs the run every other account it had already scraped.
"""

import datetime
import re
from decimal import Decimal, InvalidOperation
from typing import Any

#: Text a source uses to mean "no number here". Compared case-folded against the
#: stripped string, so "N/A" and "n/a" are one entry.
_BLANKS: frozenset[str] = frozenset(
    # The em and en dashes are here because pages render them, not by mistake.
    {"", "-", "--", "---", "\u2014", "\u2013"}
    | {"n/a", "na", "none", "null", "unavailable"}
)

#: A trailing ISO currency code, as in "1,234.56 CAD".
_TRAILING_CODE = re.compile(pattern=r"([A-Z]{3})\s*$")

#: Everything that is not part of a number, once the sign and currency are off.
_NOT_NUMERIC = re.compile(pattern=r"[^\d.,]")

#: A unit suffix that changes what the number means. Silently dropping the "%"
#: off "1.5%" would store a rate as if it were dollars.
_HAS_UNIT = re.compile(pattern=r"[%‰]|\b(?:bps|pct|percent)\b", flags=re.IGNORECASE)

#: Date formats seen across the brokers, most specific first.
_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
)

#: A date embedded in prose, as in "Balance as of 12/31/2025".
_DATE_IN_TEXT = re.compile(
    pattern=r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}"
)


def _decimal_separator(digits: str) -> str:
    """
    Decide which of ``.`` and ``,`` is the decimal point.

    "1,234.56" and "1.234,56" are the same number written two ways, and the only
    thing that distinguishes them is which separator comes last.
    :param digits: The number with sign and currency already stripped
    :return: "." or "," -- the character acting as the decimal point
    :rtype: str
    """

    last_dot: int = digits.rfind(".")
    last_comma: int = digits.rfind(",")

    if last_dot >= 0 and last_comma >= 0:
        return "." if last_dot > last_comma else ","

    if last_comma >= 0:
        # A lone comma is a thousands separator ("1,234") unless what follows it
        # cannot be a group of three ("1,5" or "1,23456").
        return "," if len(digits) - last_comma - 1 != 3 else "."

    return "."


def to_amount(text: Any) -> float | None:
    """
    Read a scraped money or quantity string as a number.

    Handles the formats the brokers actually emit: dollar signs, thousands
    separators, European separators, leading and trailing minus signs, and
    accounting parentheses for negatives.

    Returns ``None`` rather than raising, and rather than guessing: a value
    carrying a unit ("1.5%") is not a quantity of anything this stores.
    :param text: A scraped string, or a number the SDK already parsed
    :return: The value, or None when there is not one
    :rtype: float | None
    """

    if text is None:
        return None

    if isinstance(text, bool):
        # bool is an int subclass; a True balance is a bug upstream, not a 1.
        return None

    if isinstance(text, int | float):
        return float(text)

    if isinstance(text, Decimal):
        try:
            return float(text)

        except ValueError, OverflowError, InvalidOperation:
            return None

    if not isinstance(text, str):
        # Anything else is not an amount. Stringifying it first would let
        # repr() noise through -- "<object object at 0x7f94...>" contains
        # digits, and stripping the non-numeric characters off it yields a
        # perfectly plausible number.
        return None

    return _amount_from_text(text=text)


def _amount_from_text(text: str) -> float | None:
    """
    Read a scraped string as a number.

    Split from ``to_amount`` at the seam between the two questions it answers:
    above, whether this is already a number; here, what the string says. The
    branching below is the set of formats the brokers actually emit and is not
    reducible without dropping one of them -- which is why it lives on its own
    rather than being simplified.
    :param text: A scraped string
    :return: The value, or None when there is not one
    :rtype: float | None
    """

    raw: str = text.strip()

    if raw.casefold() in _BLANKS:
        return None

    if _HAS_UNIT.search(string=raw):
        return None

    # Accounting negatives: "(1,234.56)" and "($1,234.56)" are both -1234.56.
    negative: bool = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1].strip()

    # A minus can sit on either side of the currency symbol: Fidelity emits
    # "-$1,234.56", some tables emit "$-1,234.56".
    if "-" in raw:
        negative = True

    digits: str = _NOT_NUMERIC.sub(repl="", string=raw)

    if not digits or not any(char.isdigit() for char in digits):
        return None

    separator: str = _decimal_separator(digits=digits)

    if separator == ",":
        digits = digits.replace(".", "").replace(",", ".")
    else:
        digits = digits.replace(",", "")

    # More than one decimal point left means this was never a single number.
    if digits.count(".") > 1:
        return None

    try:
        value = float(digits)

    except ValueError:
        return None

    return -value if negative and value else value


def to_currency(text: Any, default: str = "USD") -> str:
    """
    Read the currency a scraped amount is denominated in.

    Only what the string actually says. A bare "1,234.56" is not evidence of
    anything, so it gets the default rather than a guess.
    :param text: The scraped amount, or an ISO code on its own
    :param default: What to return when the text names no currency
    :return: An ISO currency code
    :rtype: str
    """

    if text is None:
        return default

    raw: str = str(object=text).strip()

    if not raw:
        return default

    if "$" in raw:
        return "USD"

    if "€" in raw:
        return "EUR"

    if "£" in raw:
        return "GBP"

    trailing = _TRAILING_CODE.search(string=raw.upper())

    if trailing:
        return trailing.group(1)

    return default


def to_iso_date(text: Any) -> str | None:
    """
    Read a source's own as-of date as YYYY-MM-DD.

    This is the date the *source* says its number is for, which is not the time
    the scrape ran. The 529 balance heading carries one; SnapTrade carries an
    ISO-8601 timestamp on its last successful sync.
    :param text: A date, timestamp, or a sentence containing one
    :return: The date as YYYY-MM-DD, or None when there is not one
    :rtype: str | None
    """

    if text is None:
        return None

    if isinstance(text, datetime.datetime):
        return text.date().isoformat()

    if isinstance(text, datetime.date):
        return text.isoformat()

    raw: str = " ".join(str(object=text).split())

    if not raw or raw.casefold() in _BLANKS:
        return None

    # An ISO-8601 timestamp, which is what SnapTrade returns. Tried before the
    # regex so a "2026-01-15T09:30:00Z" is read whole rather than by its date
    # half, and before the plain formats because both would match the prefix.
    try:
        parsed: datetime.datetime = datetime.datetime.fromisoformat(
            raw.replace("Z", "+00:00")
        )

    except ValueError:
        pass

    else:
        return parsed.date().isoformat()

    found = _DATE_IN_TEXT.search(string=raw)
    candidate: str = found.group(0) if found else raw

    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(candidate, fmt).date().isoformat()

        except ValueError:
            continue

    return None


def format_amount(amount: Any, currency: Any) -> str:
    """
    Render a stored value back into display text.

    A dollar sign is only applied to USD. Stamping one onto another currency
    produces a number that sums cleanly into a USD total and is wrong.
    :param amount: The value, or None
    :param currency: The ISO currency code
    :return: Currency text such as "$1,234.56" or "1,234.56 CAD"
    :rtype: str
    """

    if amount is None:
        return ""

    try:
        value = float(amount)

    except TypeError, ValueError, InvalidOperation:
        return str(object=amount)

    code = str(object=currency or "").upper()

    if code in ("", "USD"):
        return f"-${abs(value):,.2f}" if value < 0 else f"${value:,.2f}"

    return f"{value:,.2f} {code}".strip()


def format_units(units: Any) -> str:
    """
    Render a share or unit count without a currency symbol.

    Trailing zeros are trimmed: a fund table showing "12.345" should not come
    back as "12.345000".
    :param units: The quantity, or None
    :return: The quantity as text, or "" when there is not one
    :rtype: str
    """

    if units is None:
        return ""

    try:
        value = float(units)

    except TypeError, ValueError, InvalidOperation:
        return str(object=units)

    return f"{value:,.6f}".rstrip("0").rstrip(".") or "0"
