"""Materialize PDF pages while preserving original embedded image bytes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from siftforge.extraction.models import MaterializedAsset, SourceRef
from siftforge.extraction.sources.pdf import (
    PDFImageStream,
    encoded_stream_bytes,
    iter_pdf_image_streams,
    sha256_file,
)


class PDFPageMaterializationError(RuntimeError):
    """Base error raised when a PDF page cannot be materialized safely."""


class UnsupportedPDFPageError(PDFPageMaterializationError):
    """Raised when a page needs a materialization strategy not implemented yet."""


@dataclass(frozen=True, slots=True)
class _EncodedImageFormat:
    """Concrete file representation for an encoded PDF image stream."""

    extension: str
    media_type: str


_SUPPORTED_DIRECT_IMAGE_FORMATS: dict[tuple[str, ...], _EncodedImageFormat] = {
    ("/DCTDecode",): _EncodedImageFormat(".jpg", "image/jpeg"),
    ("/JPXDecode",): _EncodedImageFormat(".jp2", "image/jp2"),
}


class PDFPageMaterializer:
    """Extract a page's original embedded image into a local file.

    The first implementation deliberately handles only the safest cheap path:
    image-only pages with exactly one directly reusable encoded image. Pages that
    need rendering or composition fail explicitly so another strategy can be added
    later without changing downstream provider contracts.
    """

    def __init__(self, path: str | Path) -> None:
        """Initialize a materializer for one PDF document."""
        self.path: Path = Path(path).expanduser().resolve()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)

        self._document_sha256: str | None = None
        self._reader: PdfReader | None = None

    @property
    def document_sha256(self) -> str:
        """Return a lazily computed hash of the source PDF."""
        if self._document_sha256 is None:
            self._document_sha256 = sha256_file(self.path)
        return self._document_sha256

    def materialize(
        self,
        source: SourceRef,
        destination_dir: str | Path,
    ) -> MaterializedAsset:
        """Materialize one PDF page as its original embedded image.

        Raises:
            PDFPageMaterializationError: If source provenance is invalid.
            UnsupportedPDFPageError: If direct byte-preserving extraction is unsafe.
        """
        page_index, page_number = self._validate_source(source)
        page = self._get_reader().pages[page_index]
        native_text: str = (page.extract_text() or "").strip()
        image_streams: tuple[PDFImageStream, ...] = tuple(
            iter_pdf_image_streams(page)
        )

        if native_text:
            raise UnsupportedPDFPageError(
                f"page {page_number} contains native text; "
                "direct image-only materialization is not applicable"
            )

        if len(image_streams) != 1:
            raise UnsupportedPDFPageError(
                f"page {page_number} contains {len(image_streams)} images; "
                "exactly one embedded image is required"
            )

        image_stream = image_streams[0]
        image_format = _SUPPORTED_DIRECT_IMAGE_FORMATS.get(image_stream.filters)
        if image_format is None:
            raise UnsupportedPDFPageError(
                f"page {page_number} uses unsupported image filters "
                f"{image_stream.filters!r}"
            )

        data: bytes = encoded_stream_bytes(image_stream.stream)
        sha256: str = hashlib.sha256(data).hexdigest()

        output_dir = Path(destination_dir).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"page-{page_number:04d}{image_format.extension}"

        reused_existing: bool = _write_if_changed(
            output_path,
            data,
            expected_sha256=sha256,
        )

        return MaterializedAsset(
            source=source,
            path=output_path,
            media_type=image_format.media_type,
            sha256=sha256,
            byte_size=len(data),
            metadata={
                "document_path": str(self.path),
                "document_sha256": self.document_sha256,
                "page_index": page_index,
                "page_number": page_number,
                "pdf_resource_name": image_stream.resource_name,
                "pdf_filters": list(image_stream.filters),
                "preserved_encoded_source": True,
                "reused_existing_file": reused_existing,
            },
        )

    def _validate_source(self, source: SourceRef) -> tuple[int, int]:
        """Validate source provenance before reading the requested page."""
        if source.media_type != "application/x.siftforge.pdf-page":
            raise PDFPageMaterializationError(
                f"unsupported source media type: {source.media_type!r}"
            )

        source_document_hash = source.metadata.get("document_sha256")
        if source_document_hash != self.document_sha256:
            raise PDFPageMaterializationError(
                "source reference belongs to a different PDF document"
            )

        page_index = source.metadata.get("page_index")
        page_number = source.metadata.get("page_number")
        if not isinstance(page_index, int) or not isinstance(page_number, int):
            raise PDFPageMaterializationError(
                "source reference is missing valid PDF page metadata"
            )

        if page_index < 0 or page_number != page_index + 1:
            raise PDFPageMaterializationError(
                "source reference contains inconsistent PDF page metadata"
            )

        if page_index >= len(self._get_reader().pages):
            raise PDFPageMaterializationError(
                f"page index {page_index} is outside the PDF"
            )

        return page_index, page_number

    def _get_reader(self) -> PdfReader:
        """Return one lazily created reader reused across materializations."""
        if self._reader is None:
            self._reader = PdfReader(self.path)
        return self._reader


def _write_if_changed(path: Path, data: bytes, expected_sha256: str) -> bool:
    """Write bytes unless an existing destination already has the same hash.

    Returns:
        `True` if an existing matching file was reused, otherwise `False`.
    """
    if path.is_file() and sha256_file(path) == expected_sha256:
        return True

    path.write_bytes(data)
    return False
