"""Manual broker package: accounts you can see but cannot scrape.

``broker.py`` holds the connection class and ``broker_args.py`` is loaded by
BrokerLoader by path. There is no ``database.py`` or ``db_navigator.py``:
BrokerLoader falls back to ``etc.broker_db.BrokerDatabase`` and
``etc.broker_nav.BrokerNavigator``, which is what all the bundled brokers do.

``Manual`` is exported lazily, on the reasoning the TSP package records: a
module loader metadata-scans every file in ``modules/`` on every run, so an
eager import here would execute the connection module for every invocation of
the tool including the ones that never touch this broker.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stonksmith.brokers.manual.broker import Manual

__all__ = ["Manual"]


def __getattr__(name: str) -> Any:
    """Resolve ``Manual`` on first access (PEP 562)."""

    if name == "Manual":
        from stonksmith.brokers.manual.broker import Manual as _Manual

        return _Manual

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
