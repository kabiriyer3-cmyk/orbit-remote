"""Input injection backends."""

from __future__ import annotations

import sys


def create_backend(demo: bool = False):
    if sys.platform == "win32" and not demo:
        from .windows import WindowsInput

        return WindowsInput()
    from .dummy import DummyInput

    return DummyInput()
