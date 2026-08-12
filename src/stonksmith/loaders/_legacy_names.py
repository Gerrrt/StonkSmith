"""
Let a user's own broker or module keep importing the pre-namespace names.

Brokers under ``~/.stonksmith/brokers`` and modules under ``~/.stonksmith/modules``
are the user's files, loaded by path. They were written against the names the
package used to install at the top level -- ``from etc.context import Context`` --
and moving the tree under ``stonksmith/`` breaks every one of them. This aliases
those names back, but only while such a file is being executed, and says so.

Removed at 1.0, together with the two ``with`` blocks that use it and
``tests/test_legacy_import_names.py``.

Three things about the mechanism were measured rather than assumed, because the
obvious version of each is wrong.

**Not ``sys.modules["etc"] = stonksmith.etc``.** That aliases the package but not
its contents: the alias object's ``__path__`` still points at the real directory,
so ``from etc.connection import Connection`` sends the import machinery down that
path and *re-executes* connection.py into a second, distinct module object. Two
``Connection`` classes then exist, ``isinstance`` across the boundary is False,
and ``except etc.exceptions.Whatever`` cannot catch what StonkSmith raises. A
finder that hands back the module already imported has none of that problem.

**``sys.meta_path.insert(0, ...)``, never append.** Appended, the finder is asked
about ``etc`` but not about ``etc.connection`` -- ``PathFinder`` answers that one
first, off the aliased parent's ``__path__``, builds a second module object, and
the machinery then assigns it onto the parent with ``setattr``. The parent *is*
``stonksmith.etc``, so the real package's attribute is overwritten and stays
overwritten after this context manager exits.

**``__spec__`` has to be put back.** ``module_from_spec()`` stamps the alias's spec
onto whatever ``create_module()`` returns, so importing ``etc.connection`` leaves
``stonksmith.etc.connection.__spec__.name`` reading ``"etc.connection"`` -- for the
rest of the process, long after the alias is gone. ``exec_module()`` is the first
hook to run after that assignment, which is why the restore lives there.

The warning is emitted under ``suppress(DeprecationWarning)`` for a reason that is
not stylistic. ``BrokerLoader.load_broker`` wraps ``exec_module()`` in a blanket
``except Exception``; under ``-W error``, or the suite's own
``filterwarnings = ["error"]``, the warning *is* an exception, so it would be
caught and reported as "failed to load and is unavailable this run". A shim that
makes the thing it exists to rescue disappear is worse than no shim. Suppressed at
the emit site the warning still records normally under
``catch_warnings(record=True)``, which is how the tests see it.

It is also logged, because ``DeprecationWarning`` is ignored by Python's default
filters outside ``__main__`` and a real user would otherwise never learn that
their broker is running on borrowed time.

What this does not cover: an import inside a function body. The alias is installed
only for the duration of ``exec_module()``, so a ``import etc.config`` sitting in
``on_login()`` runs long after it is gone and raises ``ModuleNotFoundError``. A
top-level ``import etc.config`` followed by ``etc.config.get_workspace()`` at run
time is fine -- the module globals hold the real object, and ``etc`` *is*
``stonksmith.etc``. Covering the function-local case would mean leaving the alias
installed for the life of the process, which is exactly the ambient top-level
names this rename removed.
"""

import importlib
import sys
import threading
import warnings
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
from importlib.util import spec_from_loader
from types import ModuleType
from typing import Final

from stonksmith.etc.logger import stonksmith_logger

#: The names this package used to install at the top level of site-packages.
#:
#: ``main`` is deliberately absent. It is the most collision-prone name of the six
#: -- a stray main.py in the working directory is on sys.path for any `python -c`
#: -- and a finder sitting at meta_path[0] would hijack `import main` to
#: StonkSmith's CLI entry point for as long as a user file is executing. That is
#: the collision class the rename exists to remove, and no user broker or module
#: has any reason to import the entry point.
LEGACY_ROOTS: Final[frozenset[str]] = frozenset(
    {"etc", "helpers", "loaders", "modules", "brokers"}
)

_PACKAGE: Final[str] = "stonksmith"

