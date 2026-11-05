"""Persistent host settings and the list of trusted phones."""

from __future__ import annotations

import json
import os
import secrets
import socket
import threading
import time
from pathlib import Path
from typing import Any

from .paths import data_dir

DEFAULT_PORT = 47800
DISCOVERY_PORT = 47801

DEFAULTS: dict[str, Any] = {
    "device_id": "",
    "device_name": "",
    "port": DEFAULT_PORT,
    "require_approval": True,
    "allow_input": True,
    "allow_audio": True,
    "show_uac_prompts": False,
    "uac_restore": None,  # UAC policy to put back if Orbit exits without restoring it
    "quality": 70,
    "max_width": 1600,
    "fps": 30,
    "trusted": [],
}


def generate_device_id() -> str:
    first = str(secrets.randbelow(9) + 1)
    return first + "".join(str(secrets.randbelow(10)) for _ in range(8))


def format_device_id(device_id: str) -> str:
    return " ".join(device_id[i : i + 3] for i in range(0, len(device_id), 3))


def generate_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


class Config:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._data: dict[str, Any] = json.loads(json.dumps(DEFAULTS))

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        cfg = cls(path or data_dir() / "config.json")
        try:
            loaded = json.loads(cfg.path.read_text("utf-8"))
            if isinstance(loaded, dict):
                cfg._data.update(loaded)
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            try:
                cfg.path.replace(cfg.path.with_suffix(".broken.json"))
            except OSError:
                pass
        if not cfg._data.get("device_id"):
            cfg._data["device_id"] = generate_device_id()
        if not cfg._data.get("device_name"):
            cfg._data["device_name"] = socket.gethostname() or "Windows PC"
        if not isinstance(cfg._data.get("trusted"), list):
            cfg._data["trusted"] = []
        cfg.save()
        return cfg

    def get(self, key: str) -> Any:
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key))

    def update(self, **values: Any) -> None:
        with self._lock:
            self._data.update(values)
            self.save()

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), "utf-8")
            os.replace(tmp, self.path)

    # Trusted devices -----------------------------------------------------
    def trusted(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(t) for t in self._data["trusted"]]

    def find_trusted(self, client_id: str) -> dict[str, Any] | None:
        with self._lock:
            for item in self._data["trusted"]:
                if item.get("client_id") == client_id:
                    return dict(item)
        return None

    def add_trusted(self, client_id: str, name: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._data["trusted"] = [t for t in self._data["trusted"] if t.get("client_id") != client_id]
            self._data["trusted"].append(
                {"client_id": client_id, "name": name, "token": token, "added": now, "last_seen": now}
            )
            self.save()
        return token

    def touch_trusted(self, client_id: str, name: str | None = None) -> None:
        with self._lock:
            for item in self._data["trusted"]:
                if item.get("client_id") == client_id:
                    item["last_seen"] = time.time()
                    if name:
                        item["name"] = name
            self.save()

    def remove_trusted(self, client_id: str) -> bool:
        with self._lock:
            before = len(self._data["trusted"])
            self._data["trusted"] = [t for t in self._data["trusted"] if t.get("client_id") != client_id]
            changed = len(self._data["trusted"]) != before
            if changed:
                self.save()
            return changed
