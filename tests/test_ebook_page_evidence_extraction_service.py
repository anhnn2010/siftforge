"""Tests for the active v5 one-page ebook evidence service."""

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

from siftforge.ebook.evidence import BlockRoleHint, MarkerKind
from siftforge.ebook.pipeline import EbookPDFPageEvidenceExtractionService
from siftforge.extraction.models import Attempt, ExtractionResult, ExtractionTask

_JPEG_BYTES: bytes = (
    b"\xff\xd8\xff\xe0"
    b"fixture-jpeg-bytes-that-are-not-decoded-by-the-test"
    b"\xff\xd9"
)


def _typography() -> dict[str, object]:
    """Return one complete v5 source-typography fixture."""
    return {
        "posture": "roman",
        "weight": "normal",
        "vertical_position": "baseline",
        "caps_style": "normal",
        "decorations": [],
    }


class FakeV5StructuredExtractor:
    """Return deterministic v5 page evidence without a network request."""

    def extract(self, task: ExtractionTask) -> ExtractionResult:
        """Return one list-oriented v5 structured response."""
        normalized = {
            "page_kind_hint": "text",
            "dominant_language": "vi",
            "printed_page_number": "152",
            "blocks": [
                {
                    "role_hint": "list_item",
                    "content": [
                        {
                            "text": "Hoặc vì ngại làm tổn thương...",
                            "language": "vi",
                            "source_typography": _typography(),
                            "semantic_line_break_after": False,
                        }
                    ],
                    "dominant_language": "vi",
                    "heading_level_hint": None,
                    "heading_role_hint": "unknown",
                    "marker": {
                        "kind": "bullet",
                        "raw_text": "♥",
                        "ordinal": None,
                    },
                    "region": None,
                    "alignment": "left",
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


def test_v5_service_writes_typed_page_evidence(tmp_path: Path) -> None:
    """Service should use v5 and persist deterministic normalized evidence."""
    pdf_path = tmp_path / "book.pdf"
    _make_pdf(pdf_path)

    run_dir = tmp_path / "run"
    service = EbookPDFPageEvidenceExtractionService(FakeV5StructuredExtractor())
    run = service.extract_page(pdf_path, page_number=1, run_dir=run_dir)

    block = run.page_evidence.blocks[0]
    assert block.role_hint is BlockRoleHint.LIST_ITEM
    assert block.marker is not None
    assert block.marker.kind is MarkerKind.BULLET
    assert block.marker.raw_text == "♥"
    assert block.text == "Hoặc vì ngại làm tổn thương..."
    assert block.block_id == f"{run.source.source_id}:block:0001"
    assert block.spans[0].span_id == f"{block.block_id}:span:0001"

    normalized = json.loads(
        (run_dir / "normalized" / "page.json").read_text(encoding="utf-8")
    )
    assert normalized["page_id"] == run.source.source_id
    assert normalized["blocks"][0]["role_hint"] == "list_item"
    assert normalized["blocks"][0]["marker"]["raw_text"] == "♥"

    manifest = json.loads(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["prompt"]["version"] == "5"
    assert manifest["schema"]["version"] == "5"
    assert manifest["normalization"]["model"] == "PageExtraction"
