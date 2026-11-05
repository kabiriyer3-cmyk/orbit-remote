"""Screen capture and JPEG frame encoding."""

from __future__ import annotations

import io
import math
import struct
import sys
import time
import zlib
from dataclasses import dataclass
from typing import Any, Callable

from PIL import Image, ImageDraw

FRAME_HEADER = struct.Struct("<IHHff")  # seq, width, height, cursor x, cursor y (normalized)
MSG_JSON = 0x01
MSG_FRAME = 0x02


@dataclass
class Monitor:
    index: int
    left: int
    top: int
    width: int
    height: int
    primary: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "primary": self.primary,
        }


class MssCapturer:
    """GDI capture via ``mss``. Create and use from a single thread."""

    def __init__(self) -> None:
        import mss

        self._sct = mss.mss()

    def monitors(self) -> list[Monitor]:
        result = []
        for i, m in enumerate(self._sct.monitors[1:], start=1):
            result.append(
                Monitor(i, m["left"], m["top"], m["width"], m["height"], m["left"] == 0 and m["top"] == 0)
            )
        if result and not any(m.primary for m in result):
            result[0].primary = True
        return result

    def grab(self, index: int) -> tuple[tuple[int, int], bytes, Monitor]:
        mons = self._sct.monitors
        if not 1 <= index < len(mons):
            index = 1
        m = mons[index]
        shot = self._sct.grab(m)
        mon = Monitor(index, m["left"], m["top"], m["width"], m["height"])
        return shot.size, shot.bgra, mon

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass


class DemoCapturer:
    """Synthetic desktop used for development on machines without a screen."""

    def __init__(self, cursor: Callable[[], tuple[int, int] | None] | None = None) -> None:
        self._cursor = cursor
        self._t0 = time.time()

    def monitors(self) -> list[Monitor]:
        return [Monitor(1, 0, 0, 1600, 900, True)]

    def grab(self, index: int) -> tuple[tuple[int, int], bytes, Monitor]:
        w, h = 1600, 900
        img = Image.new("RGB", (w, h), (14, 15, 18))
        d = ImageDraw.Draw(img)
        for y in range(0, h, 4):
            shade = int(18 + 22 * y / h)
            d.rectangle([0, y, w, y + 4], fill=(shade, shade, shade + 8))
        t = time.time() - self._t0
        x = int((math.sin(t * 0.8) * 0.5 + 0.5) * (w - 360))
        d.rounded_rectangle([x, 300, x + 360, 520], radius=18, fill=(94, 106, 210))
        d.text((x + 24, 330), "Orbit demo desktop", fill=(255, 255, 255))
        d.text((x + 24, 360), time.strftime("%H:%M:%S"), fill=(230, 232, 255))
        d.rectangle([0, h - 48, w, h], fill=(24, 25, 29))
        for i in range(6):
            d.rounded_rectangle([20 + i * 56, h - 40, 60 + i * 56, h - 8], radius=8, fill=(44, 46, 54))
        pos = self._cursor() if self._cursor else None
        if pos:
            cx, cy = pos
            d.polygon([(cx, cy), (cx, cy + 22), (cx + 6, cy + 16), (cx + 15, cy + 16)], fill=(255, 255, 255))
        return (w, h), img.tobytes("raw", "BGRX"), Monitor(1, 0, 0, w, h, True)

    def close(self) -> None:
        pass


def create_capturer(demo: bool, cursor: Callable[[], tuple[int, int] | None] | None = None):
    if demo:
        return DemoCapturer(cursor)
    try:
        return MssCapturer()
    except Exception:
        if sys.platform == "win32":
            raise
        return DemoCapturer(cursor)


class FrameEncoder:
    """Captures a monitor and encodes changed frames. Use from one worker thread."""

    def __init__(self, demo: bool, cursor_pos: Callable[[], tuple[int, int] | None]) -> None:
        self._demo = demo
        self._cursor_pos = cursor_pos
        self._cap = None
        self._last_sig: int | None = None
        self._seq = 0
        self.monitor: Monitor | None = None

    def _capturer(self):
        if self._cap is None:
            self._cap = create_capturer(self._demo, self._cursor_pos)
        return self._cap

    def monitors(self) -> list[Monitor]:
        return self._capturer().monitors()

    def cursor_normalized(self, mon: Monitor | None) -> tuple[float, float]:
        pos = self._cursor_pos()
        if not pos or mon is None or mon.width <= 0 or mon.height <= 0:
            return -1.0, -1.0
        x = (pos[0] - mon.left) / mon.width
        y = (pos[1] - mon.top) / mon.height
        if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
            return x, y
        return -1.0, -1.0

    def next_frame(self, index: int, quality: int, max_width: int, force: bool) -> tuple[bytes | None, tuple[float, float]]:
        size, raw, mon = self._capturer().grab(index)
        self.monitor = mon
        cursor = self.cursor_normalized(mon)
        sig = zlib.crc32(raw)
        if not force and sig == self._last_sig:
            return None, cursor
        self._last_sig = sig
        img = Image.frombuffer("RGB", size, raw, "raw", "BGRX", 0, 1)
        max_width = max(480, int(max_width))
        if img.width > max_width:
            ratio = max_width / img.width
            target = (max_width, max(1, round(img.height * ratio)))
            if img.width == max_width * 2:
                img = img.reduce(2)
            else:
                img = img.resize(target, Image.BILINEAR, reducing_gap=2.0)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=max(20, min(95, int(quality))), subsampling=2, optimize=False)
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        header = FRAME_HEADER.pack(self._seq, img.width, img.height, cursor[0], cursor[1])
        return bytes([MSG_FRAME]) + header + buf.getvalue(), cursor

    def invalidate(self) -> None:
        self._last_sig = None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.close()
            self._cap = None
