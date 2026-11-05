"""Filesystem locations for bundled resources and per-user data."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def resource_root() -> Path:
    """Folder that contains the bundled ``web`` directory."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def web_dir() -> Path:
    return resource_root() / "web"


def data_dir() -> Path:
    override = os.environ.get("ORBIT_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home()) / "OrbitRemote"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "orbit-remote"
    base.mkdir(parents=True, exist_ok=True)
    return base
