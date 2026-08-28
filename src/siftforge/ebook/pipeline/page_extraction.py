"""One-page PDF-to-structured-data application service for ebook extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from siftforge.ebook.extraction import EBOOK_PAGE_PROMPT, EBOOK_PAGE_SCHEMA
from siftforge.extraction.artifacts import FilesystemArtifactStore
from siftforge.extraction.materializers import PDFPageMaterializer
from siftforge.extraction.models import (
    ExtractionResult,
    ExtractionTask,
    MaterializedAsset,
    SourceRef,
)
from siftforge.extraction.providers import Extractor
from siftforge.extraction.sources import PDFSource


@dataclass(frozen=True, slots=True)
class EbookPageExtractionRun:
    """Artifacts and result produced by one ebook page extraction run."""

    source: SourceRef
    asset: MaterializedAsset
    result: ExtractionResult
    run_dir: Path


class EbookPDFPageExtractionService:
    """Orchestrate the first real ebook extraction vertical slice.

    This service owns ebook/PDF application wiring but delegates generic work to
    source, materializer, provider, and artifact components.

    Args:
        extractor: Provider-compatible extraction mechanism selected by the caller.
    """

    def __init__(self, extractor: Extractor) -> None:
        """Initialize the service with one externally selected extractor."""
        self._extractor: Extractor = extractor

    def extract_page(
        self,
        pdf_path: str | Path,
        page_number: int,
        run_dir: str | Path,
    ) -> EbookPageExtractionRun:
        """Extract one physical PDF page into structured ebook page content.

        Args:
            pdf_path: Input PDF containing the scanned book.
            page_number: One-based physical PDF page number.
            run_dir: Directory used for materialized assets and run artifacts.

        Returns:
            Complete one-page extraction run.

        Raises:
            ValueError: If `page_number` is outside the PDF.
        """
        if page_number < 1:
            raise ValueError("page number must be greater than or equal to 1")

        run_path = Path(run_dir).expanduser().resolve()
        artifact_store = FilesystemArtifactStore(run_path)
        pdf_source = PDFSource(pdf_path)
        source_ref = self._find_page(pdf_source, page_number)

        materializer = PDFPageMaterializer(pdf_source.path)
        asset = materializer.materialize(source_ref, run_path / "assets")

        task = ExtractionTask(
            source=source_ref,
            capability="document_transcription",
            prompt=EBOOK_PAGE_PROMPT,
            schema=EBOOK_PAGE_SCHEMA,
            assets=(asset,),
            metadata={"application": "ebook"},
        )
        result = self._extractor.extract(task)

        self._write_artifacts(
            store=artifact_store,
            source=source_ref,
            asset=asset,
            result=result,
        )

        return EbookPageExtractionRun(
            source=source_ref,
            asset=asset,
            result=result,
            run_dir=run_path,
        )

    @staticmethod
    def _find_page(pdf_source: PDFSource, page_number: int) -> SourceRef:
        """Return the requested one-based page reference from a PDF source."""
        for source_ref in pdf_source.iter_items():
            if source_ref.metadata.get("page_number") == page_number:
                return source_ref

        raise ValueError(
            f"page {page_number} is outside PDF {pdf_source.path.name!r}"
        )

    @staticmethod
    def _write_artifacts(
        store: FilesystemArtifactStore,
        source: SourceRef,
        asset: MaterializedAsset,
        result: ExtractionResult,
    ) -> None:
        """Persist provenance, raw provider output, and normalized page data."""
        raw_text = (
            result.raw_data
            if isinstance(result.raw_data, str)
            else str(result.raw_data)
        )
        store.write_text("raw/provider-response.json", raw_text)

        if isinstance(result.normalized_data, (dict, list)):
            store.write_json("normalized/page.json", result.normalized_data)
        else:
            store.write_json(
                "normalized/page.json",
                {"value": result.normalized_data},
            )

        manifest: dict[str, Any] = {
            "source": {
                "source_id": source.source_id,
                "uri": source.uri,
                "sha256": source.sha256,
                "media_type": source.media_type,
                "page_number": source.metadata.get("page_number"),
                "document_sha256": source.metadata.get("document_sha256"),
            },
            "asset": {
                "path": str(asset.path.relative_to(store.root)),
                "media_type": asset.media_type,
                "sha256": asset.sha256,
                "byte_size": asset.byte_size,
                "preserved_encoded_source": asset.metadata.get(
                    "preserved_encoded_source"
                ),
            },
            "prompt": {
                "name": result.task.prompt.name,
                "version": result.task.prompt.version,
            },
            "schema": {
                "name": result.task.schema.name,
                "version": result.task.schema.version,
            },
            "attempts": [
                {
                    "mechanism": attempt.mechanism,
                    "provider": attempt.provider,
                    "status": attempt.status,
                    "reason": attempt.reason,
                    "metadata": attempt.metadata,
                }
                for attempt in result.attempts
            ],
        }
        store.write_json("manifest.json", manifest)
