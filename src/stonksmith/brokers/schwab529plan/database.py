"""
Defines the database interface for the Schwab529Plan broker module.

BrokerLoader imports this file by path and expects a ``Database`` symbol; the
behaviour comes from etc.broker_db.BrokerDatabase.
"""

from stonksmith.etc.broker_db import BrokerDatabase


class Database(BrokerDatabase):
    """
    Database interface for the Schwab529Plan broker module.
    """

    broker_name = "schwab529plan"
