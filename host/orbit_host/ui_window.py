"""Desktop window (pywebview / WebView2) plus tray icon, with a browser fallback."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import webbrowser
from typing import Callable

from . import winutil
from .paths import data_dir, web_dir

log = logging.getLogger("orbit.ui")


class Tray:
    def __init__(self, core, on_open: Callable[[], None], on_quit: Callable[[], None]) -> None:
        self.core = core
        self.icon = None
        self._on_open = on_open
        self._on_quit = on_quit

    def start(self) -> bool:
        try:
            import pystray
            from PIL import Image

            image = Image.open(web_dir() / "img" / "icon-64.png")
            menu = pystray.Menu(
                pystray.MenuItem("Open Orbit", lambda: self._on_open(), default=True),
                pystray.MenuItem(lambda _: f"Session code: {self.core.code[:3]} {self.core.code[3:]}", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Disconnect everyone", lambda: self._disconnect_all()),
                pystray.MenuItem("Quit Orbit", lambda: self._on_quit()),
            )
            self.icon = pystray.Icon("orbit", image, "Orbit: ready for connections", menu)
            threading.Thread(target=self.icon.run, name="orbit-tray", daemon=True).start()
            return True
        except Exception as exc:
            log.warning("tray icon unavailable: %s", exc)
            self.icon = None
            return False

    def _disconnect_all(self) -> None:
        loop = self.core.loop
        if loop:
            import asyncio

            asyncio.run_coroutine_threadsafe(self.core.handle_action({"action": "disconnect_all"}), loop)

    def notify(self, title: str, message: str) -> None:
        if self.icon is not None:
            try:
                self.icon.notify(message, title)
            except Exception:
                pass

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass


def open_app_window(url: str) -> None:
    edge = winutil.find_edge()
    if edge:
        try:
            subprocess.Popen([edge, f"--app={url}", "--window-size=1080,720"])
            return
        except OSError:
            pass
    webbrowser.open(url)


def run_ui(core, url: str, start_hidden: bool = False, smoke: float | None = None) -> int:
    quit_event = threading.Event()
    state = {"window": None, "quitting": False}

    def show() -> None:
        window = state["window"]
        if window is not None:
            try:
                window.show()
                window.restore()
                return
            except Exception:
                pass
        open_app_window(url)

    def quit_app() -> None:
        state["quitting"] = True
        quit_event.set()
        tray.stop()
        window = state["window"]
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass

    tray = Tray(core, show, quit_app)
    has_tray = tray.start()
    core.ui_hooks.update(show=show, attention=show, quit=quit_app, notify=tray.notify)
    if smoke:
        threading.Timer(smoke, quit_app).start()

    used_webview = False
    try:
        import webview

        window = webview.create_window(
            "Orbit",
            url,
            width=1080,
            height=720,
            min_size=(860, 580),
            background_color=winutil.window_background(),
            hidden=start_hidden,
            text_select=False,
        )
        state["window"] = window

        def on_closing():
            if has_tray and not state["quitting"]:
                threading.Thread(target=window.hide, daemon=True).start()
                tray.notify("Orbit is still running", "Orbit keeps accepting connections from the tray.")
                return False
            return True

        def on_shown():
            try:
                handle = window.native.Handle
                hwnd = int(handle.ToInt64()) if hasattr(handle, "ToInt64") else int(handle)
                winutil.match_title_bar(hwnd)
            except Exception as exc:
                log.debug("title bar theme: %s", exc)

        window.events.closing += on_closing
        window.events.shown += on_shown
        storage = data_dir() / "webview"
        storage.mkdir(exist_ok=True)
        gui = "edgechromium" if sys.platform == "win32" else None
        webview.start(gui=gui, private_mode=False, storage_path=str(storage))
        used_webview = True
    except Exception as exc:
        log.warning("native window unavailable (%s); using browser window", exc)
    finally:
        state["window"] = None

    if not state["quitting"]:
        if not used_webview and not start_hidden:
            open_app_window(url)
        if has_tray or not used_webview:
            quit_event.wait()
    tray.stop()
    return 0
