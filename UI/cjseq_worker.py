"""Background CityJSONSeq-to-CityJSON conversion with cjseq."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal


CONVERSION_TIMEOUT_SECONDS = 600
PROCESS_STOP_GRACE_SECONDS = 2
SUCCESS_COLOR = "#256628"
ERROR_COLOR = "#932626"
CANCELLED = "__cancelled__"
CITYJSON_HEADER_BYTES = 65536
CITYJSON_TYPE_PATTERN = re.compile(rb'"type"\s*:\s*"CityJSON"')


class CjseqConversionWorker(QThread):
    """Convert CityJSONSeq files without blocking the GUI thread."""

    log = pyqtSignal(str, str)
    done = pyqtSignal(list, bool)

    def __init__(
        self,
        cjseq: str,
        sources: list[Path],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.cjseq = cjseq
        self.sources = sources

    def run(self) -> None:
        errors: list[str] = []

        for source in self.sources:
            if self.isInterruptionRequested():
                self.done.emit(errors, True)
                return

            error = self.convert_one(source)

            if error == CANCELLED:
                self.done.emit(errors, True)
                return

            if error is not None:
                errors.append(error)

        self.done.emit(errors, False)

    def convert_one(self, source: Path) -> str | None:
        if source.name.endswith(".city.jsonl"):
            destination = source.with_name(source.name[:-1])
        else:
            destination = source.with_name(source.stem + ".city.json")
        temporary = destination.with_name(destination.name + ".tmp")
        conversion_message = (
            f" # Converting: {source.name} -> {destination.name}"
        )

        try:
            temporary.unlink(missing_ok=True)
            returncode, details, cancelled = self.run_command(
                [self.cjseq, "collect"],
                source,
                temporary,
            )

            if cancelled:
                return CANCELLED
            if returncode != 0:
                raise RuntimeError(
                    details or f"cjseq exited with code {returncode}"
                )
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise RuntimeError("cjseq produced no output")

            # Avoid loading a potentially huge CityJSON file into memory.
            # cjseq writes the top-level type near the beginning of its output.
            with temporary.open("rb") as output:
                header = output.read(CITYJSON_HEADER_BYTES)
            if CITYJSON_TYPE_PATTERN.search(header) is None:
                raise ValueError(
                    "cjseq did not produce a CityJSON document"
                )

            temporary.replace(destination)
            self.log.emit(conversion_message, SUCCESS_COLOR)
            self.log.emit(f"Converted: {destination}", "")
            return None

        except (
            OSError,
            RuntimeError,
            ValueError,
        ) as error:
            message = f"{source.name}: {error}"
            self.log.emit(conversion_message, ERROR_COLOR)
            self.log.emit(f"ERROR: Conversion failed: {message}", ERROR_COLOR)
            return message
        finally:
            temporary.unlink(missing_ok=True)

    def run_command(
        self,
        command: list[str],
        input_path: Path,
        output_path: Path,
    ) -> tuple[int, str, bool]:
        creation_flags = 0
        if os.name == "nt":
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        with input_path.open("rb") as input_file, output_path.open(
            "wb"
        ) as output_file, subprocess.Popen(
                command,
                stdin=input_file,
                stdout=output_file,
                stderr=subprocess.PIPE,
                creationflags=creation_flags,
            ) as process:
            deadline = time.monotonic() + CONVERSION_TIMEOUT_SECONDS

            while True:
                try:
                    _, stderr = process.communicate(timeout=0.1)
                except subprocess.TimeoutExpired:
                    if self.isInterruptionRequested():
                        self.stop_process(process)
                        return -1, "", True

                    if time.monotonic() >= deadline:
                        self.stop_process(process)
                        raise RuntimeError(
                            "cjseq conversion timed out after "
                            f"{CONVERSION_TIMEOUT_SECONDS} seconds"
                        )
                    continue

                details = stderr.decode(
                    "utf-8",
                    errors="replace",
                ).strip()
                return process.returncode, details, False

    @staticmethod
    def stop_process(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return

        process.terminate()
        try:
            process.wait(timeout=PROCESS_STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
