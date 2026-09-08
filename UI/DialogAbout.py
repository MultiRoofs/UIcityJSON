"""About dialog: purpose of the tool, project context, team and logos.

The logo images are optional. Any logo file that is missing is simply
skipped, so the dialog still opens correctly on a fresh clone where the
image files have not been added yet.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6 import uic
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog, QLabel


# ----------------------------------------------------------------------
# 
# ----------------------------------------------------------------------

DEVELOPERS = (
    "Alejandro Morales Hernandez",          # <-
    "Razan Saadaldeen",            # <- 
)

YEAR = "2026"

MULTIROOFS_URL = "https://multiroofs.nweurope.eu/"


# Logo files are looked up in UI/resources/. The label under each logo is
# only used as the tooltip and as the alternative text when the image
# cannot be loaded.
LOGO_FILES = (
     ("logo_interreg.png", "Interreg North-West Europe"),
    ("logo_ulb.png", "Université libre de Bruxelles"),
    ("logo_mlg.png", "MLG"),
)

# Every logo is scaled to this height so the row stays visually even
# regardless of the original image sizes.
LOGO_HEIGHT = 56


class DialogAbout(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        ui_file = Path(__file__).resolve().parent / "dialogAbout.ui"
        uic.loadUi(ui_file, self)

        self.lb_about.setText(self.about_text())
        self.load_logos()

        self.bb_actions.rejected.connect(self.reject)
        self.bb_actions.accepted.connect(self.accept)

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    @staticmethod
    def about_text() -> str:
        """The descriptive part of the dialog, as rich text."""
        developers = "<br>".join(DEVELOPERS)

        return (
            "<p>This tool generates <b>LoD 2.2 building models in CityJSON "
            "format</b> from LiDAR point clouds and 2D building "
            "footprints.</p>"
            "<p>It provides a graphical interface around the "
            "<b>Roofer</b> command-line reconstruction tool: the inputs are "
            "selected in the window, Roofer is started as an external "
            "process, and its results are written as CityJSONSequence files "
            "into a timestamped run folder so earlier results are never "
            "overwritten. The generated models can be inspected in "
            "<a href='https://ninja.cityjson.org/'>CityJSON Ninja</a>.</p>"
            "<p>The tool was developed within the scope of the "
            "<b>MultiRoofs</b> project:<br>"
            f"<a href='{MULTIROOFS_URL}'>{MULTIROOFS_URL}</a></p>"
            f"<p><b>Development team</b><br>{developers}</p>"
            f"<p>{YEAR}</p>"
        )

    # ------------------------------------------------------------------
    # Logos
    # ------------------------------------------------------------------

    def load_logos(self) -> None:
        """Add every logo that is actually present in UI/resources/.

        A missing or unreadable image is skipped instead of raising, so a
        checkout without the image files still shows a usable dialog.
        """
        resources_dir = Path(__file__).resolve().parent / "resources"
        shown = 0

        for filename, name in LOGO_FILES:
            logo_path = resources_dir / filename

            if not logo_path.is_file():
                continue

            pixmap = QPixmap(str(logo_path))

            # QPixmap returns a null pixmap for an unsupported or corrupt
            # image file instead of raising an exception.
            if pixmap.isNull():
                continue

            label = QLabel()
            label.setPixmap(
                pixmap.scaledToHeight(
                    LOGO_HEIGHT,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            label.setToolTip(name)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            self.logo_layout.addWidget(label)
            shown += 1

        if shown == 0:
            # Nothing to show: hide the empty frame so the dialog does not
            # keep a blank gap above the Close button.
            self.fr_logos.setVisible(False)
            return

        # Keeps the logos left-aligned rather than stretched apart.
        self.logo_layout.addStretch(1)
