"""
Create database engine for stonksmith
"""

import cmd
import configparser
from os import listdir
from pathlib import Path
from types import ModuleType

from sqlalchemy import Engine

from etc.infrastructure import create_db_engine
from etc.logger import StonkSmithAdapter
from etc.paths import config_path, workspace_dir, ws_path
from loaders.brokerloader import BrokerLoader


class UserExitedProto(Exception):
    """
    Class to set up certain exceptions
    """


def do_exit() -> bool:
    """
    Exit STONKSMITHDB
    """

    return True


class StonkSmithDBMenu(cmd.Cmd):
    """
    Main Administrative Shell for StonkSmith Databases.
    """

    def __init__(self, config_file_path: Path) -> None:
        """
        Initialize STONKSMITHDB menu
        """

        super().__init__()
        self.config_path = Path(config_file_path)
        self.config = configparser.ConfigParser()
        self.config.read(filenames=self.config_path)

        self.broker_loader = BrokerLoader()
        self.brokers: dict[str, dict[str, str]] = self.broker_loader.get_brokers()

        self.workspace: str = self.config.get(
            section="STONKSMITH", option="workspace", fallback="default"
        )
        self.do_workspace(line=self.workspace)

        last_db: str | None = self.config.get(
            section="STONKSMITH", option="last_used_db", fallback=None
        )
        if last_db is not None:
            self.do_broker(broker=last_db)

    def write_config(self) -> None:
        """
        Create config file
        """

        with open(file=self.config_path, mode="w") as configfile:
            self.config.write(fp=configfile)

    def do_broker(self, broker: str) -> None:
        """
        Switches context to specific broker's database navigator.
        :param broker:
        :return:
        """

        if not broker or broker not in self.brokers:
            print(f"[-] Unknown broker: {broker}")
            return

        db_file: Path = Path(workspace_dir) / self.workspace / f"{broker}.db"

        if not db_file.exists():
            print(f"[-] Database file missing: {db_file}")
            return

        nav_mod: ModuleType | None = self.broker_loader.load_broker(
            broker_path=self.brokers[broker]["nvpath"]
        )
        db_mod: ModuleType | None = self.broker_loader.load_broker(
            broker_path=self.brokers[broker]["dbpath"]
        )

        if nav_mod is None or db_mod is None:
            print(f"[-] Failed to load broker modules for: {broker}")
            return

        engine: Engine = create_db_engine(db_path=db_file)
        db_instance = db_mod.Database(engine)

        self.config.set(section="STONKSMITH", option="last_used_db", value=broker)
        self.write_config()

        try:
            nav_class = nav_mod.DatabaseNavigator
            broker_menu = nav_class(self, db_instance, broker)
            broker_menu.cmdloop()

        except UserExitedProto:
            pass

    def do_workspace(self, line: str) -> None:
        """
        Manage workspaces: workspace <> | create <> | list
        :param line:
        """

        parts: list[str] = line.split()
        if not parts:
            print(f"[*] Current workspace: {self.workspace}")
            return

        cmd_arg: str = parts[0].lower()

        if cmd_arg == "create" and len(parts) > 1:
            name: str = parts[1]
            print(f"[*] Creating workspace '{name}'")
            self.create_workspace(name=name)
            self.do_workspace(line=name)

        elif cmd_arg == "list":
            print("[*] Enumerating Workspaces:")
            for ws in listdir(path=workspace_dir):
                indicator: str = "==> " if ws == self.workspace else "   "
                print(f"{indicator}{ws}")

        else:
            target_ws: Path = Path(workspace_dir) / line
            if target_ws.exists():
                self.workspace: str = line
                self.config.set(section="STONKSMITH", option="workspace", value=line)
                self.write_config()
                self.prompt = f"stonksmithdb ({line}) > "
            else:
                print(f"[-] Workspace '{line}' does not exist.")

    def create_workspace(self, name: str) -> None:
        """
        Creates new folder and all broker DBs within it.
        :param name:
        :type name:
        """

        new_path: Path = Path(workspace_dir) / name
        new_path.mkdir(parents=True, exist_ok=True)

        for broker_name, info in self.brokers.items():
            if "dbpath" in info:
                db_file: Path = new_path / f"{broker_name}.db"
                mod: ModuleType | None = self.broker_loader.load_broker(
                    broker_path=info["dbpath"]
                )
                if mod is None:
                    continue
                db_class = mod.Database
                engine: Engine = create_db_engine(db_path=db_file)
                db_instance = db_class(engine)
                db_instance.shutdown_db()


def initialize_db(logger: StonkSmithAdapter) -> None:
    """
    Initialize the database
    :param logger:
    :type logger: StonkSmithAdapter
    """

    default_ws: Path = Path(ws_path) / "default"
    default_ws.mkdir(parents=True, exist_ok=True)

    loader = BrokerLoader()
    brokers: dict[str, dict[str, str]] = loader.get_brokers()

    for name, info in brokers.items():
        db_file: Path = default_ws / f"{name}.db"
        if not db_file.exists() and "dbpath" in info:
            logger.highlight(msg=f"Initializing {name.upper()} database")
            mod: ModuleType | None = loader.load_broker(broker_path=info["dbpath"])
            if mod is None:
                continue
            db_class = mod.Database
            engine: Engine = create_db_engine(db_path=db_file)
            db_instance = db_class(engine)
            db_instance.shutdown_db()


def main() -> None:
    """
    Main function
    :return:
    """

    if not Path(config_path).exists():
        print("[-] Unable to find config file")
        raise SystemExit
    try:
        shell = StonkSmithDBMenu(config_file_path=config_path)
        shell.cmdloop()
    except KeyboardInterrupt:
        print("[*] Exiting...")


if __name__ == "__main__":
    main()
