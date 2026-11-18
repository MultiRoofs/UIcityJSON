"""Main window of the MultiRoofs LoD 2.2 CityJSON generator.

The window drives the Roofer CLI:

    roofer [options] <pointcloud> <polygon-source> <output-directory>
    roofer -c <config.toml> [<pointcloud> <polygon-source>] <output-directory>
"""

from __future__ import annotations

import codecs
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import QProcess, QSettings, Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QMainWindow,
    QMessageBox,
)

from UI import config_io
from UI.cjseq_worker import CjseqConversionWorker
from UI.config_io import ConfigError
from UI.DialogAbout import DialogAbout
from UI.DialogSettings import (
    DialogSettings,
    SETTINGS_APP,
    SETTINGS_CJSEQ_PATH,
    SETTINGS_ORG,
    SETTINGS_ROOFER_PATH,
    executable_problem,
    find_cjseq,
    find_roofer_in_path,
)
from UI.resource_utils import resource_path


CITYJSON_NINJA_URL = "https://ninja.cityjson.org/"
SETTINGS_HIDE_NINJA_MESSAGE = "view_cityjson/hide_instruction_message"

# Roofer writes CityJSONSequence files; the exact extension has changed
# between releases, so several patterns are accepted. Order matters: the
# most specific pattern is reported first.
OUTPUT_PATTERNS = ("*.city.jsonl", "*.jsonl", "*.city.json")

# Only these file extensions are accepted as LiDAR point-cloud files.
LIDAR_SUFFIXES = {".las", ".laz"}

# Positions of the entries in the LiDAR mode combo box (cmb_cloud_mode).
CLOUD_MODE_FILES = 0
CLOUD_MODE_FOLDER = 1

# How long a stopped Roofer may take to exit before it is killed.
STOP_GRACE_MS = 3000

# Temporary run configurations are written next to the original TOML so
# that all other relative paths inside it keep their meaning.
TEMP_CONFIG_PREFIX = ".multiroofs_run_"

