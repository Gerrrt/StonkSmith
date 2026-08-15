"""
Manual broker class: accounts you can see but cannot scrape.

The second broker here that authenticates with nothing, and for a different
reason from the first. TSP has no login because it does not need one -- a
balance is units times a published price and both halves are public. This one
has no login because there is nothing to log in to that a program can reach: a
plan portal with no API, no scrapeable page and no export, whose only way out is
a transfer that has not opened yet.

Leaving such an account out is the option that looks safest and is not. Every
total the workspace produces is then short by its value while looking complete,
which is the failure this project keeps designing against -- and unlike a broker
that breaks, nothing ever says so.

**What the operator supplies is a unit count, never a balance.** The [TSP]
config comment states the rule in one line: a balance is true for one day, so
storing it would leave a value that silently rots. Units move only when money
goes in or out, so an account nobody is funding has a count that stays exactly
right while its value moves daily with the market. That is the whole trade --
one hand-typed number that does not decay, against a published price that does
the decaying for it.

What it costs: a contribution nobody types in leaves the mark short by exactly
that contribution, bounded and self-correcting the moment the count is updated.
``units_as_of`` rides on every mark so a reader can judge how much room that
leaves, the same way TSP's does.

BrokerLoader imports this file by path and reads the module-level ``Broker``
alias at the bottom, so imports here must be absolute: the module is executed
under the synthetic name "broker" with no package.
"""

import datetime as dt
from pathlib import Path
from typing import Any

from requests import Response
from requests.exceptions import RequestException

from stonksmith.etc.api_connection import ApiConnection
from stonksmith.etc.config import ManualHolding, get_manual_accounts
from stonksmith.etc.logger import StonkSmithAdapter
from stonksmith.helpers.quotes import QuotesUnavailable, close_on, daily_closes

#: Matches the directory name, which is also the <name>.db stem and the CLI
#: subcommand.
BROKER_NAME = "manual"

#: Where published closes come from. One symbol at a time and a quarter of
#: history, so a run after a long break still finds a price to fall back to.
#: The same feed Ally's --from-prices reprices against, deliberately: two
#: brokers valuing positions from two different price sources would disagree
#: about the same fund on the same day.
QUOTE_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=3mo"
)

#: Be identifiable. Same shape as the TSP broker's and Ally's, and on the same
#: reasoning: this is public data and there is no reason to be coy about who is
#: asking for it.
QUOTE_USER_AGENT = (
    "Mozilla/5.0 (compatible; stonksmith/0.1.0; +https://github.com/Gerrrt/StonkSmith)"
)

#: How long to wait for one symbol's prices.
QUOTE_TIMEOUT_SECONDS = 20

#: How stale the newest close may be before the run says so. A long weekend plus
#: a holiday is the widest ordinary gap.
PRICE_STALE_DAYS = 5

SETUP_HINT = (
    "Add a [MANUAL] section to ~/.stonksmith/stonksmith.conf with one "
    '"Name | SYMBOL | units | units_as_of" line per account -- for example '
    '"Sam Custodial | SPYM | 2.000000 | 2026-08-10". A fifth field may carry '
    "what was paid, so the account reports a gain rather than a dash. To turn "
    "a balance into a unit count, divide it by that day's close: a balance is "
    "units x price, so the division inverts it exactly."
)


