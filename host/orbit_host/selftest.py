"""End-to-end self-test: capture, input injection and the encrypted protocol.

Used by CI on a real Windows runner (both from source and from the packaged
exe):  ``Orbit.exe --selftest result.json``.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any


def run(output: str | None = None, demo: bool = False) -> int:
    results: dict[str, Any] = {"platform": platform.platform(), "python": sys.version.split()[0], "frozen": bool(getattr(sys, "frozen", False)), "steps": {}}
    ok = True

    def step(name: str, fn) -> None:
        nonlocal ok
        started = time.perf_counter()
        try:
            detail = fn()
            results["steps"][name] = {"ok": True, "ms": round((time.perf_counter() - started) * 1000), "detail": detail}
        except Exception as exc:
            ok = False
            results["steps"][name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:]}

    tmp = tempfile.mkdtemp(prefix="orbit-selftest-")
    os.environ["ORBIT_DATA_DIR"] = tmp

    from . import __version__, winutil

    results["version"] = __version__
    winutil.set_dpi_awareness()

    def capture_step():
        from .capture import FrameEncoder
        from .inputs import create_backend

        backend = create_backend(demo)
        enc = FrameEncoder(demo, backend.cursor_pos)
        mons = [m.as_dict() for m in enc.monitors()]
        frame, cursor = enc.next_frame(1, 70, 1600, True)
        assert frame and frame[17:19] == b"\xff\xd8", "no JPEG produced"
        t0 = time.perf_counter()
        for _ in range(5):
            enc.next_frame(1, 70, 1600, True)
        per_frame = (time.perf_counter() - t0) / 5 * 1000
        enc.close()
        return {"monitors": mons, "frameBytes": len(frame), "encodeMs": round(per_frame, 1), "cursor": cursor}

    def input_step():
        from .inputs import create_backend

        backend = create_backend(demo)
        vx, vy, vw, vh = backend.virtual_screen()
        before = backend.cursor_pos()
        target = (vx + vw // 3, vy + vh // 3)
        backend.move_abs(*target)
        time.sleep(0.15)
        after = backend.cursor_pos()
        backend.move_rel(25, 10)
        time.sleep(0.15)
        rel = backend.cursor_pos()
        assert after is not None and abs(after[0] - target[0]) <= 2 and abs(after[1] - target[1]) <= 2, f"cursor at {after}, expected {target}"
        assert rel is not None and abs(rel[0] - target[0] - 25) <= 2 and abs(rel[1] - target[1] - 10) <= 2, f"relative move ended at {rel}"
        if before:
            backend.move_abs(*before)
        return {"backend": backend.name, "virtualScreen": [vx, vy, vw, vh], "target": target, "after": after, "relative": rel}

    def protocol_step():
        from .config import Config
        from .core import HostCore
        from .server import HostServer
        from .testclient import TestClient

        cfg = Config.load(Path(tmp) / "config.json")
        cfg.update(require_approval=False)
        core = HostCore(cfg, Path(tmp), demo=demo, port=0)
        server = HostServer(core, bind="127.0.0.1")
        server.start()
        detail: dict[str, Any] = {"port": server.port, "fingerprint": core.fingerprint}

        async def scenario():
            import aiohttp

            used_code = ""
            url = f"wss://127.0.0.1:{server.port}/ws"
            async with TestClient(url) as bad:
                await bad.auth_with_code("000000" if core.code != "000000" else "111111")
                kind, msg = await bad.recv()
                assert kind == "json" and msg["ok"] is False and msg["reason"] == "bad_code", msg
            async with TestClient(url) as client:
                assert client.host_fingerprint == core.fingerprint
                used_code = core.code
                await client.auth_with_code(core.code, trust=True)
                kind, msg = await client.recv()
                assert kind == "json" and msg["t"] == "auth" and msg["ok"], msg
                token = msg["token"]
                assert token, "no trust token issued"
                detail["monitors"] = len(msg["session"]["monitors"])
                frame = None
                for _ in range(20):
                    kind, payload = await client.recv()
                    if kind == "frame":
                        frame = payload
                        break
                assert frame and frame["jpeg"][:2] == b"\xff\xd8", "no frame received"
                detail["frame"] = {k: frame[k] for k in ("w", "h", "seq")} | {"bytes": len(frame["jpeg"])}
                await client.send({"t": "ack", "s": frame["seq"]})
                await client.send({"t": "ping", "ts": 42})
                for _ in range(20):
                    kind, payload = await client.recv()
                    if kind == "json" and payload.get("t") == "pong":
                        assert payload["ts"] == 42
                        break
                else:
                    raise AssertionError("no pong")
                # Sound: ask for the PC's audio and expect encrypted PCM packets.
                core.audio.force_tone = True  # CI runners usually have no playback device
                await client.send({"t": "audio", "on": True})
                audio_reply, audio = None, None
                for _ in range(80):
                    kind, payload = await client.recv()
                    if kind == "json" and payload.get("t") == "audio":
                        audio_reply = payload
                    elif kind == "audio":
                        audio = payload
                    elif kind == "frame":
                        await client.send({"t": "ack", "s": payload["seq"]})
                    if audio_reply and audio:
                        break
                assert audio_reply and audio_reply["on"], f"audio not enabled: {audio_reply}"
                assert audio and audio["bits"] == 16 and len(audio["pcm"]) == 960 * 2 * audio["channels"], audio and {k: audio[k] for k in ("rate", "channels", "bits")}
                await client.send({"t": "audio", "on": False})
                for _ in range(80):
                    kind, payload = await client.recv()
                    if kind == "json" and payload.get("t") == "audio" and not payload["on"]:
                        break
                    if kind == "frame":
                        await client.send({"t": "ack", "s": payload["seq"]})
                else:
                    raise AssertionError("audio did not stop")
                assert core.audio.listeners == 0, "audio hub still has listeners"
                detail["audio"] = {"rate": audio["rate"], "channels": audio["channels"], "bytes": len(audio["pcm"])}
                await client.send({"t": "bye"})
            async with TestClient(url, pin=core.fingerprint) as again:
                assert again.tls_fingerprint == core.fingerprint
                await again.auth_with_token(token, "selftest")
                kind, msg = await again.recv()
                assert kind == "json" and msg["ok"], f"trusted reconnect failed: {msg}"
                await again.send({"t": "bye"})

            # A phone that pinned a different key must refuse to talk to this host.
            try:
                async with TestClient(url, pin="0000 0000 0000 0000"):
                    raise AssertionError("connected despite a wrong pinned key")
            except ConnectionError:
                detail["pinning"] = "ok"

            # Approval flow: the PC must accept a code-based request before streaming starts.
            assert core.code != used_code, "session code was not rotated after use"
            cfg.update(require_approval=True)
            async with TestClient(url) as asker:
                await asker.auth_with_code(core.code, cid="approval-test")
                kind, msg = await asker.recv()
                assert kind == "json" and msg["t"] == "pending", msg
                for _ in range(40):
                    if core.pending:
                        break
                    await asyncio.sleep(0.05)
                request_id = next(iter(core.pending))
                async with aiohttp.ClientSession() as http:
                    async with http.post(
                        f"http://127.0.0.1:{server.admin_port}/api/host/action",
                        json={"action": "approve", "id": request_id},
                        headers={"X-Orbit-Token": core.admin_token},
                    ) as resp:
                        assert resp.status == 200 and (await resp.json())["ok"], resp.status
                kind, msg = await asker.recv()
                assert kind == "json" and msg["ok"], f"approved session failed: {msg}"
                for _ in range(20):
                    kind, payload = await asker.recv()
                    if kind == "frame":
                        break
                else:
                    raise AssertionError("no frame after approval")
                await asker.send({"t": "key", "k": "Shift", "a": "press"})
                await asker.send({"t": "ping", "ts": 7})
                for _ in range(20):
                    kind, payload = await asker.recv()
                    if kind == "json" and payload.get("t") == "pong":
                        break
                else:
                    raise AssertionError("session died after approval")
                await asker.send({"t": "bye"})
            detail["approval"] = "ok"

        try:
            asyncio.run(asyncio.wait_for(scenario(), 40))
        finally:
            server.stop()
        return detail

    def audio_device_step():
        """Informational: is there a playback device whose sound can be captured?"""
        if demo or sys.platform != "win32":
            return {"skipped": "not Windows"}
        try:
            import soundcard as sc

            speaker = sc.default_speaker()
            return {"device": str(speaker.name), "loopback": True}
        except Exception as exc:  # no audio endpoint on many CI runners
            return {"device": None, "note": f"{type(exc).__name__}: {exc}"[:200]}

    step("capture", capture_step)
    step("input", input_step)
    step("protocol", protocol_step)
    step("audio_device", audio_device_step)
    results["ok"] = ok
    text = json.dumps(results, indent=2, default=str)
    if output:
        Path(output).write_text(text, "utf-8")
    if sys.stdout:
        try:
            print(text)
        except Exception:
            pass
    return 0 if ok else 1
