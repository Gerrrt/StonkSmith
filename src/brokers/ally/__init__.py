"""Ally Invest broker package.

``broker.py`` holds the login class; ``database.py``, ``db_navigator.py``,
``broker_args.py`` and ``saver.py`` are loaded by BrokerLoader by path.

``Ally`` is exported lazily. ``modules/ally_module.py`` imports
``brokers.ally.saver`` on every run -- ModuleLoader metadata-scans every file in
``modules/`` -- so an eager import here would execute the whole login module on
every invocation, for every broker, including runs that never touch Ally.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from brokers.ally.broker import Ally

__all__ = ["Ally"]


def __getattr__(name: str) -> Any:
    """Resolve ``Ally`` on first access (PEP 562)."""

    if name == "Ally":
        from brokers.ally.broker import Ally as _Ally

        return _Ally

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
