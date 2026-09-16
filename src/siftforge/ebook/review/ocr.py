"""Local OCR adapters used as independent text-review evidence."""

from __future__ import annotations

import csv
import io
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import OcrPage, OcrWord


class LocalOcrError(RuntimeError):
    """Raised when the configured local OCR engine cannot produce evidence."""


@dataclass(frozen=True, slots=True)
class TesseractOcrConfig:
    """Configuration for the local Tesseract command-line adapter."""

    command: str = "tesseract"
    language: str = "vie+eng"
    page_segmentation_mode: int = 3
    minimum_confidence: float = 0.0


class TesseractOcrEngine:
    """Run Tesseract TSV locally and preserve word bounding boxes."""

    def __init__(self, config: TesseractOcrConfig | None = None) -> None:
        """Initialize the engine with an explicit or default configuration."""
        self._config = config or TesseractOcrConfig()

    def cache_key(self) -> str:
        """Return a stable key for review-cache compatibility checks."""
        config = self._config
        return (
            "tesseract"
            f"|command={config.command}"
            f"|language={config.language}"
            f"|psm={config.page_segmentation_mode}"
            f"|minimum_confidence={config.minimum_confidence:g}"
        )

    def extract(self, image_path: str | Path) -> OcrPage:
        """Extract one page image as plain review text plus OCR word boxes."""
        image = Path(image_path).expanduser().resolve()
        if not image.is_file():
            raise LocalOcrError(f"OCR image does not exist: {image}")
        if shutil.which(self._config.command) is None:
            raise LocalOcrError(
                f"OCR command is not available: {self._config.command}"
            )
        command = [
            self._config.command,
            str(image),
            "stdout",
            "-l",
            self._config.language,
            "--psm",
            str(self._config.page_segmentation_mode),
            "tsv",
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except OSError as exc:
            raise LocalOcrError(f"failed to launch local OCR: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or "unknown Tesseract failure"
            raise LocalOcrError(
                f"local OCR failed with exit {result.returncode}: {detail}"
            )
        return _parse_tesseract_tsv(
            result.stdout,
            language=self._config.language,
            minimum_confidence=self._config.minimum_confidence,
        )


def _parse_tesseract_tsv(
    payload: str,
    *,
    language: str,
    minimum_confidence: float,
) -> OcrPage:
    """Parse Tesseract TSV and reconstruct punctuation-aware reading text."""
    reader = csv.DictReader(io.StringIO(payload), delimiter="\t")
    parsed: list[tuple[str, float, int, int, int, int]] = []
    for row in reader:
        if row.get("level") != "5":
            continue
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            confidence = float(row.get("conf", "-1"))
            left = int(row.get("left", "0"))
            top = int(row.get("top", "0"))
            width = int(row.get("width", "0"))
            height = int(row.get("height", "0"))
        except ValueError as exc:
            raise LocalOcrError("invalid numeric field in Tesseract TSV") from exc
        if confidence < minimum_confidence:
            continue
        parsed.append((text, confidence, left, top, width, height))

    text_parts: list[str] = []
    words: list[OcrWord] = []
    current_length = 0
    previous = ""
    for word_text, confidence, left, top, width, height in parsed:
        separator = _word_separator(previous, word_text)
        if separator:
            text_parts.append(separator)
            current_length += len(separator)
        start = current_length
        text_parts.append(word_text)
        current_length += len(word_text)
        words.append(
            OcrWord(
                text=word_text,
                confidence=confidence,
                left=left,
                top=top,
                width=width,
                height=height,
                start=start,
                end=current_length,
            )
        )
        previous = word_text

    return OcrPage(
        text="".join(text_parts),
        words=tuple(words),
        engine="tesseract",
        language=language,
    )


def _word_separator(previous: str, current: str) -> str:
    """Choose a conservative separator when reconstructing OCR words."""
    if not previous:
        return ""
    if current[0] in ".,;:!?%)]}»”’":
        return ""
    if previous[-1] in "([{«“‘":
        return ""
    return " "
