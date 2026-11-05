"""Network endpoints running on a background event loop.

* Phone endpoint  — TLS (wss://) on all interfaces, port 47800 by default. The certificate
  carries the host identity key that phones pin; inside it runs the E2E channel from secure.py.
* Dashboard endpoint — plain HTTP bound to 127.0.0.1 only (ephemeral port), token protected.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import secrets
import threading
from pathlib import Path

from aiohttp import WSMsgType, web

from .config import DISCOVERY_PORT
from .core import HostCore
from .discovery import start_discovery
from .paths import web_dir
from .secure import HandshakeError, server_handshake, tls_context
from .session import Session

log = logging.getLogger("orbit.server")
LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".js")


def _is_local(request: web.Request) -> bool:
    if request.remote not in LOOPBACK:
        return False
    host = (request.host or "").split(":")[0].strip("[]").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def build_phone_app(core: HostCore) -> web.Application:
    app = web.Application(client_max_size=256 * 1024)

    async def index(_: web.Request) -> web.Response:
        return web.Response(
            text=f"Orbit host {core.public_info()['version']} is running on this PC. "
            "Open the Orbit app on your phone to connect.",
            content_type="text/plain",
        )

    async def info(_: web.Request) -> web.Response:
        return web.json_response(core.public_info(), headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})

    async def client_ws(request: web.Request) -> web.StreamResponse:
        ws = web.WebSocketResponse(max_msg_size=512 * 1024, heartbeat=15.0, compress=False)
        await ws.prepare(request)
        remote = request.remote or "?"
        try:
            msg = await ws.receive(timeout=15)
            if msg.type != WSMsgType.TEXT:
                await ws.close()
                return ws
            hello = json.loads(msg.data)
            reply, channel, th = server_handshake(core.identity, core.device_id, core.name, hello)
        except (asyncio.TimeoutError, ValueError, HandshakeError) as exc:
            log.info("handshake with %s failed: %s", remote, exc)
            if not ws.closed:
                await ws.close()
            return ws
        await ws.send_str(json.dumps(reply))
        await Session(core, ws, channel, th, remote).run()
        return ws

    app.router.add_get("/", index)
    app.router.add_get("/api/info", info)
    app.router.add_get("/ws", client_ws)
    return app


def build_admin_app(core: HostCore) -> web.Application:
    root = web_dir().resolve()
    app = web.Application(client_max_size=256 * 1024)

    def _authorized(request: web.Request, token: str | None) -> bool:
        return _is_local(request) and bool(token) and secrets.compare_digest(str(token), core.admin_token)

    async def admin_ws(request: web.Request) -> web.StreamResponse:
        if not _authorized(request, request.query.get("token")):
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(heartbeat=20.0)
        await ws.prepare(request)
        core.admin_sockets.add(ws)
        await ws.send_json(core.snapshot())
        try:
            async for _ in ws:
                pass
        finally:
            core.admin_sockets.discard(ws)
        return ws

    async def admin_action(request: web.Request) -> web.Response:
        if not _authorized(request, request.headers.get("X-Orbit-Token")):
            raise web.HTTPForbidden()
        try:
            data = await request.json()
        except ValueError:
            raise web.HTTPBadRequest()
        if not isinstance(data, dict):
            raise web.HTTPBadRequest()
        return web.json_response(await core.handle_action(data))

    async def host_file(request: web.Request) -> web.StreamResponse:
        if not _is_local(request):
            raise web.HTTPForbidden()
        rel = request.match_info.get("path") or "host.html"
        target = (root / rel).resolve()
        if root not in target.parents or not target.is_file():
            raise web.HTTPNotFound()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        return web.FileResponse(target, headers={"Cache-Control": "no-cache", "Content-Type": ctype})

    async def root_redirect(_: web.Request) -> web.Response:
        raise web.HTTPFound("/host/")

    app.router.add_get("/", root_redirect)
    app.router.add_get("/api/host/ws", admin_ws)
    app.router.add_post("/api/host/action", admin_action)
    app.router.add_get("/host/", host_file)
    app.router.add_get("/host/{path:.+}", host_file)
    return app


def _bound_port(site: web.TCPSite) -> int:
    server = getattr(site, "_server", None)
    if server and server.sockets:
        return int(server.sockets[0].getsockname()[1])
    return 0


class HostServer:
    """Runs the aiohttp server and LAN discovery on a dedicated event-loop thread."""

    def __init__(self, core: HostCore, bind: str = "0.0.0.0") -> None:
        self.core = core
        self.bind = bind
        self.port = core.port
        self.admin_port = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self._admin_runner: web.AppRunner | None = None
        self._discovery = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="orbit-server", daemon=True)

    def start(self, timeout: float = 15.0) -> None:
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("server did not start in time")
        if self._error:
            raise self._error

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self.core.loop = loop
        try:
            loop.run_until_complete(self._start())
        except BaseException as exc:  # surface bind errors to the caller
            self._error = exc
            self._ready.set()
            loop.close()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    async def _start(self) -> None:
        ssl_ctx = tls_context(self.core.identity_path, self.core.identity)
        self._runner = web.AppRunner(build_phone_app(self.core), access_log=None, handle_signals=False)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host=self.bind, port=self.port, ssl_context=ssl_ctx)
        await site.start()
        self.port = _bound_port(site) or self.port
        self.core.port = self.port
        log.info("phone endpoint (TLS) on %s:%s", self.bind, self.port)

        self._admin_runner = web.AppRunner(build_admin_app(self.core), access_log=None, handle_signals=False)
        await self._admin_runner.setup()
        admin_site = web.TCPSite(self._admin_runner, host="127.0.0.1", port=0)
        await admin_site.start()
        self.admin_port = _bound_port(admin_site)
        log.info("dashboard on http://127.0.0.1:%s/host/", self.admin_port)
        if self.bind != "127.0.0.1":
            self._discovery = await start_discovery(DISCOVERY_PORT, self.core.public_info)

    def call(self, coro, timeout: float = 10.0):
        if not self._loop:
            raise RuntimeError("server not running")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def stop(self) -> None:
        loop = self._loop
        if not loop or not loop.is_running():
            return

        async def _shutdown() -> None:
            for session in list(self.core.sessions.values()):
                await session.kick("The PC closed Orbit")
            if self._discovery:
                self._discovery.close()
            for ws in list(self.core.admin_sockets):
                await ws.close()
            if self._runner:
                await self._runner.cleanup()
            if self._admin_runner:
                await self._admin_runner.cleanup()

        try:
            asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(8)
        except Exception as exc:
            log.debug("shutdown: %s", exc)
        loop.call_soon_threadsafe(loop.stop)
        self._thread.join(timeout=5)
