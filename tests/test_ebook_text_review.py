"""Tests for local-OCR text fidelity review and provenance projection."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from siftforge.ebook.evidence import (
    BlockRoleHint,
    PageBlockEvidence,
    PageExtraction,
    SourceTypography,
    TextSpanEvidence,
)
from siftforge.ebook.models import (
    CapsStyle,
    FontPosture,
    FontWeight,
    PageKind,
    VerticalPosition,
)
from siftforge.ebook.pipeline.book_assembly import EbookPageRunArtifact
from siftforge.ebook.review import (
    OcrPage,
    OcrWord,
    PageReviewResult,
    ReviewFilterConfig,
    ReviewFinding,
    ReviewKind,
    ReviewSeverity,
    ReviewSource,
)
from siftforge.ebook.review.comparison import compare_with_ocr
from siftforge.ebook.review.filtering import filter_ocr_findings
from siftforge.ebook.review.heuristics import find_suspicious_boundaries
from siftforge.ebook.review.projection import project_page_text
from siftforge.ebook.review.report import write_review_artifacts
from siftforge.ebook.review.service import EbookTextReviewService
from siftforge.extraction.models import SourceRef


def _typography() -> SourceTypography:
    """Return ordinary source typography for review fixtures."""
    return SourceTypography(
        posture=FontPosture.ROMAN,
        weight=FontWeight.NORMAL,
        vertical_position=VerticalPosition.BASELINE,
        caps_style=CapsStyle.NORMAL,
    )


def _page(text: str, *, second_span: str | None = None) -> PageExtraction:
    """Build one small page with deterministic provenance."""
    page_id = "pdf:test:page:0013"
    block_id = f"{page_id}:block:0001"
    spans = [
        TextSpanEvidence(
            span_id=f"{block_id}:span:0001",
            text=text,
            language="vi",
            source_typography=_typography(),
        )
    ]
    if second_span is not None:
        spans.append(
            TextSpanEvidence(
                span_id=f"{block_id}:span:0002",
                text=second_span,
                language="vi",
                source_typography=_typography(),
            )
        )
    return PageExtraction(
        page_id=page_id,
        source=SourceRef(
            source_id=page_id,
            uri="book.pdf#page=13",
            media_type="image/jpeg",
        ),
        page_kind_hint=PageKind.TEXT,
        dominant_language="vi",
        printed_page_number="13",
        blocks=(
            PageBlockEvidence(
                block_id=block_id,
                sequence_index=0,
                role_hint=BlockRoleHint.PARAGRAPH,
                spans=tuple(spans),
                dominant_language="vi",
            ),
        ),
    )


def test_projection_keeps_real_span_boundary_without_inventing_space() -> None:
    """Comparison projection must expose missing source whitespace faithfully."""
    page = _page("sáng ngày", second_span="14 tháng")

    projection = project_page_text(page)

    assert projection.text == "sáng ngày14 tháng"
    anchor = projection.anchors[9]
    assert anchor is not None
    assert anchor.span_id.endswith("span:0002")


def test_ocr_comparison_localizes_missing_whitespace() -> None:
    """OCR disagreement should isolate a missing space rather than a paragraph."""
    projection = project_page_text(_page("sáng ngày14 tháng"))
    ocr = OcrPage(
        text="sáng ngày 14 tháng",
        words=(),
        engine="fake",
        language="vie",
    )

    similarity, findings = compare_with_ocr(
        page_number=13,
        projection=projection,
        ocr=ocr,
    )

    assert similarity > 0.95
    whitespace = [item for item in findings if item.kind.value == "whitespace"]
    assert len(whitespace) == 1
    assert whitespace[0].gemini_text == ""
    assert whitespace[0].reference_text == " "


def test_heuristics_flag_letter_digit_boundary_when_ocr_can_agree() -> None:
    """Independent heuristics should catch a likely source typo such as ngày14."""
    projection = project_page_text(_page("3 giờ sáng ngày14 tháng 12"))

    findings = find_suspicious_boundaries(
        page_number=13,
        projection=projection,
    )

    assert len(findings) == 1
    assert findings[0].gemini_text == "ngày14"
    assert findings[0].suggested_text == "ngày 14"
    assert findings[0].source.value == "heuristic"


def test_heuristics_flag_period_uppercase_boundary() -> None:
    """A lower-case sentence ending glued to upper-case prose needs review."""
    projection = project_page_text(_page("ở tuổi đồng nhi.Tuy nhiên, khi"))

    findings = find_suspicious_boundaries(
        page_number=152,
        projection=projection,
    )

    assert len(findings) == 1
    assert findings[0].gemini_text == "nhi.Tuy"
    assert findings[0].suggested_text == "nhi. Tuy"


def test_html_report_highlights_review_context(tmp_path: Path) -> None:
    """Human report should visibly expose the smallest differing span."""
    projection = project_page_text(_page("sáng ngày14 tháng"))
    ocr = OcrPage(
        text="sáng ngày 14 tháng",
        words=(),
        engine="fake",
        language="vie",
    )
    similarity, findings = compare_with_ocr(
        page_number=13,
        projection=projection,
        ocr=ocr,
    )
    page_result = PageReviewResult(
        page_id="pdf:test:page:0013",
        page_number=13,
        gemini_text=projection.text,
        ocr_text=ocr.text,
        ocr_similarity=similarity,
        findings=findings,
    )

    summary, report = write_review_artifacts(
        output_dir=tmp_path,
        pages=(page_result,),
    )

    assert summary.is_file()
    rendered = report.read_text(encoding="utf-8")
    assert "SiftForge text-fidelity review" in rendered
    assert "<mark>∅</mark>" in rendered
    assert "Local OCR" in rendered
    assert "Keep source" in rendered
    assert "Use OCR" in rendered
    assert "Use suggestion" in rendered
    assert "Export resolutions.json" in rendered
    assert "siftforge-text-review-resolutions" in rendered


class _FakeLoader:
    """Return prebuilt page runs for service-level tests."""

    def __init__(self, page_run: EbookPageRunArtifact) -> None:
        self._page_run = page_run

    def discover(self, runs_root: str | Path) -> tuple[EbookPageRunArtifact, ...]:
        """Return the single configured canonical page run."""
        del runs_root
        return (self._page_run,)


class _FakeOcr:
    """Return OCR that intentionally agrees with the suspicious source typo."""

    def extract(self, image_path: str | Path) -> OcrPage:
        """Return one word box used to generate the source crop."""
        del image_path
        text = "3 giờ sáng ngày14 tháng 12"
        token_start = text.index("ngày14")
        return OcrPage(
            text=text,
            words=(
                OcrWord(
                    text="ngày14",
                    confidence=96.0,
                    left=30,
                    top=30,
                    width=60,
                    height=20,
                    start=token_start,
                    end=token_start + len("ngày14"),
                ),
            ),
            engine="fake",
            language="vie",
        )


def test_service_keeps_normalized_text_and_writes_review_overlay(
    tmp_path: Path,
) -> None:
    """Review artifacts must be additive and never rewrite normalized page data."""
    run_dir = tmp_path / "page-0013"
    normalized = run_dir / "normalized"
    normalized.mkdir(parents=True)
    original_payload = '{"sentinel":"unchanged"}\n'
    (normalized / "page.json").write_text(original_payload, encoding="utf-8")
    source_image = run_dir / "assets" / "page-0013.jpg"
    source_image.parent.mkdir(parents=True)
    Image.new("RGB", (200, 120), "white").save(source_image)
    page = _page("3 giờ sáng ngày14 tháng 12")
    page_run = EbookPageRunArtifact(
        run_dir=run_dir,
        page_number=13,
        page=page,
        source_image=source_image,
        source_media_type="image/jpeg",
    )
    service = EbookTextReviewService(
        _FakeOcr(),
        loader=_FakeLoader(page_run),  # type: ignore[arg-type]
    )

    result = service.review(tmp_path, tmp_path / "review")

    assert result.finding_count == 1
    assert result.pages[0].findings[0].source.value == "heuristic"
    assert (normalized / "page.json").read_text(encoding="utf-8") == original_payload
    finding_payload = json.loads(
        (run_dir / "review" / "findings.json").read_text(encoding="utf-8")
    )
    assert finding_payload["findings"][0]["gemini_text"] == "ngày14"
    crop = result.output_dir / result.pages[0].findings[0].crop_path
    assert crop.is_file()


def test_comparison_coalesces_nearby_character_noise() -> None:
    """Several OCR character errors in one phrase should become one card."""
    projection = project_page_text(_page("vượt vũ môn"))
    ocr = OcrPage(
        text="uượt vii mmôn",
        words=(),
        engine="fake",
        language="vie",
    )

    _, findings = compare_with_ocr(
        page_number=13,
        projection=projection,
        ocr=ocr,
    )

    assert len(findings) == 1
    assert findings[0].kind.value == "replacement"


def test_filter_suppresses_diacritic_loss_even_at_high_confidence() -> None:
    """Common local-OCR accent loss should not dominate human review."""
    finding = ReviewFinding(
        finding_id="page-0013-ocr-0001",
        page_id="pdf:test:page:0013",
        page_number=13,
        source=ReviewSource.OCR,
        kind=ReviewKind.CHARACTER,
        severity=ReviewSeverity.MINOR,
        gemini_start=0,
        gemini_end=1,
        reference_start=0,
        reference_end=1,
        gemini_text="đ",
        reference_text="d",
        block_id="block",
        span_id="span",
        block_role="paragraph",
    )
    ocr = OcrPage(
        text="d",
        words=(
            OcrWord(
                text="d",
                confidence=99.0,
                left=0,
                top=0,
                width=10,
                height=10,
                start=0,
                end=1,
            ),
        ),
        engine="fake",
        language="vie",
    )

    kept, suppressed = filter_ocr_findings(
        ocr=ocr,
        ocr_findings=(finding,),
        heuristic_findings=(),
        config=ReviewFilterConfig(),
    )

    assert kept == ()
    assert len(suppressed) == 1
    assert suppressed[0].suppressed_reason == "ocr_diacritic_loss"


def test_filter_keeps_high_confidence_meaningful_body_mismatch() -> None:
    """Noise reduction must retain a confident multi-character disagreement."""
    finding = ReviewFinding(
        finding_id="page-0013-ocr-0001",
        page_id="pdf:test:page:0013",
        page_number=13,
        source=ReviewSource.OCR,
        kind=ReviewKind.REPLACEMENT,
        severity=ReviewSeverity.MAJOR,
        gemini_start=0,
        gemini_end=5,
        reference_start=0,
        reference_end=5,
        gemini_text="không",
        reference_text="khôn",
        block_id="block",
        span_id="span",
        block_role="paragraph",
    )
    ocr = OcrPage(
        text="khôn",
        words=(
            OcrWord(
                text="khôn",
                confidence=98.0,
                left=0,
                top=0,
                width=40,
                height=10,
                start=0,
                end=5,
            ),
        ),
        engine="fake",
        language="vie",
    )

    kept, suppressed = filter_ocr_findings(
        ocr=ocr,
        ocr_findings=(finding,),
        heuristic_findings=(),
        config=ReviewFilterConfig(),
    )

    assert len(kept) == 1
    assert suppressed == ()


def test_filter_can_show_all_ocr_differences_for_audit() -> None:
    """Users can disable suppression when they want the raw OCR comparison."""
    finding = ReviewFinding(
        finding_id="page-0013-ocr-0001",
        page_id="pdf:test:page:0013",
        page_number=13,
        source=ReviewSource.OCR,
        kind=ReviewKind.CHARACTER,
        severity=ReviewSeverity.MINOR,
        gemini_start=0,
        gemini_end=1,
        reference_start=0,
        reference_end=1,
        gemini_text="đ",
        reference_text="d",
        block_id="block",
        span_id="span",
        block_role="paragraph",
    )
    ocr = OcrPage(
        text="d",
        words=(
            OcrWord(
                text="d",
                confidence=20.0,
                left=0,
                top=0,
                width=10,
                height=10,
                start=0,
                end=1,
            ),
        ),
        engine="fake",
        language="vie",
    )

    kept, suppressed = filter_ocr_findings(
        ocr=ocr,
        ocr_findings=(finding,),
        heuristic_findings=(),
        config=ReviewFilterConfig(enabled=False),
    )

    assert len(kept) == 1
    assert suppressed == ()


def _write_findings(
    run_dir: Path,
    *,
    text: str,
    finding_id: str = "page-0013-heur-0001",
) -> None:
    """Persist one minimal actionable finding snapshot for status tests."""
    review_dir = run_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "findings.json").write_text(
        json.dumps(
            {
                "review_model": "TextFidelityReview-v3",
                "findings": [
                    {
                        "finding_id": finding_id,
                        "page_id": "pdf:test:page:0013",
                        "page_number": 13,
                        "gemini_range": [0, len(text)],
                        "gemini_text": text,
                    }
                ],
                "suppressed_findings": [],
            }
        ),
        encoding="utf-8",
    )


def _status_page_run(tmp_path: Path, text: str) -> EbookPageRunArtifact:
    """Build one canonical page-run shell for review-status tests."""
    run_dir = tmp_path / "page-0013"
    run_dir.mkdir(parents=True, exist_ok=True)
    source_image = run_dir / "page.jpg"
    Image.new("RGB", (20, 20), "white").save(source_image)
    return EbookPageRunArtifact(
        run_dir=run_dir,
        page_number=13,
        page=_page(text),
        source_image=source_image,
        source_media_type="image/jpeg",
    )


def test_review_status_distinguishes_unreviewed_pass_and_resolved(
    tmp_path: Path,
) -> None:
    """Strict review status should represent the full human-review lifecycle."""
    from siftforge.ebook.review import ReviewPageState, ReviewStatusService

    page_run = _status_page_run(tmp_path, "ngày14")
    service = ReviewStatusService(loader=_FakeLoader(page_run))

    assert service.inspect(tmp_path).pages[0].state is ReviewPageState.NOT_REVIEWED

    review_dir = page_run.run_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "findings.json").write_text(
        json.dumps({"findings": [], "suppressed_findings": []}),
        encoding="utf-8",
    )
    assert service.inspect(tmp_path).pages[0].state is ReviewPageState.PASS

    _write_findings(page_run.run_dir, text="ngày14")
    assert service.inspect(tmp_path).pages[0].state is ReviewPageState.NEEDS_REVIEW

    (review_dir / "resolutions.json").write_text(
        json.dumps(
            {
                "resolutions": [
                    {
                        "finding_id": "page-0013-heur-0001",
                        "decision": "keep_source",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    status = service.inspect(tmp_path)
    assert status.pages[0].state is ReviewPageState.RESOLVED
    assert status.complete is True


def test_review_status_detects_stale_finding_after_reextraction(
    tmp_path: Path,
) -> None:
    """A changed normalized page must invalidate old review snapshots."""
    from siftforge.ebook.review import ReviewPageState, ReviewStatusService

    page_run = _status_page_run(tmp_path, "ngày 14")
    _write_findings(page_run.run_dir, text="ngày14")

    status = ReviewStatusService(loader=_FakeLoader(page_run)).inspect(tmp_path)

    assert status.pages[0].state is ReviewPageState.STALE
    assert "no longer matches" in (status.pages[0].stale_reason or "")


def test_review_status_strict_gate_rejects_unresolved_findings(
    tmp_path: Path,
) -> None:
    """Strict builds should be able to stop before unresolved text is packaged."""
    import pytest

    from siftforge.ebook.review import ReviewStatusError, ReviewStatusService

    page_run = _status_page_run(tmp_path, "ngày14")
    _write_findings(page_run.run_dir, text="ngày14")
    service = ReviewStatusService(loader=_FakeLoader(page_run))

    with pytest.raises(ReviewStatusError, match="needs_review=1"):
        service.require_complete(tmp_path)
