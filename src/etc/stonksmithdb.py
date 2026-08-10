"""
Create database engine for stonksmith
"""

import cmd
import configparser
from os import listdir
from pathlib import Path
from types import ModuleType

from sqlalchemy import Engine

from etc.exceptions import SwitchBroker, UserExitedProto
from etc.infrastructure import create_db_engine
from etc.logger import StonkSmithAdapter
from etc.paths import config_path, workspace_dir, ws_path
from loaders.brokerloader import BrokerLoader

#: Commands that only exist inside a broker's sub-shell. Typing one at the top
#: level produced a bare "*** Unknown syntax" with no hint that a broker has to
#: be selected first, which is the single most common way to get stuck here.
BROKER_SHELL_COMMANDS: frozenset[str] = frozenset(
    {"add", "delete", "show", "export", "back"}
)


class StonkSmithDBMenu(cmd.Cmd):
    """
    Main Administrative Shell for StonkSmith Databases.
    """

    intro = (
        "\nStonkSmith database shell. Credentials and account history are stored "
        "per broker,\nso select one first:\n\n"
        "    broker            list available brokers\n"
        "    broker <name>     enter that broker (add/show/export live in there)\n"
        "    workspace list    list workspaces\n"
        "    sheet             rewrite the Google Sheet from these databases\n"
        "    verify            check the sheet's ownership guard on a scratch tab\n"
        "    help              commands at this level\n"
        "    exit              quit\n"
    )

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
        if last_db:
            self.do_broker(broker=last_db)

    def do_exit(self, line: str) -> bool:
        """
        Exit STONKSMITHDB
        :param line:
        :return: True, which tells cmd.Cmd to leave the command loop
        """

        del line
        print("[*] Exiting...")
        return True

    do_EOF = do_exit

    def get_names(self) -> list[str]:
        """
        Hide the EOF handler from help and tab-completion. It exists so Ctrl-D
        quits cleanly, but listing "EOF" as a command is just noise.
        :return: Command names to advertise
        """

        return [name for name in super().get_names() if name != "do_EOF"]

    def default(self, line: str) -> None:
        """
        Explain unknown input instead of printing bare "*** Unknown syntax".
        :param line: The command the user typed
        """

        command: str = line.split()[0].lower() if line.split() else ""

        if command in BROKER_SHELL_COMMANDS:
            if not self.brokers:
                # "Select one first" followed by an empty list is a dead end.
                print(
                    f"[-] '{command}' only works inside a broker, and no brokers "
                    "were found."
                )
                return

            print(
                f"[-] '{command}' only works inside a broker. Select one first, e.g.:"
            )
            for name in sorted(self.brokers):
                print(f"      broker {name}")
            return

        print(f"[-] Unknown command: {line}. Type 'help' for the commands here.")

    def do_brokers(self, line: str) -> None:
        """
        List available brokers.
        :param line:
        """

        del line
        self.list_brokers()

    def list_brokers(self) -> None:
        """
        Print each discovered broker and whether its database is ready.
        """

        if not self.brokers:
            print("[-] No brokers found.")
            return

        print("[*] Available brokers:")

        for name in sorted(self.brokers):
            info: dict[str, str] = self.brokers[name]
            db_file: Path = Path(workspace_dir) / self.workspace / f"{name}.db"

            if not {"nvpath", "dbpath"} <= set(info):
                status = "incomplete (broker package is missing files)"
            elif not db_file.exists():
                status = f"no database in workspace '{self.workspace}' yet"
            else:
                status = "ready"

            print(f"      {name:<16} {status}")

        print("\n    Enter one with: broker <name>")

    def do_sheet(self, line: str) -> None:
        """
        Rewrite the machine-owned tabs from this workspace's databases.

        The sheet is a view of the databases, so it can be rebuilt from them
        alone. Without this the only cure for "the dashboard was not updated" is
        another scrape, and for the browser-backed brokers that means a human at
        a sign-in page -- a high price for a tab that is missing a banner.
        :param line: Ignored
        :return: None
        """

        del line

        # Imported here rather than at module scope: this pulls in gspread and
        # google-auth, and the shell is mostly used for things that never touch
        # Sheets. tests/test_no_import_side_effects.py imports this module in a
        # subprocess and asserts nothing appears in $HOME.
        from etc.portfolio_sheet import refresh
        from helpers.sheets import SheetsUnavailable

        try:
            result = refresh(workspace=self.workspace)

        except SheetsUnavailable as e:
            print(f"[-] {e}")
            return

        except Exception as e:
            print(f"[-] Sheet refresh failed: {type(e).__name__}: {e}")
            return

        print(
            f"[*] Refreshed: {result.accounts} accounts, {result.holdings} "
            f"holdings, {result.transactions} movements from "
            f"{', '.join(result.brokers_read) or 'no brokers'}."
        )

        for name, reason in result.unreadable:
            # Printed as well as written to the tab. A total short by a whole
            # broker is exactly the failure that must not be quiet.
            print(f"[-] Not on the sheet: {name} could not be read ({reason}).")

    def do_verify(self, line: str) -> None:
        """
        Ask the ownership guard its three questions, against real Sheets.

        The refusal is the one rule here whose failure cannot be undone by
        running again, and observing it used to mean defacing a live tab and
        handing it back -- done once, nervously, if at all. This asks claim() the
        same three questions on a tab it makes and removes, so the check is
        repeatable and the real tabs are never opened.

        What it cannot show is that a refusal stops the *whole* sync rather than
        leaving one tab freshly written beside a stale one. That is refresh()
        claiming every tab before clearing any, and the scratch tab is not one of
        them.
        :param line: Ignored
        :return: None
        """

        del line

        # Same reason as do_sheet: this pulls in gspread and google-auth, and the
        # shell is mostly used for things that never touch Sheets.
        from etc.portfolio_sheet import GUARD_CHECK_TAB, check_ownership_guard
        from helpers.sheets import SPREADSHEET_NAME, SheetsUnavailable

        print(
            f"[*] Making the tab '{GUARD_CHECK_TAB}' in '{SPREADSHEET_NAME}', "
            "asking the guard about it, and deleting it again. No other tab is "
            "opened."
        )

        try:
            cases = check_ownership_guard()

        except SheetsUnavailable as e:
            print(f"[-] {e}")
            return

        except Exception as e:
            print(f"[-] Ownership check failed: {type(e).__name__}: {e}")
            return

        for case in cases:
            print(f"{'[+]' if case.passed else '[-]'} {case.name}")

            if not case.passed:
                # The finding, not a footnote. A guard that adopted a tab it
                # should have refused is the shape that eats somebody's work.
                print(f"    Expected {case.expected}: {case.detail or 'it did not'}")

        failed = [case for case in cases if not case.passed]

        if failed:
            print(
                f"[-] {len(failed)} of {len(cases)} did not behave. Until this "
                "reads clean, treat the machine-owned tabs as unguarded and do "
                "not keep anything of your own in the spreadsheet."
            )
            return

        print(
            f"[*] The guard behaved on all {len(cases)} counts. That is claim() "
            "against real Sheets, not a stub -- but a refusal aborting the whole "
            "sync still needs the manual step in docs/live-verification.md."
        )

    def write_config(self) -> None:
        """
        Create config file
        """

        with open(file=self.config_path, mode="w") as configfile:
            self.config.write(fp=configfile)

    def do_broker(self, broker: str) -> None:
        """
        Enter a broker's database navigator, or list the brokers if given none.

        A sub-shell can ask to switch straight to another broker, so this loops
        rather than recursing: hopping between brokers must not grow the stack.
        :param broker: Broker to enter, or "" to list what is available
        :return:
        """

        # None means finished; "" means the user asked for the listing; a name
        # means switch to it. Collapsing the first two would make `brokers`
        # from inside a sub-shell exit silently.
        pending: str | None = broker.strip()

        while pending is not None:
            if not pending:
                self.list_brokers()
                return

            pending = self.enter_broker(broker=pending)

    def enter_broker(self, broker: str) -> str | None:
        """
        Open one broker's navigator and run it until the user leaves.
        :param broker: Broker to enter
        :return: Another broker to switch to, or None when finished
        """

        if broker not in self.brokers:
            print(f"[-] Unknown broker: {broker}")
            self.list_brokers()
            return None

        info: dict[str, str] = self.brokers[broker]
        missing: list[str] = [key for key in ("nvpath", "dbpath") if key not in info]
        if missing:
            print(f"[-] Broker '{broker}' is incomplete; missing {', '.join(missing)}")
            return None

        db_file: Path = Path(workspace_dir) / self.workspace / f"{broker}.db"

        if not db_file.exists():
            print(f"[-] Database file missing: {db_file}")
            return None

        nav_mod: ModuleType | None = self.broker_loader.load_broker(
            broker_path=info["nvpath"]
        )
        db_mod: ModuleType | None = self.broker_loader.load_broker(
            broker_path=info["dbpath"]
        )

        if nav_mod is None or db_mod is None:
            print(f"[-] Failed to load broker modules for: {broker}")
            return None

        db_class = getattr(db_mod, "Database", None)
        nav_class = getattr(nav_mod, "DatabaseNavigator", None)
        if db_class is None or nav_class is None:
            print(f"[-] Broker '{broker}' is missing Database or DatabaseNavigator")
            return None

        engine: Engine = create_db_engine(db_path=db_file)
        db_instance = db_class(engine, broker)

        self.config.set(section="STONKSMITH", option="last_used_db", value=broker)
        self.write_config()

        try:
            broker_menu = nav_class(self, db_instance, broker)
            broker_menu.cmdloop()

        except SwitchBroker as switch:
            # `broker <name>` typed inside the sub-shell: leave this one and
            # go straight there, no explicit `back` required.
            return switch.broker

        except UserExitedProto:
            pass

        return None

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
                db_class = getattr(mod, "Database", None) if mod is not None else None
                if db_class is None:
                    print(
                        f"[-] Skipping {broker_name}: {info['dbpath']} does not "
                        "define a Database class."
                    )
                    continue
                engine: Engine = create_db_engine(db_path=db_file)
                db_instance = db_class(engine, broker_name)
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
            db_class = getattr(mod, "Database", None) if mod is not None else None
            if db_class is None:
                logger.fail(
                    msg=(
                        f"Skipping {name}: {info['dbpath']} does not define a "
                        "Database class."
                    )
                )
                continue
            engine: Engine = create_db_engine(db_path=db_file)
            db_instance = db_class(engine, name)
            db_instance.shutdown_db()


def main() -> None:
    """
    Main function
    :return:
    """

    # etc.paths no longer creates anything at import time, so this entry point
    # is responsible for making sure the tool is set up before it reads config.
    # Imported here, not at module scope: tool_setup imports initialize_db from
    # this module, so a top-level import would be circular.
    from etc.logger import stonksmith_logger
    from etc.tool_setup import setup_tool

    setup_tool(logger=stonksmith_logger)

    if not Path(config_path).exists():
        print("[-] Unable to find config file")
        # SystemExit with no argument is SystemExit(None), which Python maps to
        # exit status 0 -- so this hard failure used to report success.
        raise SystemExit(1)
    try:
        shell = StonkSmithDBMenu(config_file_path=config_path)
        shell.cmdloop()
    except KeyboardInterrupt:
        print("[*] Exiting...")


if __name__ == "__main__":
    main()
