#!/usr/bin/env bash
set -euo pipefail

# ============================================================
#  MultiRoofs installer for Linux
#
#  Usage:
#    ./install_multiroofs.sh                    install for the current user (no root)
#    sudo ./install_multiroofs.sh --system      install for all users
#    ./install_multiroofs.sh --uninstall        remove the user installation
#    sudo ./install_multiroofs.sh --system --uninstall
#
#  Optional last argument: what to install, either the MultiRoofs
#  folder (PyInstaller output) or MultiRoofs-x86_64.AppImage.
#  If omitted, the script looks next to itself.
# ============================================================

APP_ID="multiroofs"
APP_NAME="MultiRoofs CityJSON Generator"
APP_COMMENT="Generate LoD 2.2 CityJSON building models with Roofer"
EXE_NAME="MultiRoofs"

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
MODE="user"
ACTION="install"
SOURCE=""

usage() {
  sed -n '/^#  Usage:/,/^#  If omitted/p' "$0" | sed -e 's/^#  \{0,1\}//' -e 's/^#$//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user)      MODE="user" ;;
    --system)    MODE="system" ;;
    --uninstall) ACTION="uninstall" ;;
    -h|--help)   usage; exit 0 ;;
    -*)          echo "Unknown option: $1"; usage; exit 1 ;;
    *)           SOURCE="$1" ;;
  esac
  shift
done

# ---------- Privileges ----------
if [[ "$MODE" == "system" && $EUID -ne 0 ]]; then
  echo "A system-wide installation needs root privileges. Run:"
  if [[ "$ACTION" == "uninstall" ]]; then
    echo "  sudo $0 --system --uninstall"
  else
    echo "  sudo $0 --system"
  fi
  echo "Or install for your user only, without root:"
  echo "  $0"
  exit 1
fi
if [[ "$MODE" == "user" && $EUID -eq 0 ]]; then
  echo "Do not use sudo for a user installation."
  echo "Run it as your normal user, or use --system to install for all users."
  exit 1
fi

# ---------- Locations ----------
if [[ "$MODE" == "user" ]]; then
  DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
  INSTALL_DIR="$DATA_HOME/$APP_ID"
  BIN_DIR="$HOME/.local/bin"
  APPS_DIR="$DATA_HOME/applications"
  ICON_ROOT="$DATA_HOME/icons/hicolor"
else
  INSTALL_DIR="/opt/$APP_ID"
  BIN_DIR="/usr/local/bin"
  APPS_DIR="/usr/local/share/applications"
  ICON_ROOT="/usr/local/share/icons/hicolor"
fi
ICON_DIR="$ICON_ROOT/256x256/apps"
LAUNCHER="$BIN_DIR/$APP_ID"
DESKTOP_FILE="$APPS_DIR/$APP_ID.desktop"
ICON_FILE="$ICON_DIR/$APP_ID.png"

refresh_caches() {
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q "$APPS_DIR" 2>/dev/null || true
  fi
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f "$ICON_ROOT" 2>/dev/null || true
  fi
}

# ---------- Uninstall ----------
if [[ "$ACTION" == "uninstall" ]]; then
  rm -rf "$INSTALL_DIR"
  rm -f "$LAUNCHER" "$DESKTOP_FILE" "$ICON_FILE"
  refresh_caches
  echo "$APP_NAME has been removed ($MODE installation)."
  exit 0
fi

# ---------- Find what to install ----------
if [[ -z "$SOURCE" ]]; then
  for candidate in \
      "$SCRIPT_DIR/$EXE_NAME" \
      "$SCRIPT_DIR/dist/$EXE_NAME" \
      "$SCRIPT_DIR/$EXE_NAME-x86_64.AppImage"; do
    if [[ -e "$candidate" ]]; then SOURCE="$candidate"; break; fi
  done
fi
if [[ -z "$SOURCE" || ! -e "$SOURCE" ]]; then
  echo "Nothing to install was found."
  echo "Place the $EXE_NAME folder or $EXE_NAME-x86_64.AppImage next to this script,"
  echo "or pass its path as the last argument."
  exit 1
fi
SOURCE="$(readlink -f "$SOURCE")"

if [[ -d "$SOURCE" ]]; then
  [[ -f "$SOURCE/$EXE_NAME" ]] || { echo "$SOURCE does not contain the $EXE_NAME executable."; exit 1; }
  KIND="folder"
elif [[ "$SOURCE" == *.AppImage ]]; then
  KIND="appimage"
else
  echo "$SOURCE is neither a $EXE_NAME folder nor an AppImage."
  exit 1
fi

# ---------- Find the icon ----------
ICON_SRC=""
for candidate in \
    "$SCRIPT_DIR/$APP_ID.png" \
    "$SOURCE/_internal/UI/resources/uicityjson_icon.png" \
    "$SOURCE/UI/resources/uicityjson_icon.png" \
    "$SCRIPT_DIR/../../UI/resources/uicityjson_icon.png"; do
  if [[ -f "$candidate" ]]; then ICON_SRC="$candidate"; break; fi
done

# ---------- Install ----------
echo "Installing $APP_NAME ($MODE installation) from:"
echo "  $SOURCE"

rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$APPS_DIR"

if [[ "$KIND" == "folder" ]]; then
  cp -a "$SOURCE/." "$INSTALL_DIR/"
  TARGET="$INSTALL_DIR/$EXE_NAME"
  chmod +x "$TARGET"
  cat > "$LAUNCHER" << LAUNCH
#!/bin/sh
exec "$TARGET" "\$@"
LAUNCH
else
  TARGET="$INSTALL_DIR/$EXE_NAME.AppImage"
  install -m 755 "$SOURCE" "$TARGET"
  # AppImages normally need FUSE 2. If it is missing, run without mounting.
  cat > "$LAUNCHER" << LAUNCH
#!/bin/sh
if ! { /sbin/ldconfig -p 2>/dev/null || ldconfig -p 2>/dev/null; } | grep -q 'libfuse\.so\.2'; then
  export APPIMAGE_EXTRACT_AND_RUN=1
fi
exec "$TARGET" "\$@"
LAUNCH
fi
chmod 755 "$LAUNCHER"

if [[ "$MODE" == "system" ]]; then
  chown -R root:root "$INSTALL_DIR"
  chmod -R a+rX "$INSTALL_DIR"
fi

ICON_LINE=""
if [[ -n "$ICON_SRC" ]]; then
  mkdir -p "$ICON_DIR"
  install -m 644 "$ICON_SRC" "$ICON_FILE"
  ICON_LINE="Icon=$APP_ID"
else
  echo "Warning: no icon found, the menu entry will use a generic icon."
fi

cat > "$DESKTOP_FILE" << DESKTOP
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=$APP_COMMENT
Exec="$LAUNCHER"
$ICON_LINE
Terminal=false
Categories=Science;Utility;
DESKTOP
chmod 644 "$DESKTOP_FILE"

refresh_caches

echo
echo "SUCCESS"
echo "Application files: $INSTALL_DIR"
echo "Menu entry:        $DESKTOP_FILE"
echo "Command:           $LAUNCHER"
echo
echo "Start $APP_NAME from the application menu, or run: $APP_ID"

if [[ "$MODE" == "user" ]]; then
  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
      echo
      echo "Note: $BIN_DIR is not in your PATH, so the '$APP_ID' command will only work"
      echo "after you log out and back in (Ubuntu adds it automatically once it exists),"
      echo "or with the full path: $LAUNCHER"
      ;;
  esac
fi
