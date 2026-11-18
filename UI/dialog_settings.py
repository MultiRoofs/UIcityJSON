"""Settings dialog: location of the Roofer and cjseq executables."""

from __future__ import annotations

# These are mainly for working with the operating system and paths.
import os
import shutil
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QDialog, QFileDialog, QLineEdit, QMessageBox

from UI.resource_utils import resource_path

SETTINGS_ROOFER_PATH = "roofer/path"
SETTINGS_CJSEQ_PATH = "cjseq/path"
SETTINGS_ORG = "Multiroof"
SETTINGS_APP = "CityJSONGenerator"


def _windows_user_path_entries() -> list[Path]:
    """Return directories from the current user's Windows PATH."""
    if os.name != "nt":
        return []
    user_path = ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            user_path, _ = winreg.QueryValueEx(key, "Path")
    except (ImportError, OSError):
        # The process PATH already includes inherited user entries in most
        # launch scenarios; retain it as a fallback for portable installs.
        user_path = os.environ.get("PATH", "")
    entries: list[Path] = []
    for entry in user_path.split(os.pathsep):
        entry = os.path.expandvars(entry.strip().strip('"'))
        if entry:
            entries.append(Path(entry).expanduser())
    return entries


def find_roofer_in_path() -> Path | None:
    """Find Roofer in the Windows user PATH, then in the normal PATH."""
    try:
        candidates = ("roofer.exe", "roofer")

        if os.name == "nt":
            for directory in _windows_user_path_entries():
                for name in candidates:
                    candidate = directory / name
                    if candidate.is_file():
                        return candidate

        found = shutil.which("roofer.exe") or shutil.which("roofer")
        return Path(found) if found else None
    except (OSError, TypeError, ValueError):
        # Missing/inaccessible environment information must fall back to the
        # manual executable selector instead of terminating the application.
        return None


def find_cjseq() -> Path | None:
    """Locate cjseq via explicit override, PATH, then Cargo's bin folder."""
    override = os.environ.get("CJSEQ_PATH", "").strip().strip('"')
    if override and Path(override).is_file():
        return Path(override)
    found = shutil.which("cjseq") or shutil.which("cjseq.exe")
    if found:
        return Path(found)
    cargo_home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo"))
    for name in ("cjseq", "cjseq.exe"):
        candidate = cargo_home / "bin" / name
        if candidate.is_file() and (os.name == "nt" or os.access(candidate, os.X_OK)):
            return candidate
    return None


def executable_problem(path: Path) -> str | None:
    """Why ``path`` cannot be used as an executable, or None when it can."""
    if not path.is_file():
        return "This path does not point to an existing file."
    if os.name != "nt" and not os.access(path, os.X_OK):
        return "The file exists but has no execution permission (chmod +x)."
    return None


