"""
StonkSmith: a tool that aggregates investment account data.

This package exists to give the project a namespace. Before it, the wheel was
built with ``sources = ["src"]``, which strips a path prefix rather than declaring
a package root -- so ``src/``'s children installed straight into site-packages as
top-level ``main``, ``etc``, ``helpers``, ``modules``, ``loaders`` and ``brokers``.
Six of the most generic importable names there are, each one able to shadow, or be
shadowed by, an unrelated distribution in the same environment depending on
``sys.path`` order.

This file deliberately imports nothing. ``stonksmith.etc.paths`` is kept free of
side effects on purpose -- importing it used to mkdir into the user's home
directory -- and a package ``__init__`` that pulled in submodules would put that
cost, and every other module's, on ``import stonksmith.anything``.

It deliberately declares no ``__version__`` either. The version lives in
``pyproject.toml`` and is read back off the installed distribution's metadata by
``stonksmith.etc.cli``; a second copy here is exactly what
``tests/test_version_single_source.py`` exists to refuse.
"""
