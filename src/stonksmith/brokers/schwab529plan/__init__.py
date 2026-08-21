"""Schwab 529 Plan broker package.

``broker.py`` holds the login class. The rest is loaded by BrokerLoader by path:
- `broker_args`: Argument parsing utilities specific to the Schwab 529 Plan broker.
- `parser`: A module for parsing the Schwab 529 Plan data.

There is no `database` or `db_navigator` module: BrokerLoader falls back to
`etc.broker_db.BrokerDatabase` and `etc.broker_nav.BrokerNavigator`, which is
all the deleted ones ever were.

``Schwab529plan`` is exported lazily, matching brokers/ally. This module's own
imports are cheap, but keeping one pattern means a future heavyweight import cannot
quietly add startup cost to every run.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stonksmith.brokers.schwab529plan.broker import Schwab529plan

__all__ = ["Schwab529plan"]


def __getattr__(name: str) -> Any:
    """Resolve ``Schwab529plan`` on first access (PEP 562)."""

    if name == "Schwab529plan":
        from stonksmith.brokers.schwab529plan.broker import (
            Schwab529plan as _Schwab529plan,
        )

        return _Schwab529plan

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
