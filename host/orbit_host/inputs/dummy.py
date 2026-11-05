"""No-op backend for development on non-Windows machines (tracks a fake cursor)."""

from __future__ import annotations

import logging

log = logging.getLogger("orbit.input")


class DummyInput:
    name = "dummy"

    def __init__(self) -> None:
        self._pos = [800, 450]
        self.events: list[tuple] = []

    def _record(self, *event) -> None:
        self.events.append(event)
        if len(self.events) > 500:
            del self.events[:250]
        log.debug("input %s", event)

    def virtual_screen(self) -> tuple[int, int, int, int]:
        return 0, 0, 1600, 900

    def cursor_pos(self) -> tuple[int, int] | None:
        return int(self._pos[0]), int(self._pos[1])

    def move_abs(self, x: float, y: float) -> None:
        self._pos = [max(0, min(1599, x)), max(0, min(899, y))]
        self._record("move", int(x), int(y))

    def move_rel(self, dx: float, dy: float) -> None:
        self.move_abs(self._pos[0] + dx, self._pos[1] + dy)

    def button(self, button: str, down: bool) -> None:
        self._record("button", button, down)

    def wheel(self, dx: int, dy: int) -> None:
        self._record("wheel", dx, dy)

    def key(self, name: str, down: bool) -> bool:
        self._record("key", name, down)
        return True

    def text(self, text: str) -> None:
        self._record("text", text)

    def lock(self) -> bool:
        self._record("lock")
        return True
