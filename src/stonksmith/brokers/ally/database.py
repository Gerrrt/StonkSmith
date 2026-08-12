"""
Defines the database interface for the Ally Invest broker module.

BrokerLoader imports this file by path and expects a ``Database`` symbol; the
behaviour comes from etc.broker_db.BrokerDatabase.
"""

from etc.broker_db import BrokerDatabase


class Database(BrokerDatabase):
    """
    Database interface for the Ally Invest broker module.
    """

    broker_name = "ally"
