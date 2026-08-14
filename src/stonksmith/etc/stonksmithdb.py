"""
Create database engine for stonksmith
"""

import cmd
import configparser
import datetime as dt
from pathlib import Path
from sys import argv
from typing import Any

from sqlalchemy import Engine

from stonksmith.etc.dividends import STALE_DAYS as DIVIDENDS_STALE_DAYS
from stonksmith.etc.exceptions import SwitchBroker, UserExitedProto
from stonksmith.etc.infrastructure import create_db_engine
from stonksmith.etc.logger import StonkSmithAdapter
from stonksmith.etc.paths import config_path, workspace_dir, ws_path
from stonksmith.etc.permissions import OWNER_ONLY_DIR, restrict_dir
from stonksmith.loaders.brokerloader import BrokerInfo, BrokerLoader

#: Commands that only exist inside a broker's sub-shell. Typing one at the top
#: level produced a bare "*** Unknown syntax" with no hint that a broker has to
#: be selected first, which is the single most common way to get stuck here.
BROKER_SHELL_COMMANDS: frozenset[str] = frozenset(
    {"add", "delete", "show", "export", "back"}
)


class StonkSmithDBMenu(cmd.Cmd):
    """
    Main Administrative Shell for StonkSmith Databases.
    """

    intro = (
        "\nStonkSmith database shell. Credentials and account history are stored "
        "per broker,\nso select one first:\n\n"
        "    broker            list available brokers\n"
        "    broker <name>     enter that broker (add/show/export live in there)\n"
        "    workspace list    list workspaces\n"
        "    sheet             rewrite the Google Sheet from these databases\n"
        "    verify [tabs|guard]  check what a successful sheet write cannot show\n"
        "    stale [days]      report accounts nothing has refreshed lately\n"
        "    brief [peek|--no-open]  what changed since the last brief\n"
        "    dividends         refresh what each holding pays per share\n"
        "    help              commands at this level\n"
        "    exit              quit\n"
    )

    def __init__(self, config_file_path: Path, resume_last_broker: bool = True) -> None:
        """
        Initialize STONKSMITHDB menu

        :param config_file_path: Path to the config file
        :param resume_last_broker: Re-enter the broker the last session left in.
            A convenience for a human returning to the shell, and wrong for the
            scripted form: entering a broker runs that broker's sub-shell, so a
            `stonksmithdb sheet` would sit at a sub-prompt instead of touching
            the sheet.
        """

        super().__init__()
        self.config_path = Path(config_file_path)
        self.config = configparser.ConfigParser()
        self.config.read(filenames=self.config_path)

        self.broker_loader = BrokerLoader()
        self.brokers: dict[str, BrokerInfo] = self.broker_loader.get_brokers()

        #: Set by any command that reported a failure. It exists for the
        #: scripted form in ``main()``, which has to exit non-zero when the
        #: work did not happen. A command cannot say so by returning True --
        #: cmd.Cmd reads a truthy return as "leave the loop", so failure and
        #: quit would be the same signal.
        self.failed: bool = False

        self.workspace: str = self.config.get(
            section="STONKSMITH", option="workspace", fallback="default"
        )
        self.do_workspace(line=self.workspace)

        last_db: str | None = self.config.get(
            section="STONKSMITH", option="last_used_db", fallback=None
        )
        if last_db and resume_last_broker:
            self.do_broker(broker=last_db)

    def do_exit(self, line: str) -> bool:
        """
        Exit STONKSMITHDB
        :param line:
        :return: True, which tells cmd.Cmd to leave the command loop
        """

        del line
        print("[*] Exiting...")
        return True

    do_EOF = do_exit

    def get_names(self) -> list[str]:
        """
        Hide the EOF handler from help and tab-completion. It exists so Ctrl-D
        quits cleanly, but listing "EOF" as a command is just noise.
        :return: Command names to advertise
        """

        return [name for name in super().get_names() if name != "do_EOF"]

    def default(self, line: str) -> None:
        """
        Explain unknown input instead of printing bare "*** Unknown syntax".
        :param line: The command the user typed
        """

        command: str = line.split()[0].lower() if line.split() else ""

        # Nothing below this point is a command that ran. Set once here rather
        # than on each way out, so a new branch cannot forget it.
        self.failed = True

        if command in BROKER_SHELL_COMMANDS:
            if not self.brokers:
                # "Select one first" followed by an empty list is a dead end.
                print(
                    f"[-] '{command}' only works inside a broker, and no brokers "
                    "were found."
                )
                return

            print(
                f"[-] '{command}' only works inside a broker. Select one first, e.g.:"
            )
            for name in sorted(self.brokers):
                print(f"      broker {name}")
            return

        print(f"[-] Unknown command: {line}. Type 'help' for the commands here.")

    def do_brokers(self, line: str) -> None:
        """
        List available brokers.
        :param line:
        """

        del line
        self.list_brokers()

    def list_brokers(self) -> None:
        """
        Print each discovered broker and whether its database is ready.
        """

        if not self.brokers:
            print("[-] No brokers found.")
            return

        print("[*] Available brokers:")

        for name in sorted(self.brokers):
            db_file: Path = Path(workspace_dir) / self.workspace / f"{name}.db"

            # No "incomplete" state any more: a broker that ships neither a
            # database.py nor a db_navigator.py takes the defaults, which is
            # what all five of the bundled ones now do.
            if not db_file.exists():
                status = f"no database in workspace '{self.workspace}' yet"
            else:
                status = "ready"

            print(f"      {name:<16} {status}")

        print("\n    Enter one with: broker <name>")

    def do_sheet(self, line: str) -> None:
        """
        Rewrite the machine-owned tabs from this workspace's databases.

        The sheet is a view of the databases, so it can be rebuilt from them
        alone. Without this the only cure for "the dashboard was not updated" is
        another scrape, and for the browser-backed brokers that means a human at
        a sign-in page -- a high price for a tab that is missing a banner.

        Every way this can go wrong sets ``self.failed``, which is what the
        scripted form exits on. A scheduled refresh that cannot fail is worse
        than no scheduled refresh: the tabs stop moving and nothing says so.
        :param line: Ignored
        :return: None
        """

        del line

        # Imported here rather than at module scope: this pulls in gspread and
        # google-auth, and the shell is mostly used for things that never touch
        # Sheets. tests/test_no_import_side_effects.py imports this module in a
        # subprocess and asserts nothing appears in $HOME.
        from stonksmith.etc.portfolio_sheet import refresh
        from stonksmith.helpers.sheets import SheetsUnavailable

        try:
            result = refresh(workspace=self.workspace)

        except SheetsUnavailable as e:
            print(f"[-] {e}")
            self.failed = True
            return

        except Exception as e:
            print(f"[-] Sheet refresh failed: {type(e).__name__}: {e}")
            self.failed = True
            return

        print(
            f"[*] Refreshed: {result.accounts} accounts, {result.holdings} "
            f"holdings, {result.transactions} movements from "
            f"{', '.join(result.brokers_read) or 'no brokers'}."
        )

        for name, reason in result.unreadable:
            # Printed as well as written to the tab. A total short by a whole
            # broker is exactly the failure that must not be quiet.
            print(f"[-] Not on the sheet: {name} could not be read ({reason}).")
            # And not quiet to a scheduler either. The refresh itself worked,
            # but the sheet it produced is missing a broker's money, which is
            # the wrong total rather than a stale one.
            self.failed = True

    def do_stale(self, line: str) -> None:
        """
        Report accounts whose As Of has gone stale, and fail if any have.

        The check a schedule has no other way to make. `docs/scheduling.md` opens
        by naming the failure this closes: "a cron job that errors every night
        gets muted -- after which the portfolio has stopped updating and nothing
        says so." Exit code 1 already covers a module reporting it did nothing,
        which is the loud way to break. This covers the quiet way, which the
        design itself creates: the Net Worth series carries an account's value
        forward for thirty days and --from-prices reprices a recorded unit count
        indefinitely, so a broker can go dark for a month while every run exits 0
        and the chart stays smooth.

        Reads databases and nothing else -- no login, no Sheets, no network -- so
        it is cheap enough to run on every schedule rather than occasionally.

        The dashboard has shown this for as long as it has had a staleness panel.
        What it has never had is a way to tell anybody who was not looking at it.
        :param line: An optional day count, defaulting to STALE_DAYS
        :return: None
        """

        # Imported here rather than at module scope for do_sheet's reason: the
        # shell is mostly used for things that never read a workspace, and
        # tests/test_no_import_side_effects.py imports this module in a
        # subprocess and asserts nothing appears in $HOME.
        from stonksmith.etc.portfolio import (
            STALE_DAYS,
            AccountRow,
            Portfolio,
            read_workspace,
            stale_accounts,
            stale_cutoff,
            stale_reason,
        )

        days: int = STALE_DAYS
        asked: str = line.strip()

        if asked:
            try:
                days = int(asked)

            except ValueError:
                print(f"[-] '{asked}' is not a number of days.")
                self.failed = True
                return

            if days < 0:
                # A negative window puts the cutoff in the future, which makes
                # every account stale including the one written this morning.
                # That is not a stricter check, it is a broken one.
                print(f"[-] A day count cannot be negative, and {days} is.")
                self.failed = True
                return

        today: dt.date = dt.datetime.now(tz=dt.UTC).date()
        cutoff: str = stale_cutoff(today=today, days=days)
        portfolio: Portfolio = read_workspace(workspace=self.workspace)

        print(
            f"[*] Freshness in '{self.workspace}': {len(portfolio.accounts)} "
            f"accounts, nothing older than {cutoff} ({days} days)."
        )

        for name, reason in portfolio.unreadable:
            # The strongest freshness failure there is. A database that will not
            # open is not stale data, it is no data -- and do_sheet already
            # treats it as a failure rather than a note.
            print(f"[-] {name} could not be read ({reason}).")
            self.failed = True

        stale: tuple[AccountRow, ...] = stale_accounts(
            portfolio=portfolio, cutoff=cutoff
        )

        for row in stale:
            print(
                f"[-] {row.broker} / {row.account}: "
                f"{stale_reason(as_of=row.as_of, today=today)}."
            )

        if stale:
            self.failed = True

        # Printed either way. A check whose success is silent is one nobody can
        # tell ran, which is the same failure mode as the muted cron job this
        # exists to catch.
        print(
            f"[{'-' if stale else '+'}] {len(stale)} of "
            f"{len(portfolio.accounts)} accounts are stale."
        )

    def do_brief(self, line: str) -> None:
        """
        Render what has changed since the last brief, and open it.

        The third command at this level that reads databases and nothing else,
        beside `sheet` and `stale`: no login, no broker, no network. That is what
        makes it cheap enough to schedule every morning, and why the LaunchAgent
        in scripts/ runs this rather than a scrape -- at half past six the market
        is shut, TSP has not published, and the browser-backed brokers want a
        human.

        ``peek`` renders without advancing the baseline, for looking again later
        in the day. ``--no-open`` renders without opening, which is what the
        tests and any scripted caller want.

        An unreadable broker fails the command, as it does for `sheet`, and the
        brief is still written and still opened. A page saying the total is short
        by a broker is worth more than no page, and it is the only place that
        sentence will be seen by somebody who is not reading a log.
        :param line: "peek", "--no-open", or empty
        :return: None
        """

        # Imported here rather than at module scope, for do_sheet's reason:
        # tests/test_no_import_side_effects.py imports this module in a
        # subprocess and asserts nothing appears in $HOME, and reaching a config
        # getter at import time is one of the ways that used to happen.
        import datetime as dt
        import webbrowser

        from stonksmith.etc.brief import (
            Baseline,
            Brief,
            build_brief,
            read_baseline,
            should_advance,
            take_baseline,
            write_baseline,
        )
        from stonksmith.etc.brief_html import render
        from stonksmith.etc.config import (
            get_brief_keep_days,
            get_brief_min_position,
            get_brief_movers,
            get_brief_open_browser,
        )
        from stonksmith.etc.dividends import Dividends, read_cache
        from stonksmith.etc.paths import baseline_path, dividends_path, reports_path
        from stonksmith.etc.permissions import restrict
        from stonksmith.etc.portfolio import (
            Portfolio,
            read_workspace,
        )

        asked: set[str] = set(line.split())
        peek: bool = "peek" in asked
        opening: bool = "--no-open" not in asked and get_brief_open_browser()

        unknown: set[str] = asked - {"peek", "--no-open"}

        if unknown:
            # Refused rather than ignored. A misspelled "--no-open" that silently
            # opened a browser would be a nuisance; a misspelled "peek" that
            # silently advanced the baseline would consume the comparison the
            # caller was trying to preserve.
            print(f"[-] Not something brief understands: {' '.join(sorted(unknown))}.")
            self.failed = True
            return

        now: dt.datetime = dt.datetime.now(tz=dt.UTC)
        # with_history, unlike every other reader: the per-position trend needs
        # every snapshot's positions rather than the newest one's, and this is
        # the only consumer that wants them. The sheet sync deliberately does
        # not ask.
        portfolio: Portfolio = read_workspace(
            workspace=self.workspace, with_history=True
        )
        baseline: Baseline | None = read_baseline(path=baseline_path)
        # Read from disk rather than fetched. `brief` reaches no network, which
        # is what makes it safe to schedule every morning; `dividends` does the
        # fetching, beside the scrapes.
        rates: Dividends = read_cache(path=dividends_path)

        brief: Brief = build_brief(
            portfolio=portfolio,
            baseline=baseline,
            today=now.date(),
            limit=get_brief_movers(),
            floor=get_brief_min_position(),
            rates=rates,
        )

        reports_path.mkdir(mode=OWNER_ONLY_DIR, parents=True, exist_ok=True)
        restrict_dir(path=reports_path)

        report: Path = reports_path / f"{now.date().isoformat()}.html"
        report.write_text(data=render(brief=brief, now=now), encoding="utf-8")
        # Every account's value and the portfolio total, in a file the databases
        # are already restricted for holding.
        restrict(path=report)

        print(
            f"[*] {brief.state}: {len(brief.account_movers)} accounts and "
            f"{len(brief.holding_movers)} positions moved, "
            f"{len(brief.new_transactions)} new movements. {report}"
        )

        for name, reason in brief.unreadable:
            # The same escalation do_sheet makes, and for the same reason: this
            # is not a stale total, it is one that is missing a broker's money.
            print(f"[-] Not in the brief: {name} could not be read ({reason}).")
            self.failed = True

        self._report_settings(
            portfolio=portfolio,
            stale_by=rates.age(today=now.date()),
            cached=bool(rates.paid),
        )

        if peek:
            print("[*] Baseline left where it was: this was a peek.")

        elif should_advance(baseline=baseline, as_of=brief.as_of):
            write_baseline(
                path=baseline_path,
                baseline=take_baseline(portfolio=portfolio, as_of=brief.as_of, now=now),
            )

        else:
            # Said out loud rather than done quietly. This is the rule that keeps
            # a day's movement from being erased by the act of looking at a
            # screen that reported there wasn't any, and a reader who does not
            # know it happened cannot tell this morning from a real quiet one.
            print(
                "[*] Baseline held: nothing has been scraped since it was taken, "
                "so the next brief still reports the movement this one could not."
            )

        self._prune_reports(keep=get_brief_keep_days())

        if opening:
            webbrowser.open(url=report.as_uri())

    def _prune_reports(self, keep: int) -> None:
        """
        Delete rendered briefs older than the configured window.

        By count of files rather than by their dates. The brief only runs on the
        days somebody schedules it, so "the last 90 files" and "the last 90 days"
        are different windows -- and a weekday-only agent that kept 90 *days*
        would hold about 64 briefs while claiming a quarter. Counting what is
        there answers the question the setting is actually asked: how far back
        can I look.
        :param keep: How many to keep, or 0 to keep everything
        :return: None
        """

        from stonksmith.etc.paths import reports_path

        if keep <= 0:
            return

        # Sorted by name, which is the date: the files are written as
        # YYYY-MM-DD.html precisely so this ordering is chronological without
        # trusting a mtime that a copy or a restore would have rewritten.
        written: list[Path] = sorted(reports_path.glob(pattern="*.html"))

        for stale_report in written[: max(0, len(written) - keep)]:
            # Best-effort, on permissions.py's reasoning. A brief that cannot be
            # tidied is not a reason to fail the morning's report.
            try:
                stale_report.unlink()

            except OSError as e:
                print(f"[-] Could not remove {stale_report}: {e}")

    @staticmethod
    def _report_settings(portfolio: Any, stale_by: int | None, cached: bool) -> None:
        """
        Say which settings did not take, and which figures are getting old.

        Split out of ``do_brief`` when it crossed the complexity limit, and the
        split is along a real seam rather than a convenient one: everything here
        is advisory. None of it changes the page, none of it sets ``failed``, and
        every line exists because the *symptom* of a setting quietly not applying
        is indistinguishable from the condition that setting was written to fix.
        A colour that was not understood leaves an uncoloured row; a stated cost
        that did not land leaves a dash; an alias that matched nothing leaves the
        broker's own wording. In each case the brief is correct and is simply not
        saying what was asked, which is precisely the failure nobody notices.
        :param portfolio: What the workspace holds, carrying its own unused lines
        :param stale_by: How old the oldest dividend figure is, or None
        :param cached: Whether any dividend figure is cached at all
        """

        from stonksmith.etc.config import (
            get_account_aliases,
            get_account_colors,
            get_account_costs,
            get_brief_fund_link,
        )
        from stonksmith.etc.portfolio import unmatched_aliases

        for label in unmatched_aliases(
            portfolio=portfolio, aliases=get_account_aliases()
        ):
            # A line that matches nothing is either a typo or a broker that has
            # renamed an account -- and in the second case the account has
            # quietly reverted to the broker's own wording, which is the outcome
            # the alias was written to prevent.
            print(f"[-] Alias matched no account: {label}")

        for line in portfolio.unused_costs:
            print(f"[-] [ACCOUNTS] cost_basis not applied: {line}")

        for line in get_account_costs()[1]:
            print(f"[-] Unreadable [ACCOUNTS] cost_basis line, skipped: {line}")

        if not cached:
            print(
                "[*] No dividend figures cached; run `stonksmithdb dividends` "
                "to fill the indicated yield in."
            )

        elif stale_by is not None and stale_by > DIVIDENDS_STALE_DAYS:
            # Not a failure: distributions are quarterly at most, so an old file
            # is not a wrong one. Said anyway, because a refresh that has stopped
            # running otherwise shows up as a yield that never moves.
            print(
                f"[-] Dividend figures are {stale_by} days old; "
                "run `stonksmithdb dividends` to refresh them."
            )

        if not get_brief_fund_link():
            print(
                "[-] [BRIEF] fund_link is not an https URL containing "
                "{symbol}; symbols are not linked."
            )

        for line in get_account_colors()[1]:
            print(f"[-] Unreadable [ACCOUNTS] colors line, skipped: {line!r}")

    def do_dividends(self, line: str) -> None:
        """
        Fetch what each held symbol pays per share, and cache it.

        The one command here that reaches the network, and it exists so that the
        brief does not have to. "No login, no browser, no network" is what makes
        `brief` cheap enough to schedule every morning and what stops it failing
        the way a broker can -- a dividend figure it had to fetch would trade
        that away for a number.

        Run beside the scrapes rather than beside the brief. Distributions are
        quarterly at most, so a figure a day or two old is not stale in any sense
        that matters, and a refresh that fails costs the yield rather than the
        morning.

        Only symbols that look like public tickers are asked about, which is the
        same rule the fund links follow: a 401k fund code and a 529 portfolio
        number have no quote page, and asking produces a 404 per run forever.
        :param line: Ignored
        :return: None
        """

        del line

        import datetime as dt

        import requests

        from stonksmith.etc.brief import fund_url
        from stonksmith.etc.dividends import Dividends, Paid, read_cache, write_cache
        from stonksmith.etc.paths import dividends_path
        from stonksmith.etc.portfolio import Portfolio, read_workspace
        from stonksmith.helpers.quotes import (
            QuotesUnavailable,
            dividend_events,
            trailing_dividend,
        )

        #: Any https template will do here -- fund_url is being asked whether the
        #: symbol is a public ticker, not where its page is.
        probe: str = "https://example.invalid/{symbol}"
        url: str = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            "{symbol}?interval=1d&range=1y&events=div"
        )
        agent: str = (
            "Mozilla/5.0 (compatible; stonksmith/0.1.0; "
            "+https://github.com/Gerrrt/StonkSmith)"
        )

        portfolio: Portfolio = read_workspace(workspace=self.workspace)
        today: dt.date = dt.datetime.now(tz=dt.UTC).date()
        symbols: list[str] = sorted(
            {
                row.symbol
                for row in portfolio.holdings
                if row.symbol and fund_url(symbol=row.symbol, template=probe)
            }
        )

        if not symbols:
            print("[-] No holding carries a public ticker; nothing to fetch.")
            return

        # Read before writing, because a failed fetch must not cost a figure that
        # was already known. This whole command rebuilds the file from one pass,
        # so a night the feed was unreachable used to write found=False over
        # every symbol and the next morning's brief lost its yield entirely --
        # a transient block page downgrading good data to "no such fund".
        previous: Dividends = read_cache(path=dividends_path)

        paid: dict[str, Paid] = {}
        carried: list[str] = []

        for symbol in symbols:
            try:
                response = requests.get(
                    url.format(symbol=symbol),
                    headers={"User-Agent": agent},
                    timeout=20,
                )
                events = dividend_events(payload=response.text)

            # Two exceptions, handled identically, and the pairing is the point.
            # RequestException is the network failing to answer; QuotesUnavailable
            # is an answer this cannot use -- and that second one covers a rate
            # limit, an HTML block page and a genuine 404 alike, of which only
            # the last is a fact about the symbol. Since the payload cannot tell
            # them apart, none of them is allowed to overwrite a good figure.
            #
            # Named rather than bare `Exception`, which is what this was. The
            # carry above is exactly what makes the difference matter: a
            # TypeError from a regression in the parsing would have been caught
            # here, reported as "kept the earlier figure" and cached as a
            # success, so the brief would render perfectly every morning off code
            # that had stopped working. A broad catch that predates a fallback is
            # a broad catch that hides less than one behind it. Anything not
            # named here ends the run non-zero, which is the whole contract the
            # nightly script's `status=1` rests on.
            except (requests.RequestException, QuotesUnavailable) as e:
                held: Paid | None = previous.paid.get(symbol)

                if held is not None and held.found:
                    # Kept with its own date, not restamped. A carried figure
                    # wearing today's date is the carried-as-observed failure
                    # the headline's basis split exists to prevent, and it would
                    # blind the staleness warning that is supposed to catch a
                    # refresh which has stopped running.
                    #
                    # Dated from the file when the figure itself carries no
                    # date, which is what every entry written before as_of
                    # existed looks like. Carrying one of those unchanged left
                    # nothing in the file dated at all, so age() fell back to
                    # fetched_on -- which this run is about to set to today --
                    # and a six-week-old figure reported as fetched this
                    # morning. Once, on the first blocked night after an
                    # upgrade, which is precisely when the warning is owed. The
                    # file's own date is the honest answer there: before as_of
                    # existed a run rewrote every symbol, so fetched_on *was*
                    # the day this figure came from.
                    stamped: Paid = (
                        held
                        if held.as_of
                        else Paid(
                            per_share=held.per_share,
                            covered_days=held.covered_days,
                            found=True,
                            as_of=previous.fetched_on,
                        )
                    )
                    print(
                        f"[-] Could not refresh {symbol} ({e}); "
                        f"keeping the figure from {stamped.as_of or 'an earlier run'}"
                    )
                    paid[symbol] = stamped
                    carried.append(symbol)
                    continue

                # Recorded as not found rather than skipped, when there is
                # nothing to keep. A symbol the feed has never heard of and a
                # fund that pays nothing both produce zero, and only one of
                # those is a fact about the money.
                print(f"[-] No dividend data for {symbol}: {e}")
                paid[symbol] = Paid(found=False, as_of=today.isoformat())
                continue

            per_share, covered = trailing_dividend(paid=events, today=today)
            paid[symbol] = Paid(
                per_share=per_share,
                covered_days=covered,
                found=True,
                as_of=today.isoformat(),
            )
            print(f"[*] {symbol}: ${per_share:,.4f} per share over {covered} days")

        write_cache(
            path=dividends_path,
            dividends=Dividends(fetched_on=today.isoformat(), paid=paid),
        )

        found: int = sum(1 for row in paid.values() if row.found)
        print(f"[+] Cached {found} of {len(symbols)} symbols to {dividends_path}")

        if carried:
            # Said out loud rather than left in the file. Carrying figures
            # forward is what stops one bad night costing the yield; a run that
            # carried every symbol is a refresh that is no longer refreshing,
            # and the two look identical in the count above.
            print(
                f"[-] {len(carried)} of those are older figures kept because the "
                f"feed could not be reached: {', '.join(carried)}"
            )

        if found < len(symbols):
            # Not a failure: a symbol with no quote page is an ordinary holding
            # here, and the brief says which positions its yield covers.
            print(
                "[*] The rest have no quote page, so the brief's yield will say "
                "how many positions it stands on."
            )

    def do_verify(self, line: str) -> None:
        """
        Check what a successful sync cannot show, against real Sheets.

        Two halves, and `verify` on its own runs both. ``tabs`` reads the
        machine-owned tabs back: a write that returned says the request was
        accepted, not that
        the values arrived as the kind of thing they were meant to be. ``guard``
        asks claim() its three questions on a tab it makes and removes -- the
        refusal is the one rule here whose failure cannot be undone by running
        again, and observing it used to mean defacing a live tab.

        Neither half retires the manual steps entirely. A refusal aborting the
        *whole* sync is refresh() claiming every tab before clearing any, and the
        scratch tab is not one of them; and an absent value arriving as an empty
        cell rather than an empty string cannot be seen from a read at all.

        A check that did not behave sets ``self.failed``, as does a half that
        could not run at all, so the scripted form exits on the finding. A
        verification that reports "unguarded" and exits 0 would be read by
        everything downstream as a clean run.
        :param line: "tabs", "guard", or empty for both
        :return: None
        """

        # Same reason as do_sheet: this pulls in gspread and google-auth, and the
        # shell is mostly used for things that never touch Sheets.
        from stonksmith.etc.portfolio_sheet import (
            GUARD_CHECK_TAB,
            check_ownership_guard,
            check_tabs,
        )
        from stonksmith.helpers.sheets import SPREADSHEET_NAME

        which = line.strip().lower()

        if which not in ("", "tabs", "guard"):
            print(f"[-] Unknown check '{which}'. Use 'tabs', 'guard', or neither.")
            self.failed = True
            return

        cases: list[Any] = []

        if which in ("", "tabs"):
            print(f"[*] Reading the tabs back from '{SPREADSHEET_NAME}'.")
            read = self._checked(
                run=lambda: check_tabs(workspace=self.workspace), what="Tab check"
            )

            if read is None:
                self.failed = True
                return

            cases.extend(read)

        if which in ("", "guard"):
            print(
                f"[*] Making the tab '{GUARD_CHECK_TAB}' in '{SPREADSHEET_NAME}', "
                "asking the guard about it, and deleting it again. No other tab "
                "is opened."
            )
            guarded = self._checked(run=check_ownership_guard, what="Ownership check")

            if guarded is None:
                self.failed = True
                return

            cases.extend(guarded)

        for case in cases:
            print(f"{'[+]' if case.passed else '[-]'} {case.name}")

            if not case.passed:
                # The finding, not a footnote. A guard that adopted a tab it
                # should have refused is the shape that eats somebody's work.
                # Only on a failure: a passing refusal carries the refusal message
                # as its detail, and printing that under a [+] is four lines
                # saying the expected thing happened.
                print(f"    Expected {case.expected}: {case.detail or 'it did not'}")

        failed = [case for case in cases if not case.passed]

        if failed:
            print(
                f"[-] {len(failed)} of {len(cases)} did not behave. Until this "
                "reads clean, treat the machine-owned tabs as unguarded and do "
                "not keep anything of your own in the spreadsheet."
            )
            self.failed = True
            return

        # Named per half that actually ran. A guard-only run listing the
        # empty-cell gap points at a tab check nobody asked for, and a reader who
        # sees a caveat that does not apply learns to skim the ones that do.
        gaps: list[str] = []

        if which in ("", "tabs"):
            gaps.append("an absent value arriving as an empty cell")

        if which in ("", "guard"):
            gaps.append("a refusal aborting the whole sync")

        print(
            f"[*] All {len(cases)} checks behaved, against real Sheets rather "
            f"than a stub. {'One thing' if len(gaps) == 1 else 'Two things'} "
            f"{'it' if len(gaps) == 1 else 'they'} cannot cover "
            f"{'is' if len(gaps) == 1 else 'are'} still in "
            f"docs/live-verification.md: {', and '.join(gaps)}."
        )

    def _checked(self, run: Any, what: str) -> Any:
        """
        Run one half, turning either failure into a line rather than a traceback.
        :param run: The check to call
        :param what: What to call it in an unexpected failure
        :return: The cases, or None if it could not run
        :rtype: Any
        """

        from stonksmith.helpers.sheets import SheetsUnavailable

        try:
            return run()

        except SheetsUnavailable as e:
            print(f"[-] {e}")

        except Exception as e:
            print(f"[-] {what} failed: {type(e).__name__}: {e}")

        return None

    def write_config(self) -> None:
        """
        Create config file
        """

        with self.config_path.open(mode="w") as configfile:
            self.config.write(fp=configfile)

    def do_broker(self, broker: str) -> None:
        """
        Enter a broker's database navigator, or list the brokers if given none.

        A sub-shell can ask to switch straight to another broker, so this loops
        rather than recursing: hopping between brokers must not grow the stack.
        :param broker: Broker to enter, or "" to list what is available
        :return:
        """

        # None means finished; "" means the user asked for the listing; a name
        # means switch to it. Collapsing the first two would make `brokers`
        # from inside a sub-shell exit silently.
        pending: str | None = broker.strip()

        while pending is not None:
            if not pending:
                self.list_brokers()
                return

            pending = self.enter_broker(broker=pending)

    def enter_broker(self, broker: str) -> str | None:
        """
        Open one broker's navigator and run it until the user leaves.
        :param broker: Broker to enter
        :return: Another broker to switch to, or None when finished
        """

        if broker not in self.brokers:
            print(f"[-] Unknown broker: {broker}")
            self.list_brokers()
            return None

        db_file: Path = Path(workspace_dir) / self.workspace / f"{broker}.db"

        if not db_file.exists():
            print(f"[-] Database file missing: {db_file}")
            return None

        navigator = self.broker_loader.navigator_class(name=broker)
        database = self.broker_loader.database_class(name=broker)

        if navigator is None or database is None:
            print(f"[-] Failed to load broker modules for: {broker}")
            return None

        engine: Engine = create_db_engine(db_path=db_file)
        db_instance = database(engine, broker)

        self.config.set(section="STONKSMITH", option="last_used_db", value=broker)
        self.write_config()

        try:
            broker_menu = navigator(self, db_instance, broker)
            broker_menu.cmdloop()

        except SwitchBroker as switch:
            # `broker <name>` typed inside the sub-shell: leave this one and
            # go straight there, no explicit `back` required.
            return switch.broker

        except UserExitedProto:
            pass

        return None

    def do_workspace(self, line: str) -> None:
        """
        Manage workspaces: workspace <> | create <> | list
        :param line:
        """

        parts: list[str] = line.split()
        if not parts:
            print(f"[*] Current workspace: {self.workspace}")
            return

        cmd_arg: str = parts[0].lower()

        if cmd_arg == "create" and len(parts) > 1:
            name: str = parts[1]
            print(f"[*] Creating workspace '{name}'")
            self.create_workspace(name=name)
            self.do_workspace(line=name)

        elif cmd_arg == "list":
            print("[*] Enumerating Workspaces:")
            # iterdir() yields paths where listdir() yielded names, hence .name
            # on both lines. sorted() because neither is ordered, and a listing
            # a person reads should not shuffle between runs.
            for ws in sorted(workspace_dir.iterdir()):
                indicator: str = "==> " if ws.name == self.workspace else "   "
                print(f"{indicator}{ws.name}")

        else:
            target_ws: Path = Path(workspace_dir) / line
            if target_ws.exists():
                self.workspace: str = line
                self.config.set(section="STONKSMITH", option="workspace", value=line)
                self.write_config()
                self.prompt = f"stonksmithdb ({line}) > "
            else:
                print(f"[-] Workspace '{line}' does not exist.")

    def create_workspace(self, name: str) -> None:
        """
        Creates new folder and all broker DBs within it.
        :param name:
        :type name:
        """

        new_path: Path = Path(workspace_dir) / name
        new_path.mkdir(mode=OWNER_ONLY_DIR, parents=True, exist_ok=True)
        restrict_dir(path=new_path)

        for broker_name in self.brokers:
            db_class = self.broker_loader.database_class(name=broker_name)

            if db_class is None:
                print(f"[-] Skipping {broker_name}: its Database will not load.")
                continue

            engine: Engine = create_db_engine(db_path=new_path / f"{broker_name}.db")
            db_instance = db_class(engine, broker_name)
            db_instance.shutdown_db()


