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
    UNIT_PRICE_LABEL,
    fund_values,
    price_on,
    same_fund,
    sole_position,
    statement_funds,
    statement_period,
)

#: Module option naming a quarterly statement to read units from.
STATEMENT_OPTION = "STATEMENT"

#: Where a mark's unit count came from. Carried onto every row and every log
#: line, because a TSP value is only as current as its unit count and the
#: number itself gives no hint which of these produced it.
FROM_STATEMENT = "statement"
FROM_BALANCE = "--balance"
FROM_FLAG = "--units"
FROM_CONFIG = "config"

#: Beyond this the unit count has almost certainly missed a contribution, since
#: TSP posts monthly for uniformed members and no less often for civilians.
UNITS_STALE_DAYS = 40

#: The smallest unit count a statement can print. Everything below the third
#: decimal is rounded away before the page is typeset, so a printed count stands
#: for a real one up to half a step either side -- which is what a check against
#: the printed balance has to allow for.
UNIT_PRINT_STEP = 0.001

#: How far a balance's date may run ahead of the newest price available to
#: convert it. A long weekend plus a federal holiday is the widest ordinary gap
#: between business days; past that, the price file is stale rather than the
#: market closed, and dividing by an old price invents units.
BALANCE_PRICE_GAP_DAYS = 4


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
    ends: dt.date | None = period[1] if period else None

    if not units:
        return None, funds[0], None

    # The rows line up, so position names the fund the way it always has.
    if len(units) == len(funds):
        return units[0], funds[0], ends

    # They do not, which on a real statement means one fund was emptied into
    # another during the period and the rows below the balances have nothing to
    # say about the empty one. Taking units[0] with funds[0] here paired the
    # remaining fund's unit count with the abandoned fund's name -- the units
    # were right and only the label was wrong, so the mark it produced was
    # nearly correct and the refusal it triggered pointed at the wrong fix.
    held = sole_position(text=text)

    if held is None or len(units) != 1:
        return None, "", ends

    fund, closing = held
    prices: list[float] = fund_values(
        text=text, label=UNIT_PRICE_LABEL, count=len(funds)
    )

    # Confirmed against the statement's own arithmetic rather than assumed. If
    # the lone unit count and the lone price multiply out to the balance of the
    # fund the balances named, then all three describe the same position and
    # nothing has been inferred.
    if len(prices) != 1 or not statement_reconciles(
        text_units=units[0], price=prices[0], closing=closing
    ):
        return None, "", ends

    return units[0], fund, ends


def units_from_balance(
    prices: dict[dt.date, dict[str, float]], fund: str, balance: float, day: dt.date
) -> tuple[float, dt.date, float] | None:
    """Turn a balance read off the TSP site back into a unit count.

    The site states a balance and the date it is true for, and never states a
    unit count. But the balance *is* units times that day's price, so the
    division is exact and inverts TSP's own arithmetic rather than estimating
    it. That makes any moment spent logged in worth a fresh unit count, instead
    of waiting a quarter for a statement.

    The price is taken on or before the date given, because TSP does not
    revalue on a weekend or a holiday: a Saturday balance is still struck at
    Friday's price, and that is the price the balance was computed with. The
    date actually used is returned so the caller can show it, which is what
    makes a mistyped balance date visible rather than silently absorbed.

    Args:
        prices (dict[dt.date, dict[str, float]]): The parsed price file.
        fund (str): The fund the balance belongs to.
        balance (float): The balance as printed.
        day (dt.date): The date printed beside it.

    Returns:
        tuple[float, dt.date, float] | None: Units, the price date used, and
        that price. None when the fund has no price on or before that day.

    """
    found: tuple[dt.date, float] | None = price_on(prices=prices, fund=fund, day=day)

    if found is None:
        return None

    price_date, price = found

    if price <= 0:
        return None

    return balance / price, price_date, price


