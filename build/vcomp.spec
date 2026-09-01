# PyInstaller spec for VCOMP.  Build:  pyinstaller build/vcomp.spec
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "vcomp" / "render" / "shaders"), "vcomp/render/shaders"),
    (str(ROOT / "vcomp" / "templates" / "builtin"), "vcomp/templates/builtin"),
]
_vendor = ROOT / "vendor" / "ffmpeg"
if _vendor.exists():
    datas.append((str(_vendor), "vendor/ffmpeg"))

hiddenimports = [
    "av", "moderngl", "glcontext", "NodeGraphQt", "Qt",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=["tkinter", "matplotlib", "scipy", "pytest", "IPython", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="VCOMP",
    console=False,
    icon=str(ROOT / "assets" / "vcomp.ico") if (ROOT / "assets" / "vcomp.ico").exists() else None,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="VCOMP",
)
