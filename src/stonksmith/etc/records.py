# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""What a module hands the database.

Three records, deliberately sparse. Sources do not agree on what an account
holding looks like: a scraped 529 fund table gives a fund code, principal and
earnings; a SnapTrade position gives a ticker, units and a cost basis; a
pre-aggregated account gives nothing at all. Rather than a lowest common
denominator or a JSON blob, every field a source might not have defaults to
None, and the database stores what it was given.

These are frozen because a module builds one and hands it over; nothing
downstream should be editing a caller's record in place.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccountIdentity:
    """
    Who an account is, as opposed to what it was worth at a moment.

    ``account_key`` is the identity and must stay stable across runs: it is what
    joins this run's snapshot to every previous one. It is deliberately the same
    string the old ``save_account_data`` used as ``account_name``, so databases
    written before account history keep their continuity.
    """

    #: Stable identity within a broker. Never derive this from something that
    #: can change between runs.
    account_key: str

    #: What to show a human. Free to change; not identity.
    display_name: str

    #: The brokerage an aggregator read this from. Empty for direct scrapers,
    #: which are their own source.
    source: str = ""

    #: The source's own id for the account -- a SnapTrade UUID, an account
    #: number. Recorded because it is useful, never used as identity.
    external_id: str | None = None

    #: Who the account is for. 529 plans have one; most accounts do not.
    beneficiary: str | None = None

    #: "529", "INVESTMENT", "LOC", or whatever the source calls it.
    kind: str | None = None

    #: The account's native currency, when the source says.
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class Holding:
    """
    One position within one snapshot.

    Every field is optional because the two shapes this has to carry overlap
    only partly. A scraper fills ``fund_code``/``principal``/``earnings``; an API
    fills ``symbol``/``cost_basis``. Neither filling the other's columns is
    normal, not an error.
    """

    #: Ticker, for sources that trade in them.
    symbol: str | None = None

    #: Fund code, for sources that do not.
    fund_code: str | None = None

    #: The fund or security name.
    name: str | None = None

    units: float | None = None
    price: float | None = None
    value: float | None = None

    #: 529 plans report contributions and growth separately.
    principal: float | None = None
    earnings: float | None = None

    #: What the position cost, where the source tracks it.
    cost_basis: float | None = None

    currency: str = "USD"

    #: The value exactly as the source wrote it, before parsing.
    raw_value: str | None = None

    #: The date the unit count was true, ISO, where the source dates a quantity
    #: separately from its value. TSP is the only one that does: its price is
    #: today's and its units are as old as the last statement, so a mark that
    #: carried one date could not say which. None when the source never said.
    units_as_of: str | None = None


@dataclass(frozen=True, slots=True)
class Transaction:
    """
    One movement of money or units.

    ``external_id`` is the source's own identifier when it has one. When it does
    not -- a scraped table has no ids -- the database derives a natural key from
    the remaining fields instead, so re-scraping an overlapping window does not
    duplicate history.
    """

    #: Settlement date, as the source gave it.
    processed_on: str = ""

    #: Trade date, as the source gave it.
    traded_on: str = ""

    #: "Contribution", "BUY", "DIVIDEND" -- whatever the source calls it.
    tx_type: str = ""

    symbol: str | None = None
    description: str | None = None

    units: float | None = None
    price: float | None = None
    value: float | None = None

    currency: str = "USD"

    #: The source's own transaction id, when it has one.
    external_id: str | None = None

    #: The value exactly as the source wrote it, before parsing.
    raw: str | None = None
