#!/usr/bin/env python3
"""
paths.py: module to define default paths
"""

import os
import sys

import src

stonksmith_path = os.path.expanduser("~/.stonksmith")
tmp_path = os.path.join("/tmp", "stonksmith_hosted")

if os.name == "nt":
    tmp_path = os.getenv("LOCALAPPDATA"), "\\Temp\\stonksmith_hosted"
if hasattr(sys, "getandroidapilevel"):
    tmp_path = os.path.join(
            "/data",
            "data",
            "com.termux",
            "files",
            "usr",
            "tmp",
            "stonksmith_hosted",
        )

ws_path = os.path.join(stonksmith_path, "workspaces")
cert_path = os.path.join(stonksmith_path, "stonksmith.pem")
config_path = os.path.join(stonksmith_path, "stonksmith.conf")
workspace_dir = os.path.join(stonksmith_path, "workspaces")
data_path = os.path.join(os.path.dirname(src.__file__), "data")
etc_path = os.path.join(os.path.dirname(src.__file__), "etc")
