from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf._page import PageObject

from siftforge.extraction.models import SourceRef


@dataclass(frozen=True, slots=True)
class PDFAnalysis:
    path: Path
    sha256: str
    page_count: int
    text_pages: int
    image_only_pages: int
    mixed_pages: int
    blank_pages: int

    @property
    def is_image_only(self) -> bool:
        return self.page_count > 0 and self.image_only_pages == self.page_count


class PDFSource:
    """Expose each PDF page as an independent extraction source item.

    The source is deliberately document-domain agnostic. It does not know whether
    a page belongs to a book, invoice, report, or any other application domain.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self._document_sha256: str | None = None

    @property
    def document_sha256(self) -> str:
        if self._document_sha256 is None:
            self._document_sha256 = _sha256_file(self.path)
        return self._document_sha256

    def analyze(self) -> PDFAnalysis:
        text_pages = 0
        image_only_pages = 0
        mixed_pages = 0
        blank_pages = 0
        reader = PdfReader(self.path)

        for page in reader.pages:
            has_text = bool((page.extract_text() or "").strip())
            has_images = bool(page.images)

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

    def iter_items(self):
        document_hash = self.document_sha256
        base_uri = self.path.as_uri()
        reader = PdfReader(self.path)

        for page_index, page in enumerate(reader.pages):
            page_number = page_index + 1
            images = list(page.images)
            text = (page.extract_text() or "").strip()

            yield SourceRef(
                source_id=f"pdf:{document_hash[:12]}:page:{page_number:04d}",
                uri=f"{base_uri}#page={page_number}",
                sha256=_sha256_page(page, images),
                media_type="application/x.siftforge.pdf-page",
                metadata={
                    "document_path": str(self.path),
                    "document_sha256": document_hash,
                    "page_index": page_index,
                    "page_number": page_number,
                    "width_pt": float(page.mediabox.width),
                    "height_pt": float(page.mediabox.height),
                    "native_text_length": len(text),
                    "image_count": len(images),
                    "image_only": not text and bool(images),
                },
            )


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_page(page: PageObject, images) -> str:
    """Hash page-local PDF content without rendering or OCR."""

    digest = hashlib.sha256()
    digest.update(
        f"{float(page.mediabox.width):.6f}x{float(page.mediabox.height):.6f}".encode()
    )

    contents = page.get_contents()
    if contents is not None:
        digest.update(contents.get_data())

    for image in images:
        digest.update(image.data)

    return digest.hexdigest()
