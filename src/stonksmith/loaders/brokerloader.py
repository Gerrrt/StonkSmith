"""
Load the broker specified from command line arguments.
"""

import importlib.util
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import ClassVar, NotRequired, TypedDict, cast

from stonksmith.etc.broker_db import BrokerDatabase
from stonksmith.etc.broker_nav import BrokerNavigator
from stonksmith.etc.logger import stonksmith_logger
from stonksmith.etc.paths import package_root
from stonksmith.loaders._legacy_names import legacy_top_level_names


class BrokerInfo(TypedDict):
    """
    Where a discovered broker's files are.

    The keys are a closed set -- ``path`` plus one per entry in
    ``BrokerLoader._OPTIONAL_FILES`` -- so they are written down rather than
    left as ``dict[str, str]``, which made ``broker_info["dbpath"]`` an
    unchecked lookup that main.py has to guard by hand.
    """

    #: broker.py. Always present: finding it is what makes a directory a broker.
    path: str
    dbpath: NotRequired[str]
    nvpath: NotRequired[str]
    argspath: NotRequired[str]


class BrokerLoader:
    """
    Load assistant brokers
    """

    #: Files a broker package may provide alongside broker.py, and the key each is
    #: published under. broker.py itself is mandatory: its presence is what makes a
    #: directory a broker.
    _OPTIONAL_FILES: ClassVar[dict[str, str]] = {
        "dbpath": "database.py",
        "nvpath": "db_navigator.py",
        "argspath": "broker_args.py",
    }

    def __init__(self) -> None:
        self.stonksmith_path = Path("~/.stonksmith").expanduser()
        self._cache: dict[str, BrokerInfo] = {}

    @staticmethod
    def load_broker(broker_path: str, label: str | None = None) -> ModuleType | None:
        """
        Load a broker
        :param broker_path:
        :param label: How to name this file if it fails to load. Callers that know
            which broker they are loading pass something friendlier than a path.
        :return:
        """

        spec: ModuleSpec | None = importlib.util.spec_from_file_location(
            name="broker", location=broker_path
        )

        if spec and spec.loader:
            broker: ModuleType | None = importlib.util.module_from_spec(spec=spec)

            # exec_module() runs the broker's own code, and a broker under
            # ~/.stonksmith/brokers is work in progress as often as not. Whatever
            # it raises belongs to that one file: callers already treat None as
            # "unavailable", so a half-finished broker is skipped rather than
            # taking down the caller -- which, for gen_cli_args(), was every
            # invocation of the tool including --version and --help.
            try:
                # A user broker predating the stonksmith namespace still says
                # `from etc.context import Context`. The alias is scoped to this
                # call so the deprecated names never become importable in the
                # main process, which is the whole point of having moved.
                with legacy_top_level_names():
                    spec.loader.exec_module(module=broker)
            except Exception as e:
                stonksmith_logger.fail(
                    msg=(
                        f"{label or broker_path} failed to load and is "
                        f"unavailable this run: {type(e).__name__}: {e}"
                    ),
                )
                return None

            return broker

        return None

    def _class_from(self, name: str, key: str, symbol: str) -> type | None:
        """
        The class a broker publishes in one of its optional files.

        Absent file and broken file are different answers, which is why
        ``ships()`` exists beside this. A broker with no database.py has not
        made a mistake -- it is taking the default. One that ships a file which
        will not load, or which loads without the symbol, *has*, and defaulting
        there would quietly run it against a store it did not ask for. This
        returns None for the second case; callers check ``ships()`` first and
        stop rather than substitute.
        :param name: The broker
        :param key: Which of _OPTIONAL_FILES to look in
        :param symbol: The name the file is expected to publish
        :return: The class, or None when the file is absent or unusable
        :rtype: type | None
        """

        info: BrokerInfo | None = self.get_brokers().get(name)
        # cast rather than a type: ignore -- .get() on a TypedDict with a key
        # held in a variable cannot be narrowed, and _OPTIONAL_FILES is itself
        # the statement of which keys exist.
        path: str | None = cast("str | None", info.get(key)) if info else None

        if path is None:
            return None

        module: ModuleType | None = self.load_broker(
            broker_path=path, label=f"{name}'s {symbol}"
        )

        # load_broker has already said what went wrong and named the file. It
        # would be wrong as well as duplicated to add "does not publish a
        # Database" on top: a file that failed to import may well publish one.
        if module is None:
            return None

        found: type | None = getattr(module, symbol, None)

        if found is None:
            stonksmith_logger.fail(
                msg=(
                    f"{path} does not publish a '{symbol}'. Remove the file to "
                    f"take the default, or give it one."
                ),
            )

        return found

    def ships(self, name: str, key: str) -> bool:
        """
        Whether a broker provides one of the optional files at all.

        Separates "took the default" from "published something unusable", which
        a bare None cannot.
        :param name: The broker
        :param key: Which of _OPTIONAL_FILES to look for
        :return: True when the file is there
        :rtype: bool
        """

        info: BrokerInfo | None = self.get_brokers().get(name)
        return bool(info) and key in info

    def database_class(self, name: str) -> type | None:
        """
        The Database class for a broker.

        ``BrokerDatabase`` unless the broker overrides it. Every shipped broker
        used to carry a database.py that subclassed it and set ``broker_name``
        and nothing else -- sixteen lines each, restating a fact this loader
        already knows from the directory it found the broker in. The base class
        takes the broker as a constructor argument and always did, so the
        subclasses were never doing anything.
        :param name: The broker
        :return: The class, or None when the broker ships a broken one
        :rtype: type | None
        """

        if not self.ships(name=name, key="dbpath"):
            return BrokerDatabase

        return self._class_from(name=name, key="dbpath", symbol="Database")

    def navigator_class(self, name: str) -> type | None:
        """
        The DatabaseNavigator class for a broker.

        ``BrokerNavigator`` unless the broker overrides it, which only SnapTrade
        does. The other four db_navigator.py files subclassed it and added
        nothing at all -- not even a name.
        :param name: The broker
        :return: The class, or None when the broker ships a broken one
        :rtype: type | None
        """

        if not self.ships(name=name, key="nvpath"):
            return BrokerNavigator

        return self._class_from(name=name, key="nvpath", symbol="DatabaseNavigator")

    def get_brokers(self) -> dict[str, BrokerInfo]:
        """
        Scan directories and return a mapping of available brokers.

        A broker is a *directory* containing ``broker.py``. There is no flat-file
        form: a ``brokers/<name>.py`` beside a ``brokers/<name>/`` package made
        ``import brokers.<name>`` resolve to the package while BrokerLoader resolved
        the file, so the two silently disagreed.
        :return:
        :rtype:
        """

        if self._cache:
            return self._cache

        brokers: dict[str, BrokerInfo] = {}

        search_dirs: list[Path] = list(
            dict.fromkeys(
                [
                    Path(package_root) / "brokers",
                    self.stonksmith_path / "brokers",
                ]
            )
        )

        for base_path in search_dirs:
            if not base_path.is_dir():
                continue

            # sorted() so broker subparsers register in a stable order across
            # machines; iterdir() order is filesystem-dependent.
            for broker_dir in sorted(base_path.iterdir()):
                name: str = broker_dir.name

                if name.startswith((".", "_")) or not broker_dir.is_dir():
                    continue

                broker_file: Path = broker_dir / "broker.py"
                if not broker_file.is_file():
                    continue

                # First root wins: a user broker never shadows a bundled one.
                if name in brokers:
                    continue

                info: dict[str, str] = {"path": str(object=broker_file)}

                for key, filename in self._OPTIONAL_FILES.items():
                    candidate: Path = broker_dir / filename
                    if candidate.is_file():
                        info[key] = str(object=candidate)

                # Cast rather than construct: the optional keys are filled
                # through a variable, which no type checker can match to a
                # TypedDict field. _OPTIONAL_FILES is itself the statement of
                # which keys exist, so the two cannot drift without the literal
                # above being edited too.
                brokers[name] = cast("BrokerInfo", info)

        self._cache = brokers
        return brokers
