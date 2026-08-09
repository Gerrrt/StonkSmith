# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Shared broker database implementation.

Every broker package exposes a ``Database`` class in ``database.py``, which
BrokerLoader imports by file path. The behaviour is identical across brokers, so it
lives here and each broker subclasses it with its own default broker name.

Secrets are never stored in SQLite. The credentials table holds a keyring
reference; the secret itself lives in the OS credential store (see etc.secrets).

Account data is four tables, not one. ``accounts`` is identity and holds one row
per account ever seen; ``account_snapshots`` holds one row per account per run
with a *numeric* value beside the text the source actually printed; ``holdings``
holds the positions behind a snapshot; ``transactions`` holds movements, keyed so
that re-scraping an overlapping window does not duplicate history. A daily
change is the difference between consecutive snapshots, which is why the value
has to be a number and the as-of date has to come from the source rather than
from the clock.

Databases written before that schema existed carry a single ``accounts`` table
of per-run rows with a text balance. They are migrated on open, and the original
table is renamed aside rather than dropped -- see migrate_legacy_accounts.
"""

import datetime
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import (
    Column,
    Connection,
    Engine,
    ForeignKey,
    Index,
    Insert,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from etc.logger import stonksmith_logger
from etc.records import AccountIdentity, Holding, Transaction
from etc.secrets import delete_secret, get_secret, keyring_key, set_secret
from helpers.normalize import format_amount, to_amount, to_currency, to_iso_date

#: Where a legacy ``accounts`` table is moved so its rows survive the migration.
#: Never dropped: if the replay misreads a balance format, this is the only copy
#: of what the scrape originally recorded.
LEGACY_ACCOUNTS_TABLE = "accounts_legacy_v1"

#: What an account with no usable name is called. Matches what the pre-history
#: ``save_account_data`` path produced, so migrated rows stay stitched to the
#: rows written after the upgrade.
UNKNOWN_ACCOUNT = "Unknown account"

#: Money columns. Four decimal places is more than any broker reports and leaves
#: room for a currency that does not use two.
_MONEY = Numeric(precision=18, scale=4, asdecimal=False)

#: Quantity columns. Six places, because fractional shares are routine.
_QUANTITY = Numeric(precision=18, scale=6, asdecimal=False)


class BrokerDatabase:
    """SQLite-backed credential and account store for a single broker."""

    #: Overridden by each broker subclass.
    broker_name: str = "unknown"

    def __init__(self, db_engine: Engine, broker: str | None = None) -> None:
        self.db_engine: Engine = db_engine
        self.broker: str = broker or self.broker_name
        self.metadata = MetaData()

        self.creds_table = Table(
            "credentials",
            self.metadata,
            Column("id", Integer, primary_key=True),
            Column("username", String),
            Column("keyring_key", String),
            Column("type", String, default="plaintext"),
            Column("pillaged_from", String, default="manual"),
        )

        self.accounts_table = Table(
            "accounts",
            self.metadata,
            Column("id", Integer, primary_key=True),
            Column("broker", String, nullable=False),
            # The brokerage an aggregator read this from. Empty for direct
            # scrapers. Deliberately outside the unique key: account_key already
            # carries the brokerage for SnapTrade, and a nullable column in a
            # SQLite UNIQUE lets duplicate identities accumulate forever,
            # because every NULL is distinct from every other NULL.
            Column("source", String, nullable=False, server_default=""),
            Column("account_key", String, nullable=False),
            Column("external_id", String),
            Column("display_name", String, nullable=False),
            Column("beneficiary", String),
            Column("kind", String),
            Column("currency", String),
            Column("first_seen", String, nullable=False),
            Column("last_seen", String, nullable=False),
            UniqueConstraint("broker", "account_key", name="uq_accounts_broker_key"),
        )

        self.snapshots_table = Table(
            "account_snapshots",
            self.metadata,
            Column("id", Integer, primary_key=True),
            Column(
                "account_id",
                Integer,
                ForeignKey("accounts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("scraped_at", String, nullable=False),
            # What the source says the value is for, which is not when the
            # scrape ran. Nullable: several sources never say.
            Column("as_of", String),
            # Nullable on purpose. An account can appear in a run with no number
            # at all, and that is different from a zero and from being absent.
            Column("value", _MONEY),
            Column("currency", String, nullable=False, server_default="USD"),
            Column("raw_value", String),
            UniqueConstraint(
                "account_id", "scraped_at", name="uq_snapshot_account_time"
            ),
            Index("ix_snapshots_account_time", "account_id", "scraped_at"),
        )

        self.holdings_table = Table(
            "holdings",
            self.metadata,
            Column("id", Integer, primary_key=True),
            Column(
                "snapshot_id",
                Integer,
                ForeignKey("account_snapshots.id", ondelete="CASCADE"),
                nullable=False,
            ),
            # Ordering, not identity by symbol: a source may supply neither a
            # symbol nor a fund code, and one account can hold two lots of the
            # same fund. Holdings are replaced wholesale per snapshot, so
            # position is both sufficient and honest.
            Column("position", Integer, nullable=False),
            Column("symbol", String),
            Column("fund_code", String),
            Column("name", String),
            Column("units", _QUANTITY),
            Column("price", _QUANTITY),
            Column("value", _MONEY),
            Column("principal", _MONEY),
            Column("earnings", _MONEY),
            Column("cost_basis", _MONEY),
            Column("currency", String, nullable=False, server_default="USD"),
            Column("raw_value", String),
            # The date the unit count was true, which is not the date the value
            # was struck. A TSP mark is units times a price and the two are as of
            # different days -- the price is today's, the units are as old as the
            # last statement -- so a stored mark carrying only one of them cannot
            # be audited later. Nullable: no other source dates a quantity
            # separately from its value, and most never will.
            Column("units_as_of", String),
            UniqueConstraint(
                "snapshot_id", "position", name="uq_holding_snapshot_position"
            ),
            Index("ix_holdings_snapshot", "snapshot_id"),
        )

        self.transactions_table = Table(
            "transactions",
            self.metadata,
            Column("id", Integer, primary_key=True),
            Column(
                "account_id",
                Integer,
                ForeignKey("accounts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            Column("external_id", String),
            Column("processed_on", String, nullable=False, server_default=""),
            Column("traded_on", String, nullable=False, server_default=""),
            Column("tx_type", String, nullable=False, server_default=""),
            Column("symbol", String),
            Column("description", String),
            Column("units", _QUANTITY),
            Column("price", _QUANTITY),
            Column("value", _MONEY),
            Column("currency", String, nullable=False, server_default="USD"),
            Column("natural_key", String, nullable=False),
            Column("first_seen", String, nullable=False),
            Column("raw", String),
            UniqueConstraint(
                "account_id", "natural_key", name="uq_transaction_account_key"
            ),
            Index("ix_transactions_account_date", "account_id", "processed_on"),
        )

        # Order matters. create_all leaves an existing table alone, so a legacy
        # ``accounts`` has to be renamed out of the way before the new one can
        # be created in its place.
        renamed: bool = self.migrate_legacy_accounts()
        self.metadata.create_all(bind=self.db_engine)
        self.backfill_legacy_accounts(force=renamed)
        # After create_all, not before: on a fresh database there is no holdings
        # table to alter yet, and afterwards its guard finds the column already
        # there and does nothing.
        self.migrate_holding_dates()
        self.migrate_plaintext_secrets()

        session_factory: sessionmaker[Session] = sessionmaker(
            bind=self.db_engine, expire_on_commit=True
        )
        self.sess: Session = scoped_session(session_factory=session_factory)()

    @contextmanager
    def _write(self) -> Iterator[Connection]:
        """
        A connection with real transaction semantics.

        The engine is built with isolation_level="AUTOCOMMIT" (see
        etc.infrastructure), under which every statement commits as it runs:
        conn.commit() is a no-op and `with conn.begin():` rolls nothing back.
        Anything that writes more than one row -- a snapshot and its holdings,
        the legacy backfill -- has to override it, or a failure halfway through
        leaves the database holding half a scrape.
        :return: A connection inside a transaction that actually rolls back
        """

        with (
            self.db_engine.connect().execution_options(
                isolation_level="SERIALIZABLE"
            ) as conn,
            conn.begin(),
        ):
            yield conn

    def _table_columns(self, conn: Connection, table: str) -> set[str]:
        """
        The column names of an existing table, or an empty set if there is none.
        :param conn: An open connection
        :param table: The table name
        :return: Column names
        :rtype: set[str]
        """

        return {
            str(object=row[1])
            for row in conn.execute(text(f"PRAGMA table_info({table})"))
        }

    def migrate_legacy_accounts(self) -> bool:
        """
        Move a pre-history ``accounts`` table aside so the new one can be built.

        The old table was named for identity but held one row per account per
        run -- it was a snapshot table wearing the wrong name. Renaming rather
        than dropping keeps every scrape the user has ever taken, and keeps it
        readable if the replay in backfill_legacy_accounts turns out to have
        misread a balance format.

        Idempotent: a fresh database, an already-migrated one and a table that
        is not the legacy shape are all left untouched.
        :return: True when a rename happened
        :rtype: bool
        """

        with self.db_engine.connect() as conn:
            columns: set[str] = self._table_columns(conn=conn, table="accounts")

            if not columns:
                # Fresh database; create_all will make the new shape.
                return False

            if "account_key" in columns:
                # Already the new shape.
                return False

            if "balance" not in columns:
                # Something else entirely. Hands off.
                return False

            if self._table_columns(conn=conn, table=LEGACY_ACCOUNTS_TABLE):
                # A previous run renamed but did not finish the backfill.
                return False

            conn.execute(
                text(f"ALTER TABLE accounts RENAME TO {LEGACY_ACCOUNTS_TABLE}")
            )
            conn.commit()

        return True

    def backfill_legacy_accounts(self, force: bool = False) -> int:
        """
        Replay pre-history balance rows into the new tables.

        Each distinct ``account_name`` becomes one identity, keyed on the very
        string the old save_account_data passed -- which is what stitches a
        user's existing history to everything written after the upgrade. Each
        row becomes a snapshot, with the text balance parsed into a number and
        the original kept beside it.

        ``as_of`` stays NULL: the source's own date was never captured by the
        old schema and cannot be invented now.
        :param force: Replay even when a snapshot table already has rows,
            because the rename just happened in this same open
        :return: The number of snapshots written
        :rtype: int
        """

        with self.db_engine.connect() as conn:
            if not self._table_columns(conn=conn, table=LEGACY_ACCOUNTS_TABLE):
                return 0

            if not force:
                already: Any = conn.execute(
                    self.snapshots_table.select().limit(1)
                ).fetchone()

                if already is not None:
                    return 0

            legacy = conn.execute(
                text(
                    "SELECT account_name, balance, last_updated "
                    f"FROM {LEGACY_ACCOUNTS_TABLE} ORDER BY id"
                )
            ).fetchall()

        if not legacy:
            return 0

        seen: dict[str, dict[str, str]] = {}
        rows: list[tuple[str, str | None, str]] = []

        for account_name, balance, last_updated in legacy:
            name: str = str(object=account_name or "").strip() or UNKNOWN_ACCOUNT
            stamp: str = str(object=last_updated or "").strip() or _utc_now()

            span: dict[str, str] | None = seen.get(name)
            if span is None:
                seen[name] = {"first": stamp, "last": stamp}
            else:
                span["first"] = min(span["first"], stamp)
                span["last"] = max(span["last"], stamp)

            rows.append((name, balance, stamp))

        with self._write() as conn:
            ids: dict[str, int] = {
                name: self._upsert_account(
                    conn=conn,
                    account=AccountIdentity(account_key=name, display_name=name),
                    timestamp=span["last"],
                    first_seen=span["first"],
                )
                for name, span in seen.items()
            }

            payload: list[dict[str, Any]] = [
                {
                    "account_id": ids[name],
                    "scraped_at": stamp,
                    "as_of": None,
                    "value": to_amount(balance),
                    "currency": to_currency(balance),
                    "raw_value": balance,
                }
                for name, balance, stamp in rows
            ]

            conn.execute(
                sqlite_insert(self.snapshots_table).on_conflict_do_nothing(
                    index_elements=["account_id", "scraped_at"]
                ),
                payload,
            )

        # A migration of thousands of rows that happens in total silence is not
        # something a user should have to discover from a schema dump.
        stonksmith_logger.success(
            msg=(
                f"Migrated {len(payload)} legacy balance row(s) for "
                f"{self.broker} into account_snapshots. The original table is "
                f"kept as {LEGACY_ACCOUNTS_TABLE}."
            )
        )

        return len(payload)

    def migrate_holding_dates(self) -> int:
        """
        Give an existing ``holdings`` table its units_as_of column, and fill it.

        create_all leaves an existing table alone -- it never emits ALTER -- so a
        database written before this column existed does not grow one by being
        opened. It has to be added here, and it has to be added: save_snapshot
        names every column unconditionally, so without this the first write
        against an older file fails outright.

        The backfill moves TSP's unit dates out of ``raw_value``, where they were
        kept before there was anywhere better. Two gates, because ``raw_value``
        means "the value exactly as the source wrote it" for every other broker
        and a money string must never be mistaken for a date: the database has to
        be TSP's, and the text has to actually read as a date. ``$1,234.56`` does
        not, and neither does an empty one.

        Nothing is cleared. ``raw_value`` keeps whatever it held, the same way
        migrate_legacy_accounts renames the old table rather than dropping it: a
        migration that has to guess is a migration that should not also destroy
        the thing it guessed from.

        The column and the backfill go in together, in one transaction. Split
        across two, a crash in between would leave the column added and the dates
        unmoved -- and the column's own presence is what stops this running
        again, so that state would never be revisited. SQLite takes DDL inside a
        transaction, so the two either both land or neither does and the next
        open tries again.

        _write() before ``self.sess`` exists is deliberate and safe: it builds
        its own connection off the engine and never touches the session, which
        __init__ creates after every migration has run.
        :return: The number of dates moved
        :rtype: int
        """

        with self._write() as conn:
            columns: set[str] = self._table_columns(conn=conn, table="holdings")

            if not columns:
                # No holdings table to alter. Hands off.
                return 0

            if "units_as_of" in columns:
                # Fresh from create_all, or already migrated.
                return 0

            conn.execute(text("ALTER TABLE holdings ADD COLUMN units_as_of TEXT"))

            if self.broker != "tsp":
                return 0

            stranded: Sequence[Any] = conn.execute(
                text(
                    "SELECT id, raw_value FROM holdings "
                    "WHERE raw_value IS NOT NULL AND raw_value != ''"
                )
            ).fetchall()

            # to_iso_date rather than a strict fromisoformat, because it is what
            # every other as-of in the project is read through and it normalises
            # a date TSP stored the way a user typed it. Its leniency is not a
            # risk here: it returns None for "$1,234.56", "--" and "50", which
            # is what raw_value holds for every broker that is not this one.
            moved: list[dict[str, Any]] = [
                {"holding_id": holding_id, "when": dated}
                for holding_id, raw in stranded
                if (dated := to_iso_date(raw))
            ]

            if not moved:
                return 0

            conn.execute(
                text("UPDATE holdings SET units_as_of = :when WHERE id = :holding_id"),
                moved,
            )

        # Said out loud rather than returned into silence, the way the legacy
        # backfill reports. A date that moves between columns without anyone
        # being told is indistinguishable from one that was invented. Silent when
        # nothing moved: an empty column is not news.
        stonksmith_logger.success(
            msg=(
                f"Moved {len(moved)} unit date(s) for {self.broker} out of "
                "raw_value into units_as_of. The original text is kept."
            )
        )

        return len(moved)

    def migrate_plaintext_secrets(self) -> int:
        """
        Move any legacy plaintext passwords into the OS keyring.

        Databases created before the keyring migration have a ``password``
        column. Each non-empty value is written to the keyring, the row gets a
        ``keyring_key``, and the plaintext is cleared in place.
        :return: The number of secrets migrated
        """

        migrated = 0

        with self.db_engine.connect() as conn:
            columns: set[str] = self._table_columns(conn=conn, table="credentials")

            if "password" not in columns:
                return 0

            if "keyring_key" not in columns:
                conn.execute(
                    text("ALTER TABLE credentials ADD COLUMN keyring_key TEXT")
                )

            legacy = conn.execute(
                text(
                    "SELECT id, username, password FROM credentials "
                    "WHERE password IS NOT NULL AND password != ''"
                )
            ).fetchall()

            for cred_id, username, secret in legacy:
                key: str = keyring_key(broker=self.broker, username=username)
                set_secret(key=key, secret=secret)
                conn.execute(
                    text(
                        "UPDATE credentials SET keyring_key = :key, password = NULL "
                        "WHERE id = :cred_id"
                    ),
                    {"key": key, "cred_id": cred_id},
                )
                migrated += 1

            conn.commit()

        return migrated

    def add_credential(
        self,
        username: str,
        secret: str,
        cred_type: str = "plaintext",
        source: str = "manual",
    ) -> str:
        """
        Store a credential: the secret in the keyring, the reference in the DB.
        :param username: Account username
        :param secret: The password/secret to store
        :param cred_type: Credential type, currently only "plaintext"
        :param source: Where the credential came from
        :return: The keyring key the secret was stored under
        """

        key: str = keyring_key(broker=self.broker, username=username)
        set_secret(key=key, secret=secret)

        ins: Insert = self.creds_table.insert().values(
            username=username,
            keyring_key=key,
            type=cred_type,
            pillaged_from=source,
        )

        with self.db_engine.connect() as conn:
            conn.execute(statement=ins)
            conn.commit()

        return key

    def delete_credential(self, cred_id: int) -> bool:
        """
        Remove a credential row and its keyring entry.
        :param cred_id: The credentials.id to remove
        :return: True if a row was deleted
        """

        c = self.creds_table.c

        with self.db_engine.connect() as conn:
            row = conn.execute(
                self.creds_table.select().where(c.id == cred_id)
            ).fetchone()

            if row is None:
                return False

            key: str | None = row.keyring_key
            if key:
                delete_secret(key=key)

            conn.execute(self.creds_table.delete().where(c.id == cred_id))
            conn.commit()

        return True

    def get_credential_refs(
        self, filter_term: str | None = None
    ) -> list[tuple[str, ...]]:
        """
        List credentials WITHOUT resolving secrets. Safe for display and export.
        :param filter_term: Optional credentials.id to filter on
        :return: Rows of (id, username, keyring_key, type, source)
        :rtype: list[tuple[str, ...]]
        """

        c = self.creds_table.c

        query = self.sess.query(
            c.id,
            c.username,
            c.keyring_key,
            c.type,
            c.pillaged_from,
        )

        if filter_term:
            query = query.filter(c.id == filter_term)

        return [tuple(row) for row in query.all()]

    def get_credentials(self, filter_term: str | None = None) -> list[tuple[str, ...]]:
        """
        List credentials with secrets resolved from the keyring.

        Position 2 of each tuple is the secret, matching what
        Connection.query_db_creds unpacks.
        :param filter_term: Optional credentials.id to filter on
        :return: Rows of (id, username, secret, type, source)
        :rtype: list[tuple[str, ...]]
        """

        resolved: list[tuple[str, ...]] = []

        for cred_id, username, key, cred_type, source in self.get_credential_refs(
            filter_term=filter_term
        ):
            secret: str | None = get_secret(key=key)
            resolved.append((cred_id, username, secret or "", cred_type, source))

        return resolved

    def _upsert_account(
        self,
        conn: Connection,
        account: AccountIdentity,
        timestamp: str,
        first_seen: str | None = None,
    ) -> int:
        """
        Find or create an account identity, refreshing what the source now says.

        Everything except the key is updated on conflict, so metadata that only
        a later run learns -- a brokerage name, an external id, a beneficiary --
        backfills onto identities the legacy migration created with nothing but
        a name. COALESCE keeps a previously-known value rather than letting a
        source that has gone quiet blank it out.
        :param conn: An open connection inside a transaction
        :param account: The identity to record
        :param timestamp: This run's timestamp, recorded as last_seen
        :param first_seen: Overrides first_seen on insert, for the backfill
        :return: The accounts.id
        :rtype: int
        """

        table = self.accounts_table
        key: str = account.account_key.strip() or UNKNOWN_ACCOUNT

        stmt = sqlite_insert(table).values(
            broker=self.broker,
            source=account.source or "",
            account_key=key,
            external_id=account.external_id,
            display_name=account.display_name.strip() or key,
            beneficiary=account.beneficiary,
            kind=account.kind,
            currency=account.currency,
            first_seen=first_seen or timestamp,
            last_seen=timestamp,
        )

        stmt = stmt.on_conflict_do_update(
            index_elements=["broker", "account_key"],
            set_={
                "source": stmt.excluded.source,
                "display_name": stmt.excluded.display_name,
                "external_id": _keep_known(
                    stmt.excluded.external_id, table.c.external_id
                ),
                "beneficiary": _keep_known(
                    stmt.excluded.beneficiary, table.c.beneficiary
                ),
                "kind": _keep_known(stmt.excluded.kind, table.c.kind),
                "currency": _keep_known(stmt.excluded.currency, table.c.currency),
                "last_seen": stmt.excluded.last_seen,
            },
        ).returning(table.c.id)

        account_id: Any = conn.execute(statement=stmt).scalar_one()

        return int(account_id)

    def save_snapshot(
        self,
        account: AccountIdentity,
        scraped_at: str,
        value: float | None,
        currency: str = "USD",
        as_of: str | None = None,
        raw_value: str | None = None,
        holdings: Sequence[Holding] = (),
        transactions: Sequence[Transaction] = (),
    ) -> int:
        """
        Write one account's entire run: identity, value, positions, movements.

        All of it in one transaction. A snapshot holding half its positions is
        worse than no snapshot at all, because nothing downstream can tell the
        difference between "this account holds three funds" and "the scrape died
        after three funds".

        Re-running the same scrape is a no-op rather than a duplicate: the
        snapshot is keyed on (account, scraped_at), holdings are replaced
        wholesale, and transactions are keyed so an overlapping window
        contributes only what is new.
        :param account: Who the account is
        :param scraped_at: This run's UTC timestamp
        :param value: The balance as a number, or None if it could not be read
        :param currency: ISO currency code
        :param as_of: The date the source says the value is for
        :param raw_value: The balance exactly as the source printed it
        :param holdings: Positions behind this value, in source order
        :param transactions: Movements to record against the account
        :return: The account_snapshots.id
        :rtype: int
        """

        with self._write() as conn:
            account_id: int = self._upsert_account(
                conn=conn, account=account, timestamp=scraped_at
            )

            snapshot = sqlite_insert(self.snapshots_table).values(
                account_id=account_id,
                scraped_at=scraped_at,
                as_of=as_of,
                value=value,
                currency=currency or "USD",
                raw_value=raw_value,
            )
            snapshot = snapshot.on_conflict_do_update(
                index_elements=["account_id", "scraped_at"],
                set_={
                    "as_of": snapshot.excluded.as_of,
                    "value": snapshot.excluded.value,
                    "currency": snapshot.excluded.currency,
                    "raw_value": snapshot.excluded.raw_value,
                },
            ).returning(self.snapshots_table.c.id)

            snapshot_id = int(conn.execute(statement=snapshot).scalar_one())

            # Full replace. A re-run that found fewer positions must not leave
            # the ones it no longer sees lying around looking current.
            conn.execute(
                self.holdings_table.delete().where(
                    self.holdings_table.c.snapshot_id == snapshot_id
                )
            )

            if holdings:
                conn.execute(
                    self.holdings_table.insert(),
                    [
                        {
                            "snapshot_id": snapshot_id,
                            "position": index,
                            "symbol": holding.symbol,
                            "fund_code": holding.fund_code,
                            "name": holding.name,
                            "units": holding.units,
                            "price": holding.price,
                            "value": holding.value,
                            "principal": holding.principal,
                            "earnings": holding.earnings,
                            "cost_basis": holding.cost_basis,
                            "currency": holding.currency or "USD",
                            "raw_value": holding.raw_value,
                            "units_as_of": holding.units_as_of,
                        }
                        for index, holding in enumerate(holdings)
                    ],
                )

            if transactions:
                self._insert_transactions(
                    conn=conn,
                    account_id=account_id,
                    rows=transactions,
                    first_seen=scraped_at,
                )

        return snapshot_id

    def _insert_transactions(
        self,
        conn: Connection,
        account_id: int,
        rows: Sequence[Transaction],
        first_seen: str,
    ) -> None:
        """
        Insert movements, skipping any already recorded.
        :param conn: An open connection inside a transaction
        :param account_id: The account they belong to
        :param rows: The movements
        :param first_seen: This run's timestamp
        """

        keys: list[str] = natural_keys(rows=rows)

        conn.execute(
            sqlite_insert(self.transactions_table).on_conflict_do_nothing(
                index_elements=["account_id", "natural_key"]
            ),
            [
                {
                    "account_id": account_id,
                    "external_id": row.external_id,
                    "processed_on": row.processed_on or "",
                    "traded_on": row.traded_on or "",
                    "tx_type": row.tx_type or "",
                    "symbol": row.symbol,
                    "description": row.description,
                    "units": row.units,
                    "price": row.price,
                    "value": row.value,
                    "currency": row.currency or "USD",
                    "natural_key": key,
                    "first_seen": first_seen,
                    "raw": row.raw,
                }
                for row, key in zip(rows, keys, strict=True)
            ],
        )

    def save_transactions(
        self, account: AccountIdentity, timestamp: str, rows: Sequence[Transaction]
    ) -> int:
        """
        Record movements against an account without writing a snapshot.
        :param account: Who the account is
        :param timestamp: This run's UTC timestamp
        :param rows: The movements
        :return: The number of rows now stored for this account
        :rtype: int
        """

        if not rows:
            return 0

        with self._write() as conn:
            account_id: int = self._upsert_account(
                conn=conn, account=account, timestamp=timestamp
            )
            self._insert_transactions(
                conn=conn, account_id=account_id, rows=rows, first_seen=timestamp
            )

            stored: Any = conn.execute(
                text(
                    "SELECT COUNT(*) FROM transactions WHERE account_id = :account_id"
                ),
                {"account_id": account_id},
            ).scalar_one()

        return int(stored)

    def save_account_data(
        self, account_name: str | None, balance: str | None, timestamp: str
    ) -> None:
        """
        Record a point-in-time account balance.

        Kept for modules written against the pre-history schema, including any
        under ~/.stonksmith/modules. Their data lands in the new tables all the
        same, because the identity key is exactly the ``account_name`` string
        this has always been passed.
        :param account_name: Human-readable account name
        :param balance: Balance as scraped, kept as text
        :param timestamp: UTC timestamp string
        """

        name: str = str(object=account_name or "").strip() or UNKNOWN_ACCOUNT

        self.save_snapshot(
            account=AccountIdentity(account_key=name, display_name=name),
            scraped_at=timestamp,
            value=to_amount(balance),
            currency=to_currency(balance),
            raw_value=balance,
        )

    def get_account_data(self) -> list[tuple[str, ...]]:
        """
        List saved account snapshots, newest last.

        The shape predates account history and is kept verbatim, so navigators
        and any third-party caller see no change.
        :return: Rows of (id, account_name, balance, last_updated)
        :rtype: list[tuple[str, ...]]
        """

        rows = self._select(
            "SELECT s.id, a.account_key, s.raw_value, s.value, s.currency, "
            "s.scraped_at FROM account_snapshots s "
            "JOIN accounts a ON a.id = s.account_id "
            "ORDER BY s.scraped_at, s.id"
        )

        return [
            (
                row[0],
                row[1],
                # The text the source printed, when there is any. A migrated row
                # whose balance could not be parsed still has its original
                # string; a row written from a number renders one.
                row[2] if row[2] is not None else format_amount(row[3], row[4]),
                row[5],
            )
            for row in rows
        ]

    def _select(
        self, query: str, params: Mapping[str, Any] | None = None
    ) -> list[tuple[Any, ...]]:
        """
        Run a read query and return plain tuples.
        :param query: The SQL
        :param params: Bound parameters
        :return: Rows
        :rtype: list[tuple[Any, ...]]
        """

        with self.db_engine.connect() as conn:
            return [tuple(row) for row in conn.execute(text(query), dict(params or {}))]

    def get_accounts(self) -> list[tuple[Any, ...]]:
        """
        List account identities.
        :return: Rows of (id, source, display_name, beneficiary, kind, last_seen)
        :rtype: list[tuple[Any, ...]]
        """

        return self._select(
            "SELECT id, source, display_name, beneficiary, kind, last_seen "
            "FROM accounts ORDER BY source, display_name"
        )

    def get_snapshots(
        self, account_id: int | None = None, limit: int | None = 100
    ) -> list[tuple[Any, ...]]:
        """
        List account values over time, newest first.
        :param account_id: Restrict to one account
        :param limit: How many rows at most, or None for all of them
        :return: Rows of (id, account, as_of, scraped_at, value, currency)
        :rtype: list[tuple[Any, ...]]
        """

        where: str = "WHERE s.account_id = :account_id" if account_id else ""

        return self._select(
            *_bounded(
                query=(
                    "SELECT s.id, a.display_name, s.as_of, s.scraped_at, s.value, "
                    "s.currency FROM account_snapshots s "
                    f"JOIN accounts a ON a.id = s.account_id {where} "
                    "ORDER BY s.scraped_at DESC, s.id DESC"
                ),
                params={"account_id": account_id},
                limit=limit,
            )
        )

    def delete_snapshot(self, snapshot_id: int) -> bool:
        """
        Remove one mark, and the holdings recorded under it.

        A mark can be wrong in a way no re-run corrects. A placeholder typed
        into a command line, or a real number computed from mismatched inputs,
        lands in history as an ordinary row and stays there -- the next sync
        adds a snapshot beside it rather than replacing it, because snapshots
        are the record of what was observed when, not a current-value cache.
        Leaving one in place puts a wrong number in every chart drawn from the
        table.

        Deliberately one row at a time, by id read off ``show snapshots``.
        Anything broader -- by account, by date range -- would delete history
        that is merely old rather than wrong, and there is no undo here.

        The account is left alone. It is the thing the next run reuses, and
        removing it would turn a bad mark into a duplicate account.

        Holdings go with it through ON DELETE CASCADE, which SQLite enforces
        only because create_db_engine() turns foreign keys on.
        :param snapshot_id: The account_snapshots.id to remove
        :return: True if a row was deleted, False if there was no such id
        :rtype: bool
        """

        c = self.snapshots_table.c

        with self.db_engine.connect() as conn:
            result = conn.execute(
                self.snapshots_table.delete().where(c.id == snapshot_id)
            )
            conn.commit()

        return bool(result.rowcount)

    def get_latest_snapshots(self) -> list[tuple[Any, ...]]:
        """
        The newest value for each account, one row apiece.

        This is what a dashboard shows: current state, not history.
        :return: Rows of (snapshot_id, source, display_name, value, currency,
            as_of, scraped_at, kind)
        :rtype: list[tuple[Any, ...]]
        """

        return self._select(
            "SELECT s.id, a.source, a.display_name, s.value, s.currency, "
            "s.as_of, s.scraped_at, a.kind FROM account_snapshots s "
            "JOIN accounts a ON a.id = s.account_id "
            "WHERE s.id = ("
            "  SELECT id FROM account_snapshots "
            "  WHERE account_id = a.id ORDER BY scraped_at DESC, id DESC LIMIT 1"
            ") ORDER BY a.source, a.display_name"
        )

    def get_holdings(
        self, snapshot_id: int | None = None, limit: int | None = 500
    ) -> list[tuple[Any, ...]]:
        """
        List positions. With no snapshot id, the positions behind each account's
        newest snapshot -- which is what a dashboard wants.
        :param snapshot_id: Restrict to one snapshot
        :param limit: How many rows at most, or None for all of them
        :return: Rows of (account, symbol_or_fund, name, units, price, value,
            principal, earnings, cost_basis, currency, units_as_of)
        :rtype: list[tuple[Any, ...]]
        """

        where: str = (
            "WHERE h.snapshot_id = :snapshot_id"
            if snapshot_id
            else "WHERE s.id = ("
            "  SELECT id FROM account_snapshots "
            "  WHERE account_id = a.id ORDER BY scraped_at DESC, id DESC LIMIT 1"
            ")"
        )

        return self._select(
            *_bounded(
                query=(
                    "SELECT a.display_name, COALESCE(h.symbol, h.fund_code), h.name, "
                    "h.units, h.price, h.value, h.principal, h.earnings, "
                    "h.cost_basis, h.currency, h.units_as_of FROM holdings h "
                    "JOIN account_snapshots s ON s.id = h.snapshot_id "
                    f"JOIN accounts a ON a.id = s.account_id {where} "
                    "ORDER BY a.display_name, h.position"
                ),
                params={"snapshot_id": snapshot_id},
                limit=limit,
            )
        )

    def get_current_accounts(self) -> list[tuple[Any, ...]]:
        """
        Every account at its newest snapshot, carrying its identity.

        The read path behind the canonical row shape (see etc.portfolio). It
        exists beside get_latest_snapshots rather than replacing it because that
        one is unpacked positionally by two modules and the shell, so its shape
        is a published contract -- and it returns the display name only, which
        is explicitly *not* identity (see records.AccountIdentity). A view that
        joins across brokers needs the key.

        Deliberately unlimited. Every other reader here takes a ``limit``
        because it backs a shell command a human is scrolling; this one backs a
        total, and a total that silently drops its five-hundred-and-first row is
        worse than no total.
        :return: Rows of (account_key, source, display_name, beneficiary, kind,
            value, currency, as_of, scraped_at), one per account
        :rtype: list[tuple[Any, ...]]
        """

        return self._select(
            "SELECT a.account_key, a.source, a.display_name, a.beneficiary, "
            "a.kind, s.value, s.currency, s.as_of, s.scraped_at "
            "FROM account_snapshots s JOIN accounts a ON a.id = s.account_id "
            "WHERE s.id = ("
            "  SELECT id FROM account_snapshots "
            "  WHERE account_id = a.id ORDER BY scraped_at DESC, id DESC LIMIT 1"
            ") ORDER BY a.source, a.display_name"
        )

    def get_current_holdings(self) -> list[tuple[Any, ...]]:
        """
        The positions behind every account's newest snapshot.

        Keyed by ``account_key`` so a caller can join these to
        get_current_accounts without going through the display name, and
        carrying ``symbol`` and ``fund_code`` separately rather than coalesced,
        because which one a source fills says something about the source.

        One query for the whole database rather than one per account, and
        unlimited for the same reason as get_current_accounts.
        :return: Rows of (account_key, position, symbol, fund_code, name, units,
            price, value, principal, earnings, cost_basis, currency, as_of,
            scraped_at, units_as_of), in source order within each account
        :rtype: list[tuple[Any, ...]]
        """

        return self._select(
            "SELECT a.account_key, h.position, h.symbol, h.fund_code, h.name, "
            "h.units, h.price, h.value, h.principal, h.earnings, h.cost_basis, "
            "h.currency, s.as_of, s.scraped_at, h.units_as_of FROM holdings h "
            "JOIN account_snapshots s ON s.id = h.snapshot_id "
            "JOIN accounts a ON a.id = s.account_id "
            "WHERE s.id = ("
            "  SELECT id FROM account_snapshots "
            "  WHERE account_id = a.id ORDER BY scraped_at DESC, id DESC LIMIT 1"
            ") ORDER BY a.source, a.display_name, h.position"
        )

    def get_current_transactions(self) -> list[tuple[Any, ...]]:
        """
        Every movement this database holds, keyed the way the other two are.

        The third read path behind the canonical row shape (see etc.portfolio),
        beside get_current_accounts and get_current_holdings. It carries
        ``account_key`` rather than the display name for the same reason they
        do: a view spanning several brokers joins on identity, and a display
        name is explicitly not identity.

        **Deliberately unlimited**, and not for the reason the other two are.
        Theirs is that a total which silently drops its five-hundred-and-first
        row is worse than no total; nothing totals movements. The reason here is
        that a log is the one thing this database holds that grows without
        bound, so a limit is the difference between a history and the newest
        page of one -- shown with no indication that there is more. That is why
        get_transactions below cannot back a sheet: its ``limit=500`` would
        report the newest five hundred movements as though they were all of
        them.

        No newest-snapshot subquery, unlike the other two. Those restrict to one
        snapshot because an account has a value per run and only the last is
        current. A movement is not observed per run -- ``transactions.account_id``
        points at ``accounts`` rather than at ``account_snapshots``, and the
        natural key means re-scraping an overlapping window contributes only what
        is new. Every stored row is current, so there is nothing to scope to.

        Ordered by account and then newest-inserted first, deliberately *not* by
        ``processed_on``. That column holds the date as the source wrote it, and
        the sources disagree: SnapTrade normalizes to ISO while the 529 scraper
        stores "12/30/2025", which sorts above "01/15/2026". Ordering on it here
        would look sorted and be wrong. The dates are compared where they are
        normalized, in etc.portfolio.
        :return: Rows of (account_key, tx_type, symbol, description, units,
            price, value, currency, processed_on, traded_on, first_seen,
            external_id)
        :rtype: list[tuple[Any, ...]]
        """

        return self._select(
            "SELECT a.account_key, t.tx_type, t.symbol, t.description, t.units, "
            "t.price, t.value, t.currency, t.processed_on, t.traded_on, "
            "t.first_seen, t.external_id FROM transactions t "
            "JOIN accounts a ON a.id = t.account_id "
            "ORDER BY a.source, a.display_name, t.id DESC"
        )

    def get_transactions(
        self, account_id: int | None = None, limit: int | None = 500
    ) -> list[tuple[Any, ...]]:
        """
        List movements, newest first.

        Backs ``show transactions`` and ``export transactions`` in the shell.
        The default cap is for the first of those, where a human is scrolling;
        the second passes None, because a CSV that stops at five hundred rows
        cannot tell anyone that it did. Anything rendering a whole history to a
        sheet wants get_current_transactions above instead, which carries the
        account key rather than the display name.
        :param account_id: Restrict to one account
        :param limit: How many rows at most, or None for all of them
        :return: Rows of (id, account, processed_on, traded_on, tx_type, symbol,
            units, price, value, currency)
        :rtype: list[tuple[Any, ...]]
        """

        where: str = "WHERE t.account_id = :account_id" if account_id else ""

        return self._select(
            *_bounded(
                query=(
                    "SELECT t.id, a.display_name, t.processed_on, t.traded_on, "
                    "t.tx_type, t.symbol, t.units, t.price, t.value, t.currency "
                    "FROM transactions t "
                    f"JOIN accounts a ON a.id = t.account_id {where} "
                    "ORDER BY t.processed_on DESC, t.id DESC"
                ),
                params={"account_id": account_id},
                limit=limit,
            )
        )

    def get_daily_change(self, limit: int | None = 100) -> list[tuple[Any, ...]]:
        """
        The move between each snapshot and the one before it.

        This is the whole point of storing a number rather than "$1,234.56":
        the daily +/- is not a field any broker reports, it is a difference
        between two consecutive snapshots of the same account.
        :param limit: How many rows at most, or None for all of them
        :return: Rows of (account, as_of, scraped_at, value, previous, delta,
            currency), newest first
        :rtype: list[tuple[Any, ...]]
        """

        return self._select(
            *_bounded(
                query=(
                    "SELECT display_name, as_of, scraped_at, value, previous, "
                    "CASE WHEN previous IS NULL OR value IS NULL THEN NULL "
                    "     ELSE value - previous END, currency "
                    "FROM ("
                    "  SELECT a.display_name, s.as_of, s.scraped_at, s.value, "
                    "    s.currency,"
                    "    LAG(s.value) OVER ("
                    "      PARTITION BY s.account_id ORDER BY s.scraped_at, s.id"
                    "    ) AS previous"
                    "  FROM account_snapshots s "
                    "  JOIN accounts a ON a.id = s.account_id"
                    ") ORDER BY scraped_at DESC"
                ),
                params={},
                limit=limit,
            )
        )

    def shutdown_db(self) -> None:
        """
        Close the session.
        """

        self.sess.close()


def _utc_now() -> str:
    """
    The current UTC time in the format every module stamps its runs with.
    :return: "YYYY-MM-DD HH:MM:SS"
    :rtype: str
    """

    return datetime.datetime.now(tz=datetime.UTC).strftime(format="%Y-%m-%d %H:%M:%S")


def _bounded(
    query: str, params: dict[str, Any], limit: int | None
) -> tuple[str, dict[str, Any]]:
    """
    Cap a read, or deliberately leave it uncapped.

    Every reader below that a human scrolls takes a ``limit``, and every one of
    them is also reachable from ``export``, which writes a file. Those want
    different answers: a screenful is a courtesy, while a CSV that stops at five
    hundred rows and says nothing is the failure this project keeps finding --
    a result that looks complete with the missing part invisible. So the cap
    became optional rather than the readers becoming two sets of readers.

    The ``limit`` value goes in with the clause it belongs to and stays out when
    there is no clause. Nothing forces that: the readers here already pass
    ``account_id`` on reads whose WHERE clause is empty, and an unreferenced key
    is carried without complaint. It is kept in step because a params dict that
    matches its query is one fewer thing to reconcile when reading either.
    :param query: The SQL, without a LIMIT clause
    :param params: The bound parameters it already has
    :param limit: How many rows at most, or None for all of them
    :return: The SQL and parameters to run
    :rtype: tuple[str, dict[str, Any]]
    """

    if limit is None:
        return query, params

    return f"{query} LIMIT :limit", {**params, "limit": limit}


def _keep_known(incoming: Any, existing: Any) -> Any:
    """
    Prefer what this run learned, but never blank out what an earlier one knew.

    Sources drop fields. SnapTrade can stop returning an account's category, a
    529 page can render without the beneficiary block. Overwriting a known value
    with the NULL that produced would lose information the database already had.
    :param incoming: The value from this run
    :param existing: The column holding what is already stored
    :return: A COALESCE expression
    """

    return func.coalesce(incoming, existing)


def natural_keys(rows: Sequence[Transaction]) -> list[str]:
    """
    Derive a stable, per-account-unique key for each movement.

    A scraped transaction table has no ids, so the key is the row's own content.
    That alone is not enough: two identical $50 contributions on the same day are
    indistinguishable field by field, and collapsing them into one row loses half
    the money permanently. So repeats within a batch are numbered -- the first
    "#0", the second "#1" -- which re-scraping the same page reproduces exactly,
    while genuinely new rows get keys nothing has yet.

    The amount comes from the source's own text where there is any, so improving
    how a value is parsed does not make old rows look new. The dates, type and
    quantities are normalized -- a change to how *those* are read does shift the
    key, which is why the raw text is stored alongside every row and the key is
    kept readable rather than hashed. When a source changes its date format, a
    key you can read is worth more than sixteen saved bytes.

    The caveat this rests on: a source's same-day duplicates always appear
    together in its window. Every broker seen so far returns transactions in date
    order, so they do.
    :param rows: Movements in the order the source returned them
    :return: One key per row, in the same order
    :rtype: list[str]
    """

    counts: dict[str, int] = {}
    keys: list[str] = []

    for row in rows:
        if row.external_id:
            # The source has its own identifier. Nothing to derive.
            keys.append(f"id:{row.external_id}")
            continue

        body: str = "|".join(
            " ".join(str(object=part or "").split())
            for part in (
                row.processed_on,
                row.traded_on,
                row.tx_type,
                row.symbol,
                row.units,
                row.price,
                row.raw if row.raw is not None else row.value,
            )
        )

        ordinal: int = counts.get(body, 0)
        counts[body] = ordinal + 1
        keys.append(f"{body}#{ordinal}")

    return keys
