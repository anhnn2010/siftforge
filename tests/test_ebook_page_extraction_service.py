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
from siftforge.extraction.models import Attempt, ExtractionResult, ExtractionTask

_JPEG_BYTES: bytes = (
    b"\xff\xd8\xff\xe0"
    b"fixture-jpeg-bytes-that-are-not-decoded-by-the-test"
    b"\xff\xd9"
)


def _typography(
    posture: str = "roman",
    vertical_position: str = "baseline",
) -> dict[str, object]:
    """Return a complete typography fixture."""
    return {
        "posture": posture,
        "weight": "normal",
        "vertical_position": vertical_position,
        "caps_style": "normal",
        "decorations": [],
    }


class FakeStructuredExtractor:
    """Return deterministic ebook-shaped JSON without a network request."""

    def extract(self, task: ExtractionTask) -> ExtractionResult:
        """Return one page-18-shaped structured response."""
        normalized = {
            "page_kind": "text",
            "language": "vi",
            "printed_page_number": "18",
            "blocks": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "text": "Nguyên văn bản tiếng Anh:",
                            "typography": _typography(posture="roman"),
                        }
                    ],
                    "language": "vi",
                    "level": None,
                    "alignment": "left",
                },
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "text": "December 13",
                            "typography": _typography(posture="italic"),
                        },
                        {
                            "text": "th",
                            "typography": _typography(
                                posture="italic",
                                vertical_position="superscript",
                            ),
                        },
                    ],
                    "language": "en",
                    "level": None,
                    "alignment": "left",
                },
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


def test_service_writes_explicit_typed_typography(tmp_path: Path) -> None:
    """Service should persist typed explicit typography after normalization."""
    pdf_path = tmp_path / "book.pdf"
    _make_pdf(pdf_path)

    run_dir = tmp_path / "run"
    service = EbookPDFPageExtractionService(FakeStructuredExtractor())
    run = service.extract_page(pdf_path, page_number=1, run_dir=run_dir)

    assert run.page_content.blocks[0].content[0].typography.posture.value == "roman"
    assert run.page_content.blocks[1].content[0].typography.posture.value == "italic"

    normalized = json.loads(
        (run_dir / "normalized" / "page.json").read_text(encoding="utf-8")
    )
    roman = normalized["blocks"][0]["content"][0]["typography"]
    superscript = normalized["blocks"][1]["content"][1]["typography"]

    assert roman["posture"] == "roman"
    assert superscript["posture"] == "italic"
    assert superscript["vertical_position"] == "superscript"

    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["prompt"]["version"] == "4"
    assert manifest["schema"]["version"] == "4"
