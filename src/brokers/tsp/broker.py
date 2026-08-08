"""
Thrift Savings Plan broker class.

The only broker here that authenticates with nothing at all. Fidelity and Ally
drive a browser through a login; SnapTrade holds an API key. TSP holds neither,
because it does not need to: TSP computes a balance as units x share price, and
share prices are published daily as a public file. Units are the account's own
state, and they only move on a transaction.

So the daily path has no credential in it, nothing to expire, and nothing to
re-authenticate. A run cannot fail because a session went stale -- the failure
mode that makes the popular aggregators throw up their hands on this account
and show nothing at all.

What that costs: units have to come from somewhere, and that somewhere is a
quarterly statement (or a typed correction). Between those the mark is exact
until a contribution lands, and wrong by at most one contribution afterwards --
bounded, self-correcting at the next statement, and reported rather than
hidden. ``ApiConnection`` is subclassed for the shape rather than the key: no
username, no password, nothing to prompt for.

BrokerLoader imports this file by path and reads the module-level ``Broker``
alias at the bottom, so imports here must be absolute: the module is executed
under the synthetic name "broker" with no package.
"""

import datetime as dt
from pathlib import Path
from typing import Any

from requests import Response
from requests.exceptions import RequestException

from etc.api_connection import ApiConnection
from etc.config import (
    get_tsp_basd,
    get_tsp_contributions,
    get_tsp_fund,
    get_tsp_pay_table_url,
    get_tsp_price_url,
    get_tsp_rank,
)
from etc.logger import StonkSmithAdapter
from etc.paths import stonksmith_path
from helpers.dfas import (
    TABLE_NAMES,
    TABLE_PATHS,
    band_on,
    basic_pay_table,
    effective_date,
    normalize_grade,
    table_for,
)
from helpers.tsp import fund_prices, price_on

#: Matches the directory name, which is also the <name>.db stem and the CLI
#: subcommand.
BROKER_NAME = "tsp"

#: How stale the newest published price may be before the run says so. The file
#: is updated each business day, so a long weekend plus a federal holiday is
#: the widest ordinary gap.
PRICE_STALE_DAYS = 5

#: What to do about it, and deliberately not "or pass --prices". That flag
#: reads a downloaded price file instead of fetching one; it does not say which
#: fund is held and cannot stand in for this. Offering it here sent a live run
#: to `--prices` with nothing to give it and an argparse error for an answer.
SETUP_HINT = (
    "Add a [TSP] section to ~/.stonksmith/stonksmith.conf with a fund line, "
    "naming the fund exactly as the published price file heads its column -- "
    'for example "fund = C Fund", "fund = G Fund" or "fund = L 2060". Units '
    "can come from the same section, from --units, from --balance with "
    "--balance-as-of, or from a statement via -o STATEMENT=<file>."
)

#: tsp.gov sits behind a WAF that answers the default requests User-Agent with a
#: 403 and an HTML "Access Denied" page. It wants a UA that starts with
#: "Mozilla/5.0" and carries a second product/version token -- "Mozilla/5.0
#: (compatible; stonksmith)" is refused, this is not. So it is shaped like a
#: browser's because it has to be, while still saying truthfully who is calling.
#: The version is an identifier, not a claim about the build, and does not need
#: to track releases.
PRICE_USER_AGENT = (
    "Mozilla/5.0 (compatible; stonksmith/0.1.0; +https://github.com/Gerrrt/StonkSmith)"
)

#: What to say when the accrual keys are half filled in. Naming all four is the
#: point: a run missing one of them cannot tell which, and "rank is set but basd
#: is not" is the whole diagnosis.
ACCRUAL_HINT = (
    "Accounting for contributions needs rank, basd, member_contribution and "
    "agency_contribution together in the [TSP] section of "
    "~/.stonksmith/stonksmith.conf. Leave all four blank to value the unit "
    "count on its own."
)


