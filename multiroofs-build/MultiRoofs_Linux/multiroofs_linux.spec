# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

# Layout:
#   <project_root>/
#     main.py
#     UI/
#       resources/   (logos and MultiRoof.png)
#     multiroofs-build/
#       MultiRoofs_Linux/   <- build_dir (this spec file)
build_dir = Path(SPEC).resolve().parent
project_root = build_dir.parent.parent
ui_dir = project_root / "UI"
resources_dir = ui_dir / "resources"
icon_file = resources_dir / "uicityjson_icon.png"

for required in (project_root / "main.py", ui_dir, icon_file):
    if not required.exists():
        raise SystemExit(f"Required path not found: {required}")

datas = [
    (str(ui_dir / "mainWindow.ui"), "UI"),
    (str(ui_dir / "dialogSettings.ui"), "UI"),
    (str(ui_dir / "dialogAbout.ui"), "UI"),
    # Also available at icons/MultiRoof.png inside the app, for code that loads it from there
    (str(icon_file), "icons"),
]

# Bundle everything in UI/resources, keeping subfolders
for resource in resources_dir.rglob("*"):
    if resource.is_file():
        destination = Path("UI") / "resources" / resource.parent.relative_to(resources_dir)
        datas.append((str(resource), str(destination)))

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MultiRoofs",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MultiRoofs",
)
