"""SnapTrade broker package.

``broker.py`` holds the API client; ``database.py``, ``db_navigator.py``,
``broker_args.py`` and ``saver.py`` are loaded by BrokerLoader by path.

``SnapTradeBroker`` is exported lazily. ``modules/snaptrade_module.py`` imports
``brokers.snaptrade.saver`` on every run -- ModuleLoader metadata-scans every
file in ``modules/`` -- and the SnapTrade SDK costs roughly 0.4s and 500 modules
to import, so an eager import here would tax every invocation of every broker,
including runs that never touch SnapTrade.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from brokers.snaptrade.broker import SnapTradeBroker

__all__ = ["SnapTradeBroker"]


def __getattr__(name: str) -> Any:
    """Resolve ``SnapTradeBroker`` on first access (PEP 562)."""

    if name == "SnapTradeBroker":
        from brokers.snaptrade.broker import SnapTradeBroker as _SnapTradeBroker

        return _SnapTradeBroker

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