class Tsp(ApiConnection):
    """
    TSP, valued from public share prices and a known unit count.
    """

    session_label = "public data"

    def __init__(self) -> None:
        super().__init__()
        self.broker = "TSP"
        self.name = "TSP"
        self.fund: str = ""
        self.price_date: dt.date | None = None
        #: Set only when every accrual key is filled in and the table loaded.
        #: None is what tells the module to value the anchored count alone, so
        #: every way this can go wrong ends up reported and harmless.
        self.pay_table: dict[str, dict[str, float]] | None = None
        self.grade: str = ""
        self.basd: dt.date | None = None
        self.pay_effective: dt.date | None = None

    def broker_logger(self) -> None:
        """
        Set up logger for the TSP broker class.
        :return: None
        :rtype: None
        """

        self.logger = StonkSmithAdapter(
            extra={"broker": "TSP", "username": self.username},
            logger=self.logger.logger,
        )

    def create_conn_obj(self) -> bool:
        """
        Load the published share price file.

        Reads a local copy when ``--prices`` names one, which is both the
        offline path and the one that works when tsp.gov is unreachable from
        wherever StonkSmith runs. Otherwise fetches the configured URL.

        Reports its own failure: broker_flow() prints nothing for a False
        return, so a quiet one would produce a run that does nothing and says
        nothing about it.
        :return: True when prices are loaded
        :rtype: bool
        """

        self.fund = get_tsp_fund()

        if not self.fund:
            self.logger.fail(msg=f"No TSP fund configured. {SETUP_HINT}")
            return False

        local: str = str(object=getattr(self.args, "prices", "") or "")
        text: str | None = (
            self.read_local(path=local) if local else self.fetch_published()
        )

        if text is None:
            return False

        prices: dict[dt.date, dict[str, float]] = fund_prices(text=text)

        if not prices:
            self.logger.fail(
                msg=(
                    "The share price file parsed to no rows at all. It is "
                    "probably an error page or a login redirect rather than "
                    "the CSV."
                )
            )
            return False

        self.client = prices
        self.load_pay_table()
        return True

    def load_pay_table(self) -> None:
        """
        Load the DFAS basic pay table, when there is anything to do with it.

        Every failure here is reported and then dropped. Contribution accounting
        is an addition to a mark that already works without it, so a refused
        download, a half-filled config or an unreadable service date must cost
        the accrual and not the run -- the module values the anchored unit count
        alone and says the estimate is missing.
        :return: None
        :rtype: None
        """

        if getattr(self.args, "no_accrual", False):
            return

        rank: str = get_tsp_rank()
        written: str = get_tsp_basd()
        member, agency = get_tsp_contributions()
        given: list[bool] = [
            bool(rank),
            bool(written),
            member is not None,
            agency is not None,
        ]

        # Nothing filled in is the ordinary case and says nothing. Some of it
        # filled in is a setup that will not do what its author expected, and
        # silence there is the failure worth avoiding.
        if not any(given):
            return

        if not all(given):
            self.logger.highlight(msg=ACCRUAL_HINT)
            return

        grade: str | None = normalize_grade(rank=rank)
        table_key: str | None = table_for(rank=rank)

        if grade is None or table_key is None:
            self.logger.fail(
                msg=(
                    f"{rank!r} is not a pay grade. Use the grade rather than the "
                    'title -- "E-7", "O-3", "W-2", or "O-3E" for an officer '
                    "with over 4 years enlisted or warrant service."
                )
            )
            return

        try:
            basd: dt.date = dt.date.fromisoformat(written)

        except ValueError:
            self.logger.fail(msg=f"Unreadable basd {written!r}; expected YYYY-MM-DD.")
            return

        html: str | None = self.pay_table_html(table_key=table_key)

        if html is None:
            return

        table: dict[str, dict[str, float]] = basic_pay_table(html=html)

        if not table:
            self.logger.fail(
                msg=(
                    "The DFAS pay page parsed to no rates at all. It is probably "
                    "an error page rather than the pay table. Pass --pay-table "
                    "with a copy saved in a browser, or --no-accrual to value "
                    "the unit count on its own."
                )
            )
            return

        self.pay_table = table
        self.grade = grade
        self.basd = basd
        self.pay_effective = effective_date(html=html)

    def pay_table_html(self, table_key: str) -> str | None:
        """
        Get the published pay page, from a file, the cache, or DFAS.

        Cached because the tables change once a year, on 1 January, and a daily
        run has no business asking for the same page three hundred times to be
        told the same thing. The year is in the file name rather than checked
        inside it, so a January run misses the cache by construction and picks
        the new rates up.
        :param table_key: Which grade family's page to load, a TABLE_PATHS key
        :return: The page's HTML, or None when it could not be had
        :rtype: str | None
        """

        local: str = str(object=getattr(self.args, "pay_table", "") or "")

        if local:
            return self.read_local(path=local, what="basic pay table")

        year: int = dt.datetime.now(tz=dt.UTC).year
        cached: Path = stonksmith_path / f"dfas-basic-pay-{table_key}-{year}.html"

        if cached.is_file():
            text: str | None = self.read_local(
                path=str(object=cached), what="cached basic pay table"
            )

            if text is not None:
                return text

        fetched: str | None = self.fetch_pay_table(table_key=table_key)

        if fetched is not None:
            self.cache_pay_table(path=cached, html=fetched)

        return fetched

    @staticmethod
    def cache_pay_table(path: Path, html: str) -> None:
        """
        Keep a copy of the pay page for the rest of the year.

        Silent about failing, and deliberately not creating the directory.
        setup_tool() owns making ~/.stonksmith, so a missing one means the tool
        has not been set up and this must not be the thing that creates it --
        the same rule etc.paths and etc.config already follow. A cache that
        cannot be written costs a request, which is not worth a line of output.
        :param path: Where to write it
        :param html: The page as served
        :return: None
        :rtype: None
        """

        if not path.parent.is_dir():
            return

        try:
            path.write_text(data=html, encoding="utf-8")

        except OSError:
            return

    def fetch_pay_table(self, table_key: str) -> str | None:
        """
        Download one published basic pay page.

        Public data, no credential, and the same browser-shaped User-Agent the
        share price download needs -- dfas.mil sits behind a CDN that answers
        anything else with a 403 and an HTML block page. The header goes on the
        request rather than on the shared session, so nothing here changes what
        another broker's login server sees.
        :param table_key: Which grade family's page to fetch, a TABLE_PATHS key
        :return: The page's HTML, or None when it could not be fetched
        :rtype: str | None
        """

        url: str = f"{get_tsp_pay_table_url().rstrip('/')}/{TABLE_PATHS[table_key]}"

        try:
            response: Response = self.session.get(
                url=url, headers={"User-Agent": PRICE_USER_AGENT}, timeout=30
            )

            if not response.ok:
                detail: str = (
                    " dfas.mil refused the request rather than the page being missing."
                    if response.status_code == 403
                    else ""
                )
                self.logger.fail(
                    msg=(
                        f"The {TABLE_NAMES[table_key]} pay table returned HTTP "
                        f"{response.status_code}.{detail} Pass --pay-table with "
                        "a copy saved in a browser, or --no-accrual to value "
                        "the unit count on its own."
                    )
                )
                return None

            return response.text

        except RequestException as e:
            self.logger.fail(msg=f"Could not fetch the basic pay table: {e}")
            return None

    def read_local(self, path: str, what: str = "share price file") -> str | None:
        """
        Read a file already on disk.

        Two callers want this -- ``--prices`` and ``--pay-table`` -- and the
        only thing that differs is what to call the file in the failure. Naming
        it is not decoration: the two flags fail the same way and a message that
        did not say which one would send the reader to the wrong file.
        :param path: Path given to the flag, or to a cached copy
        :param what: What to call the file if it cannot be read
        :return: The file's text, or None when it could not be read
        :rtype: str | None
        """

        try:
            return Path(path).expanduser().read_text(encoding="utf-8")

        except OSError as e:
            self.logger.fail(msg=f"Could not read the {what}: {e}")
            return None

    def fetch_published(self) -> str | None:
        """
        Download the published share price file.

        No credential and no browser: this is a public file, and that is the
        whole point of the broker. The one thing it does need is a User-Agent,
        because the CDN in front of the file refuses the default one.

        The header goes on the request rather than on ``self.session``, which is
        shared with every other broker on the base class: nothing here should
        change what some other broker's login server sees.
        :return: The file's text, or None when it could not be fetched
        :rtype: str | None
        """

        url: str = get_tsp_price_url()

        try:
            response: Response = self.session.get(
                url=url, headers={"User-Agent": PRICE_USER_AGENT}, timeout=30
            )

            if not response.ok:
                detail: str = (
                    " tsp.gov refused the request rather than the file being "
                    "missing. Pass --prices with a copy downloaded in a browser."
                    if response.status_code == 403
                    else ""
                )
                self.logger.fail(
                    msg=(
                        "Share price file returned HTTP "
                        f"{response.status_code}.{detail}"
                    )
                )
                return None

            return response.text

        except RequestException as e:
            self.logger.fail(msg=f"Could not fetch the share price file: {e}")
            return None

    def verify_access(self) -> bool:
        """
        Confirm the configured fund actually has a recent price.

        A price file that parses but carries nothing for this fund is the one
        failure that would otherwise reach the module and be reported as an
        account worth nothing -- a number, rather than an error.
        :return: True when the fund can be valued
        :rtype: bool
        """

        prices: Any = self.client
        today: dt.date = dt.datetime.now(tz=dt.UTC).date()
        found: tuple[dt.date, float] | None = price_on(
            prices=prices, fund=self.fund, day=today
        )

        if found is None:
            known: str = ", ".join(sorted({f for day in prices for f in prices[day]}))
            self.logger.fail(
                msg=(
                    f"The price file carries no price for {self.fund!r}. "
                    f"Funds it does carry: {known}"
                )
            )
            return False

        self.price_date, price = found
        age: int = (today - self.price_date).days

        if age > PRICE_STALE_DAYS:
            # Not fatal: an old price still values the account correctly as of
            # its own date, and saying so beats refusing to run.
            self.logger.highlight(
                msg=(
                    f"Newest {self.fund} price is {self.price_date} "
                    f"({age} days old). Marks will be as of that date."
                )
            )

        self.logger.success(msg=f"{self.fund} at ${price:,.4f} as of {self.price_date}")
        self.verify_pay_rate(today=today)
        return True

    def verify_pay_rate(self, today: dt.date) -> None:
        """
        Confirm the configured grade has a published rate today.

        Checked here, before any module runs, for the reason verify_access()
        exists at all: a grade the table does not carry is one actionable line
        now, or a silently missing accrual reported nowhere later.

        Never fatal. The mark works without the accrual, so a grade that cannot
        be priced drops the estimate rather than the run.
        :param today: The run date
        :return: None
        :rtype: None
        """

        if self.pay_table is None or self.basd is None:
            return

        band: str = band_on(basd=self.basd, day=today)
        rate: float | None = self.pay_table.get(self.grade, {}).get(band)

        if rate is None:
            known: str = ", ".join(sorted(self.pay_table))
            self.logger.fail(
                msg=(
                    f"DFAS publishes no {self.grade} rate at {band!r}, so "
                    "contributions cannot be priced. Grades the table does "
                    f"carry: {known}"
                )
            )
            self.pay_table = None
            return

        self.logger.success(
            msg=f"{self.grade} at {band}: ${rate:,.2f} basic pay per month"
        )


#: BrokerLoader reads this off the path-loaded module, so the class name is free
#: to diverge from the directory name.
Broker = Tsp
