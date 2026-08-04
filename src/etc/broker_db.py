# Copyright (c) 2026 Gerrrt
# Licensed under the MIT License

"""Shared broker database implementation.

Every broker package exposes a ``Database`` class in ``database.py``, which
BrokerLoader imports by file path. The behaviour is identical across brokers, so it
lives here and each broker subclasses it with its own default broker name.

Secrets are never stored in SQLite. The credentials table holds a keyring
reference; the secret itself lives in the OS credential store (see etc.secrets).
"""

from sqlalchemy import (
    Column,
    Engine,
    Insert,
    Integer,
    MetaData,
    String,
    Table,
    text,
)
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from etc.secrets import delete_secret, get_secret, keyring_key, set_secret


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
            Column("account_name", String),
            Column("balance", String),
            Column("last_updated", String),
        )

        self.metadata.create_all(bind=self.db_engine)
        self.migrate_plaintext_secrets()

        session_factory: sessionmaker[Session] = sessionmaker(
            bind=self.db_engine, expire_on_commit=True
        )
        self.sess: Session = scoped_session(session_factory=session_factory)()

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
            columns: set[str] = {
                row[1] for row in conn.execute(text("PRAGMA table_info(credentials)"))
            }

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

    def save_account_data(
        self, account_name: str | None, balance: str | None, timestamp: str
    ) -> None:
        """
        Record a point-in-time account balance.
        :param account_name: Human-readable account name
        :param balance: Balance as scraped, kept as text
        :param timestamp: UTC timestamp string
        """

        ins: Insert = self.accounts_table.insert().values(
            account_name=account_name, balance=balance, last_updated=timestamp
        )

        with self.db_engine.connect() as conn:
            conn.execute(statement=ins)
            conn.commit()

    def get_account_data(self) -> list[tuple[str, ...]]:
        """
        List saved account snapshots, newest last.
        :return: Rows of (id, account_name, balance, last_updated)
        :rtype: list[tuple[str, ...]]
        """

        c = self.accounts_table.c
        query = self.sess.query(c.id, c.account_name, c.balance, c.last_updated)
        return [tuple(row) for row in query.all()]

    def shutdown_db(self) -> None:
        """
        Close the session.
        """

        self.sess.close()
