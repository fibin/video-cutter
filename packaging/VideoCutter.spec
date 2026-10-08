# PyInstaller spec: builds a single VideoCutter executable with ffmpeg and deno inside.
# Build with:  pyinstaller packaging/VideoCutter.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

import deno

ROOT = Path(SPECPATH).parent
WINDOWS = sys.platform == "win32"

datas = [(str(ROOT / "video_cutter" / "static"), "video_cutter/static")]
binaries = [(deno.find_deno_bin(), ".")]
hiddenimports = collect_submodules("yt_dlp")
for package in ("imageio_ffmpeg", "yt_dlp_ejs", "webview"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception:
        continue  # pywebview is not installed on Linux builds
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    [str(ROOT / "packaging" / "run_video_cutter.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="VideoCutter",
    icon=str(ROOT / "packaging" / "icon.ico"),
    console=not WINDOWS,  # on Windows it is a normal windowed app with no console
    upx=False,
)
