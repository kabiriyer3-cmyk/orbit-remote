"""Small Windows helpers: DPI awareness, elevation, firewall, autostart, dark title bar."""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys

log = logging.getLogger("orbit.win")
IS_WINDOWS = sys.platform == "win32"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_RUN_NAME = "OrbitRemote"


def set_dpi_awareness() -> None:
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def is_admin() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def launch_command(extra: list[str] | None = None) -> tuple[str, str]:
    """Executable and argument string that relaunch Orbit."""
    args = list(extra or [])
    if getattr(sys, "frozen", False):
        return sys.executable, subprocess.list2cmdline(args)
    return sys.executable, subprocess.list2cmdline(["-m", "orbit_host", *args])


def _shell_runas(exe: str, params: str) -> bool:
    if not IS_WINDOWS:
        return False
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return rc > 32


def relaunch_as_admin() -> bool:
    exe, params = launch_command(["--elevated"])
    return _shell_runas(exe, params)


def add_firewall_rules(port: int, discovery_port: int) -> bool:
    rules = [
        f'netsh advfirewall firewall delete rule name="Orbit Remote"',
        f'netsh advfirewall firewall add rule name="Orbit Remote" dir=in action=allow protocol=TCP localport={port} profile=private,domain',
        f'netsh advfirewall firewall add rule name="Orbit Remote" dir=in action=allow protocol=UDP localport={discovery_port} profile=private,domain',
    ]
    return _shell_runas("cmd.exe", "/c " + " & ".join(rules))


def get_autostart() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    if not IS_WINDOWS:
        return False
    import winreg

    exe, params = launch_command(["--minimized"])
    command = f'"{exe}" {params}'.strip()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_RUN_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, APP_RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        log.warning("autostart change failed: %s", exc)
        return False


def dark_title_bar(hwnd: int) -> None:
    if not IS_WINDOWS or not hwnd:
        return
    value = ctypes.c_int(1)
    for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, old)
        try:
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), attr, ctypes.byref(value), ctypes.sizeof(value)
            ) == 0:
                break
        except Exception:
            pass
    try:  # Windows 11 caption colour that matches the UI background
        color = ctypes.c_int(0x000B0A09)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 35, ctypes.byref(color), 4)
    except Exception:
        pass


def find_edge() -> str | None:
    if not IS_WINDOWS:
        return None
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            path = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.exists(path):
                return path
    return None
