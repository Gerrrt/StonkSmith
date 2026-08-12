"""
Defines the database interface for the SnapTrade broker module.

BrokerLoader imports this file by path and expects a ``Database`` symbol; the
behaviour comes from etc.broker_db.BrokerDatabase.

The inherited ``credentials`` table goes unused here: SnapTrade authenticates
with a client id from the config file and a consumer key from the OS keyring,
not with a username and password. See brokers/snaptrade/broker.py.
"""

from etc.broker_db import BrokerDatabase


class Database(BrokerDatabase):
    """
    Database interface for the SnapTrade broker module.
    """

    broker_name = "snaptrade"