class DialogSettings(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        uic.loadUi(resource_path("dialogSettings.ui"), self)

        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)

        saved_path = self.settings.value(SETTINGS_ROOFER_PATH, "", type=str)
        detected_roofer = find_roofer_in_path()
        self.le_roofer.setText(saved_path or (str(detected_roofer) if detected_roofer else ""))
        saved_cjseq = self.settings.value(SETTINGS_CJSEQ_PATH, "", type=str)
        detected_cjseq = find_cjseq()
        self.le_cjseq.setText(saved_cjseq or (str(detected_cjseq) if detected_cjseq else ""))

        self.pb_browse_roofer.clicked.connect(self.browse_roofer)
        self.pb_browse_cjseq.clicked.connect(self.browse_cjseq)
        self.le_roofer.textChanged.connect(self.update_status)
        self.le_cjseq.textChanged.connect(self.update_cjseq_status)
        self.bb_actions.accepted.connect(self.save_settings)
        self.bb_actions.rejected.connect(self.reject)

        self.update_status()
        self.update_cjseq_status()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def path_from(line_edit: QLineEdit) -> Path | None:
        """The (quote-stripped, ~-expanded) path typed into ``line_edit``."""
        text = line_edit.text().strip().strip('"')
        return Path(text).expanduser() if text else None

    def selected_path(self) -> Path | None:
        return self.path_from(self.le_roofer)

    def selected_cjseq_path(self) -> Path | None:
        return self.path_from(self.le_cjseq)

    def update_status(self) -> None:
        """Live feedback about the currently entered Roofer path."""
        path = self.selected_path()

        if path is None:
            self.lb_status.setText("No executable selected yet.")
            return

        self.lb_status.setText(executable_problem(path) or f"Executable found: {path}")

    def update_cjseq_status(self) -> None:
        """Live feedback about the currently entered cjseq path."""
        path = self.selected_cjseq_path()

        if path is None:
            self.lb_cjseq_status.setText("cjseq not found. Install it or select its executable.")
            return

        self.lb_cjseq_status.setText(executable_problem(path) or f"Executable found: {path}")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def browse_executable(self, line_edit: QLineEdit, title: str, windows_filter: str) -> None:
        """Let the user pick an executable and put it into ``line_edit``."""
        current = self.path_from(line_edit)

        if current is not None and current.parent.is_dir():
            start_location = str(current.parent)
        else:
            start_location = str(Path.home())

        file_filter = (
            f"{windows_filter};;Executable files (*.exe);;All files (*)"
            if os.name == "nt"
            else "All files (*)"
        )

        filename, _ = QFileDialog.getOpenFileName(self, title, start_location, file_filter)

        if filename:
            line_edit.setText(filename)

    def browse_roofer(self) -> None:
        self.browse_executable(self.le_roofer, "Select Roofer executable", "Roofer executable (roofer.exe)")

    def browse_cjseq(self) -> None:
        self.browse_executable(self.le_cjseq, "Select cjseq executable", "cjseq executable (cjseq.exe)")

    def save_settings(self) -> None:
        """Validate everything first; store the settings only if all checks pass."""
        roofer_path = self.selected_path()

        if roofer_path is None:
            QMessageBox.warning(self, "Missing Roofer", "Select the Roofer executable.")
            return

        if not roofer_path.is_file():
            QMessageBox.critical(
                self,
                "Invalid Roofer path",
                f"The selected file does not exist:\n\n{roofer_path}",
            )
            return

        if os.name != "nt" and not os.access(roofer_path, os.X_OK):
            QMessageBox.critical(
                self,
                "Not executable",
                (
                    "The selected file does not have execution "
                    "permission.\n\nRun:  chmod +x "
                    f"{roofer_path}"
                ),
            )
            return

        cjseq_path = self.selected_cjseq_path()
        if cjseq_path is not None and not cjseq_path.is_file():
            QMessageBox.critical(self, "Invalid cjseq path", f"The selected file does not exist:\n\n{cjseq_path}")
            return

        if (
            cjseq_path is not None
            and os.name != "nt"
            and not os.access(cjseq_path, os.X_OK)
        ):
            QMessageBox.critical(
                self,
                "cjseq is not executable",
                (
                    "The selected cjseq file does not have execution "
                    "permission.\n\nRun:  chmod +x "
                    f"{cjseq_path}"
                ),
            )
            return

        # A warning, not a hard rule: builds are sometimes renamed
        # (roofer-1.0.exe, roofer_dev, ...).
        if "roofer" not in roofer_path.stem.lower():
            answer = QMessageBox.question(
                self,
                "Unusual executable name",
                (
                    f"'{roofer_path.name}' does not look like the Roofer "
                    "executable.\n\nUse it anyway?"
                ),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if answer != QMessageBox.StandardButton.Yes:
                return

        # Every check passed: always persist the selected path.  PATH
        # detection is only a default; removing this value makes GUI-launched
        # Windows installations lose Roofer when their PATH is different.
        self.settings.setValue(SETTINGS_ROOFER_PATH, str(roofer_path))

        self.settings.setValue(SETTINGS_CJSEQ_PATH, str(cjseq_path) if cjseq_path else "")
        self.settings.sync()

        self.accept()
