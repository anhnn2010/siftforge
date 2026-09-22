"""Typed models for ebook text-fidelity review artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

TEXT_REVIEW_MODEL = "TextFidelityReview-v4"


class ReviewSource(StrEnum):
    """Independent signal that produced one review finding."""

    OCR = "local_ocr"
    HEURISTIC = "heuristic"


class ReviewKind(StrEnum):
    """Smallest useful category for a text-fidelity disagreement."""

    WHITESPACE = "whitespace"
    PUNCTUATION = "punctuation"
    CHARACTER = "character"
    MISSING_TEXT = "missing_text"
    EXTRA_TEXT = "extra_text"
    REPLACEMENT = "replacement"
    SUSPICIOUS_BOUNDARY = "suspicious_boundary"


class ReviewSeverity(StrEnum):
    """Human-review priority for one finding."""

    MINOR = "minor"
    MAJOR = "major"


@dataclass(frozen=True, slots=True)
class TextAnchor:
    """Map one projected character back to normalized extraction evidence."""

    page_id: str
    block_id: str
    span_id: str
    span_offset: int
    block_role: str


@dataclass(frozen=True, slots=True)
class ProjectedText:
    """Comparison text plus character-level extraction provenance."""

    text: str
    anchors: tuple[TextAnchor | None, ...]


@dataclass(frozen=True, slots=True)
class OcrWord:
    """One OCR word with confidence, source pixels, and text offsets."""

    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class OcrPage:
    """Local OCR result used only as independent review evidence."""

    text: str
    words: tuple[OcrWord, ...]
    engine: str
    language: str


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    """One localized disagreement or suspicious textual boundary."""

    finding_id: str
    page_id: str
    page_number: int
    source: ReviewSource
    kind: ReviewKind
    severity: ReviewSeverity
    gemini_start: int
    gemini_end: int
    reference_start: int | None
    reference_end: int | None
    gemini_text: str
    reference_text: str
    block_id: str | None
    span_id: str | None
    block_role: str | None = None
    suggested_text: str | None = None
    crop_path: str | None = None
    ocr_confidence: float | None = None
    suppressed_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PageReviewResult:
    """Review result for one physical page."""

    page_id: str
    page_number: int
    gemini_text: str
    ocr_text: str
    ocr_similarity: float
    findings: tuple[ReviewFinding, ...]
    suppressed_findings: tuple[ReviewFinding, ...] = ()


class ReviewProgressState(StrEnum):
    """Lifecycle state for one page in a whole-book review run."""

    OCR_STARTED = "ocr_started"
    PROCESSED = "processed"
    REUSED = "reused"


@dataclass(frozen=True, slots=True)
class ReviewProgress:
    """One live progress update emitted while reviewing page runs."""

    index: int
    total: int
    page_number: int
    state: ReviewProgressState
    processed_pages: int
    reused_pages: int
    finding_count: int = 0
    suppressed_count: int = 0
    ocr_similarity: float | None = None


@dataclass(frozen=True, slots=True)
class TextReviewRun:
    """Whole-run review result and persisted report locations."""

    runs_root: Path
    output_dir: Path
    pages: tuple[PageReviewResult, ...]
    report_path: Path
    summary_path: Path
    manifest_path: Path | None = None
    processed_pages: int = 0
    reused_pages: int = 0

    @property
    def finding_count(self) -> int:
        """Return actionable findings across all reviewed pages."""
        return sum(len(page.findings) for page in self.pages)

    @property
    def suppressed_count(self) -> int:
        """Return OCR differences filtered as low-value review noise."""
        return sum(len(page.suppressed_findings) for page in self.pages)

    @property
    def pages_with_findings(self) -> int:
        """Return number of pages that need human attention."""
        return sum(bool(page.findings) for page in self.pages)