def initialize_db(logger: StonkSmithAdapter) -> None:
    """
    Initialize the database
    :param logger:
    :type logger: StonkSmithAdapter
    """

    default_ws: Path = Path(ws_path) / "default"
    default_ws.mkdir(mode=OWNER_ONLY_DIR, parents=True, exist_ok=True)
    restrict_dir(path=default_ws)

    loader = BrokerLoader()
    brokers: dict[str, BrokerInfo] = loader.get_brokers()

    for name in brokers:
        db_file: Path = default_ws / f"{name}.db"

        if db_file.exists():
            continue

        logger.highlight(msg=f"Initializing {name.upper()} database")
        db_class = loader.database_class(name=name)

        if db_class is None:
            logger.fail(msg=f"Skipping {name}: its Database will not load.")
            continue

        engine: Engine = create_db_engine(db_path=db_file)
        db_instance = db_class(engine, name)
        db_instance.shutdown_db()


def main() -> None:
    """
    Main function
    :return:
    """

    # etc.paths no longer creates anything at import time, so this entry point
    # is responsible for making sure the tool is set up before it reads config.
    # Imported here, not at module scope: tool_setup imports initialize_db from
    # this module, so a top-level import would be circular.
    from stonksmith.etc.logger import stonksmith_logger
    from stonksmith.etc.tool_setup import setup_tool

    setup_tool(logger=stonksmith_logger)

    if not Path(config_path).exists():
        print("[-] Unable to find config file")
        # SystemExit with no argument is SystemExit(None), which Python maps to
        # exit status 0 -- so this hard failure used to report success.
        raise SystemExit(1)

    # Words after the command name run as one command and then exit, so
    # `stonksmithdb sheet` is a thing cron can call. Piping into the shell
    # already worked -- do_EOF quits cleanly -- but it exits 0 however the
    # command went, and a scheduled step that cannot fail is one that stops
    # working silently. This form reports.
    command: str = " ".join(argv[1:]).strip()

    try:
        shell = StonkSmithDBMenu(
            config_file_path=config_path, resume_last_broker=not command
        )

        if command:
            shell.onecmd(line=command)
            raise SystemExit(1 if shell.failed else 0)

        shell.cmdloop()

    except KeyboardInterrupt:
        print("[*] Exiting...")


if __name__ == "__main__":
    main()
