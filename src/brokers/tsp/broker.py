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
from etc.config import get_tsp_fund, get_tsp_price_url
from etc.logger import StonkSmithAdapter
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
        return True

    def read_local(self, path: str) -> str | None:
        """
        Read a share price file already on disk.
        :param path: Path given to --prices
        :return: The file's text, or None when it could not be read
        :rtype: str | None
        """

        try:
            return Path(path).expanduser().read_text(encoding="utf-8")

        except OSError as e:
            self.logger.fail(msg=f"Could not read the share price file: {e}")
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
        return True


#: BrokerLoader reads this off the path-loaded module, so the class name is free
#: to diverge from the directory name.
Broker = Tsp
