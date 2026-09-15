"""Resumable multi-page PDF extraction for ebook page-evidence runs."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from siftforge.ebook.extraction import (
    EBOOK_PAGE_PROMPT_V5_R2,
    EBOOK_PAGE_SCHEMA_V5,
    EbookPageEvidenceNormalizer,
)
from siftforge.ebook.pipeline.book_assembly import (
    EbookBookAssemblyError,
    EbookPageRunLoader,
)
from siftforge.ebook.pipeline.page_evidence_extraction import (
    EbookPDFPageEvidenceExtractionService,
)
from siftforge.extraction.artifacts import FilesystemArtifactStore
from siftforge.extraction.materializers import PDFPageMaterializer
from siftforge.extraction.models import SourceRef
from siftforge.extraction.providers import Extractor
from siftforge.extraction.sources import PDFSource


class EbookBookExtractionError(RuntimeError):
    """Raised when a resumable book extraction cannot continue safely."""


class EbookBookPageStatus(StrEnum):
    """Outcome of one page during a multi-page extraction run."""

    EXTRACTED = "extracted"
    REUSED = "reused"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EbookBookPageExtractionResult:
    """Outcome and provenance for one selected physical PDF page."""

    page_number: int
    status: EbookBookPageStatus
    run_dir: Path
    usage: dict[str, int | float]
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class EbookBookExtractionProgress:
    """Progress event emitted after one selected page finishes processing."""

    completed: int
    total: int
    result: EbookBookPageExtractionResult


@dataclass(frozen=True, slots=True)
class EbookBookExtractionRun:
    """Summary of one resumable multi-page page-evidence extraction run."""

    pdf_path: Path
    runs_root: Path
    manifest_path: Path
    page_results: tuple[EbookBookPageExtractionResult, ...]
    total_usage: dict[str, int | float]

    @property
    def extracted_count(self) -> int:
        """Return the number of pages freshly extracted during this run."""
        return sum(
            item.status is EbookBookPageStatus.EXTRACTED
            for item in self.page_results
        )

    @property
    def reused_count(self) -> int:
        """Return the number of valid existing page runs reused as-is."""
        return sum(
            item.status is EbookBookPageStatus.REUSED
            for item in self.page_results
        )

    @property
    def failed_count(self) -> int:
        """Return the number of selected pages that failed extraction."""
        return sum(
            item.status is EbookBookPageStatus.FAILED
            for item in self.page_results
        )


ProgressCallback = Callable[[EbookBookExtractionProgress], None]


class EbookPDFBookEvidenceExtractionService:
    """Extract a PDF page range into canonical v5 page runs with safe resume.

    Existing page runs are reused only when their source PDF/page identity,
    active prompt/schema revision, and requested model all match. Incomplete,
    stale, or incompatible page directories are rebuilt from scratch.

    Args:
        extractor: Provider-compatible page extraction mechanism.
        normalizer: Optional strict v5 page-evidence normalizer.
        page_loader: Optional canonical page-run loader used for reuse checks.
    """

    def __init__(
        self,
        extractor: Extractor,
        normalizer: EbookPageEvidenceNormalizer | None = None,
        page_loader: EbookPageRunLoader | None = None,
    ) -> None:
        """Initialize reusable collaborators without selecting a PDF yet."""
        self._normalizer = normalizer or EbookPageEvidenceNormalizer()
        self._page_service = EbookPDFPageEvidenceExtractionService(
            extractor,
            self._normalizer,
        )
        self._page_loader = page_loader or EbookPageRunLoader()

    def extract_book(
        self,
        pdf_path: str | Path,
        runs_root: str | Path,
        *,
        model: str | None,
        start_page: int = 1,
        end_page: int | None = None,
        force: bool = False,
        continue_on_error: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> EbookBookExtractionRun:
        """Extract a physical page range with checkpointed per-page artifacts.

        Args:
            pdf_path: Input scanned PDF.
            runs_root: Root containing canonical ``page-NNNN`` directories.
            model: Expected provider model identity used to validate reusable runs.
                Pass ``None`` only for extractors that do not expose model identity.
            start_page: Inclusive one-based first physical PDF page.
            end_page: Inclusive one-based last page. Defaults to the PDF's last page.
            force: Re-extract selected pages even when valid matching runs exist.
            continue_on_error: Continue to later pages after a page failure.
            progress_callback: Optional callback invoked after every selected page.

        Returns:
            Multi-page extraction summary and persisted checkpoint manifest.

        Raises:
            EbookBookExtractionError: If page selection is invalid or a page fails
                while ``continue_on_error`` is false.
        """
        source = PDFSource(pdf_path)
        source_refs = tuple(source.iter_items())
        selected = self._select_pages(
            source_refs,
            start_page=start_page,
            end_page=end_page,
        )
        root = Path(runs_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        materializer = PDFPageMaterializer(source.path)
        results: list[EbookBookPageExtractionResult] = []
        total = len(selected)

        for source_ref in selected:
            page_number = _source_page_number(source_ref)
            run_dir = root / f"page-{page_number:04d}"
            if not force and self._is_reusable(
                run_dir=run_dir,
                source_ref=source_ref,
                model=model,
            ):
                usage = _load_page_usage(run_dir)
                result = EbookBookPageExtractionResult(
                    page_number=page_number,
                    status=EbookBookPageStatus.REUSED,
                    run_dir=run_dir,
                    usage=usage,
                )
            else:
                staging_dir = root / f".page-{page_number:04d}.extracting"
                _reset_page_run(staging_dir)
                try:
                    self._page_service.extract_source_page(
                        source_ref=source_ref,
                        materializer=materializer,
                        run_dir=staging_dir,
                    )
                    _publish_page_run(staging_dir, run_dir)
                except Exception as exc:
                    _reset_page_run(staging_dir)
                    result = EbookBookPageExtractionResult(
                        page_number=page_number,
                        status=EbookBookPageStatus.FAILED,
                        run_dir=run_dir,
                        usage={},
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                    results.append(result)
                    self._write_manifest(
                        root=root,
                        source=source,
                        source_page_count=len(source_refs),
                        selected=selected,
                        model=model,
                        force=force,
                        continue_on_error=continue_on_error,
                        results=results,
                    )
                    self._emit_progress(
                        progress_callback,
                        result=result,
                        completed=len(results),
                        total=total,
                    )
                    if continue_on_error:
                        continue
                    raise EbookBookExtractionError(
                        f"page {page_number} extraction failed: {exc}; "
                        f"resume by rerunning the same command"
                    ) from exc

                usage = _load_page_usage(run_dir)
                result = EbookBookPageExtractionResult(
                    page_number=page_number,
                    status=EbookBookPageStatus.EXTRACTED,
                    run_dir=run_dir,
                    usage=usage,
                )

            results.append(result)
            self._write_manifest(
                root=root,
                source=source,
                source_page_count=len(source_refs),
                selected=selected,
                model=model,
                force=force,
                continue_on_error=continue_on_error,
                results=results,
            )
            self._emit_progress(
                progress_callback,
                result=result,
                completed=len(results),
                total=total,
            )

        total_usage = _aggregate_usage(results)
        manifest_path = self._write_manifest(
            root=root,
            source=source,
            source_page_count=len(source_refs),
            selected=selected,
            model=model,
            force=force,
            continue_on_error=continue_on_error,
            results=results,
        )
        return EbookBookExtractionRun(
            pdf_path=source.path,
            runs_root=root,
            manifest_path=manifest_path,
            page_results=tuple(results),
            total_usage=total_usage,
        )

    @staticmethod
    def _select_pages(
        source_refs: Sequence[SourceRef],
        *,
        start_page: int,
        end_page: int | None,
    ) -> tuple[SourceRef, ...]:
        """Validate an inclusive page range and return the selected references."""
        page_count = len(source_refs)
        if page_count == 0:
            raise EbookBookExtractionError("PDF contains no pages")
        if start_page < 1:
            raise EbookBookExtractionError("start page must be at least 1")
        resolved_end = page_count if end_page is None else end_page
        if resolved_end < start_page:
            raise EbookBookExtractionError(
                "end page must be greater than or equal to start page"
            )
        if start_page > page_count or resolved_end > page_count:
            raise EbookBookExtractionError(
                f"selected page range {start_page}-{resolved_end} is outside "
                f"PDF page count {page_count}"
            )
        return tuple(source_refs[start_page - 1 : resolved_end])

    def _is_reusable(
        self,
        *,
        run_dir: Path,
        source_ref: SourceRef,
        model: str | None,
    ) -> bool:
        """Return whether an existing page run exactly matches current inputs."""
        try:
            artifact = self._page_loader.load(run_dir)
            manifest = _load_json_object(run_dir / "manifest.json")
        except (EbookBookAssemblyError, OSError, ValueError):
            return False

        if artifact.page.page_id != source_ref.source_id:
            return False
        if artifact.page.source.sha256 != source_ref.sha256:
            return False
        if _manifest_value(manifest, "source", "source_id") != source_ref.source_id:
            return False
        if _manifest_value(manifest, "source", "sha256") != source_ref.sha256:
            return False
        if (
            _manifest_value(manifest, "source", "document_sha256")
            != source_ref.metadata.get("document_sha256")
        ):
            return False
        if (
            _manifest_value(manifest, "prompt", "name")
            != EBOOK_PAGE_PROMPT_V5_R2.name
        ):
            return False
        if (
            _manifest_value(manifest, "prompt", "version")
            != EBOOK_PAGE_PROMPT_V5_R2.version
        ):
            return False
        if (
            _manifest_value(manifest, "schema", "name")
            != EBOOK_PAGE_SCHEMA_V5.name
        ):
            return False
        if (
            _manifest_value(manifest, "schema", "version")
            != EBOOK_PAGE_SCHEMA_V5.version
        ):
            return False
        if model is not None and _successful_model(manifest) != model:
            return False
        return True

    def _write_manifest(
        self,
        *,
        root: Path,
        source: PDFSource,
        source_page_count: int,
        selected: Sequence[SourceRef],
        model: str | None,
        force: bool,
        continue_on_error: bool,
        results: Sequence[EbookBookPageExtractionResult],
    ) -> Path:
        """Atomically checkpoint multi-page progress after each page."""
        payload = {
            "version": 1,
            "source": {
                "path": str(source.path),
                "document_sha256": source.document_sha256,
                "page_count": source_page_count,
            },
            "contract": {
                "prompt": {
                    "name": EBOOK_PAGE_PROMPT_V5_R2.name,
                    "version": EBOOK_PAGE_PROMPT_V5_R2.version,
                },
                "schema": {
                    "name": EBOOK_PAGE_SCHEMA_V5.name,
                    "version": EBOOK_PAGE_SCHEMA_V5.version,
                },
                "model": model,
            },
            "selection": {
                "start_page": _source_page_number(selected[0]),
                "end_page": _source_page_number(selected[-1]),
                "page_count": len(selected),
            },
            "policy": {
                "reuse_matching_runs": not force,
                "force": force,
                "continue_on_error": continue_on_error,
            },
            "summary": _summary(results, selected_count=len(selected)),
            "usage": _aggregate_usage(results),
            "pages": [
                {
                    "page_number": item.page_number,
                    "status": item.status.value,
                    "run_dir": item.run_dir.relative_to(root).as_posix(),
                    "usage": item.usage,
                    "error_type": item.error_type,
                    "error_message": item.error_message,
                }
                for item in results
            ],
        }
        store = FilesystemArtifactStore(root)
        store.write_json("book-extraction.json", payload)
        return root / "book-extraction.json"

    @staticmethod
    def _emit_progress(
        callback: ProgressCallback | None,
        *,
        result: EbookBookPageExtractionResult,
        completed: int,
        total: int,
    ) -> None:
        """Emit one progress event when a caller requested progress updates."""
        if callback is None:
            return
        callback(
            EbookBookExtractionProgress(
                completed=completed,
                total=total,
                result=result,
            )
        )


def _source_page_number(source_ref: SourceRef) -> int:
    """Return validated physical page number from one PDF source reference."""
    value = source_ref.metadata.get("page_number")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EbookBookExtractionError("PDF source reference lacks page number")
    return value


def _reset_page_run(run_dir: Path) -> None:
    """Remove stale/incomplete page artifacts before a fresh provider call."""
    if run_dir.exists():
        shutil.rmtree(run_dir)



def _publish_page_run(staging_dir: Path, run_dir: Path) -> None:
    """Replace one canonical page directory without losing the previous good run."""
    backup_dir = run_dir.with_name(f".{run_dir.name}.backup")
    _reset_page_run(backup_dir)
    had_existing = run_dir.exists()
    try:
        if had_existing:
            run_dir.replace(backup_dir)
        staging_dir.replace(run_dir)
    except Exception:
        if had_existing and backup_dir.exists() and not run_dir.exists():
            backup_dir.replace(run_dir)
        raise
    else:
        _reset_page_run(backup_dir)


def _load_json_object(path: Path) -> dict[str, Any]:
    """Load one JSON object, raising a value error for invalid content."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must contain an object: {path}")
    return payload


