"""Schwab 529 Plan broker package.

``broker.py`` holds the login class. The rest is loaded by BrokerLoader by path:
- `broker_args`: Argument parsing utilities specific to the Schwab 529 Plan broker.
- `database`: Database-related utilities specific to the Schwab 529 Plan broker.
- `db_navigator`: Utilities for navigating the Schwab 529 Plan database.
- `parser`: A module for parsing the Schwab 529 Plan data.
- `saver`: A module for saving the parsed Schwab 529 Plan data to a database.

``Schwab529plan`` is exported lazily, matching brokers/fidelity. This module's own
imports are cheap, but keeping one pattern means a future heavyweight import cannot
quietly add startup cost to every run.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from brokers.schwab529plan.broker import Schwab529plan

__all__ = ["Schwab529plan"]


def __getattr__(name: str) -> Any:
    """Resolve ``Schwab529plan`` on first access (PEP 562)."""

    if name == "Schwab529plan":
        from brokers.schwab529plan.broker import Schwab529plan as _Schwab529plan

        return _Schwab529plan

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
