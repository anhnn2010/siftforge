"""One-command scanned-PDF to EPUB orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from siftforge.ebook.metadata import BookMetadataError, resolve_book_metadata
from siftforge.extraction.providers import Extractor

from .book_extraction import (
    EbookBookExtractionError,
    EbookBookExtractionRun,
    EbookPDFBookEvidenceExtractionService,
    ProgressCallback,
)
from .build_epub import EbookBuildError, EbookBuildRun, EbookBuildService


class EbookPdfToEpubError(ValueError):
    """Raised when the PDF-to-EPUB orchestration cannot complete safely."""


@dataclass(frozen=True, slots=True)
class EbookPdfToEpubRun:
    """Extraction and optional build results from one PDF-to-EPUB invocation."""

    pdf_path: Path
    runs_root: Path
    work_dir: Path
    extraction: EbookBookExtractionRun
    build: EbookBuildRun | None
    manifest_path: Path

    @property
    def complete(self) -> bool:
        """Return whether every page succeeded and a final EPUB was built."""
        return self.extraction.failed_count == 0 and self.build is not None


class EbookPdfToEpubService:
    """Resume page extraction, then build a complete EPUB when pages are ready.

    The orchestrator composes the existing extraction and provider-free build
    services without moving their responsibilities. A final EPUB is created
    only when the full physical PDF page range has no failed pages.

    Args:
        extractor: Provider-compatible page extraction mechanism.
        extraction_service: Optional injected extraction service for tests.
        build_service: Optional injected provider-free build service for tests.
    """

    def __init__(
        self,
        extractor: Extractor,
        extraction_service: EbookPDFBookEvidenceExtractionService | None = None,
        build_service: EbookBuildService | None = None,
    ) -> None:
        """Initialize the orchestration collaborators."""
        self._extraction = extraction_service or EbookPDFBookEvidenceExtractionService(
            extractor
        )
        self._build = build_service or EbookBuildService()

    def convert(
        self,
        pdf_path: str | Path,
        output_path: str | Path,
        *,
        model: str,
        title: str | None = None,
        runs_root: str | Path | None = None,
        language: str | None = None,
        author: str | None = None,
        metadata_path: str | Path | None = None,
        cover_path: str | Path | None = None,
        work_dir: str | Path | None = None,
        identifier: str | None = None,
        modified: str | None = None,
        force_extract: bool = False,
        continue_on_error: bool = False,
        validate: bool = False,
        epubcheck_jar: str | Path | None = None,
        java_command: str = "java",
        timeout_seconds: float = 120.0,
        report_path: str | Path | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> EbookPdfToEpubRun:
        """Convert the complete physical PDF into a final EPUB when possible.

        Existing canonical page runs are reused only when the extraction layer
        verifies that they exactly match the current PDF, prompt/schema, and
        model. The provider-free build is attempted only after every physical
        page in the PDF has a successful canonical run.

        Args:
            pdf_path: Input scanned PDF.
            output_path: Destination final ``.epub`` archive.
            model: Provider model identity used for all page extraction.
            title: Optional publication title override.
            runs_root: Optional canonical page-run root.
            language: Optional BCP 47 publication language override.
            author: Optional single-author override.
            metadata_path: Optional ``metadata.json`` for rich book metadata.
            cover_path: Optional cover image override.
            work_dir: Optional provider-free build workspace.
            identifier: Optional publication identifier.
            modified: Optional deterministic EPUB modified timestamp.
            force_extract: Re-extract every physical page instead of reusing runs.
            continue_on_error: Continue extracting later pages after page failures.
            validate: Whether to run EPUBCheck after packaging.
            epubcheck_jar: Optional EPUBCheck JAR path.
            java_command: Java executable used for EPUBCheck.
            timeout_seconds: EPUBCheck timeout in seconds.
            report_path: Optional EPUBCheck JSON report path.
            progress_callback: Optional callback after each physical page.

        Returns:
            Extraction result plus a build result when all pages succeeded.

        Raises:
            EbookPdfToEpubError: If configuration, extraction, or build fails.
        """
        pdf = Path(pdf_path).expanduser().resolve()
        output = Path(output_path).expanduser().resolve()
        root = (
            Path(runs_root).expanduser().resolve()
            if runs_root is not None
            else (Path.cwd() / "runs" / pdf.stem).resolve()
        )
        workspace = (
            Path(work_dir).expanduser().resolve()
            if work_dir is not None
            else (root.parent / f"{root.name}-build").resolve()
        )

        if not model.strip():
            raise EbookPdfToEpubError("model must not be empty")
        default_metadata = root / "metadata.json"
        resolved_metadata_path = (
            Path(metadata_path).expanduser().resolve()
            if metadata_path is not None
            else (default_metadata if default_metadata.is_file() else None)
        )
        try:
            resolve_book_metadata(
                metadata_path=resolved_metadata_path,
                title=title,
                language=language,
                author=author,
            )
        except BookMetadataError as exc:
            raise EbookPdfToEpubError(str(exc)) from exc

        try:
            extraction = self._extraction.extract_book(
                pdf,
                root,
                model=model,
                force=force_extract,
                continue_on_error=continue_on_error,
                progress_callback=progress_callback,
            )
        except (FileNotFoundError, EbookBookExtractionError) as exc:
            raise EbookPdfToEpubError(str(exc)) from exc

        build: EbookBuildRun | None = None
        if extraction.failed_count == 0:
            try:
                build = self._build.build(
                    root,
                    output,
                    title=title,
                    language=language,
                    author=author,
                    metadata_path=resolved_metadata_path,
                    cover_path=cover_path,
                    work_dir=workspace,
                    identifier=identifier,
                    modified=modified,
                    validate=validate,
                    epubcheck_jar=epubcheck_jar,
                    java_command=java_command,
                    timeout_seconds=timeout_seconds,
                    report_path=report_path,
                )
            except EbookBuildError as exc:
                raise EbookPdfToEpubError(str(exc)) from exc

        manifest_path = _write_conversion_manifest(
            workspace=workspace,
            pdf_path=pdf,
            output_path=output,
            model=model,
            extraction=extraction,
            build=build,
        )
        return EbookPdfToEpubRun(
            pdf_path=pdf,
            runs_root=root,
            work_dir=workspace,
            extraction=extraction,
            build=build,
            manifest_path=manifest_path,
        )


def _write_conversion_manifest(
    *,
    workspace: Path,
    pdf_path: Path,
    output_path: Path,
    model: str,
    extraction: EbookBookExtractionRun,
    build: EbookBuildRun | None,
) -> Path:
    """Persist high-level provenance across extraction and provider-free build."""
    workspace.mkdir(parents=True, exist_ok=True)
    manifest = workspace / "conversion-manifest.json"
    payload = {
        "format": "siftforge-pdf-to-epub",
        "pdf": str(pdf_path),
        "runs_root": str(extraction.runs_root),
        "output_epub": str(output_path),
        "model": model,
        "status": "complete" if build is not None else "incomplete",
        "extraction": {
            "manifest": str(extraction.manifest_path),
            "pages": len(extraction.page_results),
            "extracted": extraction.extracted_count,
            "reused": extraction.reused_count,
            "failed": extraction.failed_count,
            "usage": extraction.total_usage,
        },
        "build": _build_manifest(build),
    }
    manifest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def _build_manifest(build: EbookBuildRun | None) -> dict[str, object]:
    """Serialize the optional provider-free build result compactly."""
    if build is None:
        return {
            "attempted": False,
            "manifest": None,
            "epub": None,
            "epubcheck_passed": None,
        }
    validation = build.validation
    return {
        "attempted": True,
        "manifest": str(build.manifest_path),
        "epub": str(build.package.package.epub_path),
        "epubcheck_passed": (
            validation.result.passed if validation is not None else None
        ),
    }