#: Guards _depth and the installed finder. All loading happens on the main thread
#: today, before etc.runner builds its pool, but a module's on_login() runs in a
#: worker and nothing stops one from loading another file.
_lock: Final[threading.RLock] = threading.RLock()

_depth: int = 0
_finder: _AliasFinder | None = None


def _real_name(fullname: str) -> str:
    """``etc.connection`` -> ``stonksmith.etc.connection``."""

    return f"{_PACKAGE}.{fullname}"


def _is_legacy(fullname: str) -> bool:
    return fullname.partition(".")[0] in LEGACY_ROOTS


class _AliasLoader(Loader):
    """Hands back a module that is already imported, under a second name."""

    def __init__(self, module: ModuleType, spec: ModuleSpec | None) -> None:
        self._module: ModuleType = module
        self._spec: ModuleSpec | None = spec

    def create_module(self, spec: ModuleSpec) -> ModuleType:
        return self._module

    def exec_module(self, module: ModuleType) -> None:
        # Nothing to execute -- the module ran when it was first imported under
        # its real name. What this has to undo is module_from_spec(), which has
        # just overwritten the real package's __spec__ with the alias's. Without
        # this line stonksmith.etc.connection.__spec__.name reads
        # "etc.connection" for the rest of the process.
        module.__spec__ = self._spec


class _AliasFinder(MetaPathFinder):
    """Resolves a legacy top-level name to the module that replaced it."""

    def __init__(self) -> None:
        #: Every alias this finder put into sys.modules, so that leaving the
        #: context removes exactly those -- not everything whose root happens to
        #: be in LEGACY_ROOTS, which would evict an unrelated third-party `etc`.
        self.aliased: set[str] = set()
        self._announced: set[str] = set()

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        if not _is_legacy(fullname):
            return None

        real: str = _real_name(fullname)

        try:
            # Imported here rather than in create_module() so that a name with no
            # counterpart can be declined, leaving the ordinary
            # "No module named 'etc.nope'" -- which names what the file actually
            # wrote -- instead of a puzzling 'stonksmith.etc.nope'. No recursion:
            # `real` starts with the package name, which _is_legacy() rejects.
            module: ModuleType = importlib.import_module(real)
        except ModuleNotFoundError:
            return None

        self._announce(fullname=fullname, real=real)
        self.aliased.add(fullname)

        return spec_from_loader(
            fullname, _AliasLoader(module=module, spec=module.__spec__)
        )

    def _announce(self, fullname: str, real: str) -> None:
        message: str = (
            f"{fullname} is a legacy name and will stop working in StonkSmith "
            f"1.0. Import {real} instead."
        )

        # Suppressed, not skipped: under -W error this call raises, and the
        # caller's blanket `except Exception` would turn a deprecation notice
        # into "this broker failed to load". catch_warnings(record=True) still
        # sees it, which is what the tests assert on.
        with suppress(DeprecationWarning):
            warnings.warn(message, DeprecationWarning, stacklevel=2)

        # Once per top-level root, because DeprecationWarning is invisible under
        # Python's default filters and a user running this unattended would
        # otherwise get no signal at all. fail() because ERROR is the level
        # --quiet leaves showing.
        root: str = fullname.partition(".")[0]
        if root not in self._announced:
            self._announced.add(root)
            stonksmith_logger.fail(msg=message)


@contextmanager
def legacy_top_level_names() -> Iterator[None]:
    """
    Make the pre-namespace top-level names importable for the duration.

    Wraps ``exec_module()`` at both places a user-supplied file is run. Re-entrant:
    a file that itself loads another broker nests, and only the outermost exit
    uninstalls, so the inner one cannot pull the alias out from under its caller.
    """

    global _depth, _finder

    with _lock:
        if _depth == 0:
            _finder = _AliasFinder()
            # Position 0, not appended: appended, PathFinder resolves the
            # submodules first and overwrites the real package's attributes.
            sys.meta_path.insert(0, _finder)
        _depth += 1
        finder: _AliasFinder | None = _finder

    try:
        yield
    finally:
        with _lock:
            _depth -= 1
            if _depth == 0:
                if finder is not None and finder in sys.meta_path:
                    sys.meta_path.remove(finder)
                for name in finder.aliased if finder is not None else ():
                    sys.modules.pop(name, None)
                _finder = None
