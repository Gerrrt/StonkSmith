"""Fidelity broker package.

``broker.py`` holds the login class; ``database.py``, ``db_navigator.py``,
``broker_args.py`` and ``saver.py`` are loaded by BrokerLoader by path.

``Fidelity`` is exported lazily. ``modules/fidelity_module.py`` imports
``brokers.fidelity.saver`` on every run -- ModuleLoader metadata-scans every file in
``modules/`` -- so an eager import here would execute the whole login module on every
invocation, for every broker, including runs that never touch Fidelity.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from brokers.fidelity.broker import Fidelity

__all__ = ["Fidelity"]


def __getattr__(name: str) -> Any:
    """Resolve ``Fidelity`` on first access (PEP 562)."""

    if name == "Fidelity":
        from brokers.fidelity.broker import Fidelity as _Fidelity

        return _Fidelity

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
