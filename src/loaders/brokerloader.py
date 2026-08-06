"""
Load the broker specified from command line arguments.
"""

import importlib.util
from importlib.machinery import ModuleSpec
from os.path import expanduser
from pathlib import Path
from types import ModuleType
from typing import ClassVar

from etc.logger import stonksmith_logger
from etc.paths import package_root


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
        self.stonksmith_path = Path(expanduser(path="~/.stonksmith"))
        self._cache = {}

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

    def get_brokers(self) -> dict[str, dict[str, str]]:
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

        brokers: dict[str, dict[str, str]] = {}

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

                brokers[name] = info

        self._cache: dict[str, dict[str, str]] = brokers
        return brokers
