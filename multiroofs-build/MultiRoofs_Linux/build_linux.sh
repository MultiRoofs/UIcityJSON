#!/usr/bin/env bash
set -euo pipefail

# Layout:
#   <PROJECT_ROOT>/
#     main.py
#     requirements.txt
#     UI/
#       resources/          (logos and uicityjson_icon.png)
#     multiroofs-build/
#       MultiRoofs_Linux/   <- BUILD_DIR (this script)
#         multiroofs_linux.spec
#         AppRun
#         multiroofs.desktop
#         install_multiroofs.sh

BUILD_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PROJECT_ROOT="$(cd "$BUILD_DIR/../.." && pwd)"
VENV_DIR="$PROJECT_ROOT/venv"
ICON_PNG="$PROJECT_ROOT/UI/resources/uicityjson_icon.png"
APP_NAME="MultiRoofs"
RELEASE_NAME="MultiRoofs-linux-x86_64"
APPIMAGE_NAME="MultiRoofs-x86_64.AppImage"

# Build output (build, dist, release, MultiRoofs.AppDir, AppImage) is created next to this script
cd "$BUILD_DIR"

echo "=== MultiRoofs Linux build ==="
echo "Project root: $PROJECT_ROOT"
echo "Build folder: $BUILD_DIR"

# ---------- Check required files ----------
root_files=(
  "main.py"
  "requirements.txt"
  "UI/MainWindow.py"
  "UI/DialogSettings.py"
  "UI/DialogAbout.py"
  "UI/config_io.py"
  "UI/mainWindow.ui"
  "UI/dialogSettings.ui"
  "UI/dialogAbout.ui"
  "UI/resources/logo_interreg.png"
  "UI/resources/logo_ulb.png"
  "UI/resources/logo_mlg.png"
  "UI/resources/uicityjson_icon.png"
)
build_files=(
  "multiroofs_linux.spec"
  "AppRun"
  "multiroofs.desktop"
  "install_multiroofs.sh"
)

missing=0
for f in "${root_files[@]}"; do
  [[ -f "$PROJECT_ROOT/$f" ]] || { echo "Missing required file: $PROJECT_ROOT/$f"; missing=1; }
done
for f in "${build_files[@]}"; do
  [[ -f "$BUILD_DIR/$f" ]] || { echo "Missing required file: $BUILD_DIR/$f"; missing=1; }
done
[[ $missing -eq 0 ]] || exit 1

# ---------- Virtual environment ----------
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "Creating virtual environment in $VENV_DIR..."
  python3 -m venv "$VENV_DIR"
fi
PYTHON="$VENV_DIR/bin/python"

"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r "$PROJECT_ROOT/requirements.txt"

# ---------- PyInstaller ----------
rm -rf build dist release "$APP_NAME.AppDir"
"$PYTHON" -m PyInstaller --noconfirm --clean "$BUILD_DIR/multiroofs_linux.spec"

[[ -x "dist/$APP_NAME/$APP_NAME" ]] || { echo "PyInstaller did not create dist/$APP_NAME/$APP_NAME"; exit 1; }
echo "PyInstaller application created: $BUILD_DIR/dist/$APP_NAME/$APP_NAME"

# ---------- Release package (folder + installer) ----------
mkdir -p "release/$RELEASE_NAME"
cp -a "dist/$APP_NAME" "release/$RELEASE_NAME/$APP_NAME"
cp install_multiroofs.sh "release/$RELEASE_NAME/"
chmod +x "release/$RELEASE_NAME/install_multiroofs.sh"
cp "$ICON_PNG" "release/$RELEASE_NAME/multiroofs.png"
tar -C release -czf "release/$RELEASE_NAME.tar.gz" "$RELEASE_NAME"
echo "Release package created: $BUILD_DIR/release/$RELEASE_NAME.tar.gz"

# ---------- AppDir ----------
mkdir -p "$APP_NAME.AppDir/usr/bin"
cp -a "dist/$APP_NAME" "$APP_NAME.AppDir/usr/bin/"
cp multiroofs.desktop "$APP_NAME.AppDir/"
cp "$ICON_PNG" "$APP_NAME.AppDir/multiroofs.png"
ln -sf multiroofs.png "$APP_NAME.AppDir/.DirIcon"
cp AppRun "$APP_NAME.AppDir/AppRun"
chmod +x "$APP_NAME.AppDir/AppRun"
chmod +x "$APP_NAME.AppDir/usr/bin/$APP_NAME/$APP_NAME"

# ---------- AppImage (optional) ----------
APPIMAGETOOL=""
if command -v appimagetool >/dev/null 2>&1; then
  APPIMAGETOOL="$(command -v appimagetool)"
elif [[ -x "$BUILD_DIR/appimagetool-x86_64.AppImage" ]]; then
  APPIMAGETOOL="$BUILD_DIR/appimagetool-x86_64.AppImage"
fi

if [[ -z "$APPIMAGETOOL" ]]; then
  echo
  echo "PyInstaller build, release package and AppDir are ready."
  echo "appimagetool was not found, so the final AppImage was not created."
  echo "Place appimagetool-x86_64.AppImage in $BUILD_DIR, make it executable,"
  echo "and run ./build_linux.sh again."
  exit 0
fi

ARCH=x86_64 "$APPIMAGETOOL" "$APP_NAME.AppDir" "$APPIMAGE_NAME"

echo
echo "SUCCESS"
echo "Linux application: $BUILD_DIR/dist/$APP_NAME/$APP_NAME"
echo "Release package:   $BUILD_DIR/release/$RELEASE_NAME.tar.gz"
echo "AppImage:          $BUILD_DIR/$APPIMAGE_NAME"
