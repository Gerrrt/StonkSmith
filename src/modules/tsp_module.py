# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Module to value a TSP account from published share prices and a unit count."""

import datetime as dt
from collections.abc import Iterable
from pathlib import Path
from typing import Any, ClassVar

from brokers.tsp.saver import Saver
from etc.config import get_tsp_units
from etc.connection import Connection
from etc.context import BrokerDbProtocol, Context, SnapshotDbProtocol
from etc.records import AccountIdentity, Holding
from helpers.normalize import format_amount, format_units
from helpers.sheets import SheetsUnavailable
from helpers.tsp import (
    CLOSING_UNITS_LABEL,
    fund_values,
    price_on,
    statement_funds,
    statement_period,
)

#: Module option naming a quarterly statement to read units from.
STATEMENT_OPTION = "STATEMENT"

#: Where a mark's unit count came from. Carried onto every row and every log
#: line, because a TSP value is only as current as its unit count and the
#: number itself gives no hint which of these produced it.
FROM_STATEMENT = "statement"
FROM_FLAG = "--units"
FROM_CONFIG = "config"

#: Beyond this the unit count has almost certainly missed a contribution, since
#: TSP posts monthly for uniformed members and no less often for civilians.
UNITS_STALE_DAYS = 40


def pdf_text(pages: Iterable[Any]) -> str:
    """Join a PDF's pages into one string, page by page.

    Per page rather than in one comprehension, because a statement is several
    pages and the units live on exactly one of them. A page that extracts to
    nothing -- or raises, which pypdf does on a malformed content stream --
    should cost that page and no others; joining in a single pass gives up the
    whole document over the one page nobody needed.

    ``or ""`` is belt-and-braces: ``extract_text()`` is annotated ``-> str`` and
    returns an empty string for a page with no text, but a None here would
    otherwise turn a readable statement into an unreadable one via TypeError.

    Args:
        pages (Iterable[Any]): The reader's pages.

    Returns:
        str: The text of every page that could be read.

    """
    out: list[str] = []

    for page in pages:
        try:
            out.append(page.extract_text() or "")

        except Exception:
            # Broad on purpose: pypdf raises a wide and undocumented set here,
            # and the answer is the same for all of them -- skip the page.
            out.append("")

    return "\n".join(out)


def read_statement(path: str) -> tuple[float | None, str, dt.date | None]:
    """Pull the authoritative unit count out of a quarterly statement.

    Statements are the only place TSP states a unit count without a login, and
    the count they state is exact -- multiply it by the printed share price and
    it reproduces the printed balance to the cent.

    Args:
        path (str): Path to the statement, as text or PDF.

    Returns:
        tuple[float | None, str, dt.date | None]: Units, the fund they belong
        to, and the period end they were true on. Units is None when the file
        could not be read or carries no activity table.

    """
    target = Path(path).expanduser()

    try:
        if target.suffix.lower() == ".pdf":
            from pypdf import PdfReader

            text = pdf_text(pages=PdfReader(target).pages)
        else:
            text = target.read_text(encoding="utf-8")

    except Exception:
        # Broad on purpose: an unreadable statement is a reportable outcome for
        # the caller, not a traceback. Missing pypdf lands here too.
        return None, "", None

    funds: list[str] = statement_funds(text=text)

    if not funds:
        return None, "", None

    units: list[float] = fund_values(
        text=text, label=CLOSING_UNITS_LABEL, count=len(funds)
    )
    period = statement_period(text=text)

    if not units:
        return None, funds[0], None

    return units[0], funds[0], (period[1] if period else None)


def statement_reconciles(text_units: float, price: float, closing: float) -> bool:
    """Whether a statement's own numbers multiply out.

    A cheap integrity check on the parse: TSP computes the balance it prints as
    units times the unit price on the same page, so if those three disagree the
    parser read a row it should not have -- which is a different problem from a
    file that simply would not open, and is worth telling apart.

    Args:
        text_units (float): Closing units as parsed.
        price (float): Unit price as parsed.
        closing (float): Closing balance as parsed.

    Returns:
        bool: True when the three agree to the cent.

    """
    return abs(text_units * price - closing) < 0.01


