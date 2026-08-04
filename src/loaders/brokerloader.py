"""
Load the broker specified from command line arguments.
"""

import importlib.util
from importlib.machinery import ModuleSpec
from os.path import expanduser
from pathlib import Path
from types import ModuleType
from typing import ClassVar

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
    def load_broker(broker_path: str) -> ModuleType | None:
        """
        Load a broker
        :param broker_path:
        :return:
        """

        spec: ModuleSpec | None = importlib.util.spec_from_file_location(
            name="broker", location=broker_path
        )

        if spec and spec.loader:
            broker: ModuleType | None = importlib.util.module_from_spec(spec=spec)
            spec.loader.exec_module(module=broker)
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
