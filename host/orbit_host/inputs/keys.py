"""Key names (close to DOM ``KeyboardEvent.key``) mapped to Windows virtual-key codes."""

VK: dict[str, int] = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "shift": 0x10, "control": 0x11,
    "alt": 0x12, "pause": 0x13, "capslock": 0x14, "escape": 0x1B, "space": 0x20,
    "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24, "arrowleft": 0x25,
    "arrowup": 0x26, "arrowright": 0x27, "arrowdown": 0x28, "printscreen": 0x2C,
    "insert": 0x2D, "delete": 0x2E, "meta": 0x5B, "contextmenu": 0x5D, "numlock": 0x90,
    "scrolllock": 0x91, "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF,
    "medianext": 0xB0, "mediaprev": 0xB1, "mediastop": 0xB2, "mediaplaypause": 0xB3,
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0,
    "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}
ALIASES = {
    "ctrl": "control", "win": "meta", "cmd": "meta", "super": "meta", "os": "meta",
    "esc": "escape", "del": "delete", "return": "enter", " ": "space", "spacebar": "space",
    "left": "arrowleft", "right": "arrowright", "up": "arrowup", "down": "arrowdown",
    "pgup": "pageup", "pgdn": "pagedown", "prtsc": "printscreen", "ins": "insert",
    "menu": "contextmenu", "apps": "contextmenu",
}
for _i in range(1, 25):
    VK[f"f{_i}"] = 0x6F + _i
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())
for _d in "0123456789":
    VK[_d] = ord(_d)

EXTENDED = {
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D,
    0x90, 0xA3, 0xA5, 0x6F, 0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3,
}
MODIFIERS = {"control", "alt", "shift", "meta"}


def normalize(name: str) -> str:
    key = str(name)
    key = key.strip().lower() if len(key) > 1 else key.lower()
    return ALIASES.get(key, key)


def vk_for(name: str) -> int | None:
    return VK.get(normalize(name))