class TspModule:
    """Value TSP from public share prices and a known unit count."""

    name: str = "tsp"
    description: str = "Value the account from published share prices"
    supported_brokers: ClassVar[list[str]] = ["tsp"]

    def __init__(self) -> None:
        """Initialize the class attributes."""
        self.export_format: str = "print"
        self.statement: str = ""

    def options(
        self, context: Context | None, module_options: dict[str, Any] | None = None
    ) -> None:
        """Set up module options.

        Args:
            context (Context | None): Execution context supplied by ModuleLoader.
            module_options (dict[str, Any] | None): EXPORT sets the export
            format; STATEMENT names a quarterly statement to take units from.

        """
        del context
        options: dict[str, Any] = module_options or {}
        self.export_format = options.get("EXPORT", "print")
        self.statement = str(object=options.get(STATEMENT_OPTION, "") or "")

    def units_for(self, context: Context) -> tuple[float | None, str, str]:
        """Decide which unit count to value, and say where it came from.

        Precedence runs most-authoritative first: a statement states units, a
        flag is someone typing what they just read, and config is whatever was
        true last time. Every one of them is reported, because the number they
        produce looks identical and only the provenance says whether to trust
        it.

        Args:
            context (Context): Logging, and the parsed CLI arguments.

        Returns:
            tuple[float | None, str, str]: Units, the date they were true, and
            which source supplied them.

        """
        if self.statement:
            units, fund, as_of = read_statement(path=self.statement)

            if units is None:
                context.log.fail(
                    msg=(
                        f"Could not read a unit count from {self.statement}. "
                        "Expected a TSP quarterly statement (PDF or text)."
                    )
                )
            else:
                # One string for the log line and the return value. A statement
                # whose period would not parse has a real unit count and no
                # date for it, and "as of None" reads like a bug rather than
                # like the missing date it is -- on the one line whose whole
                # job is to say how current the number is.
                dated: str = as_of.isoformat() if as_of else ""
                context.log.success(
                    msg=(
                        f"Statement: {format_units(units)} units of {fund} "
                        f"as of {dated or 'an unstated date'}"
                    )
                )
                return units, dated, FROM_STATEMENT

        flag: float | None = getattr(context.args, "units", None)

        if flag is not None:
            as_of_flag = str(object=getattr(context.args, "units_as_of", "") or "")
            return flag, as_of_flag, FROM_FLAG

        units_cfg, as_of_cfg = get_tsp_units()
        return units_cfg, as_of_cfg, FROM_CONFIG

    def on_login(self, context: Context, connection: Connection) -> bool:
        """Mark the account and persist it.

        Args:
            context (Context): Logging, database, and shared resources.
            connection (Connection): The TSP connection, whose client holds the
            parsed share price file.

        Returns:
            bool: False when nothing reached the database.

        """
        prices: Any = getattr(connection, "client", None)
        fund: str = str(object=getattr(connection, "fund", "") or "")

        if not prices or not fund:
            context.log.fail(
                msg="TSP module requires the share price file; none was loaded."
            )
            return False

        units, as_of, source = self.units_for(context=context)

        if units is None:
            context.log.fail(
                msg=(
                    "No unit count to value. Put 'Closing Units' from your "
                    "latest quarterly statement in the [TSP] section of the "
                    "config, pass --units, or read it straight off the "
                    "statement with -o STATEMENT=<path>."
                )
            )
            return False

        today: dt.date = dt.datetime.now(tz=dt.UTC).date()
        found: tuple[dt.date, float] | None = price_on(
            prices=prices, fund=fund, day=today
        )

        if found is None:
            context.log.fail(msg=f"No published price for {fund!r}.")
            return False

        price_date, price = found
        value: float = units * price

        self.report(context=context, as_of=as_of, source=source, today=today)
        context.log.success(
            msg=(
                f"{fund}: {format_units(units)} units x ${price:,.4f} "
                f"({price_date}) = ${value:,.2f}"
            )
        )

        row: dict[str, Any] = {
            "Fund": fund,
            "Units": format_units(units),
            "Units as of": as_of or "unknown",
            "Share price": f"{price:,.4f}",
            "Price date": price_date.isoformat(),
            "Value": format_amount(value, "USD"),
            "Basis": source,
        }

        db_ok: bool = self.save(
            context=context,
            fund=fund,
            units=units,
            price=price,
            value=value,
            price_date=price_date,
            as_of=as_of,
        )
        sheets_ok: bool = self.sync(context=context, rows=[row])

        if db_ok and sheets_ok:
            context.log.success(msg="TSP sync complete.")
        elif db_ok:
            context.log.success(
                msg="TSP mark saved locally; the dashboard was not updated."
            )

        return db_ok

    @staticmethod
    def report(context: Context, as_of: str, source: str, today: dt.date) -> None:
        """Say how old the unit count is before reporting a value from it.

        The whole point of the broker. A mark carried on a three-month-old unit
        count is still arithmetic, but it is missing every contribution since --
        and the number gives no sign of that, which is precisely how a stale
        figure passes for a current one.

        Args:
            context (Context): Used for logging.
            as_of (str): The date the unit count was true, as written.
            source (str): Which input supplied it.
            today (dt.date): The run date.

        """
        if not as_of:
            context.log.highlight(
                msg=(
                    f"Unit count came from {source} with no as-of date, so how "
                    "current it is cannot be stated. Set units_as_of."
                )
            )
            return

        try:
            age: int = (today - dt.date.fromisoformat(as_of)).days

        except ValueError:
            context.log.highlight(
                msg=f"Unreadable units_as_of {as_of!r}; expected YYYY-MM-DD."
            )
            return

        if age > UNITS_STALE_DAYS:
            context.log.highlight(
                msg=(
                    f"Unit count is from {as_of} ({age} days). TSP posts "
                    "contributions at least monthly, so this mark is probably "
                    "short by one or more of them. Import a newer statement "
                    "with -o STATEMENT=<path> to reset it."
                )
            )
        else:
            context.log.display(msg=f"Unit count from {source}, true as of {as_of}.")

    @staticmethod
    def save(
        context: Context,
        fund: str,
        units: float,
        price: float,
        value: float,
        price_date: dt.date,
        as_of: str,
    ) -> bool:
        """Write the mark to the broker database.

        ``scraped_at`` is when the run happened; ``as_of`` is the price date the
        value is true for. They differ whenever the run lands on a weekend or
        before the day's price publishes, and collapsing them would date a
        Friday price as Sunday's.

        Args:
            context (Context): Logging and the database.
            fund (str): The fund held.
            units (float): Units held.
            price (float): Share price used.
            value (float): The resulting mark.
            price_date (dt.date): The date that price was published.
            as_of (str): The date the unit count was true.

        Returns:
            bool: False on a database contract violation.

        """
        timestamp: str = dt.datetime.now(tz=dt.UTC).strftime(format="%Y-%m-%d %H:%M:%S")
        db: BrokerDbProtocol = context.db
        label: str = f"TSP {fund}"

        if isinstance(db, SnapshotDbProtocol):
            db.save_snapshot(
                account=AccountIdentity(
                    account_key=label,
                    display_name=label,
                    kind="INVESTMENT",
                ),
                scraped_at=timestamp,
                as_of=price_date.isoformat(),
                value=value,
                currency="USD",
                raw_value=f"{value:.2f}",
                holdings=[
                    Holding(
                        fund_code=fund,
                        name=fund,
                        units=units,
                        price=price,
                        value=value,
                        currency="USD",
                        # The unit count's own date, kept beside the position
                        # so a stored mark stays self-describing.
                        raw_value=as_of or None,
                    )
                ],
            )
            return True

        if callable(getattr(db, "save_account_data", None)):
            db.save_account_data(
                account_name=label, balance=f"{value:.2f}", timestamp=timestamp
            )
            return True

        context.log.fail(
            msg="DB contract violation: context.db does not implement "
            "save_account_data. Skipping DB save.",
        )
        return False

    @staticmethod
    def sync(context: Context, rows: list[dict[str, Any]]) -> bool:
        """Push the mark to Google Sheets.

        Args:
            context (Context): Used for logging.
            rows (list[dict[str, Any]]): Worksheet rows.

        Returns:
            bool: False when the dashboard was not updated.

        """
        try:
            context.log.highlight(msg="Syncing data to Google Sheets...")
            Saver().save_accounts(data=rows)
            context.log.success(msg="Google Sheets updated successfully!")
            return True

        except SheetsUnavailable as e:
            context.log.fail(msg=f"Google Sheets sync skipped: {e}")
            return False

        except Exception as e:
            # Broad on purpose: the mark is already in the broker database.
            context.log.fail(msg=f"Google Sheets sync failed: {e}")
            return False
