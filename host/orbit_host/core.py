"""Shared host state: pairing code, sessions, approvals, trusted devices, activity log."""

from __future__ import annotations

import asyncio
import logging
import secrets
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from . import __version__, winutil
from .audio import AudioHub
from .config import DISCOVERY_PORT, Config, format_device_id, generate_code
from .inputs import create_backend
from .netinfo import local_ipv4
from .secure import fingerprint, load_identity, public_spki

if TYPE_CHECKING:
    from aiohttp import web

    from .session import Session

log = logging.getLogger("orbit.core")

MAX_SESSIONS = 3
APPROVAL_TIMEOUT = 60.0
LOCK_AFTER = 5
LOCK_WINDOW = 300.0
LOCK_SECONDS = 60.0


@dataclass
class PendingRequest:
    id: str
    session: "Session"
    wants_trust: bool
    created: float = field(default_factory=time.time)
    future: asyncio.Future | None = None


class HostCore:
    def __init__(self, config: Config, data_path, demo: bool = False, port: int | None = None) -> None:
        self.config = config
        self.demo = demo
        self.port = int(config.get("port") if port is None else port)
        self.identity_path = Path(data_path) / "identity.pem"
        self.identity = load_identity(self.identity_path)
        self.fingerprint = fingerprint(public_spki(self.identity))
        self.code = generate_code()
        self.admin_token = secrets.token_urlsafe(24)
        self.input = create_backend(demo)
        self.audio = AudioHub(self)
        self.sessions: dict[str, Session] = {}
        self.pending: dict[str, PendingRequest] = {}
        self.admin_sockets: set[web.WebSocketResponse] = set()
        self.activity: deque[dict[str, Any]] = deque(maxlen=200)
        self.ui_hooks: dict[str, Callable[..., Any]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._total_failures: list[float] = []
        self._broadcast_scheduled = False
        self._addr_cache: tuple[float, list[str]] = (0.0, [])
        self.log(f"Orbit {__version__} started", "info")
        self._recover_uac()
        if self.config.get("show_uac_prompts"):
            self._apply_uac(True, announce=False)

    # ------------------------------------------------------------------ info
    @property
    def device_id(self) -> str:
        return str(self.config.get("device_id"))

    @property
    def name(self) -> str:
        return str(self.config.get("device_name"))

    def addresses(self) -> list[str]:
        ts, cached = self._addr_cache
        if time.time() - ts > 10 or not cached:
            cached = local_ipv4()
            self._addr_cache = (time.time(), cached)
        return cached

    def public_info(self) -> dict[str, Any]:
        return {
            "orbit": 1,
            "id": self.device_id,
            "name": self.name,
            "port": self.port,
            "version": __version__,
            "os": "windows" if sys.platform == "win32" else sys.platform,
        }

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        return {
            "type": "state",
            "version": __version__,
            "name": self.name,
            "deviceId": format_device_id(self.device_id),
            "addresses": self.addresses(),
            "port": self.port,
            "code": self.code,
            "fingerprint": self.fingerprint,
            "demo": self.demo,
            "platform": sys.platform,
            "admin": winutil.is_admin(),
            "uacVisible": winutil.uac_prompts_visible(),
            "packaged": winutil.is_packaged(),
            "input": getattr(self.input, "name", "unknown"),
            "settings": {
                "requireApproval": bool(self.config.get("require_approval")),
                "allowInput": bool(self.config.get("allow_input")),
                "allowAudio": bool(self.config.get("allow_audio")),
                "showUacPrompts": bool(self.config.get("show_uac_prompts")),
                "quality": int(self.config.get("quality")),
                "fps": int(self.config.get("fps")),
                "maxWidth": int(self.config.get("max_width")),
                "autostart": winutil.get_autostart(),
                "deviceName": self.name,
            },
            "sessions": [s.describe_for_host(now) for s in self.sessions.values()],
            "pending": [
                {
                    "id": p.id,
                    "device": p.session.device,
                    "ip": p.session.remote,
                    "wantsTrust": p.wants_trust,
                    "age": round(now - p.created),
                    "timeout": APPROVAL_TIMEOUT,
                }
                for p in self.pending.values()
            ],
            "trusted": [
                {"clientId": t.get("client_id"), "name": t.get("name"), "added": t.get("added"), "lastSeen": t.get("last_seen")}
                for t in self.config.trusted()
            ],
            "activity": list(self.activity)[-80:],
        }

    # ------------------------------------------------------------- activity
    def log(self, text: str, kind: str = "info") -> None:
        self.activity.append({"ts": time.time(), "kind": kind, "text": text})
        log.info(text)
        self.changed()

    def changed(self) -> None:
        loop = self.loop
        if loop is None or self._broadcast_scheduled:
            return
        self._broadcast_scheduled = True
        try:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._broadcast()))
        except RuntimeError:
            self._broadcast_scheduled = False

    async def _broadcast(self) -> None:
        await asyncio.sleep(0.05)
        self._broadcast_scheduled = False
        if not self.admin_sockets:
            return
        state = self.snapshot()
        for ws in list(self.admin_sockets):
            try:
                await ws.send_json(state)
            except Exception:
                self.admin_sockets.discard(ws)

    def call_ui(self, hook: str, *args: Any) -> None:
        fn = self.ui_hooks.get(hook)
        if fn:
            try:
                fn(*args)
            except Exception as exc:  # UI hooks must never break the server
                log.debug("ui hook %s failed: %s", hook, exc)

    # ------------------------------------------------------------ security
    def regenerate_code(self) -> None:
        self.code = generate_code()
        self.log("Session code regenerated", "security")

    def rotate_code(self) -> None:
        self.code = generate_code()
        self.changed()

    def is_locked(self, ip: str) -> bool:
        return self._locked_until.get(ip, 0) > time.time()

    def record_failure(self, ip: str) -> None:
        now = time.time()
        attempts = [t for t in self._failures.get(ip, []) if now - t < LOCK_WINDOW] + [now]
        self._failures[ip] = attempts
        self._total_failures = [t for t in self._total_failures if now - t < LOCK_WINDOW] + [now]
        self.log(f"Wrong session code from {ip}", "warning")
        if len(attempts) >= LOCK_AFTER:
            self._locked_until[ip] = now + LOCK_SECONDS
            self._failures[ip] = []
            self.log(f"{ip} blocked for {int(LOCK_SECONDS)} s after repeated wrong codes", "security")
        if len(self._total_failures) >= LOCK_AFTER * 2:
            self._total_failures = []
            self.regenerate_code()

    def clear_failures(self, ip: str) -> None:
        self._failures.pop(ip, None)

    # ------------------------------------------------------------- sessions
    def can_accept_session(self) -> bool:
        return len(self.sessions) < MAX_SESSIONS

    def add_session(self, session: "Session") -> None:
        self.sessions[session.id] = session
        label = "trusted device" if session.trusted else "session code"
        self.log(f"{session.device} connected from {session.remote} ({label})", "connect")
        self.call_ui("notify", "Orbit", f"{session.device} is now controlling this PC")

    def remove_session(self, session: "Session", reason: str = "") -> None:
        if self.sessions.pop(session.id, None) is not None:
            suffix = f" ({reason.lower()})" if reason else ""
            self.log(f"{session.device} disconnected{suffix}", "disconnect")

    async def request_approval(self, session: "Session", wants_trust: bool) -> tuple[bool, bool]:
        loop = asyncio.get_running_loop()
        req = PendingRequest(secrets.token_hex(4), session, wants_trust, future=loop.create_future())
        self.pending[req.id] = req
        self.log(f"{session.device} ({session.remote}) is asking for access", "request")
        self.call_ui("attention")
        self.call_ui("notify", "Orbit: access request", f"{session.device} wants to control this PC")
        try:
            assert req.future is not None
            return await asyncio.wait_for(asyncio.shield(req.future), APPROVAL_TIMEOUT)
        except asyncio.TimeoutError:
            self.log(f"Request from {session.device} timed out", "warning")
            return False, False
        finally:
            self.pending.pop(req.id, None)
            self.changed()

    def cancel_pending_for(self, session: "Session") -> None:
        for req in list(self.pending.values()):
            if req.session is session and req.future and not req.future.done():
                req.future.set_result((False, False))

    def resolve_pending(self, request_id: str, accept: bool, trust: bool) -> bool:
        req = self.pending.get(request_id)
        if not req or not req.future or req.future.done():
            return False
        req.future.set_result((accept, accept and trust))
        self.log(f"Request from {req.session.device} {'accepted' if accept else 'declined'}", "request")
        return True

    # -------------------------------------------------------------- actions
    async def handle_action(self, data: dict[str, Any]) -> dict[str, Any]:
        action = data.get("action")
        if action == "regenerate_code":
            self.regenerate_code()
        elif action == "approve":
            self.resolve_pending(str(data.get("id")), True, bool(data.get("trust")))
        elif action == "decline":
            self.resolve_pending(str(data.get("id")), False, False)
        elif action == "disconnect":
            target = self.sessions.get(str(data.get("id")))
            if target:
                await target.kick("Disconnected by the PC")
        elif action == "disconnect_all":
            for s in list(self.sessions.values()):
                await s.kick("Disconnected by the PC")
        elif action == "view_only":
            target = self.sessions.get(str(data.get("id")))
            if target:
                await target.set_view_only(bool(data.get("value")))
        elif action == "revoke":
            client_id = str(data.get("clientId"))
            if self.config.remove_trusted(client_id):
                self.log("Trusted device removed", "security")
                for s in list(self.sessions.values()):
                    if s.client_id == client_id and s.trusted:
                        await s.kick("Access revoked")
        elif action == "settings":
            self._apply_settings(data.get("values") or {})
        elif action == "autostart":
            winutil.set_autostart(bool(data.get("value")))
        elif action == "startup_settings":
            winutil.open_startup_settings()
        elif action == "firewall":
            ok = winutil.add_firewall_rules(self.port, DISCOVERY_PORT)
            self.log("Firewall rule requested" if ok else "Firewall rule was not added", "security")
        elif action == "elevate":
            if winutil.relaunch_as_admin():
                self.call_ui("quit")
        elif action == "show":
            self.call_ui("show")
        elif action == "clear_activity":
            self.activity.clear()
        else:
            return {"ok": False, "error": "unknown action"}
        self.changed()
        return {"ok": True}

    def _apply_settings(self, values: dict[str, Any]) -> None:
        updates: dict[str, Any] = {}
        if "requireApproval" in values:
            updates["require_approval"] = bool(values["requireApproval"])
        if "allowInput" in values:
            updates["allow_input"] = bool(values["allowInput"])
        if "allowAudio" in values:
            updates["allow_audio"] = bool(values["allowAudio"])
        if "quality" in values:
            updates["quality"] = max(30, min(90, int(values["quality"])))
        if "fps" in values:
            updates["fps"] = max(5, min(60, int(values["fps"])))
        if "maxWidth" in values:
            updates["max_width"] = max(640, min(3840, int(values["maxWidth"])))
        if "deviceName" in values:
            name = str(values["deviceName"]).strip()[:48]
            if name:
                updates["device_name"] = name
        if updates:
            self.config.update(**updates)
            self.log("Settings updated", "info")
        if "allowAudio" in values and not values["allowAudio"]:
            for s in list(self.sessions.values()):
                if s.audio and self.loop:
                    asyncio.ensure_future(s.set_audio(False, reason="disabled"))
        if "showUacPrompts" in values:
            self._apply_uac(bool(values["showUacPrompts"]))

    # ------------------------------------------------------------ UAC prompts
    def _apply_uac(self, on: bool, announce: bool = True) -> bool:
        """Show UAC prompts on the normal desktop (so phones can see them), or undo that.

        Only possible while Orbit runs as administrator. The original Windows policy is
        saved in the config first, so it is restored even after a crash.
        """
        if on:
            if not winutil.is_admin():
                # Keep the user's choice: it takes effect the next time Orbit runs as administrator.
                self.config.update(show_uac_prompts=True)
                if announce:
                    self.log("Admin prompts will appear on the phone after Restart as admin", "warning")
                return False
            if winutil.uac_prompts_visible() and self.config.get("uac_restore"):
                self.config.update(show_uac_prompts=True)
                return True
            previous = winutil.show_uac_on_desktop()
            if previous is None:
                self.config.update(show_uac_prompts=False)
                self.log("Windows did not allow changing the admin prompt setting", "warning")
                return False
            if not self.config.get("uac_restore"):
                self.config.update(uac_restore=previous)
            self.config.update(show_uac_prompts=True)
            if announce:
                self.log("Admin prompts (UAC) now appear on the phone", "security")
            return True
        self.config.update(show_uac_prompts=False)
        return self._restore_uac(announce)

    def _restore_uac(self, announce: bool = True) -> bool:
        previous = self.config.get("uac_restore")
        if not previous:
            return True
        if winutil.restore_uac(previous):
            self.config.update(uac_restore=None)
            if announce:
                self.log("Admin prompts (UAC) are back on the secure desktop", "security")
            return True
        if announce:
            self.log("Restart Orbit as administrator to restore the admin prompt setting", "warning")
        return False

    def _recover_uac(self) -> None:
        """A previous run changed UAC and didn't undo it (crash, power loss): undo it now."""
        if self.config.get("uac_restore") and not self.config.get("show_uac_prompts"):
            self._restore_uac(announce=False)

    def shutdown(self) -> None:
        """Called when Orbit exits: stop sound and put Windows' UAC setting back."""
        self.audio.close()
        if self.config.get("uac_restore"):
            self._restore_uac(announce=False)
