# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""
Mark hand-kept accounts at a published close.

The module for accounts no program can reach: a plan portal with no API, no
scrapeable page and no export, whose only way out is a transfer that has not
opened. The operator supplies a unit count once; this multiplies it by the
market's own price every run.

**Nothing here invents a value.** Every mark is a configured count times a
published close, and both halves are reported -- the count with the date it was
true, the price with the date it was struck. An account whose symbol had no
price is skipped and said out loud rather than written at zero, which is the one
failure that would look like a number instead of an error and would drag a real
balance to nothing in the net worth series.

The account's ``as_of`` is the *price* date, not the run's clock and not the
unit date. That is the same answer every other view gives to "what date is this
value for", and it is what makes a manual account age visibly alongside scraped
ones: a stale price shows up in `stale` exactly as a stale scrape does.
"""

import datetime as dt
from typing import Any, ClassVar

from stonksmith.etc.config import ManualHolding
from stonksmith.etc.connection import Connection
from stonksmith.etc.context import Context, SnapshotDbProtocol
from stonksmith.etc.portfolio_sheet import sync
from stonksmith.etc.records import AccountIdentity, Holding
from stonksmith.helpers.quotes import value_of


class StonkSmithModule:
    """Value each configured account and record a snapshot."""

    # Lowercase, like every other bundled module: ModuleLoader keys the
    # registry on this attribute and lowercases what -M is given, so a
    # capitalised name is a module that lists but cannot be run.
    name: str = "manual"
    description: str = "Mark hand-kept accounts at a published close"
    supported_brokers: ClassVar[list[str]] = ["manual"]
    opsec_safe: bool = True
    multiple_hosts: bool = False

    def __init__(
        self,
        context: Context | None = None,
        module_options: dict[str, Any] | None = None,
    ) -> None:
        self.context: Context | None = context
        self.module_options: dict[str, Any] | None = module_options

    def options(self, context: Context, module_options: dict[str, Any]) -> None:
        """
        No module options. Configuration is the [MANUAL] section.
        :param context: The run context
        :param module_options: Ignored
        """

    def on_login(self, context: Context, connection: Connection) -> bool | None:
        """
        Write one snapshot per configured account.

        Returns False when nothing was written, which is what makes a scheduled
        run exit non-zero. A manual broker that silently records nothing is
        worse than one that fails: the account simply stops appearing, and a
        total short by it looks exactly like a total.
        :param context: The run context, carrying the database
        :param connection: The manual broker, carrying the loaded prices
        :return: False when no account could be valued
        :rtype: bool | None
        """

        db = context.db

        if not isinstance(db, SnapshotDbProtocol):
            # The same check tsp_module makes, and the same reason: a database
            # written against the older contract has no snapshot tables, and
            # saying so beats an AttributeError three frames down. There is no
            # save_account_data fallback here -- that path stores a *balance*
            # as text, which is precisely the rotting number this broker exists
            # to avoid storing.
            context.log.fail(
                msg=(
                    "DB contract violation: context.db does not implement "
                    "save_snapshot, so a manual account cannot be recorded. "
                    "Re-run any broker sync to build the newer tables."
                )
            )
            return False

        today: dt.date = dt.datetime.now(tz=dt.UTC).date()
        # One stamp for every account in the run. scraped_at is half the
        # snapshot key, so two accounts marked a second apart would be two runs
        # to every reader of the table -- and the net worth axis would place
        # them on the same date anyway.
        scraped_at: str = dt.datetime.now(tz=dt.UTC).strftime("%Y-%m-%d %H:%M:%S")

        accounts: list[ManualHolding] = list(getattr(connection, "accounts", []))
        written: int = 0

        # Read off the connection rather than typed onto it. Connection is the
        # shared base every broker's class extends and it knows nothing about
        # prices; widening it for one broker would put a quote feed in the
        # contract that Fidelity and Ally have to satisfy.
        priced = getattr(connection, "priced", None)

        if not callable(priced):
            context.log.fail(msg="The manual broker loaded no prices.")
            return False

        for held in accounts:
            found: tuple[dt.date, float] | None = priced(held=held, day=today)

            if found is None:
                # Skipped rather than written at zero. Already reported by
                # verify_access, so this stays quiet rather than saying it twice.
                continue

            when, price = found
            value: float = value_of(units=held.units, price=price)

            db.save_snapshot(
                account=AccountIdentity(
                    account_key=f"{held.symbol} - {held.name}",
                    display_name=held.name,
                    source="manual",
                    kind="INVESTMENT",
                    currency="USD",
                ),
                scraped_at=scraped_at,
                # The price's date, not the run's. What this value is *for* is
                # the day the market last struck a price, which is what every
                # other view means by As Of.
                as_of=when.isoformat(),
                value=value,
                currency="USD",
                holdings=[
                    Holding(
                        symbol=held.symbol,
                        units=held.units,
                        price=price,
                        value=value,
                        cost_basis=held.cost_basis,
                        currency="USD",
                        # The two dates that differ, carried separately for the
                        # reason TSP carries them: the price is today's and the
                        # count is as old as the last time anybody typed it.
                        units_as_of=held.units_as_of,
                    )
                ],
                # Deliberately none. A movement is a fact about money changing
                # hands and this module observes no movements -- it prices a
                # count. Writing the deposits that produced that count would be
                # inventing a log from a configuration line.
                transactions=[],
            )

            context.log.success(
                msg=(
                    f"{held.name}: {held.units:,.6f} {held.symbol} x "
                    f"${price:,.4f} = ${value:,.2f} as of {when} "
                    f"(units as of {held.units_as_of})"
                )
            )
            written += 1

        if not written:
            context.log.fail(msg="No manual account could be valued; nothing written.")
            return False

        sync(context=context)
        return True
