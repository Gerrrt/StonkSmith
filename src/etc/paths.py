"""
paths.py: module to define default paths
"""

import os
from pathlib import Path

paths_parent: Path = Path(__file__).resolve().parent
package_root: Path = Path(paths_parent).parent
data_path: Path = package_root / "data"
etc_path: Path = package_root / "etc"
logs_path: Path = package_root / "logs"

stonksmith_path = Path(os.path.expanduser(path="~/.stonksmith"))
home_path = Path(os.path.expanduser(path="~"))
ws_path: Path = stonksmith_path / "workspaces"
playwright_path: Path = stonksmith_path / "playwright"
workspace_dir: Path = ws_path
cert_path: Path = stonksmith_path / "stonksmith.pem"
config_path: Path = stonksmith_path / "stonksmith.conf"
token_path: Path = home_path / "token.json"
creds_path: Path = home_path / "credentials.json"

if os.name == "nt":
    tmp_base: Path = (
        Path(os.getenv(key="LOCALAPPDATA", default=os.path.expanduser(path="~")))
        / "Temp"
    )

else:
    tmp_base: Path = Path("/tmp")

tmp_path: Path = tmp_base / "stonksmith_hosted"

for p in [stonksmith_path, ws_path, tmp_path]:
    p.mkdir(parents=True, exist_ok=True)