def _manifest_value(payload: dict[str, Any], *keys: str) -> Any:
    """Return a nested manifest value or ``None`` when it is unavailable."""
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _successful_model(manifest: dict[str, Any]) -> str | None:
    """Return model metadata from the successful page extraction attempt."""
    attempts = manifest.get("attempts")
    if not isinstance(attempts, list):
        return None
    for attempt in attempts:
        if not isinstance(attempt, dict) or attempt.get("status") != "success":
            continue
        metadata = attempt.get("metadata")
        if not isinstance(metadata, dict):
            continue
        model = metadata.get("model")
        if isinstance(model, str) and model:
            return model
    return None


def _load_page_usage(run_dir: Path) -> dict[str, int | float]:
    """Return numeric token/usage counters from one canonical page manifest."""
    try:
        manifest = _load_json_object(run_dir / "manifest.json")
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    attempts = manifest.get("attempts")
    if not isinstance(attempts, list):
        return {}
    for attempt in attempts:
        if not isinstance(attempt, dict) or attempt.get("status") != "success":
            continue
        metadata = attempt.get("metadata")
        if not isinstance(metadata, dict):
            continue
        usage = metadata.get("usage")
        if not isinstance(usage, dict):
            continue
        return {
            str(key): value
            for key, value in usage.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
    return {}


def _add_usage(
    aggregate: dict[str, int | float],
    usage: dict[str, int | float],
) -> None:
    """Add numeric provider usage counters into an aggregate dictionary."""
    for key, value in usage.items():
        aggregate[key] = aggregate.get(key, 0) + value


def _aggregate_usage(
    results: Sequence[EbookBookPageExtractionResult],
) -> dict[str, int | float]:
    """Aggregate usage from all successfully available selected page runs."""
    aggregate: dict[str, int | float] = {}
    for result in results:
        _add_usage(aggregate, result.usage)
    return aggregate


def _summary(
    results: Sequence[EbookBookPageExtractionResult],
    *,
    selected_count: int,
) -> dict[str, int]:
    """Return stable progress counters for the checkpoint manifest."""
    return {
        "selected": selected_count,
        "completed": len(results),
        "extracted": sum(
            item.status is EbookBookPageStatus.EXTRACTED for item in results
        ),
        "reused": sum(
            item.status is EbookBookPageStatus.REUSED for item in results
        ),
        "failed": sum(
            item.status is EbookBookPageStatus.FAILED for item in results
        ),
        "remaining": selected_count - len(results),
    }
