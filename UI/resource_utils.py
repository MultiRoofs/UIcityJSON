"""Helpers for locating UI/resource files in source and PyInstaller builds."""

from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative_path: str | Path) -> Path:
    """Return the absolute path of a resource inside the UI package.

    In normal source execution, resources live beside this module.
    In a PyInstaller build, bundled resources are available below
    ``sys._MEIPASS/UI``.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_dir = Path(sys._MEIPASS) / "UI"
    else:
        base_dir = Path(__file__).resolve().parent

    return base_dir / Path(relative_path)
