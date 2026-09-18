"""AI-assisted extraction of reviewable book metadata from PDF front matter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from siftforge.ebook.extraction import EBOOK_METADATA_PROMPT_V1, EBOOK_METADATA_SCHEMA_V1
from siftforge.ebook.metadata import BookMetadata, book_metadata_from_dict, write_book_metadata
from siftforge.extraction.materializers import PDFPageMaterializer
from siftforge.extraction.models import ExtractionTask, SourceRef
from siftforge.extraction.providers import Extractor
from siftforge.extraction.sources import PDFSource


class EbookMetadataExtractionError(RuntimeError):
    """Raised when front-matter metadata cannot be extracted safely."""


@dataclass(frozen=True, slots=True)
class EbookMetadataExtractionRun:
    """Artifacts and typed result from one metadata extraction run."""

    metadata: BookMetadata
    metadata_path: Path
    report_path: Path
    selected_pages: tuple[int, ...]
    cover_page_number: int | None
    title_page_number: int | None
    copyright_page_number: int | None
    warnings: tuple[str, ...]


class EbookPDFMetadataExtractionService:
    """Extract bibliographic metadata from selected PDF front-matter pages."""

    def __init__(self, extractor: Extractor) -> None:
        """Store the provider-independent structured extractor."""
        self._extractor = extractor

    def extract(
        self,
        *,
        pdf_path: str | Path,
        output_path: str | Path,
        start_page: int = 1,
        end_page: int = 8,
        work_dir: str | Path | None = None,
    ) -> EbookMetadataExtractionRun:
        """Extract metadata, persist ``metadata.json``, and save review diagnostics."""
        pdf = Path(pdf_path).expanduser().resolve()
        if start_page < 1 or end_page < start_page:
            raise EbookMetadataExtractionError("invalid metadata page range")

        source = PDFSource(pdf)
        items = tuple(source.iter_items())
        if not items:
            raise EbookMetadataExtractionError("PDF contains no pages")
        if start_page > len(items):
            raise EbookMetadataExtractionError(
                f"start page {start_page} is outside PDF with {len(items)} pages"
            )
        selected = items[start_page - 1 : min(end_page, len(items))]
        selected_pages = tuple(
            int(item.metadata["page_number"]) for item in selected
        )

        destination = Path(output_path).expanduser().resolve()
        scratch = (
            Path(work_dir).expanduser().resolve()
            if work_dir is not None
            else destination.parent / ".metadata-assets"
        )
        materializer = PDFPageMaterializer(pdf)
        assets = tuple(materializer.materialize(item, scratch) for item in selected)

        book_source = SourceRef(
            source_id=f"pdf:{source.document_sha256[:12]}:book-metadata",
            uri=pdf.as_uri(),
            sha256=source.document_sha256,
            media_type="application/pdf",
            metadata={
                "document_path": str(pdf),
                "page_numbers": list(selected_pages),
            },
        )
        result = self._extractor.extract(
            ExtractionTask(
                source=book_source,
                capability="ebook.book_metadata",
                prompt=EBOOK_METADATA_PROMPT_V1,
                schema=EBOOK_METADATA_SCHEMA_V1,
                assets=assets,
                metadata={"page_numbers": list(selected_pages)},
            )
        )
        payload = result.normalized_data
        if not isinstance(payload, dict):
            raise EbookMetadataExtractionError(
                "metadata extractor returned a non-object JSON value"
            )

        metadata = book_metadata_from_dict(payload)
        write_book_metadata(metadata, destination)
        report_path = destination.with_name("metadata-extraction.json")
        report = {
            "schema_version": "1",
            "source_pdf": str(pdf),
            "selected_pages": list(selected_pages),
            "cover_page_number": _optional_positive_int(payload, "cover_page_number"),
            "title_page_number": _optional_positive_int(payload, "title_page_number"),
            "copyright_page_number": _optional_positive_int(
                payload, "copyright_page_number"
            ),
            "warnings": _string_tuple(payload.get("warnings"), "warnings"),
            "provider_attempts": [
                {
                    "mechanism": attempt.mechanism,
                    "provider": attempt.provider,
                    "status": attempt.status,
                    "reason": attempt.reason,
                    "metadata": attempt.metadata,
                }
                for attempt in result.attempts
            ],
            "raw_suggestion": payload,
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return EbookMetadataExtractionRun(
            metadata=metadata,
            metadata_path=destination,
            report_path=report_path,
            selected_pages=selected_pages,
            cover_page_number=report["cover_page_number"],
            title_page_number=report["title_page_number"],
            copyright_page_number=report["copyright_page_number"],
            warnings=tuple(report["warnings"]),
        )


def _optional_positive_int(payload: dict[str, Any], key: str) -> int | None:
    """Return one optional positive integer from provider JSON."""
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise EbookMetadataExtractionError(f"{key} must be a positive integer or null")
    return value


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    """Normalize one JSON string array used for diagnostics."""
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise EbookMetadataExtractionError(f"{field} must be an array of strings")
    return tuple(item.strip() for item in value if item.strip())