def statement_reconciles(text_units: float, price: float, closing: float) -> bool:
    """Whether a statement's own numbers multiply out.

    A cheap integrity check on the parse: TSP computes the balance it prints as
    units times the unit price on the same page, so if those three disagree the
    parser read a row it should not have -- which is a different problem from a
    file that simply would not open, and is worth telling apart.

    The tolerance comes from what the statement prints, not from a round number.
    Units are printed to three decimals, so the count on the page stands for
    anything within half a thousandth of the real one, and at $24.73 a unit that
    is already more than a cent of balance. A real statement reading 315.789
    units at $24.734400 against $7,810.84 misses by 1.1 cents -- the arithmetic
    is right and a cent of tolerance would have called it broken. The fixtures
    never showed this because their figures are round: 100.000 x 20.000000 is
    exactly 2000.00 and reconciles under any tolerance at all.

    Args:
        text_units (float): Closing units as parsed.
        price (float): Unit price as parsed.
        closing (float): Closing balance as parsed.

    Returns:
        bool: True when the three agree as closely as the printing allows.

    """
    # Half a printed unit either way, plus the half-cent the balance is itself
    # rounded to. Not a tolerance on how wrong the numbers may be -- a tolerance
    # on how much the page rounded them before printing.
    allowed: float = UNIT_PRINT_STEP / 2 * abs(price) + 0.005

    return abs(text_units * price - closing) <= allowed


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

    def units_for(
        self,
        context: Context,
        prices: dict[dt.date, dict[str, float]] | None = None,
        fund: str = "",
    ) -> tuple[float | None, str, str]:
        """Decide which unit count to value, and say where it came from.

        Precedence runs most-authoritative first. A statement and a balance are
        both exact -- the statement states units outright, and a balance
        inverts into them against a published price -- while ``--units`` is a
        raw number with nothing to check it against and config is whatever was
        true last time. Every one of them is reported, because the number they
        produce looks identical and only the provenance says whether to trust
        it.

        A balance is a flag and never a config key. It is true for exactly one
        day, so storing it would leave a value that silently rots into a wrong
        answer -- the opposite of what this module exists to prevent. The unit
        count it derives is what belongs in config, and the run prints it ready
        to paste.

        Args:
            context (Context): Logging, and the parsed CLI arguments.
            prices (dict[dt.date, dict[str, float]] | None): The parsed price
            file, needed only to back-solve ``--balance``.
            fund (str): The fund a balance belongs to.

        Returns:
            tuple[float | None, str, str]: Units, the date they were true, and
            which source supplied them.

        """
        if self.statement:
            # Not `fund`: rebinding the parameter here read the statement's own
            # fund, printed it, and threw it away, because only the units are
            # returned. A statement for one fund was then priced with the
            # configured fund's price -- 315.789 units of L 2050 marked at L
            # 2060's $24.6710 came to $7,790.83, where the statement's own fund
            # gives $14,794.59. Ninety percent wrong, with both names printed
            # on adjacent lines and nothing said about it.
            units, statement_fund, as_of = read_statement(path=self.statement)

            if units is not None and not same_fund(statement_fund, fund):
                context.log.fail(
                    msg=(
                        f"{self.statement} is a {statement_fund or 'unnamed'} "
                        f"statement, but the configured fund is {fund}. Units "
                        "are per fund and so are prices, so valuing one with "
                        "the other is meaningless. Correct [TSP] fund in "
                        "~/.stonksmith/stonksmith.conf, or point -o STATEMENT= "
                        "at the statement for that fund."
                    )
                )
                return None, "", FROM_STATEMENT

            if units is None:
                # Both reasons, because the caller cannot tell them apart from
                # here and naming only the first sends a run to check a file
                # that is perfectly fine. That is the mistake #75 was about: an
                # otherwise true message that offers the wrong next step costs
                # a round trip to find out it was the wrong one.
                context.log.fail(
                    msg=(
                        f"Could not take a unit count from {self.statement}. "
                        "Either it is not a TSP statement, or its activity "
                        "table covers more than one fund still holding money "
                        "and does not say which fund the closing units belong "
                        "to."
                    )
                )
            else:
                # One string for the log line and the return value. A statement
                # whose period would not parse has a real unit count and no
                # date for it, and "as of None" reads like a bug rather than
                # like the missing date it is -- on the one line whose whole
                # job is to say how current the number is.
                dated: str = as_of.isoformat() if as_of else ""

                # Two phrasings, because an unnamed fund is not a blank one.
                # "units of  as of ..." leaves a gap where the fund should be
                # and says nothing about which fund's price the run is about to
                # use -- on the line whose job is to say where the number came
                # from. When the statement names no fund the configured one is
                # used, so that is what the line reports, and it says why.
                whose: str = (
                    f"units of {statement_fund}"
                    if statement_fund
                    else f"units, valued as {fund} because the statement names no fund"
                )
                context.log.success(
                    msg=(
                        f"Statement: {format_units(units)} {whose} "
                        f"as of {dated or 'an unstated date'}"
                    )
                )
                return units, dated, FROM_STATEMENT

        balance: float | None = getattr(context.args, "balance", None)

        if balance is not None:
            derived = self.solve_balance(
                context=context, prices=prices, fund=fund, balance=balance
            )

            if derived is not None:
                return derived

        flag: float | None = getattr(context.args, "units", None)

        if flag is not None:
            as_of_flag = str(object=getattr(context.args, "units_as_of", "") or "")
            return flag, as_of_flag, FROM_FLAG

        units_cfg, as_of_cfg = get_tsp_units()
        return units_cfg, as_of_cfg, FROM_CONFIG

    @staticmethod
    def solve_balance(
        context: Context,
        prices: dict[dt.date, dict[str, float]] | None,
        fund: str,
        balance: float,
    ) -> tuple[float, str, str] | None:
        """Back-solve ``--balance`` into a unit count, or say why it could not.

        Every way this fails is reported and falls through to the next source
        rather than aborting the run, because a mistyped balance should cost
        the correction and not the mark. Returning None is that fall-through.

        Args:
            context (Context): Logging, and the parsed CLI arguments.
            prices (dict[dt.date, dict[str, float]] | None): The parsed price
            file.
            fund (str): The fund the balance belongs to.
            balance (float): The balance as printed on the site.

        Returns:
            tuple[float, str, str] | None: Units, the date they are true, and
            the source label. None when the balance could not be converted.

        """
        written: str = str(object=getattr(context.args, "balance_as_of", "") or "")

        if not written:
            context.log.fail(
                msg=(
                    "--balance needs --balance-as-of. The same dollars buy a "
                    "different number of units on a different day, so a "
                    "balance with no date cannot be converted at all. Use the "
                    "'Balance as of' date printed beside it."
                )
            )
            return None

        try:
            day: dt.date = dt.date.fromisoformat(written)

        except ValueError:
            context.log.fail(
                msg=f"Unreadable --balance-as-of {written!r}; expected YYYY-MM-DD."
            )
            return None

        if not prices or not fund:
            context.log.fail(
                msg="--balance needs the share price file to convert against."
            )
            return None

        solved: tuple[float, dt.date, float] | None = units_from_balance(
            prices=prices, fund=fund, balance=balance, day=day
        )

        if solved is None:
            context.log.fail(
                msg=(
                    f"No published {fund} price on or before {day}, so "
                    f"${balance:,.2f} cannot be converted to units."
                )
            )
            return None

        units, price_date, price = solved
        gap: int = (day - price_date).days

        if gap > BALANCE_PRICE_GAP_DAYS:
            # price_on() falls back to the newest price on or before the date,
            # which is right across a weekend and wrong across a stale file:
            # dividing a current balance by a month-old price silently invents
            # a unit count that is off by every day of drift in between. A
            # refusal costs one correction; this would corrupt the config.
            context.log.fail(
                msg=(
                    f"The newest {fund} price on or before {day} is from "
                    f"{price_date}, {gap} days earlier. That is too wide a gap "
                    "to convert a balance against -- update the price file, or "
                    "check the --balance-as-of date."
                )
            )
            return None

        context.log.success(
            msg=(
                f"Balance ${balance:,.2f} on {day} at ${price:,.4f} "
                f"({price_date}) = {format_units(units)} units"
            )
        )
        # The derived count is the durable half: the balance is true for one
        # day, the units it implies stay true until the next transaction. So
        # print it ready to paste, or the next run is back to a stale config.
        # Dated to the balance, not to the price -- nothing moves units over a
        # weekend, so a Saturday balance struck at Friday's price still states
        # Saturday's unit count.
        context.log.display(
            msg=(
                f"Store it: [TSP] units = {units:.4f}, units_as_of = {day.isoformat()}"
            )
        )
        return units, day.isoformat(), FROM_BALANCE

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

        units, as_of, source = self.units_for(context=context, prices=prices, fund=fund)

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
