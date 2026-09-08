"""Settings dialog: location of the Roofer executable."""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QDialog, QFileDialog, QMessageBox

SETTINGS_ROOFER_PATH = "roofer/path"


class DialogSettings(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        ui_file = Path(__file__).resolve().parent / "dialogSettings.ui"
        uic.loadUi(ui_file, self)

        self.settings = QSettings()

        saved_path = self.settings.value(SETTINGS_ROOFER_PATH, "", type=str)
        self.le_roofer.setText(saved_path)

        self.pb_browse_roofer.clicked.connect(self.browse_roofer)
        self.le_roofer.textChanged.connect(self.update_status)
        self.bb_actions.accepted.connect(self.save_settings)
        self.bb_actions.rejected.connect(self.reject)

        self.update_status()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def selected_path(self) -> Path | None:
        text = self.le_roofer.text().strip().strip('"')

        if not text:
            return None

        return Path(text).expanduser()

    def update_status(self) -> None:
        """Live feedback about the currently entered path."""
        path = self.selected_path()

        if path is None:
            self.lb_status.setText(
                "No executable selected yet."
            )
            return

        if not path.is_file():
            self.lb_status.setText(
                "This path does not point to an existing file."
            )
            return

        if os.name != "nt" and not os.access(path, os.X_OK):
            self.lb_status.setText(
                "The file exists but has no execution permission "
                "(chmod +x)."
            )
            return

        self.lb_status.setText(f"Executable found: {path}")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def browse_roofer(self) -> None:
        current = self.selected_path()

        if current is not None and current.parent.is_dir():
            start_location = str(current.parent)
        else:
            start_location = str(Path.home())

        if os.name == "nt":
            file_filter = (
                "Roofer executable (roofer.exe);;"
                "Executable files (*.exe);;"
                "All files (*)"
            )
        else:
            file_filter = "All files (*)"

        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Roofer executable",
            start_location,
            file_filter,
        )

        if filename:
            self.le_roofer.setText(filename)

    def save_settings(self) -> None:
        roofer_path = self.selected_path()

        if roofer_path is None:
            QMessageBox.warning(
                self,
                "Missing Roofer",
                "Select the Roofer executable.",
            )
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

        self.settings.setValue(SETTINGS_ROOFER_PATH, str(roofer_path))
        self.settings.sync()

        self.accept()
