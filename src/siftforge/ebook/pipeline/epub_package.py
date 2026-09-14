"""Package persisted EPUB-ready XHTML artifacts into a final EPUB archive."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from siftforge.ebook.epub import (
    EpubPackageBuilder,
    EpubPackageError,
    EpubPackageResult,
)


class EbookEpubPackageError(ValueError):
    """Raised when an EPUB-ready directory cannot be packaged."""


@dataclass(frozen=True, slots=True)
class EbookEpubPackageRun:
    """Result of one provider-free EPUB packaging run."""

    package: EpubPackageResult


class EbookEpubPackageService:
    """Create one EPUB 3 archive from EPUB-ready XHTML artifacts."""

    def __init__(self) -> None:
        """Initialize the deterministic EPUB package builder."""
        self._builder = EpubPackageBuilder()

    def build(
        self,
        epub_ready_root: str | Path,
        output_path: str | Path,
        *,
        identifier: str | None = None,
        modified: str | None = None,
    ) -> EbookEpubPackageRun:
        """Build and structurally validate one EPUB archive."""
        try:
            package = self._builder.build(
                epub_ready_root,
                output_path,
                identifier=identifier,
                modified=modified,
            )
        except EpubPackageError as exc:
            raise EbookEpubPackageError(str(exc)) from exc
        return EbookEpubPackageRun(package=package)
