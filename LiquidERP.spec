# PyInstaller: folder dist\LiquidERP z LiquidERP.exe (okno programu, bez konsoli).
# Budowanie: build.bat (albo: .venv\Scripts\pyinstaller LiquidERP.spec --noconfirm)
import os
import re

ROOT = os.path.abspath(SPECPATH)
VERSION = re.search(r'__version__ = "([^"]+)"', open(os.path.join(ROOT, "version.py"), encoding="utf-8").read()).group(1)

a = Analysis(
    [os.path.join(ROOT, "desktop.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "templates"), "templates"), (os.path.join(ROOT, "static"), "static")],
    # Moduły ładowane wewnątrz funkcji – na wszelki wypadek wymienione jawnie.
    hiddenimports=["app", "backup", "calc", "import_ejc", "mailparse", "phone_export", "production", "search",
                   "settings", "paths", "version"],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LiquidERP",
    icon=os.path.join(ROOT, "static", "liquiderp.ico"),
    console=False,
    version=os.path.join(ROOT, "build", "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="LiquidERP")
