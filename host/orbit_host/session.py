"""One authenticated phone connection: auth, screen streaming and input handling."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from aiohttp import WSMsgType, web

from .capture import MSG_JSON, FrameEncoder, Monitor
from .inputs.keys import normalize
from .secure import HandshakeError, SecureChannel, auth_proof, b64d

if TYPE_CHECKING:
    from .core import HostCore

log = logging.getLogger("orbit.session")
INPUT_TYPES = {"move", "rel", "btn", "wheel", "key", "combo", "text", "sys"}
MAX_INFLIGHT = 2
MAX_AUDIO_QUEUE = 6  # ~120 ms; older packets are dropped instead of building up lag


def _clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return max(low, min(high, v))


def _clean_name(value: Any) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", "", str(value or "")).strip()
    return text[:48] or "Phone"


class Session:
    def __init__(self, core: "HostCore", ws: web.WebSocketResponse, channel: SecureChannel, th: bytes, remote: str) -> None:
        self.id = secrets.token_hex(4)
        self.core = core
        self.ws = ws
        self.channel = channel
        self.th = th
        self.remote = remote
        self.device = "Phone"
        self.client_id = ""
        self.trusted = False
        self.view_only = False
        self.started = time.time()
        self.quality = int(core.config.get("quality"))
        self.max_width = int(core.config.get("max_width"))
        self.fps = int(core.config.get("fps"))
        self.monitor = 1
        self.monitors: list[Monitor] = []
        self.inflight = 0
        self.paused = False
        self.force = True
        self.closed = False
        self.frames = 0
        self.bytes_sent = 0
        self._ack = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._stream_task: asyncio.Task | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"orbit-capture-{self.id}")
        self._encoder = FrameEncoder(core.demo, core.input.cursor_pos)
        self._keys: set[str] = set()
        self._buttons: set[str] = set()
        self._authed = False
        self.audio = False
        self.audio_packets = 0
        self._audio_queued = 0
        self._loop: asyncio.AbstractEventLoop | None = None

    # ---------------------------------------------------------------- wire
    async def _send_plain(self, data: bytes) -> None:
        async with self._send_lock:
            if self.closed or self.ws.closed:
                return
            sealed = self.channel.seal(data)
            await self.ws.send_bytes(sealed)
            self.bytes_sent += len(sealed)

    async def send_json(self, obj: dict[str, Any]) -> None:
        await self._send_plain(bytes([MSG_JSON]) + json.dumps(obj, separators=(",", ":")).encode("utf-8"))

    def _decode(self, data: bytes) -> dict[str, Any] | None:
        plain = self.channel.open(data)
        if not plain or plain[0] != MSG_JSON:
            return None
        obj = json.loads(plain[1:].decode("utf-8"))
        return obj if isinstance(obj, dict) else None

    async def _recv_json(self, timeout: float) -> dict[str, Any] | None:
        msg = await self.ws.receive(timeout=timeout)
        if msg.type != WSMsgType.BINARY:
            return None
        return self._decode(msg.data)

    # ---------------------------------------------------------- lifecycle
    async def run(self) -> None:
        reason = ""
        self._loop = asyncio.get_running_loop()
        try:
            first = await self._recv_json(timeout=180)
            if not first:
                return
            ok, token = await self._authenticate(first)
            if not ok:
                return
            loop = asyncio.get_running_loop()
            self.monitors = await loop.run_in_executor(self._executor, self._encoder.monitors)
            primary = next((m.index for m in self.monitors if m.primary), 1)
            self.monitor = primary
            self._authed = True
            self.core.add_session(self)
            await self.send_json({"t": "auth", "ok": True, "token": token, "session": self.describe()})
            self._stream_task = asyncio.create_task(self._stream_loop())
            reason = await self._receive_loop()
        except asyncio.TimeoutError:
            reason = "timed out"
        except HandshakeError as exc:
            reason = str(exc)
            log.warning("session %s: %s", self.id, exc)
        except (ConnectionError, RuntimeError, ValueError) as exc:
            reason = "connection lost"
            log.info("session %s ended: %s", self.id, exc)
        finally:
            await self.close(reason)

    async def _fail(self, reason: str) -> tuple[bool, None]:
        await self.send_json({"t": "auth", "ok": False, "reason": reason})
        return False, None

    async def _authenticate(self, msg: dict[str, Any]) -> tuple[bool, str | None]:
        if msg.get("t") != "auth":
            return await self._fail("protocol")
        self.client_id = str(msg.get("cid") or "")[:64]
        self.device = _clean_name(msg.get("dev"))
        if self.core.is_locked(self.remote):
            return await self._fail("locked")
        if not self.core.can_accept_session():
            return await self._fail("busy")
        try:
            proof = b64d(str(msg.get("proof") or ""))
        except ValueError:
            return await self._fail("protocol")

        if msg.get("mode") == "token":
            entry = self.core.config.find_trusted(self.client_id) if self.client_id else None
            if entry and secrets.compare_digest(auth_proof(str(entry.get("token")), self.th), proof):
                self.trusted = True
                self.core.config.touch_trusted(self.client_id, self.device)
                return True, None
            return await self._fail("untrusted")

        if not secrets.compare_digest(auth_proof(self.core.code, self.th), proof):
            self.core.record_failure(self.remote)
            return await self._fail("bad_code")
        self.core.clear_failures(self.remote)
        wants_trust = bool(msg.get("trust")) and bool(self.client_id)
        trust = wants_trust
        if self.core.config.get("require_approval"):
            await self.send_json({"t": "pending", "timeout": 60})
            accepted, trust = await self._wait_for_approval(wants_trust)
            if not accepted:
                return await self._fail("declined")
        self.core.rotate_code()  # a session code is single-use
        token = self.core.config.add_trusted(self.client_id, self.device) if trust and self.client_id else None
        self.trusted = bool(token)
        return True, token

    async def _wait_for_approval(self, wants_trust: bool) -> tuple[bool, bool]:
        approval = asyncio.ensure_future(self.core.request_approval(self, wants_trust))
        try:
            while True:
                watcher = asyncio.ensure_future(self.ws.receive())
                done, _ = await asyncio.wait({approval, watcher}, return_when=asyncio.FIRST_COMPLETED)
                if watcher not in done:
                    # Approval finished first: cancel the pending receive and let aiohttp settle
                    # before the main receive loop starts reading from the socket.
                    watcher.cancel()
                    await asyncio.gather(watcher, return_exceptions=True)
                    return approval.result()
                msg = watcher.result()
                if msg.type == WSMsgType.BINARY:
                    obj = self._decode(msg.data)
                    if obj is not None and obj.get("t") != "bye":
                        continue  # e.g. a keep-alive ping while the user decides
                # The phone cancelled or disconnected while waiting.
                self.core.cancel_pending_for(self)
                await asyncio.gather(approval, return_exceptions=True)
                return False, False
        finally:
            if not approval.done():
                approval.cancel()

    async def _receive_loop(self) -> str:
        async for msg in self.ws:
            if msg.type == WSMsgType.BINARY:
                obj = self._decode(msg.data)
                if obj is None:
                    continue
                if obj.get("t") == "bye":
                    return "closed on phone"
                await self._handle(obj)
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED, WSMsgType.ERROR):
                break
            else:
                return "protocol error"
        return "connection closed"

    async def close(self, reason: str = "") -> None:
        if self.closed:
            return
        self.closed = True
        self._stop_audio()
        self.core.cancel_pending_for(self)
        if self._stream_task:
            self._stream_task.cancel()
            await asyncio.gather(self._stream_task, return_exceptions=True)
        self._release_all()
        if self._authed:
            self.core.remove_session(self, reason)
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(self._executor, self._encoder.close)
        except RuntimeError:
            pass
        self._executor.shutdown(wait=False)
        if not self.ws.closed:
            await self.ws.close()
        self.core.changed()

    async def kick(self, reason: str) -> None:
        try:
            await self.send_json({"t": "bye", "reason": reason})
        except Exception:
            pass
        await self.close(reason)

    async def set_view_only(self, value: bool) -> None:
        self.view_only = value
        if value:
            self._release_all()
        await self.send_json({"t": "control", "viewOnly": self.view_only or not self.core.config.get("allow_input")})
        self.core.log(f"{self.device}: {'view only' if value else 'full control'}", "info")

    # ------------------------------------------------------------- describe
    def describe(self) -> dict[str, Any]:
        return {
            "name": self.core.name,
            "id": self.core.device_id,
            "monitors": [m.as_dict() for m in self.monitors],
            "monitor": self.monitor,
            "quality": self.quality,
            "fps": self.fps,
            "maxWidth": self.max_width,
            "viewOnly": self.view_only or not self.core.config.get("allow_input"),
            "trusted": self.trusted,
            "audio": bool(self.core.config.get("allow_audio")),
        }

    def describe_for_host(self, now: float) -> dict[str, Any]:
        return {
            "id": self.id,
            "device": self.device,
            "ip": self.remote,
            "since": self.started,
            "duration": round(now - self.started),
            "viewOnly": self.view_only,
            "trusted": self.trusted,
            "frames": self.frames,
            "megabytes": round(self.bytes_sent / 1_048_576, 1),
            "audio": self.audio,
        }

    # --------------------------------------------------------------- audio
    async def set_audio(self, on: bool, reason: str = "") -> None:
        """Start or stop sending this PC's sound to the phone and tell the phone the result."""
        if on and not self.core.config.get("allow_audio"):
            on, reason = False, "disabled"
        if on and not self.audio:
            self.audio = True
            self.core.audio.subscribe(self)
            self.core.log(f"{self.device} is listening to this PC", "info")
        elif not on:
            self._stop_audio()
        from .audio import CHANNELS, RATE

        reply: dict[str, Any] = {"t": "audio", "on": self.audio, "rate": RATE, "channels": CHANNELS}
        if reason:
            reply["reason"] = reason
        await self.send_json(reply)
        self.core.changed()

    def _stop_audio(self) -> None:
        if self.audio:
            self.audio = False
            self.core.audio.unsubscribe(self)

    def send_audio(self, packet: bytes) -> None:
        """Called from the capture thread. Never blocks; drops audio rather than adding delay."""
        loop = self._loop
        if loop is None or self.closed or not self.audio or self.paused:
            return
        if self._audio_queued >= MAX_AUDIO_QUEUE:
            return
        self._audio_queued += 1
        try:
            loop.call_soon_threadsafe(self._schedule_audio, packet)
        except RuntimeError:  # loop already closed
            self._audio_queued -= 1

    def _schedule_audio(self, packet: bytes) -> None:
        asyncio.ensure_future(self._send_audio(packet))

    async def _send_audio(self, packet: bytes) -> None:
        try:
            if self.audio and not self.closed:
                await self._send_plain(packet)
                self.audio_packets += 1
        except Exception:
            pass
        finally:
            self._audio_queued = max(0, self._audio_queued - 1)

    def on_audio_unavailable(self, reason: str) -> None:
        """Called from the capture thread when this PC has no sound device to record."""
        loop = self._loop
        if loop is None or self.closed:
            return

        def report() -> None:
            self.audio = False
            asyncio.ensure_future(self.send_json({"t": "audio", "on": False, "reason": "unavailable"}))
            self.core.changed()

        try:
            loop.call_soon_threadsafe(report)
        except RuntimeError:
            pass

    # -------------------------------------------------------------- stream
    async def _stream_loop(self) -> None:
        loop = asyncio.get_running_loop()
        last_cursor: tuple[float, float] | None = None
        while not self.closed:
            started = loop.time()
            if self.paused or self.inflight >= MAX_INFLIGHT:
                try:
                    await asyncio.wait_for(self._ack.wait(), timeout=1.5)
                except asyncio.TimeoutError:
                    self.inflight = 0
                self._ack.clear()
                continue
            force, self.force = self.force, False
            try:
                frame, cursor = await loop.run_in_executor(
                    self._executor, self._encoder.next_frame, self.monitor, self.quality, self.max_width, force
                )
            except Exception as exc:  # capture can fail briefly (UAC, lock screen, mode change)
                log.debug("capture failed: %s", exc)
                await asyncio.sleep(0.5)
                self.force = True
                continue
            if frame is not None:
                self.inflight += 1
                self.frames += 1
                await self._send_plain(frame)
            elif cursor != last_cursor:
                await self.send_json({"t": "cur", "x": round(cursor[0], 5), "y": round(cursor[1], 5)})
            last_cursor = cursor
            interval = 1.0 / max(1, self.fps)
            await asyncio.sleep(max(0.0, interval - (loop.time() - started)))

    # --------------------------------------------------------------- input
    def _monitor(self) -> Monitor:
        if self._encoder.monitor is not None and self._encoder.monitor.index == self.monitor:
            return self._encoder.monitor
        for m in self.monitors:
            if m.index == self.monitor:
                return m
        return self.monitors[0] if self.monitors else Monitor(1, 0, 0, 1920, 1080, True)

    def _can_input(self) -> bool:
        return bool(self.core.config.get("allow_input")) and not self.view_only

    async def _handle(self, m: dict[str, Any]) -> None:
        t = m.get("t")
        if t == "ack":
            self.inflight = max(0, self.inflight - 1)
            self._ack.set()
        elif t == "ping":
            await self.send_json({"t": "pong", "ts": m.get("ts")})
        elif t == "cfg":
            if "quality" in m:
                self.quality = int(_clamp(m["quality"], 20, 95, self.quality))
            if "fps" in m:
                self.fps = int(_clamp(m["fps"], 2, 60, self.fps))
            if "maxWidth" in m:
                self.max_width = int(_clamp(m["maxWidth"], 480, 3840, self.max_width))
            self.force = True
        elif t == "mon":
            index = int(_clamp(m.get("i"), 1, 16, self.monitor))
            if any(mon.index == index for mon in self.monitors):
                self.monitor = index
                self.force = True
                await self.send_json({"t": "mon", "monitor": index, "monitors": [x.as_dict() for x in self.monitors]})
        elif t == "audio":
            await self.set_audio(bool(m.get("on")))
        elif t == "pause":
            self.paused = True
        elif t == "resume":
            self.paused = False
            self.inflight = 0
            self.force = True
            self._ack.set()
        elif t in INPUT_TYPES:
            if self._can_input():
                self._apply_input(t, m)

    def _apply_input(self, t: str, m: dict[str, Any]) -> None:
        inp = self.core.input
        if t == "move":
            mon = self._monitor()
            x = _clamp(m.get("x"), 0.0, 1.0, 0.5)
            y = _clamp(m.get("y"), 0.0, 1.0, 0.5)
            inp.move_abs(mon.left + x * (mon.width - 1), mon.top + y * (mon.height - 1))
        elif t == "rel":
            inp.move_rel(_clamp(m.get("dx"), -8000, 8000), _clamp(m.get("dy"), -8000, 8000))
        elif t == "btn":
            button = str(m.get("b") or "left")
            if button not in ("left", "right", "middle", "back", "forward"):
                return
            action = m.get("a") or "click"
            if action == "down":
                inp.button(button, True)
                self._buttons.add(button)
            elif action == "up":
                inp.button(button, False)
                self._buttons.discard(button)
            else:
                for _ in range(2 if action == "dbl" else 1):
                    inp.button(button, True)
                    inp.button(button, False)
        elif t == "wheel":
            inp.wheel(int(_clamp(m.get("dx"), -2400, 2400)), int(_clamp(m.get("dy"), -2400, 2400)))
        elif t == "key":
            key = str(m.get("k") or "")[:32]
            if not key:
                return
            action = m.get("a") or "press"
            name = normalize(key)
            if action in ("down", "press"):
                if inp.key(key, True) and action == "down":
                    self._keys.add(name)
            if action in ("up", "press"):
                inp.key(key, False)
                self._keys.discard(name)
        elif t == "combo":
            keys = [str(k)[:32] for k in (m.get("keys") or []) if k][:6]
            for key in keys:
                inp.key(key, True)
            for key in reversed(keys):
                inp.key(key, False)
        elif t == "text":
            text = str(m.get("s") or "")[:4000]
            if text:
                inp.text(text)
        elif t == "sys":
            if m.get("a") == "lock" and hasattr(inp, "lock"):
                self._release_all()
                if inp.lock():
                    self.core.log(f"{self.device} locked the PC", "security")

    def _release_all(self) -> None:
        inp = self.core.input
        for button in list(self._buttons):
            try:
                inp.button(button, False)
            except Exception:
                pass
        for key in list(self._keys):
            try:
                inp.key(key, False)
            except Exception:
                pass
        self._buttons.clear()
        self._keys.clear()