# A worker that outlives its window must retain a Python reference until its
# underlying thread finishes. Otherwise PyQt may delete a running QThread.
_orphaned_workers: set[CjseqConversionWorker] = set()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        # Load the interface designed in Qt Designer.
        uic.loadUi(resource_path("mainWindow.ui"), self)

        # QSettings remembers application/session settings.
        # Use an explicit identity so source runs and packaged Windows builds
        # always read and write the same settings store.
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        # Prevent textChanged handlers from saving partially restored fields.
        self._restoring_session = False

        # QProcess is the connection used by the GUI to start Roofer
        # Create an object that can ask the operating system to start and control another program.
        # as an external operating-system process.
        self.process = QProcess(self) #creates a QProcess object.
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

        # Background CityJSONSeq -> CityJSON conversion, while one is running.
        self.converter: CjseqConversionWorker | None = None

        # Identifies the current Roofer run, so a delayed "kill" timer from
        # an earlier run can never stop a later one.
        self.run_serial = 0

        # Roofer output arrives in chunks that may split a multi-byte
        # character, so it is decoded incrementally.
        self.output_decoder = codecs.getincrementaldecoder("utf-8")(
            errors="replace"
        )

        # --- signals ---------------------------------------------------
        self.pb_browse_config.clicked.connect(self.browse_config_file)
        self.pb_clear_config.clicked.connect(self.clear_config_file)
        self.pb_browse_cloud.clicked.connect(self.browse_lidar)
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

        # Persist input paths as soon as they change, instead of waiting for
        # a normal close or a conversion. This survives crashes and restarts.
        self.le_config.textChanged.connect(self.store_session)
        self.le_footprint.textChanged.connect(self.store_session)
        self.le_output.textChanged.connect(self.store_session)

        # QProcess signals.
        self.process.readyReadStandardOutput.connect(self.read_process_output)
        self.process.finished.connect(self.process_finished)
        self.process.errorOccurred.connect(self.process_error)

        self.restore_session()
        self.statusbar.showMessage("Ready")

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------
# the setting that is saved in  the  settings goes to the → GUI
    def restore_session(self) -> None:
        """Restore the paths that were used the last time."""
        self._restoring_session = True
        try:
            self._restore_session_values()
        finally:
            self._restoring_session = False
        self.store_session()

    def _restore_session_values(self) -> None:
        """Restore fields without allowing intermediate signal saves."""
        saved_footprint = self.settings.value("session/footprint", "", type=str)
        saved_output = self.settings.value("session/output", "", type=str)

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
#Continue only if values is actually a Python list   For example: values = ["a.las", "b.las"]
# This section address 3 cases of lidar (list, folder, path)
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

        self.le_footprint.setText(saved_footprint)
        self.le_output.setText(saved_output)

        config_text = self.settings.value("session/config", "", type=str)

        # Keep showing the saved path even when the file was moved or deleted;
        # validation will explain the problem when the user runs the job.
        self.le_config.setText(config_text)
        if config_text and Path(config_text).is_file():
            self.load_config_file(Path(config_text), quiet=True)
            # Loading TOML fills its own paths. Explicit session selections
            # take precedence, including a previously chosen output folder.
            if saved_footprint:
                self.le_footprint.setText(saved_footprint)
            if saved_output:
                self.le_output.setText(saved_output)

    def store_session(self) -> None:
        if self._restoring_session:
            return
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
        self.settings.sync()

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
        self.run_settings_dialog()

    def run_settings_dialog(self) -> bool:
        """Show the settings dialog; True when the user saved the settings."""
        dialog = DialogSettings(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        return dialog.exec() == QDialog.DialogCode.Accepted

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

        if not self.run_settings_dialog():
            return None

        return self.stored_roofer_path()

    def stored_roofer_path(self) -> Path | None:
        saved_path = self.settings.value(SETTINGS_ROOFER_PATH, "", type=str)
        if saved_path:
            try:
                path = Path(saved_path).expanduser()
                if executable_problem(path) is None:
                    return path
            except (OSError, TypeError, ValueError):
                pass

        try:
            return find_roofer_in_path()
        except (OSError, TypeError, ValueError):
            return None

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
            if self.load_config_file(Path(filename)):
                self.store_session()

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

# that sends the values from the config_mr to the GUI
        self.le_config.setText(str(config_path))
        self.remember_dir("config", config_path)

        # Missing config values intentionally clear the UI fields.
        if len(lidar_sources) == 1 and Path(lidar_sources[0]).is_dir():
            # Roofer accepts a folder as a point-cloud source.
            self.set_lidar_folder(Path(lidar_sources[0]))
        elif lidar_sources:
            self.set_lidar_files(
                [Path(path) for path in lidar_sources]
            )
        else:
            self.clear_lidar_selection()

        # A TOML file may omit these optional values. Do not replace a path
        # already selected by the user with an empty string.
        if paths["footprint"]:
            self.le_footprint.setText(paths["footprint"])
        if paths["output"]:
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

        # The output folder is mandatory in the interface, but the TOML only
        # has a value to compare against when it sets ``output-directory``.
        # Comparing it otherwise would report a change on every single run.
        keys = ["footprint"]

        if config_io.has_output_directory(self.config_document):
            keys.append("output")

        if any(
            current[key]
            != self.normalized_path_text(
                self.config_snapshot.get(key, "")
            )
            for key in keys
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

        # Re-read the file: it may have been edited outside the GUI since it
        # was loaded, e.g. an ``output-directory`` added by hand.
        try:
            self.config_document = config_io.load_document(self.config_path)
        except ConfigError as error:
            QMessageBox.critical(
                self,
                "Invalid configuration file",
                str(error),
            )
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

        # Keep the GUI mode synchronized with the actual LiDAR input.
        self.cmb_cloud_mode.setCurrentIndex(CLOUD_MODE_FILES)

        self.update_lidar_display()

    def set_lidar_folder(self, path: Path) -> None:
        """Use a folder containing LAS/LAZ files as the LiDAR input."""
        self.lidar_files = []
        self.lidar_folder = path.expanduser()

        # Keep the GUI mode synchronized with the actual LiDAR input.
        self.cmb_cloud_mode.setCurrentIndex(CLOUD_MODE_FOLDER)

        self.update_lidar_display()

    def clear_lidar_selection(self) -> None:
        self.lidar_files = []
        self.lidar_folder = None
        self.update_lidar_display()
        self.store_session()

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

        This is the single place that controls the LiDAR mode combo box
        and Browse button; ``set_processing_state`` delegates to it.
        """
        if processing is None:
            processing = self.is_busy()

        editable = (
            self.config_path is None
            or self.config_pointclouds_editable
        )
        enabled = editable and not processing

        self.pb_browse_cloud.setEnabled(enabled)
        self.cmb_cloud_mode.setEnabled(enabled)

    def browse_lidar(self) -> None:
        """Open the LiDAR browser selected in ``cmb_cloud_mode``.

        Index 0 selects one or more LAS/LAZ files.
        Index 1 selects a folder containing LAS/LAZ files.
        """
        if self.cmb_cloud_mode.currentIndex() == CLOUD_MODE_FOLDER:
            self.browse_lidar_folder()
        else:
            self.browse_lidar_file()

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
            self.store_session()
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
        problem = self.lidar_folder_problem(path)

        if problem is not None:
            self.show_warning(*problem)
            return

        # Every file passed validation, so accept the folder.
        self.set_lidar_folder(path)
        self.store_session()
        self.remember_dir(
            "lidar",
            path,
        )

    @staticmethod
    def lidar_folder_problem(path: Path) -> tuple[str, str] | None:
        """Return ``(title, message)`` when ``path`` is not a usable folder.

        Only regular files directly inside the folder are checked, and the
        folder must contain nothing but .las / .laz files.
        """
        try:
            files = [child for child in path.iterdir() if child.is_file()]
        except OSError as error:
            return (
                "Point-cloud folder unreadable",
                (
                    "The selected folder could not be read:"
                    f"\n\n{path}"
                    f"\n\n{error}"
                ),
            )

        if not files:
            return (
                "Empty point-cloud folder",
                (
                    "The selected folder is empty.\n\n"
                    "Select a folder containing only .las or .laz files."
                ),
            )

        invalid_names = [
            child.name
            for child in files
            if child.suffix.lower() not in LIDAR_SUFFIXES
        ]

        if invalid_names:
            return (
                "Invalid point-cloud folder",
                (
                    "The selected folder must contain only "
                    ".las or .laz files.\n\n"
                    "Unsupported file(s) found:\n\n"
                    + "\n".join(invalid_names)
                ),
            )

        return None

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
            self.store_session()

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
            self.store_session()

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

            # Validate again immediately before Roofer starts. This protects
            # against files being added after the folder was selected.
            problem = self.lidar_folder_problem(lidar_input)

            if problem is not None:
                self.show_warning(*problem)
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
        if self.is_busy():
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
#reading from  a TOML configuration
        roofer_path, lidar_input, footprint_path, output_path = validated

        self.generated_files = []
        self.log_box.clear()
        self.pb_view.setEnabled(False)
        self.actionOpenRunFolder.setEnabled(False)
        self.cleanup_run_config()
        self.stop_requested = False
        self.run_serial += 1
        self.output_decoder.reset()

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
        """Remove the run folder again when nothing was written to it.

        A folder that already contains output is left alone (and stays
        remembered, so the log and run-folder actions still point to it).
        """
        if self.output_folder is None:
            return

        try:
            self.output_folder.rmdir()
        except OSError:
            return

        self.output_folder = None

    def stop_roofer(self) -> None:
        if self.converter is not None:
            answer = QMessageBox.question(
                self,
                "Stop conversion",
                (
                    "Stop the CityJSON conversion?\n\n"
                    "The CityJSONSeq files written by Roofer are kept."
                ),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if answer == QMessageBox.StandardButton.Yes:
                self.append_log("")
                self.append_log("Stopping conversion...")
                self.converter.requestInterruption()

            return

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

        # Do not block the interface while waiting: on Windows terminate()
        # is ignored by console programs, so Roofer is killed after a short
        # grace period from a timer instead of from a blocking wait.
        serial = self.run_serial
        QTimer.singleShot(
            STOP_GRACE_MS,
            lambda: self.kill_if_running(serial),
        )

    def kill_if_running(self, serial: int) -> None:
        """Kill Roofer if the run identified by ``serial`` is still alive."""
        if (
            serial == self.run_serial
            and self.process.state() != QProcess.ProcessState.NotRunning
        ):
            self.process.kill()

    # ------------------------------------------------------------------
    # Roofer output
    # ------------------------------------------------------------------

    def read_process_output(self, final: bool = False) -> None:
        raw_data = bytes(self.process.readAllStandardOutput())
        text = self.output_decoder.decode(raw_data, final=final)

        if text.strip():
            self.append_log(text.rstrip())

    def process_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        self.read_process_output(final=True)
        self.cleanup_run_config()

        if self.stop_requested:
            self.set_processing_state(False)
            self.discard_run_folder()
            self.statusbar.showMessage("Roofer stopped by the user")
            self.append_log("")
            self.append_log("Roofer was stopped before it finished.")
            self.stop_requested = False
            return

        if (
            exit_status != QProcess.ExitStatus.NormalExit
            or exit_code != 0
        ):
            self.set_processing_state(False)
            self.discard_run_folder()
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
            self.set_processing_state(False)
            self.statusbar.showMessage("No output folder")
            return

        # Roofer is done. The interface stays locked while its CityJSONSeq
        # files are converted to CityJSON in the background.
        self.start_conversion(self.output_folder)

    # ------------------------------------------------------------------
    # CityJSONSeq -> CityJSON conversion (background thread)
    # ------------------------------------------------------------------

    def resolve_cjseq(self) -> Path | None:
        """The cjseq executable from the settings, PATH or Cargo's bin."""
        saved = self.settings.value(SETTINGS_CJSEQ_PATH, "", type=str).strip()

        if saved and Path(saved).is_file():
            return Path(saved)

        return find_cjseq()

    def start_conversion(self, folder: Path) -> None:
        """Convert Roofer's CityJSONSeq files; the originals are preserved."""
        sources = sorted(folder.rglob("*.jsonl"))

        if not sources:
            self.finish_run([])
            return

        cjseq = self.resolve_cjseq()

        if cjseq is None:
            # cjseq is an external executable, not a Python dependency.
            # The user may install it, expose it on PATH, or choose it in Settings.
            message = (
                "cjseq was not found. Install cjseq if it is not installed, "
                "add its executable directory to the PATH environment "
                "variable, or select the cjseq executable in Settings."
            )
            self.append_log(f"ERROR: {message}", color="#c62828")
            self.finish_run([message], cjseq_missing=True)
            return

        self.append_log("")
        self.statusbar.showMessage("Converting CityJSONSeq to CityJSON...")

        worker = CjseqConversionWorker(str(cjseq), sources, self)
        worker.log.connect(self.on_conversion_log)
        worker.done.connect(self.on_conversion_done)
        worker.finished.connect(worker.deleteLater)

        self.converter = worker
        worker.start()

    def on_conversion_log(self, text: str, color: str) -> None:
        self.append_log(text, color or None)

    def on_conversion_done(self, errors: list, cancelled: bool) -> None:
        self.converter = None

        if not cancelled:
            self.finish_run([str(error) for error in errors])
            return

        self.set_processing_state(False)

        if self.output_folder is not None:
            self.generated_files = self.collect_output_files(
                self.output_folder
            )
            self.actionOpenRunFolder.setEnabled(True)

        self.pb_view.setEnabled(bool(self.cityjson_files()))
        self.statusbar.showMessage("CityJSON conversion stopped by the user")
        self.append_log("")
        self.append_log("Conversion was stopped before it finished.")

    def finish_run(
        self, conversion_errors: list[str], cjseq_missing: bool = False
    ) -> None:
        """Report the result of a finished run (Roofer + conversion)."""
        self.set_processing_state(False)

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

        for file_path in self.generated_files:
            self.append_log(f"Created: {file_path}")

        # Only converted CityJSON files count as results: the CityJSONSeq
        # files are kept next to them as intermediate output.
        cityjson_files = self.cityjson_files()
        self.pb_view.setEnabled(bool(cityjson_files))

        if conversion_errors:
            self.statusbar.showMessage(
                "Roofer finished, some CityJSON conversions failed"
                if cityjson_files
                else "Roofer finished, CityJSON conversion failed"
            )

            QMessageBox.warning(
                self,
                "CityJSON conversion warning",
                "Roofer finished, but some CityJSON conversions failed:\n\n"
                + "\n".join(conversion_errors)
                + (
                    "" if cjseq_missing else "\n\nCheck the conversion errors above."
                )
                + "\n\nThe original CityJSONSeq files are still available.",
            )
            return

        if not cityjson_files:
            self.statusbar.showMessage("No converted CityJSON files found")
            self.append_log(
                "ERROR: Roofer finished, but no converted CityJSON "
                "(.city.json) files were created.",
                color="#c62828",
            )
            QMessageBox.warning(
                self,
                "No converted CityJSON files",
                "Roofer finished, but no converted CityJSON (.city.json) "
                "files were created. The original CityJSONSeq files "
                "remain available in the run folder.",
            )
            return

        self.statusbar.showMessage(
            "LoD 2.2 CityJSON model created successfully"
        )

        QMessageBox.information(
            self,
            "Finished",
            (
                "LoD 2.2 reconstruction completed successfully.\n\n"
                f"{len(cityjson_files)} CityJSON file(s) created with its corresponding CityJSONL file."
            ),
        )

    def cityjson_files(self) -> list[Path]:
        """The converted ``*.city.json`` files among the generated files."""
        return [
            path
            for path in self.generated_files
            if path.name.endswith(".city.json")
        ]

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

        self.discard_run_folder()
        self.statusbar.showMessage("Could not start Roofer")
        self.append_log("")
        self.append_log(f"Process error: {message}")

        QMessageBox.critical(
            self,
            "Could not run Roofer",
            f"Roofer could not be started:\n\n{message}",
        )

    # ------------------------------------------------------------------
    # View CityJSON
    # ------------------------------------------------------------------

    def view_cityjson(self) -> None:
        """Open CityJSON Ninja and reveal the file so it can be dropped in.

        Ninja has no documented way to load a file from a URL, so the file
        itself still has to be dragged into the page. The window therefore
        only prepares both sides of that drag.
        """
        cityjson_files = self.cityjson_files()

        if not cityjson_files:
            self.show_warning(
                "No CityJSON file",
                (
                    "No converted CityJSON (.city.json) file is available."
                    "\n\nGenerate a model first. If the conversion failed, "
                    "check that cjseq is installed."
                ),
            )
            return

        first_file = cityjson_files[0]

        if not first_file.is_file():
            QMessageBox.critical(
                self,
                "File not found",
                f"The generated file no longer exists:\n\n{first_file}",
            )
            return

        QDesktopServices.openUrl(QUrl(CITYJSON_NINJA_URL))
        self.show_file_in_explorer(first_file)

        # The browser and file manager should always open. Only the
        # explanatory message can be permanently hidden by the user.
        hide_message = self.settings.value(
            SETTINGS_HIDE_NINJA_MESSAGE,
            False,
            type=bool,
        )

        if not hide_message:
            message_box = QMessageBox(self)
            message_box.setIcon(QMessageBox.Icon.Information)
            message_box.setWindowTitle("View CityJSON")
            message_box.setText(
                "CityJSON Ninja has been opened in your browser and the "
                "file manager shows the generated file.\n\n"
                f"Drag {first_file.name} into the Ninja page to view it."
            )
            message_box.setStandardButtons(QMessageBox.StandardButton.Ok)

            dont_show_again = QCheckBox("Don't show this message again")
            message_box.setCheckBox(dont_show_again)

            message_box.exec()

            if dont_show_again.isChecked():
                self.settings.setValue(
                    SETTINGS_HIDE_NINJA_MESSAGE,
                    True,
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

    def append_log(self, text: str, color: str | None = None) -> None:
        scrollbar = self.log_box.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= scrollbar.maximum() - 2

        # Use a document cursor so appending does not move the user's cursor,
        # clear their selection, or force the viewport to the bottom.
        cursor = QTextCursor(self.log_box.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)

        if not self.log_box.document().isEmpty():
            # Start the new line with default formats, otherwise it would
            # inherit the colour of the previous (coloured) line.
            cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())

        text_format = QTextCharFormat()

        if color is not None:
            text_format.setForeground(QColor(color))

        cursor.insertText(text, text_format)
        if was_at_bottom:
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

    def is_busy(self) -> bool:
        """True while Roofer or the CityJSON conversion is running."""
        return (
            self.converter is not None
            or self.process.state() != QProcess.ProcessState.NotRunning
        )

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
        if self.is_busy():
            what = (
                "The CityJSON conversion"
                if self.converter is not None
                else "Roofer"
            )

            answer = QMessageBox.question(
                self,
                "Still running",
                (
                    f"{what} is still running.\n\n"
                    "Close the application and stop it?"
                ),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if answer == QMessageBox.StandardButton.No:
                event.ignore()
                return

            self.stop_requested = True

            if self.converter is not None:
                worker = self.converter
                self.converter = None

                # The window is closing: the worker must not call back into it.
                for signal in (worker.log, worker.done):
                    try:
                        signal.disconnect()
                    except TypeError:
                        pass

                worker.requestInterruption()
                if not worker.wait(5000):
                    # Keep the thread alive until it finishes; destroying a
                    # running QThread can crash the application.
                    _orphaned_workers.add(worker)
                    worker.setParent(None)
                    worker.finished.connect(
                        lambda w=worker: _orphaned_workers.discard(w)
                    )

            if self.process.state() != QProcess.ProcessState.NotRunning:
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
