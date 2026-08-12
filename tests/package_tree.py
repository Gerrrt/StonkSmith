"""Where the package's files are, named once.

Two dozen tests reach into the source tree by path -- to ``spec_from_file_location``
a broker, to ``ast.parse`` a module for a literal, or to assert what a directory
holds. Before the package had a namespace they all spelled ``REPO / "src"``, which
conflated two different things: the directory that goes on ``sys.path``, and the
directory the files actually live in. Those were the same path, so nothing forced
the distinction, and moving the tree under ``src/stonksmith`` would have needed 23
files each edited correctly.

Hence ``SRC`` and ``PACKAGE``. ``SRC`` is a ``sys.path`` entry and nothing else --
it is what ``PYTHONPATH`` is set to, and it must stay the parent of the package.
``PACKAGE`` is where the files are. A test wanting a file always wants ``PACKAGE``.

The import-time check is the other half. A path anchor that stops resolving does
not usually fail loudly: ``Path.glob`` on a directory that does not exist yields
nothing, so an assertion that some glob is empty keeps passing while testing
nothing at all. That is exactly what ``test_broker_discovery`` does with its
stray-file check, and it is the failure this module exists to convert into a
collection error naming the path that is wrong.
"""

from pathlib import Path

REPO: Path = Path(__file__).resolve().parents[1]

#: A sys.path entry. Never a file anchor -- see PACKAGE.
SRC: Path = REPO / "src"

#: The installed package. Every file anchor hangs off this.
PACKAGE: Path = SRC / "stonksmith"
BROKERS: Path = PACKAGE / "brokers"
MODULES: Path = PACKAGE / "modules"

for _name, _path in (("PACKAGE", PACKAGE), ("BROKERS", BROKERS), ("MODULES", MODULES)):
    if not _path.is_dir():
        raise RuntimeError(
            f"tests/package_tree.py: {_name} points at {_path}, which does not "
            "exist. The package moved and this file was not updated -- fix it "
            "here rather than in the tests that import it, or their path-based "
            "assertions will quietly stop asserting anything."
        )
