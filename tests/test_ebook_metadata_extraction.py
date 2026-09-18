"""Tests for AI-assisted front-matter book metadata extraction."""

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

from siftforge.ebook.metadata_extraction import EbookPDFMetadataExtractionService
from siftforge.extraction.models import Attempt, ExtractionResult, ExtractionTask

_JPEG_BYTES = b"\xff\xd8\xff\xe0metadata-fixture\xff\xd9"


class FakeMetadataExtractor:
    """Return deterministic bibliographic metadata without a network request."""

    def extract(self, task: ExtractionTask) -> ExtractionResult:
        """Return metadata plus front-matter page-role hints."""
        assert task.capability == "ebook.book_metadata"
        assert len(task.assets) == 2
        payload = {
            "title": "18 Năm Kim Cương",
            "subtitle": None,
            "language": "vi",
            "authors": ["Tác giả A"],
            "publisher": "Nhà xuất bản A",
            "publication_date": "2020",
            "isbn": "978-1-2345-6789-0",
            "description": None,
            "subjects": [],
            "rights": "Copyright 2020",
            "series": None,
            "series_index": None,
            "contributors": ["Dịch giả: B"],
            "cover_page_number": 1,
            "title_page_number": 2,
            "copyright_page_number": 2,
            "warnings": ["Review publication date."],
        }
        return ExtractionResult(
            task=task,
            raw_data=json.dumps(payload, ensure_ascii=False),
            normalized_data=payload,
            attempts=(
                Attempt(
                    mechanism="ai",
                    provider="fake",
                    status="success",
                    metadata={"model": "fixture"},
                ),
            ),
        )


def _make_pdf(path: Path, page_count: int = 2) -> None:
    """Create image-only PDF pages suitable for direct materialization."""
    writer = PdfWriter()
    for index in range(page_count):
        page = writer.add_blank_page(width=100, height=100)
        image = EncodedStreamObject()
        image._data = _JPEG_BYTES + bytes([index])
        image[NameObject("/Type")] = NameObject("/XObject")
        image[NameObject("/Subtype")] = NameObject("/Image")
        image[NameObject("/Width")] = NumberObject(1)
        image[NameObject("/Height")] = NumberObject(1)
        image[NameObject("/ColorSpace")] = NameObject("/DeviceRGB")
        image[NameObject("/BitsPerComponent")] = NumberObject(8)
        image[NameObject("/Filter")] = NameObject("/DCTDecode")
        image_reference = writer._add_object(image)
        xobjects = DictionaryObject({NameObject("/Im0"): image_reference})
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/XObject"): xobjects}
        )
        contents = DecodedStreamObject()
        contents.set_data(b"q 100 0 0 100 0 0 cm /Im0 Do Q")
        page[NameObject("/Contents")] = writer._add_object(contents)
    with path.open("wb") as handle:
        writer.write(handle)


def test_metadata_extraction_writes_reviewable_metadata_and_report(tmp_path: Path) -> None:
    """Suggested metadata should be persisted separately from extraction diagnostics."""
    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    output = tmp_path / "runs" / "book" / "metadata.json"

    run = EbookPDFMetadataExtractionService(FakeMetadataExtractor()).extract(
        pdf_path=pdf,
        output_path=output,
        start_page=1,
        end_page=2,
    )

    assert run.metadata.title == "18 Năm Kim Cương"
    assert run.metadata.authors == ("Tác giả A",)
    assert run.cover_page_number == 1
    assert run.selected_pages == (1, 2)
    assert run.warnings == ("Review publication date.",)

    metadata = json.loads(output.read_text(encoding="utf-8"))
    assert metadata["title"] == "18 Năm Kim Cương"
    assert metadata["cover"] is None
    assert "cover_page_number" not in metadata

    report = json.loads(run.report_path.read_text(encoding="utf-8"))
    assert report["cover_page_number"] == 1
    assert report["title_page_number"] == 2
    assert report["provider_attempts"][0]["provider"] == "fake"
