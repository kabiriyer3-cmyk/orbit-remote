"""Small Windows helpers: DPI awareness, elevation, firewall, autostart, title bar theme, MSIX detection."""

from __future__ import annotations

import ctypes
import functools
import logging
import os
import subprocess
import sys

log = logging.getLogger("orbit.win")
IS_WINDOWS = sys.platform == "win32"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_RUN_NAME = "OrbitRemote"
# Windows draws the UAC prompt on an isolated "secure desktop" that no app can see or click.
# Turning this policy off makes the prompt a normal window on the interactive desktop, so an
# elevated Orbit can stream it to the phone and click it. HKLM, so it needs administrator rights.
UAC_POLICY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
SECURE_DESKTOP_VALUE = "PromptOnSecureDesktop"
# ConsentPromptBehaviorAdmin: 1 and 2 always use the secure desktop, and recent Windows 11
# builds also keep the default 5 there. Map each to the same kind of prompt without the secure
# desktop (credentials -> 3, consent -> 4) while the option is on; 0, 3 and 4 already work.
CONSENT_ADMIN_VALUE = "ConsentPromptBehaviorAdmin"
CONSENT_WITHOUT_SECURE_DESKTOP = {1: 3, 2: 4, 5: 4}


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


def _read_policy(name: str, default: int) -> int | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UAC_POLICY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return int(value)
    except FileNotFoundError:
        return default  # Windows uses its default when the value is absent
    except (OSError, ValueError) as exc:
        log.debug("cannot read UAC policy %s: %s", name, exc)
        return None


def _write_policy(name: str, value: int) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UAC_POLICY_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(value))


def uac_policy() -> dict[str, int] | None:
    """Current UAC prompt policy, or None when it can't be read (not Windows, access denied)."""
    if not IS_WINDOWS:
        return None
    secure = _read_policy(SECURE_DESKTOP_VALUE, 1)
    consent = _read_policy(CONSENT_ADMIN_VALUE, 5)
    if secure is None or consent is None:
        return None
    return {SECURE_DESKTOP_VALUE: secure, CONSENT_ADMIN_VALUE: consent}


def uac_prompts_visible() -> bool:
    """True when UAC prompts appear on the normal desktop, where Orbit can stream them."""
    policy = uac_policy()
    return bool(policy) and policy[SECURE_DESKTOP_VALUE] == 0


def show_uac_on_desktop() -> dict[str, int] | None:
    """Move UAC prompts off the secure desktop. Returns the previous policy so it can be restored.

    Needs administrator rights. UAC still asks for every elevation; only the isolated
    secure-desktop switch is turned off.
    """
    if not IS_WINDOWS or not is_admin():
        return None
    before = uac_policy()
    if before is None:
        return None
    try:
        _write_policy(SECURE_DESKTOP_VALUE, 0)
        mapped = CONSENT_WITHOUT_SECURE_DESKTOP.get(before[CONSENT_ADMIN_VALUE])
        if mapped is not None:
            _write_policy(CONSENT_ADMIN_VALUE, mapped)
        return before
    except OSError as exc:
        log.warning("cannot change UAC policy: %s", exc)
        restore_uac(before)
        return None


def restore_uac(previous: dict[str, int] | None) -> bool:
    """Put the UAC policy back to ``previous`` (as returned by ``show_uac_on_desktop``)."""
    if not IS_WINDOWS or not previous or not is_admin():
        return False
    ok = True
    for name in (SECURE_DESKTOP_VALUE, CONSENT_ADMIN_VALUE):
        if name in previous:
            try:
                _write_policy(name, previous[name])
            except OSError as exc:
                log.warning("cannot restore UAC policy %s: %s", name, exc)
                ok = False
    return ok


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


def open_startup_settings() -> None:
    """Store build: startup is a package StartupTask the user switches on in Settings."""
    if IS_WINDOWS:
        try:
            os.startfile("ms-settings:startupapps")
        except OSError as exc:
            log.warning("could not open Startup apps settings: %s", exc)


def window_background() -> str:
    return "#08090A"


@functools.lru_cache(maxsize=1)
def is_packaged() -> bool:
    """True when running from an MSIX package (Microsoft Store build)."""
    if not IS_WINDOWS:
        return False
    try:
        length = ctypes.c_uint32(0)
        # ERROR_INSUFFICIENT_BUFFER (122) means there is a package identity; 15700 means there isn't.
        return ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None) == 122
    except Exception:
        return False


def match_title_bar(hwnd: int) -> None:
    """Dark title bar whose colour matches the window (Windows 11 also takes the caption colour)."""
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
    try:  # DWMWA_CAPTION_COLOR, COLORREF 0x00BBGGRR
        color = ctypes.c_int(0x000A0908)  # #08090A
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
