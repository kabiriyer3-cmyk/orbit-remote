# PyInstaller spec for the Windows host: one self-contained, windowed Orbit.exe.
# Build:  pyinstaller orbit.spec --noconfirm
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [("orbit_host/web", "web")]
datas += collect_data_files("webview")

hiddenimports = ["pystray._win32", "PIL.ImageDraw"]
hiddenimports += collect_submodules("webview.platforms")
hiddenimports += collect_submodules("orbit_host")

a = Analysis(
    ["run_orbit.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "unittest", "pydoc", "test", "webview.platforms.qt", "webview.platforms.gtk", "webview.platforms.cocoa", "webview.platforms.android", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Orbit",
    icon="../assets/orbit.ico",
    version="version_info.txt",
    console=False,
    disable_windowed_traceback=False,
    upx=False,
    runtime_tmpdir=None,
)
