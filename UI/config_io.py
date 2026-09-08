"""Reading and writing Roofer TOML configuration files.

Every edit goes through :mod:`tomlkit` so that comments, key order and
formatting of the user's configuration file are preserved.  

All functions raise :class:`ConfigError` on any problem; the GUI turns
that into a message box.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:  # pragma: no cover - trivial import guard
    import tomlkit
except ImportError:  # tomlkit is an explicit runtime requirement
    tomlkit = None  # type: ignore[assignment]


POLYGON_KEY = "polygon-source"
OUTPUT_KEY = "output-directory"
POINTCLOUDS_KEY = "pointclouds"
SOURCE_KEY = "source"

TOMLKIT_MISSING = (
    "The 'tomlkit' package is required to read and write Roofer "
    "configuration files.\n\nInstall it with:\n\n    pip install tomlkit"
)


class ConfigError(Exception):
    """Any problem while reading, editing or writing a configuration."""


def _require_tomlkit() -> None:
    if tomlkit is None:
        raise ConfigError(TOMLKIT_MISSING)


# ----------------------------------------------------------------------
# Loading / saving
# ----------------------------------------------------------------------


def load_document(config_path: Path) -> Any:
    """Parse ``config_path`` and return an editable tomlkit document."""
    _require_tomlkit()

    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(
            f"The configuration file could not be read:\n\n{error}"
        ) from error

    try: 
        return tomlkit.parse(text) #convert the text into a structured document
    except Exception as error:  # tomlkit raises several parse errors
        raise ConfigError(
            f"The configuration file is not valid TOML:\n\n{error}"
        ) from error


def dumps(document: Any) -> str:
    """Serialise a document back to TOML text."""
    _require_tomlkit()
    return tomlkit.dumps(document)


def write_document(
    document: Any,
    target_path: Path,
    make_backup: bool = False,
) -> None:
    """Write ``document`` to ``target_path`` atomically.

    When ``make_backup`` is true an existing file is first copied to
    ``<name>.bak`` so the user can always recover the original.
    """
    text = dumps(document)
    temp_path = target_path.with_name(target_path.name + ".writing")

    try:
        if make_backup and target_path.is_file():
            backup_path = target_path.with_name(target_path.name + ".bak")
            backup_path.write_text(
                target_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

        temp_path.write_text(text, encoding="utf-8")
        os.replace(temp_path, target_path)
    except OSError as error:
        temp_path.unlink(missing_ok=True)
        raise ConfigError(
            f"The configuration file could not be written:\n\n{error}"
        ) from error


# ----------------------------------------------------------------------
# Reading values
# ----------------------------------------------------------------------


def _as_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def polygon_source(document: Any) -> str:
    return _as_text(document.get(POLYGON_KEY))


def output_directory(document: Any) -> str:
    return _as_text(document.get(OUTPUT_KEY))


def has_output_directory(document: Any) -> bool:
    """True when the configuration sets a top-level ``output-directory``."""
    return OUTPUT_KEY in document


def pointcloud_count(document: Any) -> int:
    pointclouds = document.get(POINTCLOUDS_KEY)

    if pointclouds is None:
        return 0

    try:
        return len(pointclouds)
    except TypeError:
        return 0


def pointcloud_sources(document: Any) -> list[str]:
    """Return every non-empty point-cloud source from all entries."""
    pointclouds = document.get(POINTCLOUDS_KEY)

    if pointclouds is None:
        return []

    result: list[str] = []

    try:
        entries = list(pointclouds)
    except TypeError:
        return []

    for entry in entries:
        if not hasattr(entry, "get"):
            raise ConfigError(
                "The 'pointclouds' value in this configuration is not a "
                "[[pointclouds]] table."
            )

        source = entry.get(SOURCE_KEY)

        if isinstance(source, str):
            text = source.strip()
            if text:
                result.append(text)
            continue

        if isinstance(source, (list, tuple)):
            for item in source:
                text = _as_text(item)
                if text:
                    result.append(text)

    return result


def first_pointcloud_source(document: Any) -> str:
    """Return the first configured source path, if any."""
    sources = pointcloud_sources(document)
    return sources[0] if sources else ""


def resolved_pointcloud_sources(
    document: Any,
    base_dir: Path,
) -> list[str]:
    """Return all configured point-cloud sources as absolute paths."""
    return [
        resolve(base_dir, source)
        for source in pointcloud_sources(document)
        if source
    ]


def can_edit_pointcloud_sources(document: Any) -> bool:
    """Whether the GUI can safely rewrite the point-cloud source structure.

    One ``[[pointclouds]]`` table may contain one or many source files and is
    representable by the GUI. Multiple tables may carry different metadata,
    so they are kept read-only to avoid flattening their structure.
    """
    return pointcloud_count(document) <= 1


def resolve(base_dir: Path, value: str) -> str:
    """Turn a (possibly relative) configuration value into an absolute path."""
    value = _as_text(value)

    if not value:
        return ""

    path = Path(value).expanduser()

    if not path.is_absolute():
        path = base_dir / path

    try:
        return str(path.resolve())
    except OSError:
        return str(path)

#config_paths() is a small helper function in config_io.py. Its job is
# :Take the important paths from the parsed TOML configuration and convert them into absolute paths.
def config_paths(document: Any, base_dir: Path) -> dict[str, str]:
    """The LiDAR / footprint / output paths of a configuration, absolute."""
    return {
        "lidar": resolve(base_dir, first_pointcloud_source(document)),
        "footprint": resolve(base_dir, polygon_source(document)),
        "output": resolve(base_dir, output_directory(document)),
    }


def relative_to_config(absolute_text: str, config_dir: Path) -> str:
    """Express an absolute path relative to the configuration folder.

    Roofer resolves relative paths against the configuration file, so
    keeping paths relative makes the configuration portable.  On Windows a
    path on another drive cannot be made relative; the absolute path is
    used in that case.
    """
    if not absolute_text:
        return ""

    path = Path(absolute_text)

    try:
        return Path(os.path.relpath(path, config_dir)).as_posix()
    except ValueError:
        return path.as_posix()


# ----------------------------------------------------------------------
# Writing values
# ----------------------------------------------------------------------


def set_polygon_source(document: Any, value: str) -> None:
    document[POLYGON_KEY] = value


def set_output_directory(document: Any, value: str) -> None:
    """Set ``output-directory``, but only when the key already exists.

    Roofer takes the output directory from the command line, so a
    configuration that does not mention the key should not suddenly gain it.
    """
    if OUTPUT_KEY in document:
        document[OUTPUT_KEY] = value


def set_pointcloud_sources(
    document: Any,
    values: list[str],
) -> None:
    """Set one or more sources in a single ``[[pointclouds]]`` table.

    Multiple ``[[pointclouds]]`` tables are not rewritten because each table
    can carry independent metadata such as quality/date/class information.
    """
    _require_tomlkit()

    cleaned = [
        value.strip()
        for value in values
        if isinstance(value, str) and value.strip()
    ]

    if not cleaned:
        return

    if not can_edit_pointcloud_sources(document):
        raise ConfigError(
            "This configuration contains multiple [[pointclouds]] tables. "
            "The GUI will not rewrite them because doing so could lose "
            "table-specific metadata."
        )

    if pointcloud_count(document) == 0:
        table = tomlkit.table()

        if len(cleaned) == 1:
            table[SOURCE_KEY] = cleaned[0]
        else:
            array = tomlkit.array()
            for value in cleaned:
                array.append(value)
            table[SOURCE_KEY] = array

        aot = tomlkit.aot()
        aot.append(table)
        document[POINTCLOUDS_KEY] = aot
        return

    entry = document[POINTCLOUDS_KEY][0]

    if not hasattr(entry, "get"):
        # e.g. pointclouds = ["a.laz"] instead of [[pointclouds]] tables.
        raise ConfigError(
            "The 'pointclouds' value in this configuration is not a "
            "[[pointclouds]] table, so the GUI cannot rewrite it."
        )

    existing = entry.get(SOURCE_KEY)

    if len(cleaned) == 1 and isinstance(existing, str):
        entry[SOURCE_KEY] = cleaned[0]
        return

    array = tomlkit.array()
    for value in cleaned:
        array.append(value)

    entry[SOURCE_KEY] = array


def apply_paths(
    document: Any,
    config_dir: Path,
    lidar: str | list[str] | None,
    footprint: str,
    output: str | None = None,
) -> None:
    """Write the given absolute paths into ``document``.

    ``lidar`` may be one path, multiple paths, or ``None`` to leave the
    point-cloud structure untouched. ``output`` is optional; when omitted,
    the existing ``output-directory`` is left unchanged.
    """
    if footprint:
        set_polygon_source(
            document,
            relative_to_config(footprint, config_dir),
        )

    if lidar is not None:
        if isinstance(lidar, str):
            lidar_values = [lidar] if lidar else []
        else:
            lidar_values = [value for value in lidar if value]

        if lidar_values:
            set_pointcloud_sources(
                document,
                [
                    relative_to_config(value, config_dir)
                    for value in lidar_values
                ],
            )

    if output is not None:
        set_output_directory(
            document,
            relative_to_config(output, config_dir),
        )

