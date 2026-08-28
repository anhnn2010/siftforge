"""PDF source discovery and low-level embedded-image inspection."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf._page import PageObject
from pypdf.generic import DictionaryObject, StreamObject

from siftforge.extraction.models import SourceRef


@dataclass(frozen=True, slots=True)
class PDFAnalysis:
    """Summary of source characteristics discovered in a PDF document."""

    path: Path
    sha256: str
    page_count: int
    text_pages: int
    image_only_pages: int
    mixed_pages: int
    blank_pages: int

    @property
    def is_image_only(self) -> bool:
        """Return whether every page contains images and no native text."""
        return self.page_count > 0 and self.image_only_pages == self.page_count


@dataclass(frozen=True, slots=True)
class PDFImageStream:
    """Reference to an embedded image stream used by a PDF page."""

    resource_name: str
    stream: StreamObject
    filters: tuple[str, ...]


class PDFSource:
    """Expose each PDF page as an independent extraction source item.

    Args:
        path: Filesystem path to the PDF document.

    Raises:
        FileNotFoundError: If the supplied PDF path does not exist.
    """

    def __init__(self, path: str | Path) -> None:
        """Initialize source discovery for one PDF document."""
        self.path: Path = Path(path).expanduser().resolve()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self._document_sha256: str | None = None

    @property
    def document_sha256(self) -> str:
        """Return a lazily computed SHA-256 hash of the whole PDF."""
        if self._document_sha256 is None:
            self._document_sha256 = sha256_file(self.path)
        return self._document_sha256

    def analyze(self) -> PDFAnalysis:
        """Inspect and classify native text/image composition for all pages."""
        text_pages: int = 0
        image_only_pages: int = 0
        mixed_pages: int = 0
        blank_pages: int = 0
        reader: PdfReader = PdfReader(self.path)

        for page in reader.pages:
            has_text: bool = bool((page.extract_text() or "").strip())
            has_images: bool = any(iter_pdf_image_streams(page))

            if has_text and has_images:
                mixed_pages += 1
            elif has_text:
                text_pages += 1
            elif has_images:
                image_only_pages += 1
            else:
                blank_pages += 1

        return PDFAnalysis(
            path=self.path,
            sha256=self.document_sha256,
            page_count=len(reader.pages),
            text_pages=text_pages,
            image_only_pages=image_only_pages,
            mixed_pages=mixed_pages,
            blank_pages=blank_pages,
        )

    def iter_items(self) -> Iterator[SourceRef]:
        """Yield one stable `SourceRef` for every page in the PDF."""
        document_hash: str = self.document_sha256
        base_uri: str = self.path.as_uri()
        reader: PdfReader = PdfReader(self.path)

        for page_index, page in enumerate(reader.pages):
            page_number: int = page_index + 1
            image_streams: tuple[PDFImageStream, ...] = tuple(
                iter_pdf_image_streams(page)
            )
            text: str = (page.extract_text() or "").strip()

            yield SourceRef(
                source_id=f"pdf:{document_hash[:12]}:page:{page_number:04d}",
                uri=f"{base_uri}#page={page_number}",
                sha256=sha256_pdf_page(page, image_streams),
                media_type="application/x.siftforge.pdf-page",
                metadata={
                    "document_path": str(self.path),
                    "document_sha256": document_hash,
                    "page_index": page_index,
                    "page_number": page_number,
                    "width_pt": float(page.mediabox.width),
                    "height_pt": float(page.mediabox.height),
                    "native_text_length": len(text),
                    "image_count": len(image_streams),
                    "image_filters": [
                        list(image_stream.filters) for image_stream in image_streams
                    ],
                    "image_only": not text and bool(image_streams),
                },
            )


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 hash of a file without loading it fully into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_pdf_page(
    page: PageObject,
    image_streams: tuple[PDFImageStream, ...],
) -> str:
    """Hash page-local PDF content without rendering or OCR."""
    digest = hashlib.sha256()
    dimensions = (
        f"{float(page.mediabox.width):.6f}x{float(page.mediabox.height):.6f}"
    )
    digest.update(dimensions.encode())

    contents = page.get_contents()
    if contents is not None:
        digest.update(contents.get_data())

    for image_stream in image_streams:
        digest.update(encoded_stream_bytes(image_stream.stream))

    return digest.hexdigest()


def iter_pdf_image_streams(page: PageObject) -> Iterator[PDFImageStream]:
    """Yield image streams reachable from a page, including nested Form XObjects."""
    resources = page.get("/Resources")
    if resources is None:
        return

    resolved_resources = resources.get_object()
    if not isinstance(resolved_resources, DictionaryObject):
        return

    yield from _iter_images_from_resources(
        resolved_resources,
        resource_prefix="",
        visited=set(),
    )


def encoded_stream_bytes(stream: StreamObject) -> bytes:
    """Return image bytes exactly as encoded in the PDF stream.

    The private pypdf `_data` access is intentionally isolated here because
    high-level image access may decode/re-encode JPEG data. A contract test protects
    this compatibility boundary.

    Raises:
        RuntimeError: If pypdf no longer exposes encoded bytes as expected.
    """
    raw_data: Any = getattr(stream, "_data", None)
    if not isinstance(raw_data, bytes):
        raise RuntimeError("pypdf stream does not expose encoded bytes as expected")
    return raw_data


def _iter_images_from_resources(
    resources: DictionaryObject,
    resource_prefix: str,
    visited: set[tuple[int, int] | int],
) -> Iterator[PDFImageStream]:
    """Recursively traverse PDF XObject resources and yield image streams."""
    xobjects = resources.get("/XObject")
    if xobjects is None:
        return

    resolved_xobjects = xobjects.get_object()
    if not isinstance(resolved_xobjects, DictionaryObject):
        return

    for name, reference in resolved_xobjects.items():
        obj = reference.get_object()
        identity = _object_identity(reference, obj)
        if identity in visited:
            continue
        visited.add(identity)

        resource_name = f"{resource_prefix}{name}"
        subtype = obj.get("/Subtype")

        if subtype == "/Image" and isinstance(obj, StreamObject):
            yield PDFImageStream(
                resource_name=resource_name,
                stream=obj,
                filters=_normalize_filters(obj.get("/Filter")),
            )
            continue

        if subtype == "/Form":
            nested_resources = obj.get("/Resources")
            if nested_resources is None:
                continue
            resolved_nested = nested_resources.get_object()
            if isinstance(resolved_nested, DictionaryObject):
                yield from _iter_images_from_resources(
                    resolved_nested,
                    resource_prefix=f"{resource_name}/",
                    visited=visited,
                )


def _normalize_filters(value: Any) -> tuple[str, ...]:
    """Normalize a PDF `/Filter` value into a predictable tuple."""
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return (str(value),)


def _object_identity(reference: Any, obj: Any) -> tuple[int, int] | int:
    """Return a traversal identity for direct or indirect PDF objects."""
    idnum = getattr(reference, "idnum", None)
    generation = getattr(reference, "generation", None)
    if isinstance(idnum, int) and isinstance(generation, int):
        return (idnum, generation)
    return id(obj)
