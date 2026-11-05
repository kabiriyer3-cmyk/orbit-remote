"""Mouse and keyboard injection through the Win32 ``SendInput`` API."""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from .keys import EXTENDED, normalize, vk_for

log = logging.getLogger("orbit.input")

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MAPVK_VK_TO_VSC = 0
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT

_BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),
    "back": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, 1),
    "forward": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, 2),
}


def _send(*inputs: INPUT) -> int:
    if not inputs:
        return 0
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        log.debug("SendInput blocked (%s of %s), error %s", sent, len(inputs), ctypes.get_last_error())
    return sent


def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
    return inp


def _key(vk: int, up: bool) -> INPUT:
    flags = KEYEVENTF_KEYUP if up else 0
    if vk in EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC) & 0xFFFF
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return inp


def _unicode(unit: int, up: bool) -> INPUT:
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0), 0, 0)
    return inp


class WindowsInput:
    name = "sendinput"

    def virtual_screen(self) -> tuple[int, int, int, int]:
        return (
            user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
            max(1, user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
            max(1, user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
        )

    def cursor_pos(self) -> tuple[int, int] | None:
        pt = wintypes.POINT()
        if user32.GetCursorPos(ctypes.byref(pt)):
            return pt.x, pt.y
        return None

    def move_abs(self, x: float, y: float) -> None:
        vx, vy, vw, vh = self.virtual_screen()
        px = min(max(int(round(x)), vx), vx + vw - 1)
        py = min(max(int(round(y)), vy), vy + vh - 1)
        nx = min(65535, ((px - vx) * 65536 + vw - 1) // vw)
        ny = min(65535, ((py - vy) * 65536 + vh - 1) // vh)
        _send(_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny))

    def move_rel(self, dx: float, dy: float) -> None:
        pos = self.cursor_pos()
        if pos is None:
            return
        self.move_abs(pos[0] + dx, pos[1] + dy)

    def button(self, button: str, down: bool) -> None:
        spec = _BUTTONS.get(button)
        if not spec:
            return
        down_flag, up_flag, xbutton = spec
        _send(_mouse(down_flag if down else up_flag, data=xbutton))

    def wheel(self, dx: int, dy: int) -> None:
        events = []
        if dy:
            events.append(_mouse(MOUSEEVENTF_WHEEL, data=int(dy)))
        if dx:
            events.append(_mouse(MOUSEEVENTF_HWHEEL, data=int(dx)))
        _send(*events)

    def key(self, name: str, down: bool) -> bool:
        vk = vk_for(name)
        if vk is None:
            if len(name) == 1 and down:
                self.text(name)
                return True
            return False
        _send(_key(vk, not down))
        return True

    def text(self, text: str) -> None:
        events: list[INPUT] = []
        for ch in text:
            if ch in "\r\n":
                events += [_key(0x0D, False), _key(0x0D, True)]
                continue
            if ch == "\t":
                events += [_key(0x09, False), _key(0x09, True)]
                continue
            data = ch.encode("utf-16-le")
            for i in range(0, len(data), 2):
                unit = int.from_bytes(data[i : i + 2], "little")
                events += [_unicode(unit, False), _unicode(unit, True)]
        for i in range(0, len(events), 64):
            _send(*events[i : i + 64])

    def lock(self) -> bool:
        return bool(user32.LockWorkStation())


__all__ = ["WindowsInput", "normalize"]
