"""Command-line entry point for the Orbit host."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import urllib.request
from logging.handlers import RotatingFileHandler

from . import __version__


def _fix_stdio() -> None:
    # Windowed (no-console) builds have no stdout/stderr.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")


def _parse(argv):
    p = argparse.ArgumentParser(prog="orbit", description="Orbit host: control this PC from your phone.")
    p.add_argument("--port", type=int, help="TCP port (default 47800)")
    p.add_argument("--headless", action="store_true", help="run without a window")
    p.add_argument("--demo", action="store_true", help="synthetic screen and no real input (development)")
    p.add_argument("--minimized", action="store_true", help="start hidden in the tray")
    p.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--smoke", type=float, help=argparse.SUPPRESS)
    p.add_argument("--selftest", nargs="?", const="", metavar="RESULT.json", help="run the self-test and exit")
    p.add_argument("--data-dir", help="settings folder")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"Orbit {__version__}")
    return p.parse_args(argv)


def _setup_logging(verbose: bool) -> None:
    from .paths import data_dir

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        fh = RotatingFileHandler(data_dir() / "orbit.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


def _message_box(text: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "Orbit", 0x40)
    else:
        print(text, file=sys.stderr)


def _instance_file():
    from .paths import data_dir

    return data_dir() / "instance.json"


def _wake_existing() -> bool:
    """If another Orbit instance is running, bring its window to front and return True."""
    try:
        info = json.loads(_instance_file().read_text("utf-8"))
        req = urllib.request.Request(
            f"http://127.0.0.1:{int(info['adminPort'])}/api/host/action",
            data=json.dumps({"action": "show"}).encode(),
            headers={"Content-Type": "application/json", "X-Orbit-Token": str(info["token"])},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return bool(json.loads(resp.read()).get("ok"))
    except Exception:
        return False


def main(argv=None) -> int:
    _fix_stdio()
    args = _parse(sys.argv[1:] if argv is None else argv)
    if args.data_dir:
        os.environ["ORBIT_DATA_DIR"] = args.data_dir

    if args.selftest is not None:
        from .selftest import run

        return run(args.selftest or None, demo=args.demo)

    _setup_logging(args.verbose)
    log = logging.getLogger("orbit")

    from . import winutil
    from .config import Config
    from .core import HostCore
    from .paths import data_dir
    from .server import HostServer

    winutil.set_dpi_awareness()
    config = Config.load()
    port = args.port or int(config.get("port"))
    if not args.smoke and _wake_existing():
        return 0

    core = HostCore(config, data_dir(), demo=args.demo, port=port)
    server = HostServer(core)
    try:
        server.start()
    except OSError as exc:
        log.error("cannot listen on port %s: %s", port, exc)
        _message_box(f"Orbit can't use port {port} because another app is using it.\n\n{exc}")
        return 2

    try:
        _instance_file().write_text(json.dumps({"port": server.port, "adminPort": server.admin_port, "token": core.admin_token, "pid": os.getpid()}), "utf-8")
    except OSError:
        pass
    url = f"http://127.0.0.1:{server.admin_port}/host/#token={core.admin_token}"

    try:
        if args.headless:
            addresses = ", ".join(f"{ip}:{server.port}" for ip in core.addresses())
            print(f"Orbit {__version__}, {core.name}")
            print(f"  Address:      {addresses}")
            print(f"  Session code: {core.code}")
            print(f"  Security key: {core.fingerprint}")
            print(f"  Dashboard:    {url}")
            sys.stdout.flush()
            stop = threading.Event()
            if args.smoke:
                threading.Timer(args.smoke, stop.set).start()
            try:
                while not stop.wait(0.5):
                    pass
            except KeyboardInterrupt:
                pass
            return 0
        from .ui_window import run_ui

        return run_ui(core, url, start_hidden=args.minimized, smoke=args.smoke)
    finally:
        server.stop()
        try:
            _instance_file().unlink()
        except OSError:
            pass
