"""
Module to load modules
"""

import importlib.util
import inspect
from argparse import Namespace
from os import listdir
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from etc.context import BrokerDbProtocol, Context
from etc.logger import StonkSmithAdapter, _base_logger  # pyright: ignore
from etc.paths import package_root, stonksmith_path
from loaders.brokerloader import ModuleSpec


def _is_valid_module(filename: str) -> bool:
    exclusions = ("__init__.py", "example.py")
    return filename.endswith(".py") and filename not in exclusions


def _is_valid_spec(spec: ModuleSpec | None) -> ModuleType | None:
    if spec and spec.loader:
        module_obj: ModuleType = importlib.util.module_from_spec(spec=spec)
        spec.loader.exec_module(module=module_obj)
        return module_obj
    return None


def _is_target_class(module_obj: ModuleType) -> type | None:
    for _, obj in inspect.getmembers(object=module_obj, predicate=inspect.isclass):
        if obj.__module__ == module_obj.__name__:
            return obj
    return None


def _gather_attributes(
    module_path: Path, target_class: type | None
) -> dict[str, dict[str, str | Path | bool | list[str]]] | None:
    if target_class is None:
        return None
    else:
        return {
            getattr(target_class, "name", "Unknown"): {
                "path": module_path,
                "description": getattr(target_class, "description", "Missing"),
                "options": getattr(
                    getattr(target_class, "options", None), "__doc__", "None"
                ),
                "supported_brokers": getattr(target_class, "supported_brokers", []),
            }
        }


