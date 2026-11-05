"""Capture this PC's sound (WASAPI loopback) and fan it out to phones that asked for it.

One shared capture thread serves every session that turned sound on, so the desktop is
only recorded while at least one phone is listening. Audio travels as ``MSG_AUDIO`` packets
on the same end-to-end encrypted channel as the screen and input.

Packet layout (little-endian), sealed exactly like every other message:

    byte 0            MSG_AUDIO (0x03)
    struct "<IBBH"    sample rate, channels, bits per sample (16), sequence
    payload           interleaved signed 16-bit PCM

Capture uses the ``soundcard`` package (WASAPI loopback) when it is available. When no
output device can be opened — a headless CI runner, a machine with no sound card, or a
development box — the hub can emit a quiet test tone instead so the path stays testable.
"""

from __future__ import annotations

import logging
import math
import struct
import sys
import threading
import time
from typing import TYPE_CHECKING

from .capture import MSG_AUDIO

if TYPE_CHECKING:
    from .core import HostCore

log = logging.getLogger("orbit.audio")

RATE = 48000
CHANNELS = 2
BITS = 16
BLOCK = 960  # frames per packet (20 ms at 48 kHz)
_HEADER = struct.Struct("<IBBH")


def _com_init() -> None:
    """Join the multithreaded COM apartment for this capture thread (WASAPI needs COM)."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED; S_FALSE if already in


def _com_uninit() -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.ole32.CoUninitialize()


def _packet(seq: int, pcm: bytes) -> bytes:
    return bytes([MSG_AUDIO]) + _HEADER.pack(RATE, CHANNELS, BITS, seq & 0xFFFF) + pcm


class AudioHub:
    """Shared desktop-audio capture with per-session subscriptions.

    Sessions call ``subscribe``/``unsubscribe`` from the event loop; capture runs on its own
    thread and hands packets to ``session.send_audio``, which must be thread-safe.
    """

    def __init__(self, core: "HostCore", force_tone: bool = False) -> None:
        self.core = core
        self.force_tone = force_tone or core.demo
        self._subs: set = set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.source = "none"

    # ---------------------------------------------------------- subscribe
    @property
    def listeners(self) -> int:
        with self._lock:
            return len(self._subs)

    def subscribe(self, session) -> None:
        with self._lock:
            self._subs.add(session)
            if self._thread is None or not self._thread.is_alive() or self._stop.is_set():
                self._start_locked()

    def _start_locked(self) -> None:
        # Every capture thread gets its own stop flag, so a quick off/on never races with a
        # thread that is still winding down: once a flag is set, that thread is finished.
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,), name="orbit-audio", daemon=True)
        self._thread.start()

    def unsubscribe(self, session) -> None:
        with self._lock:
            self._subs.discard(session)
            if not self._subs:
                self._stop.set()  # never join here: this runs on the event loop

    def close(self) -> None:
        with self._lock:
            self._subs.clear()
            self._stop.set()

    def _dispatch(self, packet: bytes) -> None:
        with self._lock:
            subs = list(self._subs)
        for session in subs:
            try:
                session.send_audio(packet)
            except Exception:  # a single broken session must not stop the stream
                pass

    # ------------------------------------------------------------- thread
    def _run(self, stop: threading.Event) -> None:
        try:
            if self.force_tone:
                self._capture_tone(stop)
                return
            try:
                self._capture_loopback(stop)
            except Exception as exc:
                log.warning("desktop audio capture unavailable: %s", exc)
                if not stop.is_set():
                    self._notify_unavailable(stop, str(exc))
        finally:
            with self._lock:
                stop.set()
                if self._subs and self._stop is stop:
                    self._start_locked()  # someone subscribed while this thread was ending

    def _notify_unavailable(self, stop: threading.Event, reason: str) -> None:
        self.source = "none"
        with self._lock:
            subs = list(self._subs)
            self._subs.clear()
            stop.set()  # later requests start a fresh attempt instead of waiting on this thread
        self.core.log("Sound could not be shared: no playback device was found", "warning")
        for session in subs:
            try:
                session.on_audio_unavailable(reason)
            except Exception:
                pass

    # ----------------------------------------------------- real capture
    def _capture_loopback(self, stop: threading.Event) -> None:
        import warnings

        _com_init()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # soundcard warns about harmless discontinuities
                import numpy as np
                import soundcard as sc

                self.source = "loopback"
                announced = ""
                while not stop.is_set() and self.listeners:
                    speaker = sc.default_speaker()
                    if speaker.name != announced:
                        self.core.log(f"Sharing sound from {speaker.name}", "info")
                        announced = speaker.name
                    mic = sc.get_microphone(str(speaker.id), include_loopback=True)
                    self._record_until_change(stop, sc, np, mic, speaker.id)
                if announced:
                    self.core.log("Stopped sharing sound", "info")
        finally:
            _com_uninit()

    def _record_until_change(self, stop: threading.Event, sc, np, mic, speaker_id: str) -> None:
        """Stream one output device until listeners leave or Windows switches the default output."""
        seq = 0
        silence = _packet(0, b"\x00\x00" * (BLOCK * CHANNELS))
        quiet_run = 0
        next_check = time.monotonic() + 2.0
        with mic.recorder(samplerate=RATE, channels=CHANNELS, blocksize=BLOCK) as rec:
            while not stop.is_set() and self.listeners:
                data = rec.record(numframes=BLOCK)
                if time.monotonic() >= next_check:
                    next_check = time.monotonic() + 2.0
                    try:
                        if sc.default_speaker().id != speaker_id:
                            return  # headphones plugged in, output switched, etc.
                    except Exception:
                        pass
                if data.shape[0] == 0:
                    continue
                if float(np.abs(data).max()) < 1e-4:
                    # A few silent packets keep the phone's playback clock primed, then rest the network.
                    quiet_run += 1
                    if quiet_run <= 3:
                        self._dispatch(silence)
                    continue
                quiet_run = 0
                pcm = (np.clip(data, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
                seq = (seq + 1) & 0xFFFF
                self._dispatch(_packet(seq, pcm))

    # ----------------------------------------------------- test tone
    def _capture_tone(self, stop: threading.Event) -> None:
        """Quiet 440 Hz tone on a real-time schedule (demo mode and the self-test)."""
        import array

        self.source = "tone"
        seq = 0
        phase = 0.0
        step = 2 * math.pi * 440.0 / RATE
        period = BLOCK / RATE
        deadline = time.monotonic()
        while not stop.is_set() and self.listeners:
            samples = array.array("h")
            for _ in range(BLOCK):
                value = int(math.sin(phase) * 32767 * 0.2)
                samples.append(value)
                samples.append(value)
                phase += step
            phase %= 2 * math.pi
            seq = (seq + 1) & 0xFFFF
            self._dispatch(_packet(seq, samples.tobytes()))
            deadline += period
            stop.wait(max(0.0, deadline - time.monotonic()))


__all__ = ["AudioHub", "RATE", "CHANNELS", "BITS", "BLOCK"]
