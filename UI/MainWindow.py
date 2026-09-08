"""Main window of the MultiRoofs LoD 2.2 CityJSON generator.

The window drives the Roofer CLI:

    roofer [options] <pointcloud> <polygon-source> <output-directory>
    roofer -c <config.toml> [<pointcloud> <polygon-source>] <output-directory>

The output directory is always passed on the command line - also in
configuration mode - because Roofer requires it as the last positional
argument. Every run gets its own timestamped folder so previous results
are never overwritten.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import QFileInfo, QProcess, QSettings, QSize, Qt, QUrl
from PyQt6.QtGui import QCloseEvent, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFileIconProvider,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
)

from UI import config_io
from UI.config_io import ConfigError
from UI.DialogAbout import DialogAbout
from UI.DialogSettings import DialogSettings, SETTINGS_ROOFER_PATH


CITYJSON_NINJA_URL = "https://ninja.cityjson.org/"

# Roofer writes CityJSONSequence files; the exact extension has changed
# between releases, so several patterns are accepted. Order matters: the
# most specific pattern is reported first.
OUTPUT_PATTERNS = ("*.city.jsonl", "*.jsonl", "*.city.json")

# Only these file extensions are accepted as LiDAR point-cloud files.
LIDAR_SUFFIXES = {".las", ".laz"}

# Temporary run configurations are written next to the original TOML so
# that all other relative paths inside it keep their meaning.
TEMP_CONFIG_PREFIX = ".multiroofs_run_"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        # Load the interface designed in Qt Designer.
        ui_file = Path(__file__).resolve().parent / "mainWindow.ui"
        uic.loadUi(ui_file, self)

        # QSettings remembers application/session settings.
        self.settings = QSettings()

        # QProcess is the connection used by the GUI to start Roofer
        # as an external operating-system process.
        self.process = QProcess(self)
        self.process.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels
        )

        # --- state -----------------------------------------------------
        self.config_path: Path | None = None
        self.config_document = None
        self.config_snapshot: dict[str, str] = {
            "footprint": "",
            "output": "",
        }
        self.config_lidar_snapshot: list[str] = []
        self.config_pointclouds_editable = True

        # LiDAR selection can be one file, multiple files, or one folder.
        self.lidar_files: list[Path] = []
        self.lidar_folder: Path | None = None

        self.output_folder: Path | None = None
        self.generated_files: list[Path] = []

        # Temporary configuration written for the current run, if any.
        self.run_config: Path | None = None
        self.stop_requested = False

        # --- signals ---------------------------------------------------
        self.pb_browse_config.clicked.connect(self.browse_config_file)
        self.pb_clear_config.clicked.connect(self.clear_config_file)
        self.pb_browse_cloud.clicked.connect(self.browse_lidar_file)
        self.pb_browse_cloud_folder.clicked.connect(self.browse_lidar_folder)
        self.pb_browse_footprint.clicked.connect(self.browse_footprint_file)
        self.pb_browse_output.clicked.connect(self.browse_output_folder)

        self.pb_generate.clicked.connect(self.generate_cityjson)
        self.pb_cancel.clicked.connect(self.stop_roofer)
        self.pb_view.clicked.connect(self.view_cityjson)

        self.pb_copy_log.clicked.connect(self.copy_log)
        self.pb_save_log.clicked.connect(self.save_log)

        self.actionSettings.triggered.connect(self.show_settings)
        self.actionOpenRunFolder.triggered.connect(self.open_run_folder)
        self.actionAbout.triggered.connect(self.show_about)
        self.actionClose.triggered.connect(self.close)

        # QProcess signals.
        self.process.readyReadStandardOutput.connect(self.read_process_output)
        self.process.finished.connect(self.process_finished)
        self.process.errorOccurred.connect(self.process_error)

        self.restore_session()
        self.statusbar.showMessage("Ready")

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def restore_session(self) -> None:
        """Restore the paths that were used the last time."""
        mode = self.settings.value(
            "session/lidar_mode",
            "",
            type=str,
        )
        values_text = self.settings.value(
            "session/lidar_values",
            "",
            type=str,
        )

        restored = False

        if values_text:
            try:
                values = json.loads(values_text)
            except (TypeError, json.JSONDecodeError):
                values = []

            if isinstance(values, list):
                paths = [
                    Path(value)
                    for value in values
                    if isinstance(value, str) and value
                ]

                if mode == "folder" and paths:
                    self.set_lidar_folder(paths[0])
                    restored = True
                elif paths:
                    self.set_lidar_files(paths)
                    restored = True

        if not restored:
            # Backward compatibility with the older single-path setting.
            legacy = self.settings.value(
                "session/lidar",
                "",
                type=str,
            )
            if legacy:
                legacy_path = Path(legacy)
                if legacy_path.is_dir():
                    self.set_lidar_folder(legacy_path)
                else:
                    self.set_lidar_files([legacy_path])

        self.le_footprint.setText(
            self.settings.value("session/footprint", "", type=str)
        )
        self.le_output.setText(
            self.settings.value("session/output", "", type=str)
        )

        config_text = self.settings.value("session/config", "", type=str)

        if config_text and Path(config_text).is_file():
            self.load_config_file(Path(config_text), quiet=True)

    def store_session(self) -> None:
        self.settings.setValue(
            "session/config",
            self.le_config.text().strip(),
        )

        if self.lidar_folder is not None:
            lidar_mode = "folder"
            lidar_values = [str(self.lidar_folder)]
        else:
            lidar_mode = "files"
            lidar_values = [str(path) for path in self.lidar_files]

        self.settings.setValue(
            "session/lidar_mode",
            lidar_mode,
        )
        self.settings.setValue(
            "session/lidar_values",
            json.dumps(lidar_values),
        )

        self.settings.setValue(
            "session/footprint",
            self.le_footprint.text().strip(),
        )
        self.settings.setValue(
            "session/output",
            self.le_output.text().strip(),
        )

    def start_dir(self, key: str, fallback: str = "") -> str:
        """Remembered starting folder for a file dialog."""
        value = self.settings.value(f"dirs/{key}", "", type=str)

        if value and Path(value).is_dir():
            return value

        if fallback and Path(fallback).is_dir():
            return fallback

        return str(Path.home())

    def remember_dir(self, key: str, path: Path) -> None:
        folder = path if path.is_dir() else path.parent
        self.settings.setValue(f"dirs/{key}", str(folder))

    # ------------------------------------------------------------------
    # Settings / Roofer executable
    # ------------------------------------------------------------------

    def show_settings(self) -> None:
        DialogSettings(self).exec()

    def get_roofer_path(self) -> Path | None:
        """The configured Roofer executable, asking for it when needed."""
        roofer_path = self.stored_roofer_path()

        if roofer_path is not None:
            return roofer_path

        QMessageBox.information(
            self,
            "Roofer path required",
            "Select the Roofer executable before generating a model.",
        )

        if DialogSettings(self).exec() != QDialog.DialogCode.Accepted:
            return None

        return self.stored_roofer_path()

    def stored_roofer_path(self) -> Path | None:
        saved_path = self.settings.value(SETTINGS_ROOFER_PATH, "", type=str)

        if not saved_path:
            return None

        roofer_path = Path(saved_path)

        return roofer_path if roofer_path.is_file() else None

    # ------------------------------------------------------------------
    # Configuration file
    # ------------------------------------------------------------------

    def browse_config_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Roofer configuration file",
            self.start_dir("config"),
            "TOML configuration files (*.toml);;All files (*)",
        )

        if filename:
            self.load_config_file(Path(filename))

    def clear_config_file(self) -> None:
        """Forget the configuration and return to direct-input mode.

        The TOML file itself is never deleted. Before forgetting its folder,
        stale temporary run configurations are cleaned when possible.
        """
        if self.config_path is not None:
            self.remove_stale_run_configs(max_age_hours=24)

        self.config_path = None
        self.config_document = None
        self.config_snapshot = {
            "footprint": "",
            "output": "",
        }
        self.config_lidar_snapshot = []
        self.config_pointclouds_editable = True

        self.le_config.clear()
        self.update_lidar_controls()
        self.statusbar.showMessage("Configuration file cleared")

    def load_config_file(self, config_path: Path, quiet: bool = False) -> bool:
        """Load a configuration and populate the corresponding UI fields."""
        try:
            document = config_io.load_document(config_path)
            paths = config_io.config_paths(document, config_path.parent)
            lidar_sources = config_io.resolved_pointcloud_sources(
                document,
                config_path.parent,
            )
        except ConfigError as error:
            if not quiet:
                QMessageBox.critical(
                    self,
                    "Invalid configuration file",
                    str(error),
                )
            return False

        self.config_path = config_path
        self.config_document = document
        self.config_snapshot = {
            "footprint": paths["footprint"],
            "output": paths["output"],
        }
        self.config_lidar_snapshot = lidar_sources.copy()
        self.config_pointclouds_editable = (
            config_io.can_edit_pointcloud_sources(document)
        )

        self.le_config.setText(str(config_path))
        self.remember_dir("config", config_path)

        # Missing config values intentionally clear the UI fields.
        if lidar_sources:
            self.set_lidar_files(
                [Path(path) for path in lidar_sources]
            )
        else:
            self.clear_lidar_selection()

        self.le_footprint.setText(paths["footprint"])
        self.le_output.setText(paths["output"])

        self.update_lidar_controls()

        if not self.config_pointclouds_editable and not quiet:
            QMessageBox.information(
                self,
                "Multiple point-cloud groups",
                (
                    "This configuration contains multiple [[pointclouds]] "
                    "tables. Roofer can use them, but the GUI will not "
                    "rewrite their point-cloud sources because each table "
                    "may contain different metadata.\n\n"
                    "The configured sources are shown for reference. "
                    "Clear the configuration to choose different LiDAR "
                    "inputs in direct mode."
                ),
            )

        self.remove_stale_run_configs(max_age_hours=24)
        self.statusbar.showMessage("Configuration file loaded")
        return True

    def ensure_config_loaded(self) -> bool:
        """Make sure the loaded document matches the text field.

        Returns False only when the text field points at something that
        cannot be used; an empty field simply means "no configuration".
        """
        text = self.le_config.text().strip().strip('"')

        if not text:
            if self.config_path is not None:
                self.clear_config_file()
            return True

        typed_path = Path(text).expanduser()

        if self.config_path is not None and self.config_path == typed_path:
            return True

        if not typed_path.is_file():
            self.show_warning(
                "Invalid configuration file",
                f"The configuration file does not exist:\n\n{typed_path}",
            )
            return False

        return self.load_config_file(typed_path)

    # ------------------------------------------------------------------
    # Comparing the interface with the configuration
    # ------------------------------------------------------------------

    def current_ui_paths(self) -> dict[str, str]:
        return {
            "footprint": self.normalized_path_text(
                self.le_footprint.text()
            ),
            "output": self.normalized_path_text(
                self.le_output.text()
            ),
        }

    def current_lidar_sources(self) -> list[str]:
        """Current file-based LiDAR inputs as absolute paths."""
        if self.lidar_folder is not None:
            return [self.normalized_path_text(str(self.lidar_folder))]

        return [
            self.normalized_path_text(str(path))
            for path in self.lidar_files
        ]

    @staticmethod
    def normalized_path_text(text: str) -> str:
        text = text.strip().strip('"')

        if not text:
            return ""

        try:
            return str(Path(text).expanduser().resolve())
        except OSError:
            return str(Path(text).expanduser())

    def config_paths_changed(self) -> bool:
        current = self.current_ui_paths()

        if any(
            current[key]
            != self.normalized_path_text(
                self.config_snapshot.get(key, "")
            )
            for key in ("footprint", "output")
        ):
            return True

        if not self.config_pointclouds_editable:
            return False

        return self.current_lidar_sources() != [
            self.normalized_path_text(path)
            for path in self.config_lidar_snapshot
        ]

    # ------------------------------------------------------------------
    # Preparing the configuration for one run
    # ------------------------------------------------------------------

    def prepare_config_for_run(
        self,
        run_output_folder: Path,
    ) -> Path | None:
        """Return the configuration file to hand to Roofer, or None.

        None means the user cancelled or an error was already reported.
        """
        if self.config_path is None or self.config_document is None:
            return None

        current = self.current_ui_paths()
        lidar_sources = (
            None
            if not self.config_pointclouds_editable
            else self.current_lidar_sources()
        )

        use_temporary = False

        if self.config_paths_changed():
            use_temporary = self.ask_and_maybe_update_config(
                current,
                lidar_sources,
            )

            if use_temporary is None:
                return None

        # A configuration that sets output-directory itself would contradict
        # the run folder given on the command line, so such a run always uses
        # a temporary copy that points at this run's folder.
        if not use_temporary and not config_io.has_output_directory(
            self.config_document
        ):
            return self.config_path

        try:
            return self.create_temporary_config(run_output_folder)
        except ConfigError as error:
            QMessageBox.critical(
                self,
                "Temporary configuration failed",
                str(error),
            )
            return None

    def ask_and_maybe_update_config(
        self,
        current: dict[str, str],
        lidar_sources: list[str] | None,
    ) -> bool | None:
        """Ask what to do with the changed paths.

        Returns True when a temporary copy must be used, False when the
        original configuration was updated in place, and None when the user
        cancelled or the update failed.
        """
        answer = QMessageBox.question(
            self,
            "Configuration paths changed",
            (
                "The paths in the interface differ from the selected "
                "configuration file.\n\nUpdate the configuration file "
                "with the paths shown in the interface?\n\n"
                "Yes - the file is updated (a .bak copy is kept).\n"
                "No  - the file stays unchanged and a temporary copy "
                "is used for this run."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No,
        )

        if answer == QMessageBox.StandardButton.Cancel:
            return None

        if answer != QMessageBox.StandardButton.Yes:
            return True

        assert self.config_path is not None

        try:
            # Re-read before writing: the file may have been edited outside
            # the GUI since it was loaded, and the in-memory copy would
            # silently undo those edits.
            document = config_io.load_document(self.config_path)

            config_io.apply_paths(
                document,
                self.config_path.parent,
                lidar=lidar_sources,
                footprint=current["footprint"],
                output=current["output"],
            )
            config_io.write_document(
                document,
                self.config_path,
                make_backup=True,
            )
            self.config_document = config_io.load_document(
                self.config_path
            )
        except ConfigError as error:
            QMessageBox.critical(
                self,
                "Configuration update failed",
                str(error),
            )
            return None

        self.config_snapshot = current.copy()

        if lidar_sources is not None:
            self.config_lidar_snapshot = lidar_sources.copy()

        self.append_log(
            f"Configuration file updated: {self.config_path}"
        )

        return False

    def create_temporary_config(self, run_output_folder: Path) -> Path:
        """Write a temporary copy of the configuration for one run.

        It carries the current editable UI paths, and - when the original
        configuration sets ``output-directory`` - points that key at this
        run's folder so it agrees with the command line.
        """
        assert self.config_path is not None

        base_dir = self.config_path.parent
        current = self.current_ui_paths()

        document = config_io.load_document(
            self.config_path
        )

        config_io.apply_paths(
            document,
            base_dir,
            lidar=(
                None
                if not self.config_pointclouds_editable
                else self.current_lidar_sources()
            ),
            footprint=current["footprint"],
            output=None,
        )

        if config_io.has_output_directory(document):
            config_io.set_output_directory(
                document,
                config_io.relative_to_config(
                    str(run_output_folder),
                    base_dir,
                ),
            )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_path = base_dir / (
            f"{TEMP_CONFIG_PREFIX}{timestamp}_{os.getpid()}.toml"
        )

        config_io.write_document(
            document,
            temp_path,
        )

        return temp_path

    def cleanup_run_config(self) -> None:
        if self.run_config is None:
            return

        try:
            self.run_config.unlink(missing_ok=True)
        except OSError:
            pass

        self.run_config = None

    # ------------------------------------------------------------------
    # Manual LiDAR / footprint / output selection
    # ------------------------------------------------------------------

    def set_lidar_files(self, paths: list[Path]) -> None:
        """Use one or more LAS/LAZ files as the LiDAR input."""
        self.lidar_folder = None
        self.lidar_files = [
            path.expanduser()
            for path in paths
        ]
        self.update_lidar_display()

    def set_lidar_folder(self, path: Path) -> None:
        """Use a folder containing LAS/LAZ files as the LiDAR input."""
        self.lidar_files = []
        self.lidar_folder = path.expanduser()
        self.update_lidar_display()

    def clear_lidar_selection(self) -> None:
        self.lidar_files = []
        self.lidar_folder = None
        self.update_lidar_display()

    def update_lidar_display(self) -> None:
        if self.lidar_folder is not None:
            self.le_cloud.setText(
                str(self.lidar_folder)
            )
            self.le_cloud.setToolTip(
                f"Folder input:\n{self.lidar_folder}"
            )
            return

        if not self.lidar_files:
            self.le_cloud.clear()
            self.le_cloud.setToolTip("")
            return

        if len(self.lidar_files) == 1:
            self.le_cloud.setText(
                str(self.lidar_files[0])
            )
        else:
            self.le_cloud.setText(
                f"{len(self.lidar_files)} point-cloud files selected"
            )

        self.le_cloud.setToolTip(
            "\n".join(
                str(path)
                for path in self.lidar_files
            )
        )

    def update_lidar_controls(self, processing: bool | None = None) -> None:
        """Enable LiDAR selection unless the config locks it or a run is busy.

        This is the single place that decides the state of the two LiDAR
        buttons; ``set_processing_state`` delegates to it.
        """
        if processing is None:
            processing = (
                self.process.state()
                != QProcess.ProcessState.NotRunning
            )

        editable = (
            self.config_path is None
            or self.config_pointclouds_editable
        )
        enabled = editable and not processing

        self.pb_browse_cloud.setEnabled(enabled)
        self.pb_browse_cloud_folder.setEnabled(enabled)

    def browse_lidar_file(self) -> None:
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "Select LiDAR point cloud(s)",
            self.start_dir("lidar"),
            (
                "LiDAR files (*.las *.laz);;"
                "LAS files (*.las);;"
                "LAZ files (*.laz);;"
                "All files (*)"
            ),
        )

        if filenames:
            paths = [
                Path(filename)
                for filename in filenames
            ]
            self.set_lidar_files(paths)
            self.remember_dir(
                "lidar",
                paths[0],
            )

    def browse_lidar_folder(self) -> None:
        """Select and immediately validate a folder containing LiDAR files."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select folder with point clouds",
            self.start_dir("lidar"),
        )

        # The user pressed Cancel.
        if not folder:
            return

        path = Path(folder)

        try:
            # Only regular files directly inside the selected folder are checked.
            files = [
                child
                for child in path.iterdir()
                if child.is_file()
            ]
        except OSError as error:
            self.show_warning(
                "Point-cloud folder unreadable",
                (
                    "The selected folder could not be read:"
                    f"\n\n{path}"
                    f"\n\n{error}"
                ),
            )
            return

        # The selected directory must contain at least one file.
        if not files:
            self.show_warning(
                "Empty point-cloud folder",
                (
                    "The selected folder is empty.\n\n"
                    "Select a folder containing only .las or .laz files."
                ),
            )
            return

        # Reject the complete folder if any file is not LAS/LAZ.
        invalid_files = [
            child
            for child in files
            if child.suffix.lower() not in LIDAR_SUFFIXES
        ]

        if invalid_files:
            invalid_names = "\n".join(
                child.name
                for child in invalid_files
            )

            self.show_warning(
                "Invalid point-cloud folder",
                (
                    "The selected folder must contain only "
                    ".las or .laz files.\n\n"
                    "Unsupported file(s) found:\n\n"
                    f"{invalid_names}"
                ),
            )
            return

        # Every file passed validation, so accept the folder.
        self.set_lidar_folder(path)
        self.remember_dir(
            "lidar",
            path,
        )

    def browse_footprint_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select 2D building footprints",
            self.start_dir("footprint"),
            "GeoPackage files (*.gpkg);;All files (*)",
        )

        if filename:
            self.le_footprint.setText(filename)
            self.remember_dir(
                "footprint",
                Path(filename),
            )

    def browse_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select output folder",
            self.start_dir("output"),
        )

        if folder:
            self.le_output.setText(folder)
            self.remember_dir(
                "output",
                Path(folder),
            )

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def validate_inputs(
        self,
    ) -> tuple[
        Path,
        list[Path] | Path | None,
        Path,
        Path,
    ] | None:
        """Validate every required input before starting Roofer."""
        roofer_path = self.get_roofer_path()

        if roofer_path is None:
            return None

        current = self.current_ui_paths()

        if not current["footprint"]:
            self.show_warning(
                "Missing footprint file",
                "Select a GPKG building-footprint file.",
            )
            return None

        if not current["output"]:
            self.show_warning(
                "Missing output folder",
                "Select an output folder.",
            )
            return None

        footprint_path = Path(
            current["footprint"]
        )
        output_path = Path(
            current["output"]
        )

        if not footprint_path.is_file():
            self.show_warning(
                "Invalid footprint file",
                f"The footprint file does not exist:\n\n{footprint_path}",
            )
            return None

        if footprint_path.suffix.lower() != ".gpkg":
            self.show_warning(
                "Invalid footprint file",
                "The footprint file must end with .gpkg.",
            )
            return None

        lidar_input: list[Path] | Path | None

        if (
            self.config_path is not None
            and not self.config_pointclouds_editable
        ):
            # Roofer will read all point-cloud groups from the TOML.
            lidar_input = None

        elif self.lidar_folder is not None:
            # Use the selected folder as LiDAR input.
            lidar_input = self.lidar_folder

            # Check that it still exists.
            if not lidar_input.is_dir():
                self.show_warning(
                    "Invalid point-cloud folder",
                    f"The folder does not exist:\n\n{lidar_input}",
                )
                return None

            try:
                # Validate again immediately before Roofer starts.
                # This protects against files being added after selection.
                files = [
                    child
                    for child in lidar_input.iterdir()
                    if child.is_file()
                ]
            except OSError as error:
                self.show_warning(
                    "Point-cloud folder unreadable",
                    (
                        "The selected folder could not be read:"
                        f"\n\n{lidar_input}"
                        f"\n\n{error}"
                    ),
                )
                return None

            if not files:
                self.show_warning(
                    "Empty point-cloud folder",
                    (
                        "The selected folder is empty.\n\n"
                        "Select a folder containing only .las or .laz files."
                    ),
                )
                return None

            # The folder must consist only of LAS/LAZ files.
            invalid_files = [
                child
                for child in files
                if child.suffix.lower() not in LIDAR_SUFFIXES
            ]

            if invalid_files:
                invalid_names = "\n".join(
                    child.name
                    for child in invalid_files
                )

                self.show_warning(
                    "Invalid point-cloud folder",
                    (
                        "The selected folder must contain only "
                        ".las or .laz files.\n\n"
                        "Unsupported file(s) found:\n\n"
                        f"{invalid_names}"
                    ),
                )
                return None

        else:
            lidar_input = self.lidar_files.copy()

            if not lidar_input:
                self.show_warning(
                    "Missing LiDAR input",
                    (
                        "Select one or more LAS/LAZ files, or select "
                        "a folder containing point clouds."
                    ),
                )
                return None

            for path in lidar_input:
                if not path.is_file():
                    self.show_warning(
                        "Invalid LiDAR file",
                        f"The LiDAR file does not exist:\n\n{path}",
                    )
                    return None

                if path.suffix.lower() not in LIDAR_SUFFIXES:
                    self.show_warning(
                        "Invalid LiDAR file",
                        (
                            "Every selected point-cloud file must end "
                            "with .las or .laz."
                        ),
                    )
                    return None

        try:
            output_path.mkdir(
                parents=True,
                exist_ok=True,
            )
        except OSError as error:
            QMessageBox.critical(
                self,
                "Output folder error",
                f"The output folder could not be created:\n\n{error}",
            )
            return None

        if not output_path.is_dir():
            self.show_warning(
                "Invalid output folder",
                f"The output path is not a folder:\n\n{output_path}",
            )
            return None

        return (
            roofer_path,
            lidar_input,
            footprint_path,
            output_path,
        )

    # ------------------------------------------------------------------
    # Run Roofer
    # ------------------------------------------------------------------

    def generate_cityjson(self) -> None:
        if self.process.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.information(
                self,
                "Roofer is running",
                "Please wait until Roofer finishes, or press Stop.",
            )
            return

        if not self.ensure_config_loaded():
            return

        validated = self.validate_inputs()

        if validated is None:
            return

        roofer_path, lidar_input, footprint_path, output_path = validated

        self.generated_files = []
        self.clear_generated_file_buttons()
        self.log_box.clear()
        self.pb_view.setEnabled(False)
        self.actionOpenRunFolder.setEnabled(False)
        self.cleanup_run_config()
        self.stop_requested = False

        run_folder = self.create_run_folder(
            output_path,
            self.run_name_for(lidar_input),
        )

        if run_folder is None:
            return

        self.output_folder = run_folder

        if self.config_path is not None:
            config_for_run = self.prepare_config_for_run(run_folder)

            if config_for_run is None:
                # Nothing was started: drop the still-empty run folder.
                self.discard_run_folder()
                return

            if config_for_run != self.config_path:
                self.run_config = config_for_run

            arguments = ["-c", str(config_for_run), str(run_folder)]
            working_directory = config_for_run.parent
        else:
            if lidar_input is None:
                self.show_warning(
                    "Missing LiDAR input",
                    "Select LiDAR input before running Roofer.",
                )
                self.discard_run_folder()
                return

            if isinstance(lidar_input, list):
                lidar_arguments = [
                    str(path)
                    for path in lidar_input
                ]
            else:
                lidar_arguments = [
                    str(lidar_input)
                ]

            # Direct Roofer command:
            # roofer <pointcloud> <polygon-source> <output-directory>
            arguments = [
                *lidar_arguments,
                str(footprint_path),
                str(run_folder),
            ]

            # Keep Roofer's own folder as working directory so companion
            # libraries next to the executable are found on Windows.
            working_directory = roofer_path.parent

        self.lb_run_folder.setText(f"Current run folder: {run_folder}")
        self.store_session()

        self.append_log(f"Roofer executable : {roofer_path}")

        if self.config_path is not None:
            self.append_log(f"Configuration     : {self.config_path}")

            if self.run_config is not None:
                self.append_log(f"Run configuration : {self.run_config}")
        else:
            self.append_log("Configuration     : none (direct arguments)")

        if (
            self.config_path is not None
            and not self.config_pointclouds_editable
        ):
            self.append_log(
                "LiDAR input       : multiple point-cloud groups "
                "from configuration"
            )
        elif isinstance(lidar_input, list):
            self.append_log(
                f"LiDAR input       : {len(lidar_input)} file(s)"
            )
            for path in lidar_input:
                self.append_log(
                    f"  - {path}"
                )
        else:
            self.append_log(
                f"LiDAR input       : {lidar_input}"
            )

        self.append_log(f"Footprints        : {footprint_path}")
        self.append_log(f"Output base       : {output_path}")
        self.append_log(f"Run folder        : {run_folder}")
        self.append_log(f"Working directory : {working_directory}")
        self.append_log("")
        self.append_log(
            "Command: "
            + " ".join([str(roofer_path)] + arguments)
        )
        self.append_log("")

        # Tell QProcess which executable to run.
        self.process.setProgram(str(roofer_path))

        # Give Roofer the command-line arguments.
        self.process.setArguments(arguments)

        # Set the external process working directory.
        self.process.setWorkingDirectory(str(working_directory))

        self.set_processing_state(True)
        self.statusbar.showMessage("Generating LoD 2.2 buildings...")

        # Ask the operating system to start Roofer.
        self.process.start()

    def run_name_for(
        self,
        lidar_input: list[Path] | Path | None,
    ) -> str:
        if isinstance(lidar_input, list):
            if not lidar_input:
                return "roofer"

            first_name = lidar_input[0].stem or "roofer"

            if len(lidar_input) == 1:
                return first_name

            return f"{first_name}_plus_{len(lidar_input) - 1}"

        if isinstance(lidar_input, Path):
            name = (
                lidar_input.name
                if lidar_input.is_dir()
                else lidar_input.stem
            )
            return name or "roofer"

        if self.config_path is not None:
            return self.config_path.stem or "roofer"

        return "roofer"

    def create_run_folder(
        self,
        main_output_path: Path,
        name: str,
    ) -> Path | None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_folder = main_output_path / f"{name}_{timestamp}"

        run_folder = base_folder
        counter = 2

        while run_folder.exists():
            run_folder = Path(f"{base_folder}_{counter}")
            counter += 1

        try:
            run_folder.mkdir(parents=True)
        except OSError as error:
            QMessageBox.critical(
                self,
                "Output folder error",
                f"The run folder could not be created:\n\n{error}",
            )
            return None

        return run_folder

    def discard_run_folder(self) -> None:
        """Remove the run folder again when nothing was written to it."""
        if self.output_folder is not None:
            try:
                self.output_folder.rmdir()
            except OSError:
                pass

        self.output_folder = None
        self.lb_run_folder.setText("No model generated yet.")

    def stop_roofer(self) -> None:
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return

        answer = QMessageBox.question(
            self,
            "Stop Roofer",
            "Stop the running reconstruction?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self.stop_requested = True
        self.append_log("")
        self.append_log("Stopping Roofer...")

        self.process.terminate()

        if not self.process.waitForFinished(3000):
            self.process.kill()

    # ------------------------------------------------------------------
    # Roofer output
    # ------------------------------------------------------------------

    def read_process_output(self) -> None:
        raw_data = self.process.readAllStandardOutput()
        text = bytes(raw_data).decode("utf-8", errors="replace")

        if text.strip():
            self.append_log(text.rstrip())

    def process_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        self.read_process_output()
        self.set_processing_state(False)
        self.cleanup_run_config()

        if self.stop_requested:
            self.statusbar.showMessage("Roofer stopped by the user")
            self.append_log("")
            self.append_log("Roofer was stopped before it finished.")
            self.stop_requested = False
            return

        if (
            exit_status != QProcess.ExitStatus.NormalExit
            or exit_code != 0
        ):
            self.statusbar.showMessage("Roofer failed")
            self.append_log("")
            self.append_log(f"Roofer stopped with exit code {exit_code}.")

            QMessageBox.critical(
                self,
                "Roofer error",
                (
                    "Roofer did not finish successfully.\n\n"
                    "Read the processing messages for details."
                ),
            )
            return

        if self.output_folder is None:
            self.statusbar.showMessage("No output folder")
            return

        self.generated_files = self.collect_output_files(self.output_folder)
        self.actionOpenRunFolder.setEnabled(True)

        if not self.generated_files:
            self.statusbar.showMessage("No CityJSON output found")
            self.append_log("")
            self.append_log(
                "Roofer finished, but no CityJSON file was found in "
                f"{self.output_folder}."
            )

            QMessageBox.warning(
                self,
                "No output found",
                (
                    "Roofer finished successfully, but no CityJSON file "
                    "was found in the run folder."
                ),
            )
            return

        self.clear_generated_file_buttons()

        for file_path in self.generated_files:
            self.add_generated_file_button(file_path)
            self.append_log(f"Created: {file_path}")

        self.files_layout.addStretch(1)
        self.pb_view.setEnabled(True)
        self.statusbar.showMessage(
            "LoD 2.2 CityJSON model created successfully"
        )

        QMessageBox.information(
            self,
            "Finished",
            (
                "LoD 2.2 reconstruction completed successfully.\n\n"
                f"{len(self.generated_files)} CityJSON file(s) created."
            ),
        )

    @staticmethod
    def collect_output_files(folder: Path) -> list[Path]:
        found: list[Path] = []
        seen: set[Path] = set()

        for pattern in OUTPUT_PATTERNS:
            for path in sorted(folder.rglob(pattern)):
                if path.is_file() and path not in seen:
                    seen.add(path)
                    found.append(path)

        return found

    def process_error(self, error: QProcess.ProcessError) -> None:
        """Report only failures that produce no ``finished`` signal.

        Qt emits ``errorOccurred`` and ``finished`` when a started process
        crashes, so handling every error here would show two dialogs.
        """
        message = self.process.errorString()

        if error != QProcess.ProcessError.FailedToStart:
            self.append_log(f"Process error: {message}")
            return

        self.set_processing_state(False)
        self.cleanup_run_config()

        self.statusbar.showMessage("Could not start Roofer")
        self.append_log("")
        self.append_log(f"Process error: {message}")

        QMessageBox.critical(
            self,
            "Could not run Roofer",
            f"Roofer could not be started:\n\n{message}",
        )

    # ------------------------------------------------------------------
    # Generated file buttons
    # ------------------------------------------------------------------

    def clear_generated_file_buttons(self) -> None:
        while self.files_layout.count():
            item = self.files_layout.takeAt(0)
            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

    def add_generated_file_button(self, file_path: Path) -> None:
        button = QPushButton(file_path.name)

        icon = QFileIconProvider().icon(QFileInfo(str(file_path)))
        button.setIcon(icon)
        button.setIconSize(QSize(24, 24))
        button.setMinimumHeight(44)
        button.setToolTip(
            f"{file_path}\n\nClick: show in file manager\n"
            "Right-click: more actions"
        )

        button.clicked.connect(
            lambda _checked=False, path=file_path: self.show_file_in_explorer(
                path
            )
        )

        button.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        button.customContextMenuRequested.connect(
            lambda point, path=file_path, source=button: self.file_menu(
                source,
                point,
                path,
            )
        )

        self.files_layout.addWidget(button)

    def file_menu(
        self,
        source: QPushButton,
        point,
        file_path: Path,
    ) -> None:
        menu = QMenu(self)

        show_action = menu.addAction("Show in file manager")
        open_action = menu.addAction("Open with default application")
        copy_action = menu.addAction("Copy full path")
        ninja_action = menu.addAction("Open CityJSON Ninja")

        chosen = menu.exec(source.mapToGlobal(point))

        if chosen is None:
            return

        if chosen == show_action:
            self.show_file_in_explorer(file_path)
        elif chosen == open_action:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(file_path))
            )
        elif chosen == copy_action:
            QApplication.clipboard().setText(str(file_path))
            self.statusbar.showMessage(
                "Path copied to the clipboard",
                4000,
            )
        elif chosen == ninja_action:
            QDesktopServices.openUrl(QUrl(CITYJSON_NINJA_URL))

    # ------------------------------------------------------------------
    # View CityJSON
    # ------------------------------------------------------------------

    def view_cityjson(self) -> None:
        """Open CityJSON Ninja and reveal the file so it can be dropped in.

        Ninja has no documented way to load a file from a URL, so the file
        itself still has to be dragged into the page. The window therefore
        only prepares both sides of that drag.
        """
        if not self.generated_files:
            self.show_warning(
                "No CityJSON file",
                "Generate a CityJSON model first.",
            )
            return

        first_file = self.generated_files[0]

        if not first_file.is_file():
            QMessageBox.critical(
                self,
                "File not found",
                f"The generated file no longer exists:\n\n{first_file}",
            )
            return

        QDesktopServices.openUrl(QUrl(CITYJSON_NINJA_URL))
        self.show_file_in_explorer(first_file)

        QMessageBox.information(
            self,
            "View CityJSON",
            (
                "CityJSON Ninja has been opened in your browser and the "
                "file manager shows the generated file.\n\n"
                f"Drag {first_file.name} into the Ninja page to view it."
            ),
        )

    def open_run_folder(self) -> None:
        if self.output_folder is None or not self.output_folder.is_dir():
            self.show_warning(
                "No run folder",
                "Generate a CityJSON model first.",
            )
            return

        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.output_folder))
        )

    @staticmethod
    def show_file_in_explorer(file_path: Path) -> None:
        """Open the platform file manager and reveal the generated file."""
        file_path = file_path.resolve()

        try:
            if os.name == "nt":
                # Explorer needs "/select," to stay an unquoted switch with
                # only the path quoted. Passing a list would let subprocess
                # quote the whole argument, which Explorer ignores: it then
                # opens the default folder instead of the file's location.
                subprocess.Popen(
                    f'explorer.exe /select,"{file_path}"',
                    shell=False,
                )
                return

            if sys.platform == "darwin":
                subprocess.Popen(
                    [
                        "open",
                        "-R",
                        str(file_path),
                    ]
                )
                return

        except OSError:
            pass

        # Linux / fallback: open the containing directory.
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(
                str(file_path.parent)
            )
        )

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------

    def append_log(self, text: str) -> None:
        self.log_box.appendPlainText(text)

        scrollbar = self.log_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def copy_log(self) -> None:
        QApplication.clipboard().setText(
            self.log_box.toPlainText()
        )
        self.statusbar.showMessage(
            "Log copied to the clipboard",
            4000,
        )

    def save_log(self) -> None:
        default_dir = (
            str(self.output_folder)
            if self.output_folder is not None
            else self.start_dir("output")
        )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save processing messages",
            str(Path(default_dir) / f"roofer_log_{timestamp}.txt"),
            "Text files (*.txt);;All files (*)",
        )

        if not filename:
            return

        try:
            Path(filename).write_text(
                self.log_box.toPlainText(),
                encoding="utf-8",
            )
        except OSError as error:
            QMessageBox.critical(
                self,
                "Could not save log",
                f"{error}",
            )
            return

        self.statusbar.showMessage(
            f"Log saved to {filename}",
            5000,
        )

    # ------------------------------------------------------------------
    # State / cleanup
    # ------------------------------------------------------------------

    def set_processing_state(self, processing: bool) -> None:
        enabled = not processing

        for widget in (
            self.pb_generate,
            self.pb_browse_config,
            self.pb_clear_config,
            self.pb_browse_footprint,
            self.pb_browse_output,
            self.le_config,
            self.le_footprint,
            self.le_output,
            self.actionSettings,
        ):
            widget.setEnabled(enabled)

        self.update_lidar_controls(processing)
        self.le_cloud.setEnabled(enabled)

        self.pb_cancel.setEnabled(processing)
        self.pbar_running.setVisible(processing)

    def show_warning(self, title: str, message: str) -> None:
        QMessageBox.warning(
            self,
            title,
            message,
        )

    def show_about(self) -> None:
        """Show the About dialog.

        A new dialog is created for every invocation and destroyed when it
        closes, so no state from a previous invocation is kept.
        """
        dialog = DialogAbout(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.exec()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.process.state() != QProcess.ProcessState.NotRunning:
            answer = QMessageBox.question(
                self,
                "Roofer is still running",
                (
                    "Roofer is still running.\n\n"
                    "Close the application and stop Roofer?"
                ),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if answer == QMessageBox.StandardButton.No:
                event.ignore()
                return

            self.stop_requested = True
            self.process.kill()
            self.process.waitForFinished(3000)

        self.cleanup_run_config()
        self.remove_stale_run_configs()
        self.store_session()

        event.accept()

    def remove_stale_run_configs(
        self,
        max_age_hours: int = 24,
    ) -> None:
        """Delete old temporary run configs left by abnormal termination.

        Files newer than ``max_age_hours`` are kept so another running GUI
        instance is not disturbed.
        """
        if self.config_path is None:
            return

        cutoff = datetime.now().timestamp() - (max_age_hours * 3600)

        try:
            leftovers = self.config_path.parent.glob(
                f"{TEMP_CONFIG_PREFIX}*.toml"
            )

            for path in leftovers:
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
        except OSError:
            pass