"""Ally Invest broker package.

``broker.py`` holds the login class; ``broker_args.py`` is loaded by
BrokerLoader by path. There is no ``database.py`` or ``db_navigator.py``:
BrokerLoader falls back to ``etc.broker_db.BrokerDatabase`` and
``etc.broker_nav.BrokerNavigator``, which is all the deleted ones ever were.

``Ally`` is exported lazily, and since 1.0 it is the only broker for which that
still buys anything: ``broker.py`` imports Playwright, and Ally is now the sole
browser-backed broker. ModuleLoader metadata-scans every file in ``modules/`` on
every run of every broker, so an eager export here would drag the whole browser
transport into a SnapTrade run that never opens one.
``tests/test_broker_discovery.py`` pins that, and probes this package to do it.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stonksmith.brokers.ally.broker import Ally

__all__ = ["Ally"]


def __getattr__(name: str) -> Any:
    """Resolve ``Ally`` on first access (PEP 562)."""

    if name == "Ally":
        from stonksmith.brokers.ally.broker import Ally as _Ally

        return _Ally

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
