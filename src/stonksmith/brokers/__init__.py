"""
Broker implementations.

Each broker is a subpackage containing ``broker.py`` -- the login class, exported as
``Broker`` -- plus whichever of ``database.py``, ``db_navigator.py``,
``broker_args.py`` and ``parser.py`` it needs. Every bundled broker ships
``broker_args.py``; ``schwab529plan`` is the only one with a ``parser.py`` and
``snaptrade`` the only one with a ``db_navigator.py``, and none ships a
``database.py``.

This file deliberately imports nothing. ``loaders.brokerloader`` finds brokers by
scanning for directories containing ``broker.py`` and loads each file by path, so
importing them here would only add startup cost to every run.

Note that BrokerLoader does not register what it loads in ``sys.modules``: a class
imported from one of these subpackages is a distinct object from the one the loader
returns for the same source file, so ``isinstance`` across that boundary is False.
"""
