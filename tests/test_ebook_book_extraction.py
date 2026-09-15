"""Tests for resumable multi-page ebook page-evidence extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    EncodedStreamObject,
    NameObject,
    NumberObject,
)

from siftforge.ebook.pipeline import (
    EbookBookExtractionError,
    EbookBookPageStatus,
    EbookPDFBookEvidenceExtractionService,
)
from siftforge.extraction.models import Attempt, ExtractionResult, ExtractionTask


class FakeBookExtractor:
    """Return deterministic page evidence and optionally fail selected pages."""

    def __init__(
        self,
        *,
        model: str = "fixture-model",
        fail_pages: set[int] | None = None,
    ) -> None:
        """Configure deterministic model provenance and intentional failures."""
        self.model = model
        self.fail_pages = fail_pages or set()
        self.calls: list[int] = []

    def extract(self, task: ExtractionTask) -> ExtractionResult:
        """Return one ordinary paragraph for the requested physical page."""
        page_number = task.source.metadata["page_number"]
        assert isinstance(page_number, int)
        self.calls.append(page_number)
        if page_number in self.fail_pages:
            raise RuntimeError(f"intentional page {page_number} failure")

        payload = {
            "page_kind_hint": "text",
            "dominant_language": "vi",
            "printed_page_number": str(page_number),
            "blocks": [
                {
                    "role_hint": "paragraph",
                    "content": [
                        {
                            "text": f"Trang {page_number}.",
                            "language": "vi",
                            "source_typography": {
                                "posture": "roman",
                                "weight": "normal",
                                "vertical_position": "baseline",
                                "caps_style": "normal",
                                "decorations": [],
                            },
                            "semantic_line_break_after": False,
                        }
                    ],
                    "dominant_language": "vi",
                    "heading_level_hint": None,
                    "heading_role_hint": "unknown",
                    "marker": None,
                    "region": None,
                    "alignment": "left",
                }
            ],
            "warnings": [],
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
                    metadata={
                        "model": self.model,
                        "usage": {
                            "prompt_token_count": 10,
                            "candidates_token_count": page_number,
                            "total_token_count": 10 + page_number,
                        },
                    },
                ),
            ),
        )


def _make_image_pdf(path: Path, page_count: int) -> None:
    """Create a multi-page image-only PDF accepted by direct materialization."""
    writer = PdfWriter()
    for page_number in range(1, page_count + 1):
        page = writer.add_blank_page(width=100, height=100)
        image = EncodedStreamObject()
        image._data = (
            b"\xff\xd8\xff\xe0fixture-jpeg-page-"
            + str(page_number).encode()
            + b"\xff\xd9"
        )
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


def test_extract_book_reuses_matching_page_runs(tmp_path: Path) -> None:
    """A second identical run should avoid all provider calls and preserve usage."""
    pdf = tmp_path / "book.pdf"
    _make_image_pdf(pdf, 3)
    runs = tmp_path / "runs"
    first_extractor = FakeBookExtractor()
    first = EbookPDFBookEvidenceExtractionService(first_extractor).extract_book(
        pdf,
        runs,
        model="fixture-model",
    )

    assert first_extractor.calls == [1, 2, 3]
    assert first.extracted_count == 3
    assert first.reused_count == 0
    assert first.failed_count == 0
    assert first.total_usage["total_token_count"] == 36

    second_extractor = FakeBookExtractor()
    second = EbookPDFBookEvidenceExtractionService(second_extractor).extract_book(
        pdf,
        runs,
        model="fixture-model",
    )

    assert second_extractor.calls == []
    assert second.extracted_count == 0
    assert second.reused_count == 3
    assert second.total_usage["total_token_count"] == 36
    manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))
    assert manifest["summary"] == {
        "completed": 3,
        "extracted": 0,
        "failed": 0,
        "remaining": 0,
        "reused": 3,
        "selected": 3,
    }


def test_extract_book_page_range_and_force_rebuild(tmp_path: Path) -> None:
    """Inclusive page selection and force mode should be explicit and predictable."""
    pdf = tmp_path / "book.pdf"
    _make_image_pdf(pdf, 4)
    runs = tmp_path / "runs"
    first_extractor = FakeBookExtractor()
    service = EbookPDFBookEvidenceExtractionService(first_extractor)
    first = service.extract_book(
        pdf,
        runs,
        model="fixture-model",
        start_page=2,
        end_page=3,
    )

    assert first_extractor.calls == [2, 3]
    assert [item.page_number for item in first.page_results] == [2, 3]
    assert not (runs / "page-0001").exists()
    assert not (runs / "page-0004").exists()

    second_extractor = FakeBookExtractor()
    second = EbookPDFBookEvidenceExtractionService(second_extractor).extract_book(
        pdf,
        runs,
        model="fixture-model",
        start_page=2,
        end_page=3,
        force=True,
    )

    assert second_extractor.calls == [2, 3]
    assert second.extracted_count == 2
    assert second.reused_count == 0


def test_extract_book_model_change_invalidates_reuse(tmp_path: Path) -> None:
    """Changing the requested model should rebuild otherwise valid page runs."""
    pdf = tmp_path / "book.pdf"
    _make_image_pdf(pdf, 1)
    runs = tmp_path / "runs"
    EbookPDFBookEvidenceExtractionService(FakeBookExtractor()).extract_book(
        pdf,
        runs,
        model="fixture-model",
    )

    changed = FakeBookExtractor(model="different-model")
    run = EbookPDFBookEvidenceExtractionService(changed).extract_book(
        pdf,
        runs,
        model="different-model",
    )

    assert changed.calls == [1]
    assert run.extracted_count == 1
    assert run.reused_count == 0


def test_extract_book_stops_then_resumes_after_failure(tmp_path: Path) -> None:
    """Completed pages should survive a failure and be reused on the next run."""
    pdf = tmp_path / "book.pdf"
    _make_image_pdf(pdf, 3)
    runs = tmp_path / "runs"
    failing = FakeBookExtractor(fail_pages={2})

    with pytest.raises(EbookBookExtractionError, match="page 2 extraction failed"):
        EbookPDFBookEvidenceExtractionService(failing).extract_book(
            pdf,
            runs,
            model="fixture-model",
        )

    checkpoint = json.loads(
        (runs / "book-extraction.json").read_text(encoding="utf-8")
    )
    assert checkpoint["summary"]["completed"] == 2
    assert checkpoint["summary"]["failed"] == 1
    assert checkpoint["summary"]["remaining"] == 1
    assert (runs / "page-0001" / "manifest.json").is_file()

    healthy = FakeBookExtractor()
    resumed = EbookPDFBookEvidenceExtractionService(healthy).extract_book(
        pdf,
        runs,
        model="fixture-model",
    )

    assert healthy.calls == [2, 3]
    assert [item.status for item in resumed.page_results] == [
        EbookBookPageStatus.REUSED,
        EbookBookPageStatus.EXTRACTED,
        EbookBookPageStatus.EXTRACTED,
    ]
    assert resumed.failed_count == 0


def test_extract_book_can_continue_after_failed_page(tmp_path: Path) -> None:
    """Continue mode should retain a failed checkpoint while processing later pages."""
    pdf = tmp_path / "book.pdf"
    _make_image_pdf(pdf, 3)
    runs = tmp_path / "runs"
    extractor = FakeBookExtractor(fail_pages={2})
    run = EbookPDFBookEvidenceExtractionService(extractor).extract_book(
        pdf,
        runs,
        model="fixture-model",
        continue_on_error=True,
    )

    assert extractor.calls == [1, 2, 3]
    assert run.failed_count == 1
    assert run.extracted_count == 2
    assert run.page_results[1].error_type == "RuntimeError"
    assert (runs / "page-0003" / "manifest.json").is_file()


def test_failed_refresh_preserves_previous_canonical_run(tmp_path: Path) -> None:
    """A failed incompatible refresh must not destroy the last complete page run."""
    pdf = tmp_path / "book.pdf"
    _make_image_pdf(pdf, 1)
    runs = tmp_path / "runs"
    EbookPDFBookEvidenceExtractionService(FakeBookExtractor()).extract_book(
        pdf,
        runs,
        model="fixture-model",
    )
    original = (runs / "page-0001" / "manifest.json").read_bytes()

    failing = FakeBookExtractor(
        model="different-model",
        fail_pages={1},
    )
    with pytest.raises(EbookBookExtractionError):
        EbookPDFBookEvidenceExtractionService(failing).extract_book(
            pdf,
            runs,
            model="different-model",
        )

    assert (runs / "page-0001" / "manifest.json").read_bytes() == original
    assert not (runs / ".page-0001.extracting").exists()
    assert not (runs / ".page-0001.backup").exists()
