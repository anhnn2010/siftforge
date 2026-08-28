"""One-page PDF-to-typed-content application service for ebook extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from siftforge.ebook.extraction import (
    EBOOK_PAGE_PROMPT,
    EBOOK_PAGE_SCHEMA,
    EbookPageNormalizer,
)
from siftforge.ebook.models import PageContent
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
    """Artifacts and typed result produced by one ebook page extraction run."""

    source: SourceRef
    asset: MaterializedAsset
    extraction: ExtractionResult
    page_content: PageContent
    run_dir: Path


class EbookPDFPageExtractionService:
    """Orchestrate one PDF-page extraction through the typed ebook boundary.

    Args:
        extractor: Provider-compatible extraction mechanism selected by the caller.
        normalizer: Optional ebook-domain normalizer for structured provider output.
    """

    def __init__(
        self,
        extractor: Extractor,
        normalizer: EbookPageNormalizer | None = None,
    ) -> None:
        """Initialize the service with externally selected extraction components."""
        self._extractor: Extractor = extractor
        self._normalizer: EbookPageNormalizer = normalizer or EbookPageNormalizer()

    def extract_page(
        self,
        pdf_path: str | Path,
        page_number: int,
        run_dir: str | Path,
    ) -> EbookPageExtractionRun:
        """Extract one physical PDF page into validated typed ebook content.

        Args:
            pdf_path: Input PDF containing the scanned book.
            page_number: One-based physical PDF page number.
            run_dir: Directory used for materialized assets and run artifacts.

        Returns:
            Complete one-page extraction run including typed page content.

        Raises:
            ValueError: If `page_number` is outside the PDF.
            EbookPageNormalizationError: If provider output violates the ebook
                domain contract.
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
        extraction = self._extractor.extract(task)
        page_content = self._normalizer.normalize(
            page_id=source_ref.source_id,
            payload=extraction.normalized_data,
        )

        self._write_artifacts(
            store=artifact_store,
            source=source_ref,
            asset=asset,
            extraction=extraction,
            page_content=page_content,
        )

        return EbookPageExtractionRun(
            source=source_ref,
            asset=asset,
            extraction=extraction,
            page_content=page_content,
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

    def _write_artifacts(
        self,
        store: FilesystemArtifactStore,
        source: SourceRef,
        asset: MaterializedAsset,
        extraction: ExtractionResult,
        page_content: PageContent,
    ) -> None:
        """Persist provenance, raw output, and typed normalized page content."""
        raw_text = (
            extraction.raw_data
            if isinstance(extraction.raw_data, str)
            else str(extraction.raw_data)
        )
        store.write_text("raw/provider-response.json", raw_text)
        store.write_json(
            "normalized/page.json",
            self._normalizer.to_dict(page_content),
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
                "name": extraction.task.prompt.name,
                "version": extraction.task.prompt.version,
            },
            "schema": {
                "name": extraction.task.schema.name,
                "version": extraction.task.schema.version,
            },
            "normalization": {
                "model": "PageContent",
                "status": "success",
            },
            "attempts": [
                {
                    "mechanism": attempt.mechanism,
                    "provider": attempt.provider,
                    "status": attempt.status,
                    "reason": attempt.reason,
                    "metadata": attempt.metadata,
                }
                for attempt in extraction.attempts
            ],
        }
        store.write_json("manifest.json", manifest)
