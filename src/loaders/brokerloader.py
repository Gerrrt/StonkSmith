"""
Load the broker specified from command line arguments.
"""

import importlib.util
from _frozen_importlib import ModuleSpec
from os.path import expanduser
from pathlib import Path
from types import ModuleType

from etc.paths import package_root


class BrokerLoader:
    """
    Load assistant brokers
    """

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
            if not base_path.exists():
                continue

            for broker_file in base_path.glob(pattern="[!_]*.py"):
                name: str = broker_file.stem
                if name in brokers:
                    continue

                info: dict[str, str] = {"path": str(object=Path(broker_file))}
                broker_dir: Path = base_path / name

                if broker_dir.is_dir():
                    sub_files: dict[str, Path] = {
                        "dbpath": broker_dir / "database.py",
                        "nvpath": broker_dir / "db_navigator.py",
                        "argspath": broker_dir / "broker_args.py",
                    }
                    for key, p in sub_files.items():
                        if p.exists():
                            info[key] = str(object=p)

                brokers[name] = info

        self._cache: dict[str, dict[str, str]] = brokers
        return brokers
