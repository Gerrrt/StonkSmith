"""SnapTrade broker package.

``broker.py`` holds the API client; ``db_navigator.py`` and ``broker_args.py``
are loaded by BrokerLoader by path. There is no ``database.py``:
BrokerLoader falls back to ``etc.broker_db.BrokerDatabase``, which is all the
deleted one ever was.

The inherited ``credentials`` table goes unused here. SnapTrade authenticates
with a client id from the config file and a consumer key from the OS keyring,
not with a username and password -- see ``broker.py``. That is why ``add creds``
against this broker is not the setup step it looks like; ``db_navigator.py``
overrides the shell to say so, which is why this is the one broker that still
has one.

``SnapTradeBroker`` is exported lazily. ModuleLoader metadata-scans every file
in ``modules/`` on every run of every broker, and the SnapTrade SDK costs roughly
0.4s and 500 modules to import, so an eager export here would tax every
invocation of every broker, including runs that never touch SnapTrade.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stonksmith.brokers.snaptrade.broker import SnapTradeBroker

__all__ = ["SnapTradeBroker"]


def __getattr__(name: str) -> Any:
    """Resolve ``SnapTradeBroker`` on first access (PEP 562)."""

    if name == "SnapTradeBroker":
        from stonksmith.brokers.snaptrade.broker import (
            SnapTradeBroker as _SnapTradeBroker,
        )

        return _SnapTradeBroker

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