class ModuleLoader:
    """
    Loads modules
    """

    def __init__(
        self, args: Namespace, db: BrokerDbProtocol, logger: StonkSmithAdapter
    ) -> None:
        self.args: Namespace = args
        self.db: BrokerDbProtocol = db
        self.logger: StonkSmithAdapter = logger
        self._cache: dict[str, dict[str, str | Path | bool | list[str]]] | None = {}

    def list_available(self) -> None:
        """
        List available modules for the selected broker.
        :return:
        :rtype:
        """

        modules: dict[str, dict[str, str | Path | bool | list[str]]] | None = (
            self.list_modules()
        )

        if modules is not None:
            filtered: list[str] = [
                f"{name}: {info['description']}"
                for name, info in sorted(modules.items())
                if self.args.broker in cast(list[str], info["supported_brokers"])
            ]

            for entry in filtered:
                self.logger.display(msg=entry)

    def show_options(self) -> None:
        """
        Show options for requested modules.
        :return:
        :rtype:
        """

        modules: dict[str, dict[str, str | Path | bool | list[str]]] | None = (
            self.list_modules()
        )

        if modules is not None:
            for module_name in getattr(self.args, "module", []):
                if module_name in modules:
                    self.logger.highlight(
                        msg=f"[*] {module_name} module options:\n{modules[module_name]['options']}"
                    )

    def prepare(self) -> Any | None:
        """
        Validate and initialize modules based on CLI args.
        :return:
        :rtype:
        """

        modules: dict[str, dict[str, str | Path | bool | list[str]]] | None = (
            self.list_modules()
        )
        requested: list[str] = [m.lower() for m in getattr(self.args, "module", [])]

        for module in requested:
            if modules is None or module not in modules:
                self.logger.error(msg=f"[-] Module not found: {module}")
                continue

            self.logger.display(
                msg=f"Load: [purple bold]{module}[/] {modules[module]['path']}"
            )
            module_obj: Any | None = self.init_module(
                module_path=cast(Path, modules[module]["path"])
            )

            if not module_obj:
                return None

            return module_obj

        return None

    def module_is_sane(self, module_path: Path, module: type | None) -> bool:
        """
        Check for all required attributes of module class
        :param module:
        :type module:
        :param module_path:
        :return:
        """

        requirements: list[tuple[str, str]] = [
            ("name", "missing name"),
            ("description", "missing description"),
            ("supported_brokers", "missing supported_brokers"),
            ("options", "missing options"),
        ]

        for attribute, message in requirements:
            if not hasattr(module, attribute):
                self.logger.error(msg=f"[-] {module_path} {message}")
                return False

        if not (hasattr(module, "on_login") or hasattr(module, "on_admin_login")):
            self.logger.error(msg=f"[-] {module_path} missing login handler")
            return False

        return True

    def init_module(self, module_path: Path) -> Any | None:
        """
        Initialize a module for execution
        :param module_path:
        :return:
        """

        try:
            spec: ModuleSpec | None = importlib.util.spec_from_file_location(
                name="StonkSmithModule", location=module_path
            )

            if spec is not None:
                module: ModuleType | None = _is_valid_spec(spec=spec)
            else:
                module = None

            if module is None:
                return None

            target_class: type | None = _is_target_class(module_obj=module)

            if not target_class or not self.module_is_sane(
                module_path=module_path, module=target_class
            ):
                return None

            if self.args.broker not in getattr(target_class, "supported_brokers", []):
                self.logger.error(
                    msg=f"[-] {getattr(target_class, 'name', 'Unknown')} not supported for {self.args.broker}"
                )
                return None

            module_logger = StonkSmithAdapter(
                extra={"module_name": getattr(target_class, "name", "Unknown").upper()},
                logger=_base_logger,
            )
            context = Context(db=self.db, logger=module_logger, args=self.args)

            raw_module_options: list[str] = cast(
                list[str],
                getattr(
                    self.args,
                    "module_option",
                    getattr(self.args, "module_options", []),
                ),
            )

            module_options: dict[str, str] = {}
            for opt in raw_module_options:
                if "=" in opt:
                    key: str
                    value: str
                    key, value = opt.split(sep="=", maxsplit=1)
                    module_options[key.upper()] = value

            module_instance: Any = cast(Any, target_class)()
            module_instance.options(context, module_options)
            return module_instance

        except (ImportError, AttributeError) as e:
            self.logger.error(msg=f"[-] Error initializing {module_path}: {e}")
            return None

    def get_module_info(
        self, module_path: Path
    ) -> dict[str, dict[str, str | Path | bool | list[str]]] | None:
        """
        Get module info
        :param module_path:
        :return:
        """

        try:
            spec: ModuleSpec | None = importlib.util.spec_from_file_location(
                name="StonkSmithModule",
                location=module_path,
            )

            if spec is not None:
                module_obj: ModuleType | None = _is_valid_spec(spec=spec)
            else:
                module_obj = None

            if module_obj is not None:
                target_class: type | None = _is_target_class(module_obj=module_obj)
            else:
                target_class = None

            if target_class and self.module_is_sane(
                module_path=module_path, module=target_class
            ):
                return _gather_attributes(
                    module_path=module_path, target_class=target_class
                )

        except (ImportError, AttributeError) as e:
            self.logger.highlight(msg=f"[-] Metadata fail for {module_path}: {e}")

        return None

    def list_modules(
        self,
    ) -> dict[str, dict[str, str | Path | bool | list[str]]] | None:
        """
        List modules
        :return:
        """

        if self._cache:
            return self._cache

        modules: dict[str, dict[str, str | Path | bool | list[str]]] | None = {}
        search_paths: list[Path] = [
            Path(package_root) / "modules",
            Path(stonksmith_path) / "modules",
        ]

        for path in search_paths:
            try:
                for file in listdir(path=path):
                    if _is_valid_module(filename=file):
                        data: (
                            dict[str, dict[str, str | Path | bool | list[str]]] | None
                        ) = self.get_module_info(module_path=Path(path) / file)
                        if data:
                            modules.update(data)
            except FileNotFoundError:
                continue

        self._cache: dict[str, dict[str, str | Path | bool | list[str]]] | None = (
            modules
        )
        return modules
