"""
Defines the database interface for the Schwab529Plan broker module.
"""

from sqlalchemy import Column, Engine, Insert, Integer, MetaData, String, Table
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from sqlalchemy.orm.query import RowReturningQuery
from sqlalchemy.sql.base import ReadOnlyColumnCollection


class Database:
    """
    Database interface for the Schwab529Plan broker module.
    """

    def __init__(self, db_engine: Engine) -> None:
        self.db_engine: Engine = db_engine
        self.metadata = MetaData()

        self.creds_table = Table(
            "credentials",
            self.metadata,
            Column("id", Integer, primary_key=True),
            Column("username", String),
            Column("password", String),
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
        session_factory: sessionmaker[Session] = sessionmaker(
            bind=self.db_engine, expire_on_commit=True
        )
        self.sess: Session = scoped_session(session_factory=session_factory)()

    def get_credentials(self, filter_term: str | None = None) -> list[tuple[str, ...]]:
        """
        Custom method for Module
        :param filter_term:
        :type filter_term:
        :return: List of credentials
        :rtype: list[tuple[str, ...]]
        """

        c: ReadOnlyColumnCollection[str, Column[str]] = self.creds_table.c

        query: RowReturningQuery[tuple[str, str, str, str, str]] = self.sess.query(
            c.id,
            c.username,
            c.password,
            c.type,
            c.pillaged_from,
        )

        if filter_term:
            query: RowReturningQuery[tuple[str, str, str, str, str]] = query.filter(
                c.id == filter_term
            )

        return [tuple(row) for row in query.all()]

    def save_account_data(
        self, account_name: str, balance: str, timestamp: str
    ) -> None:
        """
        Custom method for Module
        :param account_name:
        :type account_name:
        :param balance:
        :type balance:
        :param timestamp:
        :type timestamp:
        :return:
        :rtype:
        """

        ins: Insert = self.accounts_table.insert().values(
            account_name=account_name, balance=balance, last_updated=timestamp
        )

        with self.db_engine.connect() as conn:
            conn.execute(statement=ins)
            conn.commit()

    def shutdown_db(self) -> None:
        """
        Shutdown the database connection
        """

        self.sess.close()
