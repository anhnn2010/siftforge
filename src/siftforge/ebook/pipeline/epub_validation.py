"""Validate generated EPUB archives with the official EPUBCheck tool."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from siftforge.ebook.epub import (
    EpubCheckExecutionError,
    EpubCheckResult,
    EpubCheckRunner,
)


class EbookEpubValidationError(ValueError):
    """Raised when the EPUBCheck validation workflow cannot execute."""


@dataclass(frozen=True, slots=True)
class EbookEpubValidationRun:
    """Result and optional persisted report for one EPUBCheck run."""

    result: EpubCheckResult
    report_path: Path | None


class EbookEpubValidationService:
    """Run EPUBCheck and optionally persist the captured validation report."""

    def validate(
        self,
        epub_path: str | Path,
        epubcheck_jar: str | Path,
        *,
        java_command: str = "java",
        timeout_seconds: float = 120.0,
        report_path: str | Path | None = None,
    ) -> EbookEpubValidationRun:
        """Validate one EPUB without changing the archive being checked."""
        try:
            runner = EpubCheckRunner(
                java_command=java_command,
                timeout_seconds=timeout_seconds,
            )
            result = runner.validate(epub_path, epubcheck_jar)
        except (ValueError, EpubCheckExecutionError) as exc:
            raise EbookEpubValidationError(str(exc)) from exc

        persisted: Path | None = None
        if report_path is not None:
            persisted = Path(report_path).expanduser().resolve()
            persisted.parent.mkdir(parents=True, exist_ok=True)
            persisted.write_text(result.to_json(), encoding="utf-8")

        return EbookEpubValidationRun(
            result=result,
            report_path=persisted,
        )
