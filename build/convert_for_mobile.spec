# PyInstaller spec for the standalone Convert for Mobile tool.
# Build:  pyinstaller build/convert_for_mobile.spec
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent

datas = []
_vendor = ROOT / "vendor" / "ffmpeg"
if _vendor.exists():
    datas.append((str(_vendor), "vendor/ffmpeg"))

hiddenimports = ["Qt"]

a = Analysis(
    [str(ROOT / "convert_for_mobile.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=["tkinter", "matplotlib", "scipy", "pytest", "IPython", "pandas",
              "moderngl", "av", "NodeGraphQt"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ConvertForMobile",
    console=False,
    icon=str(ROOT / "assets" / "vcomp.ico") if (ROOT / "assets" / "vcomp.ico").exists() else None,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="ConvertForMobile",
)
