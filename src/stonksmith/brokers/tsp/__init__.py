"""Thrift Savings Plan broker package.

``broker.py`` holds the connection class; ``broker_args.py`` and ``saver.py``
are loaded by BrokerLoader by path. There is no ``database.py`` or
``db_navigator.py``: BrokerLoader falls back to ``etc.broker_db.BrokerDatabase``
and ``etc.broker_nav.BrokerNavigator``, which is all the deleted ones ever were.

``Tsp`` is exported lazily. ``modules/tsp_module.py`` imports
``brokers.tsp.saver`` on every run -- ModuleLoader metadata-scans every file in
``modules/`` -- so an eager import here would execute the whole connection
module on every invocation, for every broker, including runs that never touch
TSP.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stonksmith.brokers.tsp.broker import Tsp

__all__ = ["Tsp"]


def __getattr__(name: str) -> Any:
    """Resolve ``Tsp`` on first access (PEP 562)."""

    if name == "Tsp":
        from stonksmith.brokers.tsp.broker import Tsp as _Tsp

        return _Tsp

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
