"""
paths.py: module to define default paths

This module only *names* paths. It deliberately creates nothing: importing it
used to mkdir into the user's home directory, so merely importing any part of
StonkSmith -- in a test, a REPL, or an editor's autocomplete -- mutated the real
filesystem. etc.tool_setup.setup_tool() is the one place that creates them.
"""

import os
from pathlib import Path

paths_parent: Path = Path(__file__).resolve().parent
package_root: Path = Path(paths_parent).parent
data_path: Path = package_root / "data"
etc_path: Path = package_root / "etc"

stonksmith_path = Path("~/.stonksmith").expanduser()
# Logs belong with the rest of the user's state, not inside the installed
# package. setup_tool() already creates ~/.stonksmith/logs.
logs_path: Path = stonksmith_path / "logs"
home_path = Path("~").expanduser()
ws_path: Path = stonksmith_path / "workspaces"
playwright_path: Path = stonksmith_path / "playwright"
workspace_dir: Path = ws_path
cert_path: Path = stonksmith_path / "stonksmith.pem"
config_path: Path = stonksmith_path / "stonksmith.conf"
#: Where the morning brief is written. One rendered file per day it ran.
reports_path: Path = stonksmith_path / "reports"
#: What the last brief was shown, so the next one can say what changed.
baseline_path: Path = stonksmith_path / "brief_baseline.json"
#: What each held symbol pays per share, so the brief need not reach the network.
dividends_path: Path = stonksmith_path / "dividends.json"
token_path: Path = home_path / "token.json"
creds_path: Path = home_path / "credentials.json"

if os.name == "nt":
    # `or`, not a getenv default: LOCALAPPDATA set but empty would otherwise
    # give Path(""), which is the current directory rather than a temp one.
    tmp_base: Path = Path(os.getenv(key="LOCALAPPDATA") or Path("~").expanduser()) / (
        "Temp"
    )

else:
    tmp_base: Path = Path("/tmp")

tmp_path: Path = tmp_base / "stonksmith_hosted"

#: Directories setup_tool() creates. Kept here so the list lives with the paths.
#:
#: reports/ belongs here rather than in tool_setup's second list for the reason
#: that list's comment gives: every rendered brief states the portfolio total,
#: every account's value and every position behind them, which is the same
#: information the databases hold. The directory mode is what covers a file
#: written before a later run could restrict it.
managed_dirs: tuple[Path, ...] = (stonksmith_path, ws_path, tmp_path, reports_path)
