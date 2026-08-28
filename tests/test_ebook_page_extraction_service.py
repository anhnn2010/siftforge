"""Tests for the one-page ebook application service."""

from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    EncodedStreamObject,
    NameObject,
    NumberObject,
)

from siftforge.ebook.pipeline import EbookPDFPageExtractionService
from siftforge.extraction.models import (
    Attempt,
    ExtractionResult,
    ExtractionTask,
)

_JPEG_BYTES: bytes = (
    b"\xff\xd8\xff\xe0"
    b"fixture-jpeg-bytes-that-are-not-decoded-by-the-test"
    b"\xff\xd9"
)


class FakeStructuredExtractor:
    """Return deterministic ebook-shaped JSON without a network request."""

    def extract(self, task: ExtractionTask) -> ExtractionResult:
        """Return one structured text page for application-service testing."""
        normalized = {
            "page_kind": "text",
            "language": "vi",
            "printed_page_number": "1",
            "blocks": [
                {
                    "type": "paragraph",
                    "text": "Nội dung thử nghiệm.",
                    "level": None,
                }
            ],
            "warnings": [],
        }
        return ExtractionResult(
            task=task,
            raw_data=json.dumps(normalized, ensure_ascii=False),
            normalized_data=normalized,
            attempts=(
                Attempt(
                    mechanism="ai",
                    provider="fake",
                    status="success",
                    metadata={"model": "fixture"},
                ),
            ),
        )


def _make_pdf(path: Path) -> None:
    """Create one image-only page suitable for byte-preserving materialization."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)

    image = EncodedStreamObject()
    image._data = _JPEG_BYTES
    image[NameObject("/Type")] = NameObject("/XObject")
    image[NameObject("/Subtype")] = NameObject("/Image")
    image[NameObject("/Width")] = NumberObject(1)
    image[NameObject("/Height")] = NumberObject(1)
    image[NameObject("/ColorSpace")] = NameObject("/DeviceRGB")
    image[NameObject("/BitsPerComponent")] = NumberObject(8)
    image[NameObject("/Filter")] = NameObject("/DCTDecode")
    image_reference = writer._add_object(image)

    xobjects = DictionaryObject()
    xobjects[NameObject("/Im0")] = image_reference
    resources = DictionaryObject()
    resources[NameObject("/XObject")] = xobjects
    page[NameObject("/Resources")] = resources

    contents = DecodedStreamObject()
    contents.set_data(b"q 100 0 0 100 0 0 cm /Im0 Do Q")
    page[NameObject("/Contents")] = writer._add_object(contents)

    with path.open("wb") as handle:
        writer.write(handle)


def test_service_writes_complete_one_page_run(tmp_path: Path) -> None:
    """Service should materialize, extract, and persist inspectable artifacts."""
    pdf_path = tmp_path / "book.pdf"
    _make_pdf(pdf_path)

    run_dir = tmp_path / "run"
    service = EbookPDFPageExtractionService(FakeStructuredExtractor())
    run = service.extract_page(pdf_path, page_number=1, run_dir=run_dir)

    assert run.asset.path.read_bytes() == _JPEG_BYTES
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "raw" / "provider-response.json").is_file()
    assert (run_dir / "normalized" / "page.json").is_file()

    normalized = json.loads(
        (run_dir / "normalized" / "page.json").read_text(encoding="utf-8")
    )
    assert normalized["blocks"][0]["text"] == "Nội dung thử nghiệm."

    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["prompt"]["version"] == "1"
    assert manifest["schema"]["version"] == "1"
    assert manifest["attempts"][0]["provider"] == "fake"
