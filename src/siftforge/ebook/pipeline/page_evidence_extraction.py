"""One-page PDF-to-v5-evidence application service for ebook extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from siftforge.ebook.evidence import PageExtraction
from siftforge.ebook.extraction import (
    EBOOK_PAGE_PROMPT_V5,
    EBOOK_PAGE_SCHEMA_V5,
    EbookPageEvidenceNormalizer,
)
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
class EbookPageEvidenceExtractionRun:
    """Artifacts and typed evidence produced by one v5 page extraction run."""

    source: SourceRef
    asset: MaterializedAsset
    extraction: ExtractionResult
    page_evidence: PageExtraction
    run_dir: Path


class EbookPDFPageEvidenceExtractionService:
    """Orchestrate one PDF page through the active v5 page-evidence contract.

    Args:
        extractor: Provider-compatible extraction mechanism selected by the caller.
        normalizer: Optional strict v5 evidence normalizer.
    """

    def __init__(
        self,
        extractor: Extractor,
        normalizer: EbookPageEvidenceNormalizer | None = None,
    ) -> None:
        """Initialize the service without selecting provider/model policy."""
        self._extractor: Extractor = extractor
        self._normalizer: EbookPageEvidenceNormalizer = (
            normalizer or EbookPageEvidenceNormalizer()
        )

    def extract_page(
        self,
        pdf_path: str | Path,
        page_number: int,
        run_dir: str | Path,
    ) -> EbookPageEvidenceExtractionRun:
        """Extract one physical PDF page into strict v5 page-local evidence.

        Args:
            pdf_path: Input PDF containing the scanned book.
            page_number: One-based physical PDF page number.
            run_dir: Directory used for materialized assets and run artifacts.

        Returns:
            Complete one-page extraction run including typed page evidence.

        Raises:
            ValueError: If ``page_number`` is outside the PDF.
            EbookPageNormalizationError: If provider output violates the v5
                page-evidence contract.
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
            prompt=EBOOK_PAGE_PROMPT_V5,
            schema=EBOOK_PAGE_SCHEMA_V5,
            assets=(asset,),
            metadata={
                "application": "ebook",
                "contract_version": "5",
                "output_model": "PageExtraction",
            },
        )
        extraction = self._extractor.extract(task)
        page_evidence = self._normalizer.normalize(
            page_id=source_ref.source_id,
            source=source_ref,
            payload=extraction.normalized_data,
        )

        self._write_artifacts(
            store=artifact_store,
            source=source_ref,
            asset=asset,
            extraction=extraction,
            page_evidence=page_evidence,
        )

        return EbookPageEvidenceExtractionRun(
            source=source_ref,
            asset=asset,
            extraction=extraction,
            page_evidence=page_evidence,
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
        page_evidence: PageExtraction,
    ) -> None:
        """Persist provenance, raw output, and normalized v5 page evidence."""
        raw_text = (
            extraction.raw_data
            if isinstance(extraction.raw_data, str)
            else str(extraction.raw_data)
        )
        store.write_text("raw/provider-response.json", raw_text)
        store.write_json(
            "normalized/page.json",
            self._normalizer.to_dict(page_evidence),
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
                "model": "PageExtraction",
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
