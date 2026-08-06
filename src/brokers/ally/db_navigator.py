"""
Navigate database entries for Ally Invest.

BrokerLoader imports this file by path and expects a ``DatabaseNavigator``
symbol; the commands come from etc.broker_nav.BrokerNavigator.
"""

from etc.broker_nav import BrokerNavigator


class DatabaseNavigator(BrokerNavigator):
    """
    Navigate database entries for Ally Invest.
    """