class Manual(ApiConnection):
    """
    Accounts valued from a hand-kept unit count and a published price.
    """

    session_label = "public data"

    def __init__(self) -> None:
        super().__init__()
        self.broker = "Manual"
        self.name = "Manual"
        self.accounts: list[ManualHolding] = []
        #: Symbol to its published closes. One entry per distinct symbol rather
        #: than per account, so two accounts holding the same fund cost one
        #: request and are guaranteed to be marked at the same price.
        self.prices: dict[str, dict[dt.date, float]] = {}
        self.price_dates: dict[str, dt.date] = {}

    def broker_logger(self) -> None:
        """
        Set up logger for the manual broker class.
        :return: None
        :rtype: None
        """

        self.logger = StonkSmithAdapter(
            extra={"broker": "Manual", "username": self.username},
            logger=self.logger.logger,
        )

    def create_conn_obj(self) -> bool:
        """
        Read the configured accounts and load a price for each symbol.

        Reports its own failure: broker_flow() prints nothing for a False
        return, so a quiet one would produce a run that does nothing and says
        nothing about why.
        :return: True when at least one account can be valued
        :rtype: bool
        """

        self.accounts, refused = get_manual_accounts()

        for line in refused:
            # Named rather than counted. This is hand-typed configuration for
            # an account no source will ever correct, so a line that did not
            # parse has to be distinguishable from no configuration at all --
            # otherwise a mistyped account is indistinguishable from one nobody
            # added.
            self.logger.fail(msg=f"Unreadable [MANUAL] line, skipped: {line!r}")

        if not self.accounts:
            self.logger.fail(msg=f"No manual accounts configured. {SETUP_HINT}")
            return False

        local: str = str(object=getattr(self.args, "prices", "") or "")
        symbols: list[str] = sorted({held.symbol for held in self.accounts})

        # --prices names one payload and a payload carries one symbol's closes.
        # With two symbols configured, the loop below would read that same file
        # for each of them and mark a fund at another fund's price -- a mark
        # that is wrong by however far the two have diverged, written without a
        # word of complaint. Refused rather than warned about: the warning would
        # scroll past and the wrong number would stay in the database.
        if local and len(symbols) > 1:
            self.logger.fail(
                msg=(
                    f"--prices names one file and {len(symbols)} symbols are "
                    f"configured ({', '.join(symbols)}). It cannot say which "
                    "fund the closes belong to, and applying them to all of "
                    "them would price each at another's price. Drop the flag "
                    "to fetch each symbol, or configure one account at a time."
                )
            )
            return False

        for symbol in symbols:
            loaded: dict[dt.date, float] | None = (
                self.read_local(path=local)
                if local
                else self.fetch_quotes(symbol=symbol)
            )

            if loaded:
                self.prices[symbol] = loaded

        if not self.prices:
            self.logger.fail(msg="No prices could be loaded for any configured symbol.")
            return False

        self.client = self.prices
        return True

    def read_local(self, path: str) -> dict[dt.date, float] | None:
        """
        Parse a chart payload already on disk.

        The offline path, and the one that works when the quote feed is
        unreachable from wherever StonkSmith runs -- the same escape hatch TSP's
        --prices provides.
        :param path: Path given to the flag
        :return: Parsed closes, or None when the file could not be read
        :rtype: dict[dt.date, float] | None
        """

        try:
            return daily_closes(payload=Path(path).expanduser().read_text("utf-8"))

        except OSError as e:
            self.logger.fail(msg=f"Could not read the price file: {e}")
            return None

        except QuotesUnavailable as e:
            self.logger.fail(msg=f"The price file carried no usable closes: {e}")
            return None

    def fetch_quotes(self, symbol: str) -> dict[dt.date, float] | None:
        """
        Download published closes for one symbol.

        One symbol's failure is reported and dropped rather than taking the run
        down: a workspace with three manual accounts should still mark the two
        whose funds answered.
        :param symbol: The fund's ticker
        :return: Parsed closes, or None when they could not be had
        :rtype: dict[dt.date, float] | None
        """

        try:
            response: Response = self.session.get(
                url=QUOTE_URL.format(symbol=symbol),
                headers={"User-Agent": QUOTE_USER_AGENT},
                timeout=QUOTE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()

            return daily_closes(payload=response.text)

        except QuotesUnavailable as e:
            self.logger.fail(msg=f"No prices for {symbol}: {e}")
            return None

        except RequestException as e:
            self.logger.fail(msg=f"Could not fetch prices for {symbol}: {e}")
            return None

    def verify_access(self) -> bool:
        """
        Confirm every configured account has a price to be valued at.

        The one failure that would otherwise reach the module and be written as
        an account worth nothing -- a number, rather than an error, and one that
        would drag a real balance to zero in the net worth series.
        :return: True when at least one account can be valued
        :rtype: bool
        """

        today: dt.date = dt.datetime.now(tz=dt.UTC).date()
        valuable: int = 0

        for held in self.accounts:
            found: tuple[dt.date, float] | None = close_on(
                prices=self.prices.get(held.symbol, {}), day=today
            )

            if found is None:
                self.logger.fail(
                    msg=(
                        f"No published close for {held.symbol!r}, so "
                        f"{held.name!r} cannot be valued and is skipped."
                    )
                )
                continue

            when, price = found
            self.price_dates[held.symbol] = when
            age: int = (today - when).days

            if age > PRICE_STALE_DAYS:
                # Not fatal: an old close still values the account correctly as
                # of its own date, and saying so beats refusing to run.
                self.logger.highlight(
                    msg=(
                        f"Newest {held.symbol} close is {when} ({age} days old). "
                        f"{held.name} will be marked as of that date."
                    )
                )

            self.logger.success(
                msg=(
                    f"{held.name}: {held.units:,.6f} {held.symbol} at "
                    f"${price:,.4f} as of {when}, units as of {held.units_as_of}"
                )
            )
            valuable += 1

        return valuable > 0

    def priced(self, held: ManualHolding, day: dt.date) -> tuple[dt.date, float] | None:
        """
        The close this account should be marked at.
        :param held: The configured account
        :param day: The date wanted
        :return: (price date, close), or None when nothing was published
        :rtype: tuple[dt.date, float] | None
        """

        return close_on(prices=self.prices.get(held.symbol, {}), day=day)

    def login(self) -> bool:
        """
        There is nothing to log in to. Kept explicit rather than inherited so
        the absence reads as a decision rather than an omission.
        :return: True
        :rtype: bool
        """

        return True

    def teardown(self) -> None:
        """Nothing is held open."""


#: BrokerLoader reads this off the path-loaded module, so the class name is free
#: to diverge from the directory name.
Broker: Any = Manual
